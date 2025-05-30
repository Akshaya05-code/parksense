import time
import os
import cv2
import pytesseract
from datetime import datetime
from dronekit import connect, VehicleMode
from model_loader import ModelLoader
from model_inference import ModelInference
from database import Database

# --- Configuration ---
SERIAL_PORTS = ['/dev/ttyUSB0', 'COM3']
BAUD_RATE = 57600
THROTTLE_CH = 3
STEERING_CH = 1
CENTER = 1500
THROTTLE_NEUTRAL = 1500
THROTTLE_MAX = 2000
DURATION = 10  # seconds
# Estimated max speed in meters per second at full throttle
MAX_SPEED_MPS = 1.0
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
CAR_MODEL = '../models/car.onnx'
NP_MODEL = '../models/np.onnx'

# Uncomment & adjust if Tesseract isn't on your PATH:
# pytesseract.pytesseract.tesseract_cmd = r'/usr/bin/tesseract'
# pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'


def send_rc(vehicle, throttle, steering):
    vehicle.channels.overrides = {THROTTLE_CH: throttle, STEERING_CH: steering}
    print(f"[DEBUG] RC override -> Throttle: {throttle}, Steering: {steering}")


def connect_vehicle():
    for port in SERIAL_PORTS:
        try:
            v = connect(port, baud=BAUD_RATE, wait_ready=False)
            print(f"[DEBUG] Connected to vehicle on {port}")
            return v
        except Exception as e:
            print(f"[DEBUG] Failed to connect on {port}: {e}")
    raise RuntimeError("Unable to connect to any Pixhawk port.")


def arm_and_manual(vehicle):
    print("[DEBUG] Performing pre-arm checks...")
    timeout = time.time() + 10
    while not vehicle.is_armable and time.time() < timeout:
        fix = getattr(vehicle.gps_0, 'fix_type', 'N/A')
        sats = getattr(vehicle.gps_0, 'satellites_visible', 'N/A')
        volt = getattr(vehicle.battery, 'voltage', 'N/A')
        print(f"  [DEBUG] Waiting: GPS fix {fix}, sats {sats}, battery {volt}V")
        time.sleep(1)

    if not vehicle.is_armable:
        print("[DEBUG] Warning: Vehicle not armable. Proceeding without arming.")
    else:
        vehicle.armed = True
        while not vehicle.armed and time.time() < timeout:
            print("  [DEBUG] Waiting for arming...")
            time.sleep(1)

        vehicle.mode = VehicleMode('MANUAL')
        mtimeout = time.time() + 10
        while vehicle.mode.name != 'MANUAL' and time.time() < mtimeout:
            print(f"  [DEBUG] Switching mode: current {vehicle.mode.name}")
            vehicle.mode = VehicleMode('MANUAL')
            time.sleep(1)

        print(f"[DEBUG] Armed: {vehicle.armed}, Mode: {vehicle.mode.name}")


