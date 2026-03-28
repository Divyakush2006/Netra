"""
Project Netra — Behavioral Anomaly Signature Engine (BASE)
Multi-factor anomaly scoring for real-time threat assessment.
"""

import time
import logging
from typing import Dict, List, Optional
from datetime import datetime

logger = logging.getLogger("netra.anomaly")


class AnomalyEngine:
    """
    Computes real-time anomaly scores for tracked objects using
    multiple behavioral factors.
    
    Factors:
    1. Dwell Time — loitering in one area
    2. Speed Anomaly — moving too fast or too slow for context
    3. Path Curvature — circling, pacing (suspicious patterns)
    4. Direction Changes — erratic movement
    5. Zone Violation — being in a restricted area
    6. Time Anomaly — unusual activity for current time of day
    """

    # Factor weights (sum to 1.0)
    WEIGHTS = {
        "dwell": 0.25,
        "speed": 0.15,
        "curvature": 0.15,
        "direction": 0.10,
        "zone": 0.20,
        "time": 0.15,
    }

    # Thresholds
    DWELL_WARN_SECONDS = 60       # 1 min = start scoring
    DWELL_CRITICAL_SECONDS = 300  # 5 min = high score
    SPEED_MAX_NORMAL = 200        # pixels/sec — above = running
    SPEED_MIN_NORMAL = 5          # Below = stationary (potential loitering)
    CURVATURE_WARN = 2.0          # Path ratio > 2 = suspicious curvature
    DIRECTION_WARN = 5            # > 5 direction changes in window = erratic

    # Alert thresholds
    ALERT_THRESHOLD = 5.0         # Score > 5 triggers alert
    CRITICAL_THRESHOLD = 7.5      # Score > 7.5 = critical alert

    def __init__(self):
        self.restricted_zones: List[dict] = []
        self.quiet_hours = (23, 6)  # 11 PM to 6 AM = unusual activity
        self.score_history: Dict[int, List[dict]] = {}  # track_id → scores over time

    def set_restricted_zones(self, zones: List[dict]):
        """
        Set restricted zones.
        Each zone: {"name": "Server Room", "x1": 100, "y1": 100, "x2": 300, "y2": 300}
        """
        self.restricted_zones = zones
        logger.info(f"Set {len(zones)} restricted zones")

    def set_quiet_hours(self, start_hour: int, end_hour: int):
        """Set hours during which activity is considered unusual."""
        self.quiet_hours = (start_hour, end_hour)

    def score_track(self, track: dict) -> dict:
        """
        Compute anomaly score for a tracked object.
        
        Args:
            track: Dict from ObjectTracker.to_dict()
            
        Returns:
            {
                "track_id": int,
                "overall_score": float (0-10),
                "factors": {factor_name: individual_score},
                "threat_level": "low"|"medium"|"high"|"critical",
                "description": str
            }
        """
        factors = {}
        descriptions = []

        # --- 1. Dwell Time Score ---
        dwell = track.get("dwell_time", 0)
        if dwell > self.DWELL_CRITICAL_SECONDS:
            factors["dwell"] = 10.0
            descriptions.append(f"Loitering for {int(dwell)}s (critical)")
        elif dwell > self.DWELL_WARN_SECONDS:
            factors["dwell"] = min(10, (dwell / self.DWELL_CRITICAL_SECONDS) * 10)
            descriptions.append(f"Loitering for {int(dwell)}s")
        else:
            factors["dwell"] = 0.0

        # --- 2. Speed Anomaly ---
        speed = track.get("speed", 0)
        if speed > self.SPEED_MAX_NORMAL:
            factors["speed"] = min(10, (speed / self.SPEED_MAX_NORMAL) * 5)
            descriptions.append(f"Running (speed: {speed:.0f} px/s)")
        elif speed < self.SPEED_MIN_NORMAL and dwell > 30:
            factors["speed"] = 3.0  # Stationary but not yet loitering threshold
        else:
            factors["speed"] = 0.0

        # --- 3. Path Curvature ---
        curvature = track.get("path_curvature", 0)
        if curvature > self.CURVATURE_WARN:
            factors["curvature"] = min(10, (curvature / self.CURVATURE_WARN) * 5)
            descriptions.append(f"Suspicious movement pattern (curvature: {curvature:.1f})")
        else:
            factors["curvature"] = 0.0

        # --- 4. Direction Changes ---
        dir_changes = track.get("direction_changes", 0)
        if dir_changes > self.DIRECTION_WARN:
            factors["direction"] = min(10, (dir_changes / self.DIRECTION_WARN) * 5)
            descriptions.append(f"Erratic movement ({dir_changes} direction changes)")
        else:
            factors["direction"] = 0.0

        # --- 5. Zone Violation ---
        center = track.get("center", [0, 0])
        zone_score, violated_zone = self._check_zone_violation(center)
        factors["zone"] = zone_score
        if violated_zone:
            descriptions.append(f"In restricted zone: {violated_zone}")

        # --- 6. Time Anomaly ---
        time_score = self._check_time_anomaly()
        factors["time"] = time_score
        if time_score > 0:
            descriptions.append("Activity during unusual hours")

        # --- Compute Overall Score ---
        overall = sum(
            factors[k] * self.WEIGHTS[k] 
            for k in self.WEIGHTS
        )
        overall = round(min(10.0, overall), 1)

        # Determine threat level
        if overall >= self.CRITICAL_THRESHOLD:
            threat_level = "critical"
        elif overall >= self.ALERT_THRESHOLD:
            threat_level = "high"
        elif overall >= 3.0:
            threat_level = "medium"
        else:
            threat_level = "low"

        result = {
            "track_id": track.get("track_id", -1),
            "overall_score": overall,
            "factors": {k: round(v, 1) for k, v in factors.items()},
            "threat_level": threat_level,
            "description": "; ".join(descriptions) if descriptions else "Normal behavior",
        }

        # Store in history
        track_id = track.get("track_id", -1)
        if track_id not in self.score_history:
            self.score_history[track_id] = []
        self.score_history[track_id].append({
            "time": time.time(),
            "score": overall,
        })
        # Keep last 100 entries
        if len(self.score_history[track_id]) > 100:
            self.score_history[track_id] = self.score_history[track_id][-100:]

        return result

    def score_all_tracks(self, tracks: List[dict]) -> List[dict]:
        """Score multiple tracks at once."""
        return [self.score_track(t) for t in tracks]

    def get_alerts(self, tracks: List[dict]) -> List[dict]:
        """Get tracks that exceed the alert threshold."""
        scores = self.score_all_tracks(tracks)
        return [s for s in scores if s["overall_score"] >= self.ALERT_THRESHOLD]

    def get_score_history(self, track_id: int) -> List[dict]:
        """Get score history for a specific track."""
        return self.score_history.get(track_id, [])

    def _check_zone_violation(self, center: List[float]) -> tuple:
        """Check if position is in a restricted zone."""
        cx, cy = center
        for zone in self.restricted_zones:
            if (zone["x1"] <= cx <= zone["x2"] and 
                zone["y1"] <= cy <= zone["y2"]):
                return (10.0, zone.get("name", "Restricted"))
        return (0.0, None)

    def _check_time_anomaly(self) -> float:
        """Check if current time is within quiet hours."""
        current_hour = datetime.now().hour
        start, end = self.quiet_hours
        
        if start > end:  # Wraps midnight (e.g., 23 to 6)
            if current_hour >= start or current_hour < end:
                return 5.0
        else:
            if start <= current_hour < end:
                return 5.0
        return 0.0

    def get_stats(self) -> dict:
        """Get anomaly engine stats."""
        return {
            "active_tracks": len(self.score_history),
            "restricted_zones": len(self.restricted_zones),
            "quiet_hours": f"{self.quiet_hours[0]:02d}:00 - {self.quiet_hours[1]:02d}:00",
            "weights": self.WEIGHTS,
        }
