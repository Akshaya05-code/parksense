import cv2
import pytesseract
import numpy as np
from pathlib import Path

pytesseract.pytesseract.tesseract_cmd = "/usr/bin/tesseract"

class NumberPlateExtractor:
    """Class to extract text from number plate images using pytesseract."""
    
    def __init__(self, tesseract_cmd=None):
        """
        Initialize the NumberPlateExtractor.
        
        Args:
            tesseract_cmd (str, optional): Path to tesseract executable if required.
        """
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = "/usr/bin/tesseract"
    
    def preprocess_plate(self, img):
        """Preprocess the number plate image to improve OCR accuracy.
        
        Args:
            img (np.ndarray): Input image of the number plate.
        
        Returns:
            np.ndarray: Preprocessed image.
        """
        try:
            # Convert to grayscale
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            # Apply adaptive thresholding
            thresh = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                cv2.THRESH_BINARY_INV, 11, 2
            )
            # Apply slight Gaussian blur to reduce noise
            blurred = cv2.GaussianBlur(thresh, (3, 3), 0)
            return blurred
        except Exception as e:
            print(f"Error in preprocessing number plate: {e}")
            return None
    
    def extract_text(self, img):
        """Extract text from a number plate image using pytesseract.
        
        Args:
            img (np.ndarray): Input image of the number plate.
        
        Returns:
            str: Extracted text or None if extraction fails.
        """
        try:
            preprocessed = self.preprocess_plate(img)
            if preprocessed is None:
                print("Preprocessing returned None.")
                return None
            
            # Save preprocessed image for debugging
            cv2.imwrite("preprocessed_plate.jpg", preprocessed)
            print("Preprocessed image saved as preprocessed_plate.jpg")
            
            # Configure tesseract for alphanumeric characters
            custom_config = r'--oem 3 --psm 8 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
            text = pytesseract.image_to_string(preprocessed, config=custom_config)
            print(f"Raw OCR output: '{text}'")
            text = text.strip().replace('\n', '').replace(' ', '')
            
            # Basic validation: check if text is reasonable (e.g., length > 2)
            if len(text) > 2 and any(c.isalnum() for c in text):
                return text
            print("Text validation failed: too short or no alphanumeric characters.")
            return None
        except Exception as e:
            print(f"Error extracting text from number plate: {e}")
            return None
    
    def process_plate(self, img, box):
        """Crop the number plate region and extract text.
        
        Args:
            img (np.ndarray): Original image containing the number plate.
            box (list): Bounding box [x1, y1, x2, y2] for the number plate.
        
        Returns:
            str: Extracted number plate text or None if extraction fails.
        """
        try:
            x1, y1, x2, y2 = map(int, box)
            # Ensure coordinates are within image bounds
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(img.shape[1], x2), min(img.shape[0], y2)
            if x2 <= x1 or y2 <= y1:
                print("Invalid bounding box dimensions.")
                return None
            
            # Crop the number plate region
            plate_img = img[y1:y2, x1:x2]
            if plate_img.size == 0:
                print("Empty cropped image.")
                return None
            
            # Save cropped image for debugging
            cv2.imwrite("cropped_plate.jpg", plate_img)
            print("Cropped image saved as cropped_plate.jpg")
            
            return self.extract_text(plate_img)
        except Exception as e:
            print(f"Error processing number plate: {e}")
            return None

if __name__ == "__main__":
    try:
        # Initialize the extractor with the correct Tesseract path
        extractor = NumberPlateExtractor(tesseract_cmd=r"/usr/bin/tesseract")
        
        # Load the sample image using absolute path
        sample_image_path = "../captured_images/car1.jpg"
        img = cv2.imread(sample_image_path)
        if img is None:
            print(f"Failed to load sample image: {sample_image_path}")
            exit(1)
        
        # Set bounding box to entire image size
        height, width = img.shape[:2]
        sample_box = [0, 0, width, height]
        print(f"Image dimensions: {width}x{height}, Using sample_box: {sample_box}")
        
        # Process the number plate
        plate_text = extractor.process_plate(img, sample_box)
        if plate_text:
            print(f"Extracted number plate text: {plate_text}")
        else:
            print("Failed to extract number plate text.")
            
    except Exception as e:
        print(f"Error in test: {e}")
