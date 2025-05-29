# from rover_movement import Rover as BaseRover
# from model_loader import ModelLoader
# from model_inference import ModelInference
# import os

# class Rover(BaseRover):
#     def __init__(self, serial_port="/dev/ttyUSB0", baud_rate=57600, input_uri="/dev/video0", 
#                  output_uri="display://0", width=640, height=480, 
#                  car_model_path="models/car.onnx", np_model_path="models/np.onnx"):
#         """Initialize the Rover with movement, camera, and inference capabilities."""
#         # Initialize the base Rover class for movement and camera control
#         super().__init__(serial_port=serial_port, baud_rate=baud_rate, input_uri=input_uri, 
#                          output_uri=output_uri, width=width, height=height)
        
#         # Initialize model inference
#         try:
#             self.model_loader = ModelLoader(car_model_path, np_model_path)
#             self.inference = ModelInference(self.model_loader, conf_threshold=0.5, iou_threshold=0.45)
#             print("Model inference initialized successfully.")
#         except Exception as e:
#             print(f"Failed to initialize model inference: {e}")
#             self.cleanup()
#             raise

#     def run_inference(self, img_path, output_path):
#         """Run car and number plate detection on a captured image."""
#         try:
#             car_boxes, car_scores, car_class_ids, np_boxes, np_scores, np_class_ids = self.inference.infer(
#                 img_path=img_path, output_path=output_path
#             )
#             print(f"Car detections: {len(car_boxes)}")
#             print(f"Number plate detections: {len(np_boxes)}")
#             return car_boxes, car_scores, car_class_ids, np_boxes, np_scores, np_class_ids
#         except Exception as e:
#             print(f"Inference failed: {e}")
#             return None

#     def perform_mission(self, segment=1, distance=2.0):
#         """Execute a sample mission: move, capture image, and run inference."""
#         try:
#             # Mount the camera
#             if not self.mount_camera():
#                 print("Failed to mount camera. Aborting mission.")
#                 return
            
#             # Move forward
#             self.forward(distance)
            
#             # Capture an image
#             img_path = self.capture_image(segment, distance)
#             if img_path is None:
#                 print("Failed to capture image. Skipping inference.")
#                 return
            
#             # Run inference on the captured image
#             output_path = f"captured_images/output_segment_{segment}_{distance:.1f}m.jpg"
#             self.run_inference(img_path, output_path)
            
#         except Exception as e:
#             print(f"Mission failed: {e}")
#         finally:
#             self.dismount_camera()

# if __name__ == "__main__":
#     try:
#         # Initialize the rover
#         rover = Rover()
        
#         # Perform a sample mission
#         rover.perform_mission(segment=1, distance=2.0)
        
#         # Additional movements for demonstration
#         rover.mount_camera()
#         rover.backward(1.0)
#         rover.reverse(1.0)
#         rover.left(45)
#         rover.right(45)
#         rover.spin_left(90)
#         rover.spin_right(90)
#         rover.capture_image(segment=2, distance=1.0)
        
#     finally:
#         rover.cleanup()

from rover_movement import Rover as BaseRover
from model_loader import ModelLoader
from model_inference import ModelInference
from number_plate_extract import NumberPlateExtractor
from database import Database
import os
import time
import jetson_utils
import cv2
import numpy as np
from datetime import datetime

