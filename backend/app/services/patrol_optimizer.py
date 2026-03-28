"""
Project Netra — Patrol Optimizer
Adaptive Predictive Patrol with time-weighted heat maps.
"""

import time
import logging
import math
from typing import List, Dict, Optional
from datetime import datetime
from collections import defaultdict

logger = logging.getLogger("netra.patrol")


class PatrolOptimizer:
    """
    Generates optimized patrol routes based on historical detection data.
    
    Key innovation: Time-bucketed heat maps that weight patrol waypoints
    by detection density — the camera spends more time watching areas
    where threats have historically appeared at the current time of day.
    """

    # Time buckets
    TIME_BUCKETS = {
        "early_morning": (5, 8),
        "morning": (8, 12),
        "afternoon": (12, 17),
        "evening": (17, 21),
        "night": (21, 1),
        "late_night": (1, 5),
    }

    # Grid resolution for heat map
    GRID_ROWS = 3
    GRID_COLS = 4

    def __init__(self):
        # Heat map: {time_bucket: {(row, col): count}}
        self.heat_maps: Dict[str, Dict[tuple, float]] = defaultdict(lambda: defaultdict(float))
        
        # Detection log for trend analysis
        self.detection_log: List[dict] = []
        
        # Current optimized route
        self.current_route: List[dict] = []
        
        # Settings
        self.base_dwell_ms = 2000
        self.min_dwell_ms = 500
        self.max_dwell_ms = 8000
        self.decay_factor = 0.95  # Heat decay per hour

    def record_detection(self, pan: int, tilt: int, class_name: str, 
                          confidence: float, camera_id: int = 1):
        """
        Record a detection to update heat maps.
        
        Args:
            pan: Servo pan angle (0-180) where detection occurred
            tilt: Servo tilt angle (30-150)
            class_name: Detected object class
            confidence: Detection confidence
            camera_id: Camera node ID
        """
        now = datetime.now()
        bucket = self._get_time_bucket(now.hour)
        
        # Map pan/tilt to grid cell
        col = min(int(pan / 180 * self.GRID_COLS), self.GRID_COLS - 1)
        row = min(int((tilt - 30) / 120 * self.GRID_ROWS), self.GRID_ROWS - 1)
        
        # Weight by class importance
        weight = self._class_weight(class_name) * confidence
        
        # Update heat map
        self.heat_maps[bucket][(row, col)] += weight
        
        # Log detection
        self.detection_log.append({
            "timestamp": now.isoformat(),
            "bucket": bucket,
            "row": row,
            "col": col,
            "class": class_name,
            "weight": weight,
            "camera_id": camera_id,
        })
        
        # Keep log manageable
        if len(self.detection_log) > 5000:
            self.detection_log = self.detection_log[-5000:]
        
        logger.debug(f"Detection recorded: ({row},{col}) bucket={bucket} weight={weight:.2f}")

    def generate_route(self, camera_id: int = 1) -> List[dict]:
        """
        Generate an optimized patrol route for the current time of day.
        
        Returns:
            List of waypoints: [{"pan": int, "tilt": int, "dwell": int, "priority": float}]
        """
        current_bucket = self._get_time_bucket(datetime.now().hour)
        heat_map = self.heat_maps.get(current_bucket, {})
        
        if not heat_map:
            # No data for this time — return default coverage route
            return self._default_route()
        
        # Apply decay to old data
        self._apply_decay()
        
        # Sort zones by heat value (highest first)
        sorted_zones = sorted(heat_map.items(), key=lambda x: x[1], reverse=True)
        
        # Calculate total heat for normalization
        total_heat = sum(v for _, v in sorted_zones) or 1
        
        # Generate waypoints — all zones get visited, hot zones get more dwell time
        waypoints = []
        for (row, col), heat_value in sorted_zones:
            # Convert grid cell to servo angles
            pan = int((col + 0.5) / self.GRID_COLS * 180)
            tilt = int((row + 0.5) / self.GRID_ROWS * 120 + 30)
            
            # Dwell time proportional to heat
            priority = heat_value / total_heat
            dwell = int(self.base_dwell_ms + priority * (self.max_dwell_ms - self.base_dwell_ms))
            dwell = max(self.min_dwell_ms, min(self.max_dwell_ms, dwell))
            
            waypoints.append({
                "pan": pan,
                "tilt": tilt,
                "dwell": dwell,
                "priority": round(priority, 3),
                "heat": round(heat_value, 1),
            })
        
        # Add cold zones (not in heat map) with minimum dwell
        for row in range(self.GRID_ROWS):
            for col in range(self.GRID_COLS):
                if (row, col) not in heat_map:
                    pan = int((col + 0.5) / self.GRID_COLS * 180)
                    tilt = int((row + 0.5) / self.GRID_ROWS * 120 + 30)
                    waypoints.append({
                        "pan": pan,
                        "tilt": tilt,
                        "dwell": self.min_dwell_ms,
                        "priority": 0.0,
                        "heat": 0.0,
                    })
        
        # Optimize route order (nearest-neighbor TSP)
        optimized = self._optimize_route_order(waypoints)
        
        self.current_route = optimized
        logger.info(f"Generated patrol route: {len(optimized)} waypoints for bucket '{current_bucket}'")
        
        return optimized

    def get_heat_map(self, time_bucket: Optional[str] = None) -> dict:
        """
        Get heat map data for visualization.
        
        Returns:
            {"grid_rows": int, "grid_cols": int, "bucket": str, "cells": [...]}
        """
        if time_bucket is None:
            time_bucket = self._get_time_bucket(datetime.now().hour)
        
        heat_map = self.heat_maps.get(time_bucket, {})
        
        cells = []
        max_heat = max(heat_map.values()) if heat_map else 1
        
        for row in range(self.GRID_ROWS):
            for col in range(self.GRID_COLS):
                value = heat_map.get((row, col), 0)
                cells.append({
                    "row": row,
                    "col": col,
                    "value": round(value, 1),
                    "normalized": round(value / max_heat, 3) if max_heat > 0 else 0,
                })
        
        return {
            "grid_rows": self.GRID_ROWS,
            "grid_cols": self.GRID_COLS,
            "bucket": time_bucket,
            "cells": cells,
            "total_detections": len(self.detection_log),
        }

    def get_all_heat_maps(self) -> dict:
        """Get heat maps for all time buckets."""
        return {
            bucket: self.get_heat_map(bucket)
            for bucket in self.TIME_BUCKETS
        }

    def _default_route(self) -> List[dict]:
        """Default sweep route when no heat map data exists."""
        waypoints = []
        # Sweep left to right at multiple tilt levels
        for row in range(self.GRID_ROWS):
            cols = range(self.GRID_COLS) if row % 2 == 0 else range(self.GRID_COLS - 1, -1, -1)
            for col in cols:
                pan = int((col + 0.5) / self.GRID_COLS * 180)
                tilt = int((row + 0.5) / self.GRID_ROWS * 120 + 30)
                waypoints.append({
                    "pan": pan,
                    "tilt": tilt,
                    "dwell": self.base_dwell_ms,
                    "priority": 1.0 / (self.GRID_ROWS * self.GRID_COLS),
                    "heat": 0,
                })
        return waypoints

    def _optimize_route_order(self, waypoints: List[dict]) -> List[dict]:
        """Nearest-neighbor optimization to minimize servo travel."""
        if len(waypoints) <= 2:
            return waypoints
        
        remaining = list(range(len(waypoints)))
        ordered = [remaining.pop(0)]
        
        while remaining:
            last = waypoints[ordered[-1]]
            best_idx = min(remaining, key=lambda i: 
                abs(waypoints[i]["pan"] - last["pan"]) + 
                abs(waypoints[i]["tilt"] - last["tilt"]))
            ordered.append(best_idx)
            remaining.remove(best_idx)
        
        return [waypoints[i] for i in ordered]

    def _apply_decay(self):
        """Apply exponential decay to heat maps."""
        for bucket in self.heat_maps:
            for key in list(self.heat_maps[bucket].keys()):
                self.heat_maps[bucket][key] *= self.decay_factor
                if self.heat_maps[bucket][key] < 0.01:
                    del self.heat_maps[bucket][key]

    def _get_time_bucket(self, hour: int) -> str:
        """Map hour to time bucket."""
        for bucket, (start, end) in self.TIME_BUCKETS.items():
            if start <= end:
                if start <= hour < end:
                    return bucket
            else:  # Wraps midnight
                if hour >= start or hour < end:
                    return bucket
        return "night"

    def _class_weight(self, class_name: str) -> float:
        """Weight detection by object class importance."""
        weights = {
            "person": 2.0,
            "car": 1.5,
            "truck": 1.5,
            "motorcycle": 1.3,
            "bicycle": 1.0,
            "dog": 0.5,
            "cat": 0.3,
            "bird": 0.1,
        }
        return weights.get(class_name, 1.0)

    def get_stats(self) -> dict:
        """Get optimizer stats."""
        return {
            "total_detections": len(self.detection_log),
            "active_buckets": len(self.heat_maps),
            "current_bucket": self._get_time_bucket(datetime.now().hour),
            "current_route_length": len(self.current_route),
        }
