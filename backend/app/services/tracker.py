"""
Project Netra — Object Tracker
Multi-object tracking using simplified DeepSORT-style tracking.
Maintains track IDs, trajectories, velocities, and dwell times.
"""

import time
import logging
import math
from typing import List, Dict, Optional, Tuple
from collections import defaultdict

import numpy as np

logger = logging.getLogger("netra.tracker")


class Track:
    """A single tracked object."""
    
    _next_id = 1

    def __init__(self, bbox: List[float], class_name: str, confidence: float):
        self.track_id = Track._next_id
        Track._next_id += 1
        
        self.class_name = class_name
        self.confidence = confidence
        self.bbox = bbox  # [x1, y1, x2, y2]
        
        # Position history
        self.center = self._bbox_center(bbox)
        self.trajectory: List[Tuple[float, float, float]] = [(self.center[0], self.center[1], time.time())]
        
        # Timing
        self.first_seen = time.time()
        self.last_seen = time.time()
        self.age = 0  # Frames since creation
        self.hits = 1  # Times detected
        self.misses = 0  # Consecutive frames missed
        
        # Velocity (pixels per second)
        self.velocity = [0.0, 0.0]
        
        # Dwell tracking
        self.dwell_start_pos = self.center
        self.dwell_time = 0.0  # Seconds staying roughly in same spot
        self.dwell_threshold = 50  # Pixels — if moved less than this, still "dwelling"
        
        # Zone
        self.current_zone: Optional[str] = None
        self.zone_history: List[str] = []

    def update(self, bbox: List[float], confidence: float):
        """Update track with new detection."""
        now = time.time()
        old_center = self.center
        
        self.bbox = bbox
        self.confidence = confidence
        self.center = self._bbox_center(bbox)
        self.trajectory.append((self.center[0], self.center[1], now))
        
        # Keep trajectory limited
        if len(self.trajectory) > 300:
            self.trajectory = self.trajectory[-300:]
        
        # Calculate velocity
        dt = now - self.last_seen
        if dt > 0:
            self.velocity = [
                (self.center[0] - old_center[0]) / dt,
                (self.center[1] - old_center[1]) / dt,
            ]
        
        # Update dwell time
        dist_from_dwell_start = math.sqrt(
            (self.center[0] - self.dwell_start_pos[0]) ** 2 +
            (self.center[1] - self.dwell_start_pos[1]) ** 2
        )
        
        if dist_from_dwell_start <= self.dwell_threshold:
            self.dwell_time = now - self.first_seen if self.dwell_time == 0 else self.dwell_time + dt
        else:
            # Object moved significantly — reset dwell
            self.dwell_start_pos = self.center
            self.dwell_time = 0
        
        self.last_seen = now
        self.age += 1
        self.hits += 1
        self.misses = 0

    def mark_missed(self):
        """Mark track as not detected in current frame."""
        self.misses += 1
        self.age += 1

    def get_speed(self) -> float:
        """Get current speed in pixels/second."""
        return math.sqrt(self.velocity[0] ** 2 + self.velocity[1] ** 2)

    def get_direction_changes(self, window: int = 10) -> int:
        """Count direction changes in recent trajectory."""
        if len(self.trajectory) < 3:
            return 0
        
        recent = self.trajectory[-window:]
        changes = 0
        
        for i in range(2, len(recent)):
            dx1 = recent[i-1][0] - recent[i-2][0]
            dy1 = recent[i-1][1] - recent[i-2][1]
            dx2 = recent[i][0] - recent[i-1][0]
            dy2 = recent[i][1] - recent[i-1][1]
            
            # Cross product sign change = direction change
            cross = dx1 * dy2 - dy1 * dx2
            if abs(cross) > 5:  # Threshold for meaningful change
                changes += 1
        
        return changes

    def get_path_curvature(self) -> float:
        """Estimate path curvature (0=straight, higher=more curved)."""
        if len(self.trajectory) < 3:
            return 0.0
        
        # Compare actual path length to straight-line distance
        total_dist = 0
        for i in range(1, len(self.trajectory)):
            dx = self.trajectory[i][0] - self.trajectory[i-1][0]
            dy = self.trajectory[i][1] - self.trajectory[i-1][1]
            total_dist += math.sqrt(dx*dx + dy*dy)
        
        if total_dist < 1:
            return 0.0
        
        # Straight-line distance from first to last point
        dx = self.trajectory[-1][0] - self.trajectory[0][0]
        dy = self.trajectory[-1][1] - self.trajectory[0][1]
        straight_dist = math.sqrt(dx*dx + dy*dy)
        
        if straight_dist < 1:
            return 10.0  # Circular motion (high curvature)
        
        return (total_dist / straight_dist) - 1.0

    def to_dict(self) -> dict:
        """Convert to dictionary for API response."""
        return {
            "track_id": self.track_id,
            "class_name": self.class_name,
            "confidence": self.confidence,
            "bbox": self.bbox,
            "center": list(self.center),
            "velocity": self.velocity,
            "speed": round(self.get_speed(), 1),
            "dwell_time": round(self.dwell_time, 1),
            "direction_changes": self.get_direction_changes(),
            "path_curvature": round(self.get_path_curvature(), 2),
            "trajectory": [[p[0], p[1]] for p in self.trajectory[-50:]],
            "zone": self.current_zone,
            "alive_time": round(time.time() - self.first_seen, 1),
        }

    @staticmethod
    def _bbox_center(bbox: List[float]) -> Tuple[float, float]:
        return ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)


