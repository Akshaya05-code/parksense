from flask import Flask, render_template, Response, request, redirect, url_for
from ocr import correct_by_position, process_image
import cv2
import easyocr
import qrcode
import io
import base64
import uuid
import re
from pymongo import MongoClient, ReturnDocument
from datetime import datetime
import atexit

app = Flask(__name__)
camera = cv2.VideoCapture(0)
reader = easyocr.Reader(['en'])
frame_global = None

# MongoDB connection
client = MongoClient("mongodb+srv://akshayareddy:akshaya20@clusterprac.w63oe.mongodb.net/?retryWrites=true&w=majority&appName=Clusterprac")
db = client["parksense"]
collection = db["visitors"]
slots_collection = db["slots"]

@atexit.register
def cleanup():
    camera.release()

def generate_stream():
    global frame_global
    while True:
        success, frame = camera.read()
        if not success:
            break
        frame_global = frame
        _, buffer = cv2.imencode('.jpg', frame)
        frame_bytes = buffer.tobytes()
        yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

@app.route('/')
def index():
    return render_template("home.html")

@app.route('/video_feed')
def video_feed():
    return Response(generate_stream(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/capture', methods=['POST'])
def capture():
    global frame_global
    if frame_global is None:
        return "No frame captured."

    text = process_image(frame_global)
    print(text)
    car_number = correct_by_position(text)
    print(car_number)

    qr = qrcode.make(f"https://1038-183-82-97-138.ngrok-free.app/register?car={car_number}")
    buffer = io.BytesIO()
    qr.save(buffer, format="PNG")
    img_str = base64.b64encode(buffer.getvalue()).decode()

    return render_template("capture.html", car_number=car_number, qr_img=img_str)

@app.route('/register', methods=['GET', 'POST'])
def register():
    car_number = request.args.get('car', 'UNKNOWN')
    error = request.args.get('error', '')

    if request.method == 'POST':
        mobile = request.form['mobile'].strip()

        if not re.fullmatch(r"\d{10}", mobile):
            return redirect(url_for('register', car=car_number, error="Invalid mobile number."))

        active_user = collection.find_one({
            "mobile": mobile,
            "exit_time": {"$exists": False}
        })

        if active_user:
            return redirect(url_for('register', car=car_number, error="Mobile already registered with active parking."))

        slot = slots_collection.find_one_and_update(
            {"status": "empty"},
            {"$set": {"status": "occupied"}},
            return_document=ReturnDocument.AFTER
        )
        assigned_slot = slot['slot_id'] if slot else "None"

        collection.insert_one({
            "car_number": car_number,
            "mobile": mobile,
            "assigned_slot": assigned_slot,
            "entry_time": datetime.now()
        })

        return redirect(url_for('confirm', car_number=car_number, mobile=mobile, slot=assigned_slot))

    return render_template("register.html", car_number=car_number, error=error)


@app.route('/confirm')
def confirm():
    car_number = request.args.get("car_number")
    mobile = request.args.get("mobile")
    slot = request.args.get("slot")
    
    qr_id = str(uuid.uuid4())

    collection.update_one(
        {"car_number": car_number, "mobile": mobile, "assigned_slot": slot},
        {"$set": {"qr_id": qr_id, "confirmed": True}}
    )

    qr_data = f"https://1038-183-82-97-138.ngrok-free.app/exit?qr_id={qr_id}"
    qr = qrcode.make(qr_data)
    buffer = io.BytesIO()
    qr.save(buffer, format="PNG")
    img_str = base64.b64encode(buffer.getvalue()).decode()

    return render_template("confirm.html", car_number=car_number, mobile=mobile, slot=slot, qr_img=img_str)


@app.route('/parking-map')
def parking_map():
    slot = request.args.get('slot', 'A1')  # Default to A1 if missing
    return render_template('parking_map.html', slot=slot)
    

@app.route('/exit')
def exit_qr():
    qr_id = request.args.get('qr_id')
    record = collection.find_one({"qr_id": qr_id})
    if not record:
        return "Invalid or unregistered QR code."

    # Ensure entry_time is a datetime object
    entry_time = record.get("entry_time")
    if isinstance(entry_time, str):
        entry_time = datetime.strptime(entry_time, '%Y-%m-%d %H:%M:%S')
    
    exit_time = datetime.now()  # Current time as datetime object

    # Calculate the duration
    duration = exit_time - entry_time
    total_minutes = int(duration.total_seconds() // 60)
    hours = total_minutes // 60
    minutes = total_minutes % 60

    base_charge = 50
    if total_minutes <= 60:
        total_cost = base_charge
    else:
        extra_hours = ((total_minutes - 60) + 59) // 60
        total_cost = base_charge + (extra_hours * 30)

    # Formatting time range and duration
    time_range = f"{entry_time.strftime('%I:%M %p')} to {exit_time.strftime('%I:%M %p')}"
    formatted_duration = f"{hours} hour(s) {minutes} minute(s)"

    # Update slot status to 'empty'
    slots_collection.update_one(
        {"slot_id": record["assigned_slot"]},
        {"$set": {"status": "empty"}}
    )

    # Update the exit_time and total_cost in the collection as datetime object
    collection.update_one(
        {"qr_id": qr_id},
        {"$set": {"exit_time": exit_time, "total_cost": total_cost}}
    )

    return render_template("exit.html",
                           car_number=record['car_number'],
                           time_range=time_range,
                           duration=formatted_duration,
                           total_cost=total_cost)
    
if __name__ == '__main__':
    app.run(debug=True)
