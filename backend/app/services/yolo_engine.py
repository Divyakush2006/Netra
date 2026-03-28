"""
Project Netra — YOLOv8 Detection Engine
Runs YOLOv8 inference on camera frames.
"""

import logging
import time
from typing import List, Optional
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger("netra.yolo")

# Try to import ultralytics
try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False
    logger.warning("ultralytics not installed — YOLO engine will use mock detections")


class YOLOEngine:
    """YOLOv8 object detection engine."""

    # Classes we care about for surveillance
    THREAT_CLASSES = {
        0: "person",
        1: "bicycle",
        2: "car",
        3: "motorcycle",
        5: "bus",
        7: "truck",
        14: "bird",
        15: "cat",
        16: "dog",
        24: "backpack",
        25: "umbrella",
        26: "handbag",
        27: "tie",
        28: "suitcase",
        39: "bottle",
        56: "chair",
        63: "laptop",
        67: "cell phone",
    }

    def __init__(self, model_path: str = None):
        self.model = None
        self.model_path = model_path or self._find_model()
        self.inference_count = 0
        self.avg_inference_time = 0

        if YOLO_AVAILABLE and self.model_path:
            try:
                self.model = YOLO(self.model_path)
                logger.info(f"YOLO model loaded: {self.model_path}")
            except Exception as e:
                logger.error(f"Failed to load YOLO model: {e}")
        else:
            logger.info("Running in mock detection mode")

    def _find_model(self) -> Optional[str]:
        """Search for YOLO model file."""
        search_paths = [
            Path("yolov8n.pt"),
            Path("models/yolov8n.pt"),
            Path("../yolov8n.pt"),
        ]
        for p in search_paths:
            if p.exists():
                return str(p)
        
        # Auto-download yolov8n if ultralytics is available
        if YOLO_AVAILABLE:
            return "yolov8n.pt"  # Will auto-download
        return None

    def detect(self, frame: np.ndarray, confidence_threshold: float = 0.4) -> List[dict]:
        """
        Run detection on a single frame.
        
        Args:
            frame: BGR numpy array (OpenCV format)
            confidence_threshold: Minimum confidence to include
            
        Returns:
            List of detection dicts:
            [{"class_name": "person", "confidence": 0.92, "bbox": [x1, y1, x2, y2]}]
        """
        start_time = time.time()
        detections = []

        if self.model:
            # Real YOLO inference
            results = self.model(frame, verbose=False, conf=confidence_threshold)
            
            for result in results:
                boxes = result.boxes
                if boxes is not None:
                    for box in boxes:
                        cls_id = int(box.cls[0])
                        conf = float(box.conf[0])
                        x1, y1, x2, y2 = box.xyxy[0].tolist()
                        
                        class_name = self.THREAT_CLASSES.get(
                            cls_id, 
                            result.names.get(cls_id, f"class_{cls_id}")
                        )
                        
                        detections.append({
                            "class_name": class_name,
                            "confidence": round(conf, 3),
                            "bbox": [round(x1, 1), round(y1, 1), 
                                     round(x2, 1), round(y2, 1)],
                            "class_id": cls_id,
                        })
        else:
            # Mock detections for testing without YOLO
            detections = self._mock_detect(frame)

        # Track performance
        elapsed = time.time() - start_time
        self.inference_count += 1
        self.avg_inference_time = (
            (self.avg_inference_time * (self.inference_count - 1) + elapsed) 
            / self.inference_count
        )

        return detections

    def detect_from_jpeg(self, jpeg_bytes: bytes, confidence_threshold: float = 0.4) -> List[dict]:
        """Run detection on JPEG bytes (from ESP32-CAM)."""
        nparr = np.frombuffer(jpeg_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if frame is None:
            return []
        return self.detect(frame, confidence_threshold)

    def annotate_frame(self, frame: np.ndarray, detections: List[dict]) -> np.ndarray:
        """Draw detection boxes on frame."""
        annotated = frame.copy()
        
        for det in detections:
            x1, y1, x2, y2 = [int(v) for v in det["bbox"]]
            class_name = det["class_name"]
            conf = det["confidence"]
            
            # Color based on class
            if class_name == "person":
                color = (0, 255, 0)  # Green
            elif class_name in ("car", "truck", "bus", "motorcycle"):
                color = (255, 165, 0)  # Orange
            else:
                color = (0, 200, 255)  # Yellow
            
            # Draw box
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
            
            # Label
            label = f"{class_name} {conf:.2f}"
            label_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0]
            cv2.rectangle(annotated, (x1, y1 - label_size[1] - 10),
                          (x1 + label_size[0], y1), color, -1)
            cv2.putText(annotated, label, (x1, y1 - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)

        return annotated

    def _mock_detect(self, frame: np.ndarray) -> List[dict]:
        """Generate mock detections for testing without YOLO model."""
        h, w = frame.shape[:2]
        # Simple motion-based mock: detect bright regions as "persons"
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        detections = []
        for cnt in contours[:5]:  # Max 5 mock detections
            area = cv2.contourArea(cnt)
            if area > 500:
                x, y, bw, bh = cv2.boundingRect(cnt)
                detections.append({
                    "class_name": "person",
                    "confidence": 0.75,
                    "bbox": [float(x), float(y), float(x + bw), float(y + bh)],
                    "class_id": 0,
                })
        return detections

    def get_stats(self) -> dict:
        """Get engine performance stats."""
        return {
            "model_loaded": self.model is not None,
            "inference_count": self.inference_count,
            "avg_inference_ms": round(self.avg_inference_time * 1000, 1),
        }
