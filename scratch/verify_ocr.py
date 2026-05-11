try:
    import easyocr
    import numpy as np
    import cv2
    from PIL import Image
    print("SUCCESS: All OCR dependencies are available.")
except ImportError as e:
    print(f"FAILURE: Missing dependency: {e}")
except Exception as e:
    print(f"FAILURE: Error during import: {e}")
