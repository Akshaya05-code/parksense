import os
import cv2
from rover_movement import Rover
from model_inference import Inference
from database import Database

def main():
    # Configuration
    total_distance = 100.0  # meters to move forward
    segment_distance = 2.0  # meters per segment for frequent captures
    velocity = 1.0  # m/s
    throttle_percent = 50
    num_segments = int(total_distance / segment_distance)
    output_dir = "captured_images"
    os.makedirs(output_dir, exist_ok=True)
    
    # Step 1: Camera connection (handled by Rover class)
    # Step 2: Database connection
    rover = Rover()
    db = Database()
    inference = Inference(
        car_model_path="models/car.onnx",
        number_plate_model_path="models/np.onnx"
    )
    number_plates = []  # Store unique number plates
    
    try:
        # Step 3: Start movement (move forward 100 meters in segments)
        for segment in range(num_segments + 1):
            distance = segment * segment_distance
            
            # Step 4: Take live footage
            img_path = rover.capture_image(segment, distance)
            if img_path:
                frame = cv2.imread(img_path)
                if frame is None:
                    print(f"Failed to load image {img_path}")
                    continue
                
                # Step 5: Identify cars and pass to number plate detection model
                car_boxes, img_width, img_height = inference.detect_cars(frame)
                for box in car_boxes:
                    x, y, w, h = box
                    x1 = int(x - w / 2)
                    y1 = int(y - h / 2)
                    x2 = int(x + w / 2)
                    y2 = int(y + h / 2)
                    roi = frame[y1:y2, x1:x2]
                    
                    # Number plate detection and text extraction
                    plate_box, _, _ = inference.detect_number_plate(roi)
                    if plate_box is not None:
                        px, py, pw, ph = plate_box
                        px1 = int(px - pw / 2)
                        py1 = int(py - ph / 2)
                        px2 = int(px + pw / 2)
                        py2 = int(py + ph / 2)
                        plate_roi = roi[py1:py2, px1:px2]
                        
                        number_plate = inference.extract_number_plate_text(plate_roi)
                        if number_plate and number_plate not in number_plates:
                            number_plates.append(number_plate)
                            print(f"Detected number plate: {number_plate}")
            
            # Move to the next segment (except on the last iteration)
            if segment < num_segments:
                rover.move_forward(segment_distance, velocity, throttle_percent)
        
        # After moving 100 meters, rotate 180 degrees to face the launch position
        print("Rotating 180 degrees to face launch position...")
        rover.spin_right(180.0)
        
        # Step 7: Return to launch position (move back 100 meters)
        print("Returning to launch position...")
        rover.move_backward(total_distance, velocity, throttle_percent)
        
        # Step 6: Update database with detected number plates
        for plate in number_plates:
            if not db.check_number_plate(plate):
                db.upsert_number_plate(plate)
                print(f"Upserted number plate: {plate}")
    
    except KeyboardInterrupt:
        print("\nOperation interrupted by user.")
    
    finally:
        # Cleanup
        rover.cleanup()
        db.close()

if __name__ == "__main__":
    main()