"""
Project Netra — Detection Router
Endpoints for YOLO detection, tracking, and anomaly scoring.
"""

import io
import time
import logging
from typing import Optional

import cv2
import numpy as np
from fastapi import APIRouter, Request, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse

logger = logging.getLogger("netra.api.detection")
router = APIRouter()


@router.post("/analyze")
async def analyze_frame(request: Request, file: UploadFile = File(...),
                         camera_id: int = 1, confidence: float = 0.4):
    """
    Analyze a single frame: YOLO detection → tracking → anomaly scoring.
    Upload a JPEG image and receive full analysis.
    """
    yolo = request.app.state.yolo
    tracker = request.app.state.tracker
    anomaly = request.app.state.anomaly
    patrol = request.app.state.patrol
    
    # Read uploaded image
    contents = await file.read()
    nparr = np.frombuffer(contents, np.uint8)
    frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    
    if frame is None:
        raise HTTPException(400, "Invalid image file")
    
    # Step 1: YOLO Detection
    detections = yolo.detect(frame, confidence)
    
    # Step 2: Object Tracking
    tracked_objects = tracker.update(detections)
    
    # Step 3: Anomaly Scoring
    anomaly_scores = anomaly.score_all_tracks(tracked_objects)
    
    # Step 4: Record detections for patrol optimizer
    for det in detections:
        bbox = det["bbox"]
        center_x = (bbox[0] + bbox[2]) / 2
        # Map center_x to approximate pan angle (assuming 640px width → 0-180 degrees)
        pan_estimate = int(center_x / frame.shape[1] * 180)
        tilt_estimate = 90  # Default
        patrol.record_detection(pan_estimate, tilt_estimate, 
                                 det["class_name"], det["confidence"], camera_id)
    
    # Step 5: Generate alerts
    alerts = anomaly.get_alerts(tracked_objects)
    
    # Broadcast to WebSocket clients
    if hasattr(request.app.state, 'ws_clients'):
        ws_data = {
            "type": "detection",
            "data": {
                "camera_id": camera_id,
                "detections": detections,
                "tracked_objects": tracked_objects,
                "anomaly_scores": anomaly_scores,
                "alerts": alerts,
                "timestamp": time.time(),
            }
        }
        for ws in list(request.app.state.ws_clients):
            try:
                await ws.send_json(ws_data)
            except Exception:
                request.app.state.ws_clients.discard(ws)
    
    return {
        "camera_id": camera_id,
        "frame_size": list(frame.shape[:2]),
        "detections": detections,
        "tracked_objects": tracked_objects,
        "anomaly_scores": anomaly_scores,
        "alerts": alerts,
        "yolo_stats": yolo.get_stats(),
    }


@router.post("/analyze/annotated")
async def analyze_annotated(request: Request, file: UploadFile = File(...),
                              confidence: float = 0.4):
    """Analyze frame and return annotated image with detection boxes."""
    yolo = request.app.state.yolo
    
    contents = await file.read()
    nparr = np.frombuffer(contents, np.uint8)
    frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    
    if frame is None:
        raise HTTPException(400, "Invalid image file")
    
    detections = yolo.detect(frame, confidence)
    annotated = yolo.annotate_frame(frame, detections)
    
    # Encode back to JPEG
    _, buffer = cv2.imencode('.jpg', annotated, [cv2.IMWRITE_JPEG_QUALITY, 90])
    
    return StreamingResponse(
        io.BytesIO(buffer.tobytes()),
        media_type="image/jpeg",
        headers={"X-Detections": str(len(detections))}
    )


@router.get("/tracks")
async def get_tracks(request: Request):
    """Get all currently active tracked objects."""
    tracker = request.app.state.tracker
    return {
        "tracks": tracker.get_all_tracks(),
        "count": len(tracker.tracks),
        "frame_count": tracker.frame_count,
    }


@router.get("/tracks/{track_id}")
async def get_track(track_id: int, request: Request):
    """Get details of a specific tracked object."""
    tracker = request.app.state.tracker
    track = tracker.get_track(track_id)
    
    if track is None:
        raise HTTPException(404, f"Track {track_id} not found")
    
    # Include anomaly score
    anomaly = request.app.state.anomaly
    score = anomaly.score_track(track)
    
    return {
        "track": track,
        "anomaly": score,
        "score_history": anomaly.get_score_history(track_id),
    }


@router.get("/anomaly/scores")
async def get_anomaly_scores(request: Request):
    """Get anomaly scores for all tracked objects."""
    tracker = request.app.state.tracker
    anomaly = request.app.state.anomaly
    
    tracks = tracker.get_all_tracks()
    scores = anomaly.score_all_tracks(tracks)
    
    return {
        "scores": scores,
        "alerts": [s for s in scores if s["overall_score"] >= 5.0],
        "stats": anomaly.get_stats(),
    }


@router.post("/anomaly/zones")
async def set_restricted_zones(request: Request, zones: list):
    """Set restricted zones for anomaly detection."""
    anomaly = request.app.state.anomaly
    anomaly.set_restricted_zones(zones)
    return {"status": "zones_updated", "count": len(zones)}


@router.get("/stats")
async def detection_stats(request: Request):
    """Get detection engine statistics."""
    yolo = request.app.state.yolo
    tracker = request.app.state.tracker
    anomaly = request.app.state.anomaly
    
    return {
        "yolo": yolo.get_stats(),
        "tracker": {
            "active_tracks": len(tracker.tracks),
            "total_frames": tracker.frame_count,
        },
        "anomaly": anomaly.get_stats(),
    }