def preprocess_plate(plate_img):
    gray = cv2.cvtColor(plate_img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    _, binary = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return binary


def main():
    cap = None
    vehicle = None
    db = None

    # Stats counters & collectors
    num_frames = 0
    car_count = 0
    plate_count = 0
    plate_texts = []
    plate_image_paths = []
    cumulative_distance = 0.0

    try:
        # --- DATABASE SETUP ---
        db = Database()

        # --- VEHICLE & CAMERA SETUP ---
        vehicle = connect_vehicle()
        arm_and_manual(vehicle)

        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            print("[ERROR] Cannot open webcam.")
            return

        print("[DEBUG] Webcam connected. Loading models...")
        loader = ModelLoader(CAR_MODEL, NP_MODEL)
        inference = ModelInference(loader)

        # Compute throttle-based speed factor
        throttle_val = int(THROTTLE_NEUTRAL + (THROTTLE_MAX - THROTTLE_NEUTRAL) * 0.35)
        speed_factor = (throttle_val - THROTTLE_NEUTRAL) / float(THROTTLE_MAX - THROTTLE_NEUTRAL)
        print(f"[DEBUG] Speed factor set to {speed_factor:.2f}")

        send_rc(vehicle, throttle_val, CENTER)
        start_time = time.time()
        last_time = start_time
        print("[DEBUG] Entering main loop...")

        # --- MAIN LOOP ---
        while time.time() - start_time < DURATION:
            try:
                ret, frame = cap.read()
                if not ret:
                    print("[DEBUG] Frame read failed; skipping.")
                    continue

                current_time = time.time()
                dt = current_time - last_time
                last_time = current_time
                # Estimate distance traveled since last frame
                distance_increment = speed_factor * MAX_SPEED_MPS * dt
                cumulative_distance += distance_increment

                num_frames += 1
                ts = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]
                print(f"\n[DEBUG] Frame #{num_frames} @ {ts} | +{distance_increment:.3f}m -> {cumulative_distance:.3f}m total")

                # Save raw frame
                raw_fp = os.path.join(OUTPUT_DIR, f"frame_{ts}.jpg")
                cv2.imwrite(raw_fp, frame)
                print(f"[DEBUG] Saved raw frame: {raw_fp}")

                # Run model inference
                vis_fp = os.path.join(OUTPUT_DIR, f"vis_{ts}.jpg")
                cars, cscores, cids, plates, pscores, pids = inference.infer(raw_fp, vis_fp)
                print(f"[DEBUG] Detected {len(cars)} cars, {len(plates)} plates")

                # Process car crops
                if len(cars) > 0:
                    car_count += len(cars)
                    for i, (x1, y1, x2, y2) in enumerate(cars):
                        print(f"[DEBUG] Car {i} bbox: ({x1:.1f},{y1:.1f})→({x2:.1f},{y2:.1f})")
                        crop = frame[int(y1):int(y2), int(x1):int(x2)]
                        cf = os.path.join(OUTPUT_DIR, f"car_{ts}_{i}.jpg")
                        cv2.imwrite(cf, crop)
                        print(f"[DEBUG] Saved car crop: {cf}")

                # Process plate crops + OCR
                if len(plates) > 0:
                    for j, (x1, y1, x2, y2) in enumerate(plates):
                        print(f"[DEBUG] Plate {j} bbox: ({x1:.1f},{y1:.1f})→({x2:.1f},{y2:.1f})")
                        crop = frame[int(y1):int(y2), int(x1):int(x2)]
                        pf = os.path.join(OUTPUT_DIR, f"plate_{ts}_{j}.jpg")
                        cv2.imwrite(pf, crop)
                        plate_image_paths.append(pf)
                        plate_count += 1
                        print(f"[DEBUG] Saved plate crop: {pf}")

                        # OCR
                        processed = preprocess_plate(crop)
                        text = pytesseract.image_to_string(processed, config='--psm 7').strip()
                        print(f"[DEBUG] Raw OCR output: '{text}'")
                        if text:
                            plate_texts.append(text)
                            print(f"[DEBUG] Cleaned Text: '{text}'")
                            # Upload to database with distance from launch
                            if db:
                                db.upsert_number_plate(text, cumulative_distance)
                        else:
                            print("[DEBUG] No text extracted.")

                # Keep rover moving
                send_rc(vehicle, throttle_val, CENTER)
                time.sleep(0.05)

            except Exception as frame_err:
                print(f"[ERROR] Frame #{num_frames} processing error: {frame_err}")
                # continue to next frame

        # --- STOP ROVER ---
        print("\n[DEBUG] Movement duration ended; stopping rover...")
        for _ in range(5):
            send_rc(vehicle, THROTTLE_NEUTRAL, CENTER)
            time.sleep(0.2)
        vehicle.channels.overrides = {}

    except Exception as e:
        print(f"[ERROR] Setup/main loop failure: {e}")

    finally:
        # Cleanup resources
        if cap:
            cap.release()
        if vehicle:
            try:
                vehicle.close()
            except:
                pass
        if db:
            db.close()
        print("[DEBUG] Resources cleaned up.")

        # --- FINAL SUMMARY ---
        elapsed = time.time() - start_time
        fps = num_frames / elapsed if elapsed > 0 else 0.0
        print("\n=== Final Detection Summary ===")
        print(f"Frames processed:       {num_frames}")
        print(f"Overall FPS:           {fps:.2f}")
        print(f"Total cars detected:   {car_count}")
        print(f"Total plates detected: {plate_count}")
        print(f"Extracted plate texts: {plate_texts}")
        print(f"Total distance:        {cumulative_distance:.3f} m")
        print(f"Saved plate images ({len(plate_image_paths)}):")
        for p in plate_image_paths:
            print(f"  • {p}")


if __name__ == '__main__':
    main()

