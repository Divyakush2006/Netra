"""
Project Netra — Pydantic Models / Schemas
Data models for API requests, responses, and internal data transfer.
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


# ==========================================
# Enums
# ==========================================
class ThreatLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AlertType(str, Enum):
    MOTION = "motion"
    PERSON = "person"
    VEHICLE = "vehicle"
    LOITERING = "loitering"
    ZONE_VIOLATION = "zone_violation"
    SPEED_ANOMALY = "speed_anomaly"
    BEHAVIOR_ANOMALY = "behavior_anomaly"
    MESH_HANDOFF = "mesh_handoff"


class PatrolMode(str, Enum):
    MANUAL = "manual"
    AUTO = "auto"
    ADAPTIVE = "adaptive"


# ==========================================
# Camera
# ==========================================
class ServoCommand(BaseModel):
    direction: str = Field(..., description="left, right, up, down, center, goto")
    value: int = Field(default=5, description="Step size or encoded pan/tilt for goto")


class CameraStatus(BaseModel):
    node_id: int
    online: bool
    ip_address: str
    pan: int
    tilt: int
    patrolling: bool
    network_quality: int
    edge_mode: bool
    uptime: int
    heap_free: int


class CameraConfig(BaseModel):
    resolution: Optional[int] = None
    quality: Optional[int] = None
    edge_mode: Optional[bool] = None


# ==========================================
# Detection
# ==========================================
class Detection(BaseModel):
    class_name: str
    confidence: float
    bbox: List[float] = Field(..., description="[x1, y1, x2, y2]")
    track_id: Optional[int] = None


class DetectionFrame(BaseModel):
    camera_id: int
    timestamp: datetime
    detections: List[Detection]
    frame_number: int


# ==========================================
# Tracking
# ==========================================
class TrackedObject(BaseModel):
    track_id: int
    class_name: str
    confidence: float
    bbox: List[float]
    center: List[float] = Field(..., description="[cx, cy]")
    velocity: List[float] = Field(default=[0, 0], description="[vx, vy] pixels/sec")
    dwell_time: float = Field(default=0, description="Time in seconds at current location")
    trajectory: List[List[float]] = Field(default=[], description="List of [x, y] positions")
    zone: Optional[str] = None


# ==========================================
# Anomaly
# ==========================================
class AnomalyScore(BaseModel):
    track_id: int
    overall_score: float = Field(..., ge=0, le=10)
    factors: dict = Field(default={}, description="Individual factor scores")
    threat_level: ThreatLevel
    description: str


class BehaviorProfile(BaseModel):
    track_id: int
    dwell_time: float
    avg_speed: float
    path_curvature: float
    direction_changes: int
    zone_violations: int
    time_anomaly: bool


# ==========================================
# Patrol
# ==========================================
class PatrolWaypoint(BaseModel):
    pan: int = Field(..., ge=0, le=180)
    tilt: int = Field(..., ge=30, le=150)
    dwell: int = Field(default=2000, description="Dwell time in ms")
    priority: float = Field(default=1.0, description="Priority weight for adaptive patrol")


class PatrolConfig(BaseModel):
    mode: PatrolMode
    waypoints: List[PatrolWaypoint] = []
    speed: int = Field(default=80, ge=1, le=100, description="Patrol speed %")
    adaptive_enabled: bool = False


# ==========================================
# Alert
# ==========================================
class Alert(BaseModel):
    id: Optional[int] = None
    timestamp: datetime = Field(default_factory=datetime.now)
    camera_id: int
    alert_type: AlertType
    threat_level: ThreatLevel
    score: float
    message: str
    track_id: Optional[int] = None
    acknowledged: bool = False
    snapshot_path: Optional[str] = None


# ==========================================
# Heat Map
# ==========================================
class HeatMapCell(BaseModel):
    row: int
    col: int
    value: float


class HeatMapData(BaseModel):
    camera_id: int
    grid_rows: int
    grid_cols: int
    cells: List[HeatMapCell]
    time_bucket: str = Field(description="morning, afternoon, evening, night")


# ==========================================
# Digital Twin
# ==========================================
class MapObject(BaseModel):
    track_id: int
    class_name: str
    x: float
    y: float
    velocity_x: float = 0
    velocity_y: float = 0
    anomaly_score: float = 0
    trail: List[List[float]] = []


class MapState(BaseModel):
    timestamp: datetime
    objects: List[MapObject]
    cameras: List[CameraStatus]
    active_alerts: int


# ==========================================
# WebSocket Messages
# ==========================================
class WSMessage(BaseModel):
    type: str  # detection, alert, camera_status, patrol_update, map_update
    data: dict
