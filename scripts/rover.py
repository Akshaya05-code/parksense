from rover_movement import Rover as BaseRover
from model_loader import ModelLoader
from model_inference import ModelInference
import os

class Rover(BaseRover):
    def __init__(self, serial_port="/dev/ttyUSB0", baud_rate=57600, input_uri="/dev/video0", 
                 output_uri="display://0", width=640, height=480, 
                 car_model_path="models/car.onnx", np_model_path="models/np.onnx"):
        """Initialize the Rover with movement, camera, and inference capabilities."""
        # Initialize the base Rover class for movement and camera control
        super().__init__(serial_port=serial_port, baud_rate=baud_rate, input_uri=input_uri, 
                         output_uri=output_uri, width=width, height=height)
        
        # Initialize model inference
        try:
            self.model_loader = ModelLoader(car_model_path, np_model_path)
            self.inference = ModelInference(self.model_loader, conf_threshold=0.5, iou_threshold=0.45)
            print("Model inference initialized successfully.")
        except Exception as e:
            print(f"Failed to initialize model inference: {e}")
            self.cleanup()
            raise

    def run_inference(self, img_path, output_path):
        """Run car and number plate detection on a captured image."""
        try:
            car_boxes, car_scores, car_class_ids, np_boxes, np_scores, np_class_ids = self.inference.infer(
                img_path=img_path, output_path=output_path
            )
            print(f"Car detections: {len(car_boxes)}")
            print(f"Number plate detections: {len(np_boxes)}")
            return car_boxes, car_scores, car_class_ids, np_boxes, np_scores, np_class_ids
        except Exception as e:
            print(f"Inference failed: {e}")
            return None

    def perform_mission(self, segment=1, distance=2.0):
        """Execute a sample mission: move, capture image, and run inference."""
        try:
            # Mount the camera
            if not self.mount_camera():
                print("Failed to mount camera. Aborting mission.")
                return
            
            # Move forward
            self.forward(distance)
            
            # Capture an image
            img_path = self.capture_image(segment, distance)
            if img_path is None:
                print("Failed to capture image. Skipping inference.")
                return
            
            # Run inference on the captured image
            output_path = f"captured_images/output_segment_{segment}_{distance:.1f}m.jpg"
            self.run_inference(img_path, output_path)
            
        except Exception as e:
            print(f"Mission failed: {e}")
        finally:
            self.dismount_camera()

if __name__ == "__main__":
    try:
        # Initialize the rover
        rover = Rover()
        
        # Perform a sample mission
        rover.perform_mission(segment=1, distance=2.0)
        
        # Additional movements for demonstration
        rover.mount_camera()
        rover.backward(1.0)
        rover.reverse(1.0)
        rover.left(45)
        rover.right(45)
        rover.spin_left(90)
        rover.spin_right(90)
        rover.capture_image(segment=2, distance=1.0)
        
    finally:
        rover.cleanup()