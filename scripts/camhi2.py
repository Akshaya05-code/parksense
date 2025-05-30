import time
import os
import cv2
from datetime import datetime
from dronekit import connect, VehicleMode
from model_loader import ModelLoader
from model_inference import ModelInference

# --- Configuration ---
SERIAL_PORTS = ['/dev/ttyUSB0', 'COM3']  # Try Linux then Windows
BAUD_RATE = 57600
THROTTLE_CH = 3  # Forward/backward
STEERING_CH = 1  # Left/right
CENTER = 1500
THROTTLE_NEUTRAL = 1500
THROTTLE_MAX = 2000
CAPTURE_INTERVAL = 2  # seconds
DURATION = 10  # total movement seconds
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
CAR_MODEL = '../models/car.onnx'
NP_MODEL = '../models/np.onnx'


def send_rc(vehicle, throttle, steering):
    vehicle.channels.overrides = {THROTTLE_CH: throttle, STEERING_CH: steering}
    print(f"RC override -> Throttle: {throttle}, Steering: {steering}")


def connect_vehicle():
    for port in SERIAL_PORTS:
        try:
            v = connect(port, baud=BAUD_RATE, wait_ready=False)
            print(f"Connected to vehicle on {port}")
            return v
        except Exception as e:
            print(f"Failed to connect on {port}: {e}")
    raise RuntimeError("Unable to connect to any Pixhawk port.")


def arm_and_manual(vehicle):
    print("Performing pre-arm checks...")
    timeout = time.time() + 10
    while not vehicle.is_armable and time.time() < timeout:
        fix = getattr(vehicle.gps_0, 'fix_type', 'N/A')
        sats = getattr(vehicle.gps_0, 'satellites_visible', 'N/A')
        volt = getattr(vehicle.battery, 'voltage', 'N/A')
        print(f" Waiting: GPS fix {fix}, sats {sats}, battery {volt}V")
        time.sleep(1)

    if not vehicle.is_armable:
        print("Warning: Vehicle not armable. Proceeding without arming.")
        return False

    vehicle.armed = True
    while not vehicle.armed and time.time() < timeout:
        print(" Waiting for arming...")
        time.sleep(1)

    vehicle.mode = VehicleMode('MANUAL')
    mtimeout = time.time() + 10
    while vehicle.mode.name != 'MANUAL' and time.time() < mtimeout:
        print(f" Switching mode: current {vehicle.mode.name}")
        vehicle.mode = VehicleMode('MANUAL')
        time.sleep(1)

    print(f"Armed: {vehicle.armed}, Mode: {vehicle.mode.name}")
    return True


def main():
    cap = None
    vehicle = None
    try:
        # Connect and arm
        vehicle = connect_vehicle()
        arm_and_manual(vehicle)

        # Open webcam
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            print("Error: Cannot open webcam. Exiting.")
            return
        print("Webcam connected.")

        # Load ONNX models
        loader = ModelLoader(CAR_MODEL, NP_MODEL)
        inference = ModelInference(loader)

        # Start movement
        throttle_val = int(THROTTLE_NEUTRAL + (THROTTLE_MAX - THROTTLE_NEUTRAL) * 0.35)
        send_rc(vehicle, throttle_val, CENTER)
        start_time = time.time()
        last_capture = start_time

        # Capture loop
        while time.time() - start_time < DURATION:
            send_rc(vehicle, throttle_val, CENTER)
            now = time.time()
            if now - last_capture >= CAPTURE_INTERVAL:
                ret, frame = cap.read()
                if not ret:
                    print("Frame capture failed.")
                    last_capture = now
                    continue

                ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                base = f"capture_{ts}"
                # Save raw
                raw_fp = os.path.join(OUTPUT_DIR, f"{base}.jpg")
                cv2.imwrite(raw_fp, frame)
                print(f"Saved raw: {raw_fp}")

                # Inference
                vis_fp = os.path.join(OUTPUT_DIR, f"vis_{base}.jpg")
                cars, cscores, cids, plates, pscores, pids = inference.infer(raw_fp, vis_fp)
                print(f"Saved viz: {vis_fp}")

                # Crop detections
                for i, (x1, y1, x2, y2) in enumerate(cars):
                    car_crop = frame[int(y1):int(y2), int(x1):int(x2)]
                    cf = os.path.join(OUTPUT_DIR, f"car_{base}_{i}.jpg")
                    cv2.imwrite(cf, car_crop)
                    print(f"Saved car crop: {cf}")
                for j, (x1, y1, x2, y2) in enumerate(plates):
                    plate_crop = frame[int(y1):int(y2), int(x1):int(x2)]
                    pf = os.path.join(OUTPUT_DIR, f"plate_{base}_{j}.jpg")
                    cv2.imwrite(pf, plate_crop)
                    print(f"Saved plate crop: {pf}")

                last_capture = now
            time.sleep(0.1)

        # Stop rover after loop
        print("Stopping rover...")
        for _ in range(5):
            send_rc(vehicle, THROTTLE_NEUTRAL, CENTER)
            time.sleep(0.2)
        if vehicle:
            vehicle.channels.overrides = {}

    except Exception as e:
        print(f"Error: {e}")
        # Ensure rover stops on error
        if vehicle:
            for _ in range(3):
                send_rc(vehicle, THROTTLE_NEUTRAL, CENTER)
                time.sleep(0.1)
            vehicle.channels.overrides = {}

    finally:
        # Final stop to guarantee rover is stationary
        if vehicle:
            try:
                for _ in range(5):
                    send_rc(vehicle, THROTTLE_NEUTRAL, CENTER)
                    time.sleep(0.2)
                vehicle.channels.overrides = {}
            except Exception:
                pass
        # Release resources
        if cap:
            cap.release()
        if vehicle:
            try:
                vehicle.close()
            except:
                pass
        print("Resources cleaned up.")

if __name__ == '__main__':
    main()