class Rover(BaseRover):
    def __init__(self, serial_port="/dev/ttyUSB0", baud_rate=57600, input_uri="/dev/video0", 
                 output_uri="display://0", width=640, height=480, 
                 car_model_path="models/car.onnx", np_model_path="models/np.onnx",
                 mongo_uri="mongodb+srv://akshayareddy:akshaya20@clusterprac.w63oe.mongodb.net/?retryWrites=true&w=majority&appName=Clusterprac"):
        """Initialize the Rover with movement, camera, inference, and database capabilities."""
        super().__init__(serial_port=serial_port, baud_rate=baud_rate, input_uri=input_uri, 
                         output_uri=output_uri, width=width, height=height)
        
        try:
            self.model_loader = ModelLoader(car_model_path, np_model_path)
            self.inference = ModelInference(self.model_loader, conf_threshold=0.5, iou_threshold=0.45)
            self.plate_extractor = NumberPlateExtractor()
            print("Model inference and plate extractor initialized successfully.")
        except Exception as e:
            print(f"Failed to initialize model inference or plate extractor: {e}")
            self.cleanup()
            raise
        
        try:
            self.db = Database(mongo_uri=mongo_uri)
            print("Database initialized successfully.")
        except Exception as e:
            print(f"Failed to initialize database: {e}")
            self.cleanup()
            raise
        
        self.detected_plates = []
    
    def process_frame(self, img, segment, distance_covered, total_distance, num_slots):
        """Process a single frame for car and number plate detection, and extract text."""
        try:
            img_np = jetson_utils.cudaToNumpy(img)
            img_np = cv2.cvtColor(img_np, cv2.COLOR_RGBA2BGR)
            temp_path = f"temp_frame_{segment}_{distance_covered:.1f}m.jpg"
            cv2.imwrite(temp_path, img_np)
            
            car_boxes, car_scores, car_class_ids, np_boxes, np_scores, np_class_ids = self.inference.infer(
                img_path=temp_path, output_path=temp_path
            )
            
            if len(car_boxes) > 0 and len(np_boxes) > 0:
                for box in np_boxes:
                    plate_text = self.plate_extractor.process_plate(img_np, box)
                    if plate_text:
                        slot = int((distance_covered / total_distance) * num_slots) + 1
                        self.detected_plates.append((plate_text, datetime.utcnow(), slot))
                        print(f"Detected plate: {plate_text}, Slot: {slot}, Timestamp: {datetime.utcnow()}")
            
            if os.path.exists(temp_path):
                os.remove(temp_path)
            
            return True
        except Exception as e:
            print(f"Error processing frame: {e}")
            return False
    
    def perform_mission(self, total_distance=10.0, num_slots=5, velocity=1.0, segment_duration=1.0):
        """Execute a mission: move forward, capture video, detect cars and plates, and update database."""
        try:
            if not self.mount_camera():
                print("Failed to mount camera. Aborting mission.")
                return
            
            total_time = total_distance / velocity
            segment_distance = velocity * segment_duration
            distance_covered = 0.0
            segment = 1
            
            print(f"Starting mission: {total_distance}m, {num_slots} slots, velocity {velocity}m/s")
            start_time = time.time()
            
            self.forward(total_distance, velocity=velocity)
            
            while distance_covered < total_distance:
                if self.input_stream is None:
                    print("Camera stream closed unexpectedly.")
                    break
                
                img = self.input_stream.Capture()
                if img is None:
                    print("Failed to capture frame.")
                    time.sleep(0.1)
                    continue
                
                self.output_stream.Render(img)
                self.output_stream.SetStatus(f"Mission | Distance: {distance_covered:.1f}m | Segment {segment}")
                
                self.process_frame(img, segment, distance_covered, total_distance, num_slots)
                
                elapsed_time = time.time() - start_time
                distance_covered = min(elapsed_time * velocity, total_distance)
                segment = int(distance_covered / segment_distance) + 1
                
                time.sleep(0.1)
            
            self.current_throttle = self.THROTTLE_NEUTRAL
            self.send_rc_override(self.current_throttle, self.CENTER)
            self.vehicle.channels.overrides = {}
            print("\nMission movement complete.")
            
            self.verify_and_upsert_plates(num_slots)
            
        except Exception as e:
            print(f"Mission failed: {e}")
        finally:
            self.dismount_camera()
            self.db.close()
    
    def verify_and_upsert_plates(self, num_slots):
        """Verify detected plates against database and upsert new entries."""
        try:
            print("Verifying and upserting detected plates...")
            for plate_text, timestamp, slot in self.detected_plates:
                if slot > num_slots:
                    print(f"Warning: Slot {slot} exceeds number of slots ({num_slots}). Skipping.")
                    continue
                
                exists = self.db.check_number_plate(plate_text)
                if not exists:
                    result = self.db.upsert_number_plate(plate_text)
                    if result:
                        print(f"Added plate {plate_text} to slot {slot} at {timestamp}")
                    else:
                        print(f"Failed to upsert plate {plate_text}")
                else:
                    print(f"Plate {plate_text} already exists in database.")
            
            self.detected_plates = []
        except Exception as e:
            print(f"Error verifying/upserting plates: {e}")
    
    def cleanup(self):
        """Clean up rover, camera, and database connections."""
        super().cleanup()
        try:
            self.db.close()
        except:
            pass

if __name__ == "__main__":
    try:
        # Initialize the rover with test parameters
        rover = Rover(
            serial_port="/dev/ttyUSB0",
            input_uri="/dev/video0",
            car_model_path="models/car.onnx",
            np_model_path="models/np.onnx",
            mongo_uri="mongodb+srv://akshayareddy:akshaya20@clusterprac.w63oe.mongodb.net/?retryWrites=true&w=majority&appName=Clusterprac"
        )
        
        # Test mission: 5 meters, 3 slots, 0.5 m/s velocity, 1-second segments
        rover.perform_mission(
            total_distance=5.0,
            num_slots=3,
            velocity=0.5,
            segment_duration=1.0
        )
        
    except Exception as e:
        print(f"Test mission failed: {e}")
    finally:
        rover.cleanup()