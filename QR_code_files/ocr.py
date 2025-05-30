import cv2
import numpy as np
import easyocr
import imutils
import re

def correct_by_position(ocr_str):
    # Remove unwanted characters
    ocr_str = re.sub(r'[^A-Za-z0-9]', '', ocr_str).upper()
    #print(ocr_str)
    # Correction maps
    digit_to_alpha = {'0': 'O', '1': 'I', '2': 'Z', '4':'A','5': 'S', '8': 'B', '6': 'G'}
    alpha_to_digit = {'O': '0', 'I': '1', 'Z': '2', 'S': '5', 'B': '8', 'G': '6', 'Q': '0', 'L': '1','E':'6','J':'3',']':'3'}

    # Fillers
    letters = []
    digits = []

    # Stage-wise extraction
    i = 0
    # 1. First 2 letters
    while len(letters) < 2 and i < len(ocr_str):
        ch = ocr_str[i]
        if ch.isalpha():
            letters.append(ch)
        elif ch in digit_to_alpha:
            letters.append(digit_to_alpha[ch])
        i += 1

    # 2. Next 2 digits
    while len(digits) < 2 and i < len(ocr_str):
        ch = ocr_str[i]
        if ch.isdigit():
            digits.append(ch)
        elif ch in alpha_to_digit:
            digits.append(alpha_to_digit[ch])
        i += 1
    if(len(ocr_str)==10):
        # 3. Next 1 or 2 letters
        while len(letters) < 4 and i < len(ocr_str):
            ch = ocr_str[i]
            if ch.isalpha():
                letters.append(ch)
            elif ch in digit_to_alpha:
                letters.append(digit_to_alpha[ch])
            i += 1

    
    elif(len(ocr_str)==9):
        # Next 1 letter
        while len(letters) < 3 and i < len(ocr_str):
            ch = ocr_str[i]
            if ch.isalpha():
                letters.append(ch)
            elif ch in digit_to_alpha:
                letters.append(digit_to_alpha[ch])
            i += 1
    
    # 4. Last 4 digits
    while len(digits) < 6 and i < len(ocr_str):
        ch = ocr_str[i]
        if ch.isdigit():
            digits.append(ch)
        elif ch in alpha_to_digit:
            digits.append(alpha_to_digit[ch])
        i += 1

    if len(letters) < 3 or len(digits) < 6:
        return "Could not parse correctly"

    # Construct final format
    part1 = ''.join(letters[:2])
    part2 = ''.join(digits[:2])
    part3 = ''.join(letters[2:4])
    part4 = ''.join(digits[2:6])

    return part1 + part2 + part3 + part4


def process_image(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 11, 17, 17)
    thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                                   cv2.THRESH_BINARY_INV, 31, 2)

    keypoints = cv2.findContours(thresh.copy(), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    contours = imutils.grab_contours(keypoints)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:10]

    plate_contour = None
    for contour in contours: 
        approx = cv2.approxPolyDP(contour, 10, True)
        x, y, w, h = cv2.boundingRect(approx)
        aspect_ratio = w / float(h)
        if 2 < aspect_ratio < 6 and 500 < cv2.contourArea(contour) < 15000:
            plate_contour = approx
            break

    if plate_contour is not None:
        mask = np.zeros(gray.shape, np.uint8)
        new_image = cv2.drawContours(mask, [plate_contour], 0, 255, -1)
        new_image = cv2.bitwise_and(image, image, mask=mask)
        (x, y) = np.where(mask == 255)
        (x1, y1) = (np.min(x), np.min(y))
        (x2, y2) = (np.max(x), np.max(y))
        cropped_image = gray[x1:x2+1, y1:y2+1]

        reader = easyocr.Reader(['en'])
        result = reader.readtext(cropped_image)
        return result[0][-2] if result else "No text detected"
    
    return "No plate detected"