class ObjectTracker:
    """
    Multi-object tracker using IoU-based association.
    Maintains unique track IDs across frames.
    """

    def __init__(self, max_misses: int = 15, iou_threshold: float = 0.3):
        self.tracks: Dict[int, Track] = {}
        self.max_misses = max_misses
        self.iou_threshold = iou_threshold
        self.frame_count = 0

    def update(self, detections: List[dict]) -> List[dict]:
        """
        Update tracks with new detections.
        
        Args:
            detections: List of {"class_name", "confidence", "bbox"}
            
        Returns:
            List of tracked object dicts with IDs and trajectories
        """
        self.frame_count += 1
        
        if not detections:
            # Mark all tracks as missed
            for track in list(self.tracks.values()):
                track.mark_missed()
                if track.misses > self.max_misses:
                    del self.tracks[track.track_id]
            return [t.to_dict() for t in self.tracks.values()]

        # Compute IoU matrix between existing tracks and new detections
        track_list = list(self.tracks.values())
        
        if not track_list:
            # No existing tracks — create new ones for all detections
            for det in detections:
                track = Track(det["bbox"], det["class_name"], det["confidence"])
                self.tracks[track.track_id] = track
        else:
            # IoU matching
            iou_matrix = np.zeros((len(track_list), len(detections)))
            
            for i, track in enumerate(track_list):
                for j, det in enumerate(detections):
                    iou_matrix[i, j] = self._compute_iou(track.bbox, det["bbox"])
            
            # Greedy matching (simplified Hungarian)
            matched_tracks = set()
            matched_dets = set()
            
            while True:
                if iou_matrix.size == 0:
                    break
                max_iou = np.max(iou_matrix)
                if max_iou < self.iou_threshold:
                    break
                
                i, j = np.unravel_index(np.argmax(iou_matrix), iou_matrix.shape)
                
                track_list[i].update(detections[j]["bbox"], detections[j]["confidence"])
                matched_tracks.add(i)
                matched_dets.add(j)
                
                iou_matrix[i, :] = 0
                iou_matrix[:, j] = 0
            
            # Handle unmatched tracks
            for i, track in enumerate(track_list):
                if i not in matched_tracks:
                    track.mark_missed()
                    if track.misses > self.max_misses:
                        del self.tracks[track.track_id]
            
            # Create new tracks for unmatched detections
            for j, det in enumerate(detections):
                if j not in matched_dets:
                    track = Track(det["bbox"], det["class_name"], det["confidence"])
                    self.tracks[track.track_id] = track

        return [t.to_dict() for t in self.tracks.values()]

    def get_track(self, track_id: int) -> Optional[dict]:
        """Get a specific track by ID."""
        track = self.tracks.get(track_id)
        return track.to_dict() if track else None

    def get_all_tracks(self) -> List[dict]:
        """Get all active tracks."""
        return [t.to_dict() for t in self.tracks.values()]

    def clear(self):
        """Clear all tracks."""
        self.tracks.clear()

    @staticmethod
    def _compute_iou(box1: List[float], box2: List[float]) -> float:
        """Compute IoU between two bounding boxes."""
        x1 = max(box1[0], box2[0])
        y1 = max(box1[1], box2[1])
        x2 = min(box1[2], box2[2])
        y2 = min(box1[3], box2[3])

        intersection = max(0, x2 - x1) * max(0, y2 - y1)
        
        area1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
        area2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
        union = area1 + area2 - intersection

        return intersection / union if union > 0 else 0
