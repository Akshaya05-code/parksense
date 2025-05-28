import cv2
import numpy as np
import os
from model_loader import TensorRTModel
import pytesseract  # For OCR (number plate text extraction)

# harshith is shit
class Inference:
    def __init__(self, car_model_path, number_plate_model_path):
        """Initialize TensorRT models for car and number plate detection."""
        # Load TensorRT models (converted from ONNX if needed)
        self.car_model = TensorRTModel(car_model_path, car_model_path.replace(".onnx", ".trt"))
        self.number_plate_model = TensorRTModel(number_plate_model_path, number_plate_model_path.replace(".onnx", ".trt"))
        
        # Allocate buffers for model inputs (assuming 640x640 input for both models)
        self.car_model.allocate_buffers((1, 3, 640, 640))
        self.number_plate_model.allocate_buffers((1, 3, 640, 640))

    def preprocess_image(self, img, target_size=(640, 640)):
        """Preprocess image for model input."""
        # Store original dimensions for scaling bounding boxes back
        img_height, img_width = img.shape[:2]
        
        # Resize to target size (640x640 for number plate model)
        img_resized = cv2.resize(img, target_size, interpolation=cv2.INTER_LINEAR)
        
        # Convert from BGR (OpenCV) to RGB (if needed, depends on model training)
        img_rgb = cv2.cvtColor(img_resized, cv2.COLOR_BGR2RGB)
        
        # Normalize pixel values to [0, 1]
        img_input = img_rgb.astype(np.float32) / 255.0
        
        # Transpose to CHW format (channels, height, width) for TensorRT
        img_input = img_input.transpose(2, 0, 1)
        
        # Add batch dimension (1, C, H, W)
        img_input = np.expand_dims(img_input, axis=0)
        
        return img_input, img_width, img_height

    def nms(self, boxes, scores, iou_threshold=0.5):
        """Apply non-maximum suppression to filter overlapping boxes."""
        x1 = boxes[:, 0] - boxes[:, 2] / 2
        y1 = boxes[:, 1] - boxes[:, 3] / 2
        x2 = boxes[:, 0] + boxes[:, 2] / 2
        y2 = boxes[:, 1] + boxes[:, 3] / 2
        areas = (x2 - x1) * (y2 - y1)
        order = scores.argsort()[::-1]
        keep = []
        while order.size > 0:
            i = order[0]
            keep.append(i)
            xx1 = np.maximum(x1[i], x1[order[1:]])
            yy1 = np.maximum(y1[i], y1[order[1:]])
            xx2 = np.minimum(x2[i], x2[order[1:]])
            yy2 = np.minimum(y2[i], y2[order[1:]])
            w = np.maximum(0, xx2 - xx1)
            h = np.maximum(0, yy2 - yy1)
            iou = w * h / (areas[i] + areas[order[1:]] - w * h + 1e-9)
            order = order[1:][iou <= iou_threshold]
        return keep

    def detect_cars(self, frame):
        """Run car detection on a frame."""
        # Preprocess the frame for car detection (assuming 640x640 input)
        img_input, img_width, img_height = self.preprocess_image(frame, target_size=(640, 640))
        
        # Run inference using TensorRT
        outputs = self.car_model.infer(img_input)
        detections = outputs[0][0]  # Shape: (25200, 6) -> [x, y, w, h, conf, class_score]
        
        # Filter detections by confidence
        conf_threshold = 0.25
        scores = detections[:, 4]
        valid = scores > conf_threshold
        boxes = detections[valid, :4]  # [x, y, w, h]
        scores = scores[valid]
        
        if len(boxes) == 0:
            return [], img_width, img_height
        
        # Apply NMS to remove overlapping boxes
        keep = self.nms(boxes, scores)
        boxes = boxes[keep]
        scores = scores[keep]
        
        # Scale boxes back to original image size
        boxes[:, [0, 2]] *= img_width / 640
        boxes[:, [1, 3]] *= img_height / 640
        return boxes, img_width, img_height

    def detect_number_plate(self, roi):
        """Run number plate detection on a cropped region."""
        # Preprocess the ROI for number plate detection (requires 640x640 input)
        img_input, img_width, img_height = self.preprocess_image(roi, target_size=(640, 640))
        
        # Run inference using TensorRT
        outputs = self.number_plate_model.infer(img_input)
        detections = outputs[0][0]
        
        # Filter detections by confidence
        conf_threshold = 0.25
        scores = detections[:, 4]
        valid = scores > conf_threshold
        boxes = detections[valid, :4]
        scores = scores[valid]
        
        if len(boxes) == 0:
            return None, img_width, img_height
        
        # Apply NMS
        keep = self.nms(boxes, scores)
        boxes = boxes[keep]
        scores = scores[keep]
        
        # Scale boxes back to ROI size
        boxes[:, [0, 2]] *= img_width / 640
        boxes[:, [1, 3]] *= img_height / 640
        return boxes[0], img_width, img_height  # Return the first detection

    def extract_number_plate_text(self, roi):
        """Extract text from number plate ROI using OCR."""
        try:
            # Preprocess for OCR: Convert to grayscale and apply thresholding
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
            
            # Use Tesseract OCR with a configuration optimized for number plates
            config = '--psm 8 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
            text = pytesseract.image_to_string(thresh, config=config)
            return text.strip()
        except Exception as e:
            print(f"OCR failed: {e}")
            return None