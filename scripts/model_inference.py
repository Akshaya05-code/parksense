import cv2
import numpy as np
from pathlib import Path

class ModelInference:
    """Class to perform inference using car and number plate detection models."""
    
    def __init__(self, model_loader, conf_threshold=0.5, iou_threshold=0.45):
        """
        Initialize the ModelInference with a ModelLoader instance.
        
        Args:
            model_loader: Instance of ModelLoader with loaded ONNX models.
            conf_threshold (float): Confidence threshold for detections.
            iou_threshold (float): IoU threshold for Non-Maximum Suppression.
        """
        self.model_loader = model_loader
        self.conf_threshold = conf_threshold
        self.iou_threshold = iou_threshold
    
    def nms(self, boxes, scores, iou_threshold):
        """Apply Non-Maximum Suppression to filter overlapping bounding boxes.
        
        Args:
            boxes (np.ndarray): Array of bounding boxes [x1, y1, x2, y2].
            scores (np.ndarray): Confidence scores for each box.
            iou_threshold (float): IoU threshold for suppression.
        
        Returns:
            list: Indices of boxes to keep after NMS.
        """
        if len(boxes) == 0:
            return []
        x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
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
            inter = w * h
            iou = inter / (areas[i] + areas[order[1:]] - inter)
            inds = np.where(iou <= iou_threshold)[0]
            order = order[inds + 1]
        return keep
    
    def preprocess_image(self, img_path, input_size=(640, 640)):
        """Preprocess an image for model inference.
        
        Args:
            img_path (str): Path to the input image.
            input_size (tuple): Target size for resizing (width, height).
        
        Returns:
            tuple: (original image, preprocessed image, original height, original width)
        
        Raises:
            FileNotFoundError: If image file is not found.
        """
        img_orig = cv2.imread(str(img_path))
        if img_orig is None:
            raise FileNotFoundError(f"Could not load image: {img_path}")
        img_height, img_width = img_orig.shape[:2]
        img = cv2.resize(img_orig, input_size)  # Resize to model input size
        img = img.transpose(2, 0, 1)  # HWC to CHW
        img = img[np.newaxis, ...] / 255.0  # Add batch dimension and normalize
        img = img.astype(np.float32)
        return img_orig, img, img_height, img_width
    
    def run_inference(self, session, input_name, img):
        """Run inference on a model session.
        
        Args:
            session: ONNX Runtime inference session.
            input_name (str): Name of the model input.
            img (np.ndarray): Preprocessed input image.
        
        Returns:
            np.ndarray: Model output.
        """
        return session.run(None, {input_name: img})[0]
    
    def postprocess_detections(self, outputs, img_height, img_width, num_classes):
        """Post-process model outputs to extract bounding boxes, scores, and class IDs.
        
        Args:
            outputs (np.ndarray): Model output [batch, num_boxes, num_classes + 5].
            img_height (int): Original image height.
            img_width (int): Original image width.
            num_classes (int): Number of classes in the model.
        
        Returns:
            tuple: (boxes, scores, class_ids)
        """
        boxes = []
        scores = []
        class_ids = []
        
        for detection in outputs[0]:  # Iterate over detections
            confidence = detection[4]  # Objectness score
            if confidence > self.conf_threshold:
                class_scores = detection[5:]  # Class probabilities
                class_id = np.argmax(class_scores)
                class_score = class_scores[class_id]
                if class_score * confidence > self.conf_threshold:
                    # Extract and scale bounding box
                    center_x, center_y, width, height = detection[0:4]
                    x1 = (center_x - width / 2) * img_width / 640
                    y1 = (center_y - height / 2) * img_height / 640
                    x2 = (center_x + width / 2) * img_width / 640
                    y2 = (center_y + height / 2) * img_height / 640
                    boxes.append([x1, y1, x2, y2])
                    scores.append(confidence * class_score)
                    class_ids.append(class_id)
        
        return np.array(boxes), np.array(scores), class_ids
    
    def draw_detections(self, img, boxes, scores, class_ids, prefix=""):
        """Draw bounding boxes and labels on the image.
        
        Args:
            img (np.ndarray): Original image to draw on.
            boxes (np.ndarray): Bounding boxes [x1, y1, x2, y2].
            scores (np.ndarray): Confidence scores.
            class_ids (list): Class IDs for each detection.
            prefix (str): Prefix for labels (e.g., 'Car' or 'NP').
        
        Returns:
            np.ndarray: Image with drawn bounding boxes.
        """
        for i, box in enumerate(boxes):
            x1, y1, x2, y2 = box.astype(int)
            cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), 2)
            label = f"{prefix} Class {class_ids[i]}: {scores[i]:.2f}"
            cv2.putText(img, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
        return img
    
    def infer(self, img_path, output_path):
        """Perform inference on an image using both car and number plate models.
        
        Args:
            img_path (str): Path to the input image.
            output_path (str): Path to save the output image with detections.
        
        Returns:
            tuple: (car_boxes, car_scores, car_class_ids, np_boxes, np_scores, np_class_ids)
        
        Raises:
            RuntimeError: If output image cannot be saved.
        """
        # Preprocess image
        img_orig, img, img_height, img_width = self.preprocess_image(img_path)
        
        # Run car detection
        car_session = self.model_loader.get_car_session()
        car_input_name = self.model_loader.get_car_input_name()
        car_outputs = self.run_inference(car_session, car_input_name, img)
        car_num_classes = car_outputs.shape[2] - 5  # Infer number of classes
        car_boxes, car_scores, car_class_ids = self.postprocess_detections(
            car_outputs, img_height, img_width, car_num_classes
        )
        car_keep = self.nms(car_boxes, car_scores, self.iou_threshold) if len(car_boxes) > 0 else []
        car_boxes = car_boxes[car_keep]
        car_scores = car_scores[car_keep]
        car_class_ids = [car_class_ids[i] for i in car_keep]
        
        # Run number plate detection
        np_session = self.model_loader.get_np_session()
        np_input_name = self.model_loader.get_np_input_name()
        np_outputs = self.run_inference(np_session, np_input_name, img)
        np_num_classes = np_outputs.shape[2] - 5  # Infer number of classes
        np_boxes, np_scores, np_class_ids = self.postprocess_detections(
            np_outputs, img_height, img_width, np_num_classes
        )
        np_keep = self.nms(np_boxes, np_scores, self.iou_threshold) if len(np_boxes) > 0 else []
        np_boxes = np_boxes[np_keep]
        np_scores = np_scores[np_keep]
        np_class_ids = [np_class_ids[i] for i in np_keep]
        
        # Draw detections
        img_orig = self.draw_detections(img_orig, car_boxes, car_scores, car_class_ids, prefix="Car")
        img_orig = self.draw_detections(img_orig, np_boxes, np_scores, np_class_ids, prefix="NP")
        
        # Save output
        if not cv2.imwrite(str(output_path), img_orig):
            raise RuntimeError(f"Failed to save output image: {output_path}")
        print(f"Output saved as {output_path}")
        
        return car_boxes, car_scores, car_class_ids, np_boxes, np_scores, np_class_ids

if __name__ == "__main__":
    from model_loader import ModelLoader
    
    # Example usage for testing
    model_loader = ModelLoader(
        car_model_path="../models/car.onnx",
        np_model_path="../models//np.onnx"
    )
    inference = ModelInference(model_loader)
    car_boxes, car_scores, car_class_ids, np_boxes, np_scores, np_class_ids = inference.infer(
        img_path="../captured_images/car1.jpg",
        output_path="../captured_images/output.jpg"
    )
    print("Car detections:", len(car_boxes))
    print("Number plate detections:", len(np_boxes))
