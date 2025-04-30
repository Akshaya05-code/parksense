from flask import Flask, request, jsonify
from flask_cors import CORS
from io import BytesIO
from PIL import Image
import pymongo
import cv2
import numpy as np
from datetime import datetime
import base64
from ocr import process_image, correct_by_position

app = Flask(__name__)
CORS(app)  # Enable CORS for React frontend

# MongoDB setup
MONGO_URI = "mongodb+srv://akshayareddy:akshaya20@clusterprac.w63oe.mongodb.net/?retryWrites=true&w=majority&appName=Clusterprac"
client = pymongo.MongoClient(MONGO_URI)
db = client["parking_db"]
collection = db["authorized_plates"]
car_log_collection = db["car_logs"]

@app.route('/')
def home():
    return jsonify({
        "message": "Welcome to ParkSense",
        "links": {
            "upload": "/upload",
            "dashboard": "/dashboard"
        }
    })

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    try:
        image_stream = BytesIO(file.read())
        pil_image = Image.open(image_stream).convert('RGB')
        image = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)

        number = process_image(image)
        plate_number = correct_by_position(number)

        if plate_number:
            plate_exists = collection.find_one({"plate_number": {"$regex": f"^{plate_number}$", "$options": "i"}})
            status = "Authorized" if plate_exists else "Unauthorized"
        else:
            plate_number = "Not detected"
            status = "N/A"

        # Store image in base64
        buffered = BytesIO()
        pil_image.save(buffered, format="JPEG")
        img_str = base64.b64encode(buffered.getvalue()).decode()

        car_log_collection.insert_one({
            "image": img_str,
            "plate_number": plate_number,
            "status": status,
            "timestamp": datetime.now()
        })

        return jsonify({
            "plate_number": plate_number,
            "status": status,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/text', methods=['POST'])
def submit_text():
    data = request.get_json()
    if not data or 'text' not in data:
        return jsonify({"error": "No text provided"}), 400
    
    try:
        car_log_collection.insert_one({
            "text": data['text'],
            "type": "text",
            "timestamp": datetime.now()
        })
        return jsonify({
            "message": "Text submitted successfully",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/entries', methods=['GET'])
def dashboard():
    try:
        entries = list(car_log_collection.find().sort("timestamp", -1))
        for entry in entries:
            entry["timestamp"] = entry["timestamp"].strftime("%Y-%m-%d %H:%M:%S")
            entry["_id"] = str(entry["_id"])  # Convert ObjectId to string
        return jsonify(entries), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)