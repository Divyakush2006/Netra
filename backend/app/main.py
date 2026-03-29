"""
Project Netra — FastAPI Backend Server
Main entry point with WebSocket support, CORS, and startup hooks.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.routers import camera, detection, patrol, alerts
from app.services.mqtt_bridge import MQTTBridge
from app.services.auto_tracker import AutoTracker
from app.services.yolo_engine import YOLOEngine
from app.services.tracker import ObjectTracker
from app.services.anomaly import AnomalyEngine
from app.services.patrol_optimizer import PatrolOptimizer
from app.database.db import init_db

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("netra")


# ==========================================
# Shared Application State
# ==========================================
class AppState:
    """Shared state accessible from all routers via app.state"""
    mqtt: MQTTBridge = None
    yolo: YOLOEngine = None
    tracker: ObjectTracker = None
    anomaly: AnomalyEngine = None
    patrol: PatrolOptimizer = None
    connected_cameras: dict = {}
    ws_clients: set = set()
    # ESP32 IPs — camera streams from one, servo control on another
    camera_ip: str = "10.154.46.161"    # ESP32-CAM (MJPEG stream)
    servo_ip: str = "10.154.46.39"     # ESP32 DevKit (servo/PTZ control)


# ==========================================
# Lifespan (startup & shutdown)
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🛡️ Project Netra Backend Starting...")

    # Initialize database
    await init_db()
    logger.info("✅ Database initialized")

    # Initialize YOLO engine
    app.state.yolo = YOLOEngine()
    logger.info("✅ YOLO engine loaded")

    # Initialize object tracker
    app.state.tracker = ObjectTracker()
    logger.info("✅ Object tracker ready")

    # Initialize anomaly engine
    app.state.anomaly = AnomalyEngine()
    logger.info("✅ Anomaly engine ready")

    # Initialize patrol optimizer
    app.state.patrol = PatrolOptimizer()
    logger.info("✅ Patrol optimizer ready")

    # Initialize MQTT bridge
    app.state.mqtt = MQTTBridge(app)
    app.state.mqtt.connect()
    logger.info("✅ MQTT bridge connected")

    # Initialize auto-tracker
    app.state.auto_tracker = AutoTracker(app)
    logger.info("✅ Auto-tracker ready")

    # Shared state
    app.state.connected_cameras = {}
    app.state.ws_clients = set()

    # Set default ESP32 IPs so dashboard gets them on first load
    app.state.camera_ip = AppState.camera_ip
    app.state.servo_ip = AppState.servo_ip

    logger.info("🚀 Project Netra Backend Ready!")
    logger.info("📡 Dashboard: http://localhost:5173")
    logger.info("📖 API Docs: http://localhost:8000/docs")

    yield

    # Shutdown
    logger.info("🛑 Shutting down...")
    if app.state.mqtt:
        app.state.mqtt.disconnect()


# ==========================================
# FastAPI App
# ==========================================
app = FastAPI(
    title="Project Netra",
    description="Intelligent Adaptive Surveillance System — Backend API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow dashboard to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(camera.router, prefix="/api/camera", tags=["Camera"])
app.include_router(detection.router, prefix="/api/detection", tags=["Detection"])
app.include_router(patrol.router, prefix="/api/patrol", tags=["Patrol"])
app.include_router(alerts.router, prefix="/api/alerts", tags=["Alerts"])


# ==========================================
# Health Check
# ==========================================
@app.get("/")
async def root():
    return {
        "name": "Project Netra",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "docs": "/docs",
            "camera": "/api/camera",
            "detection": "/api/detection",
            "patrol": "/api/patrol",
            "alerts": "/api/alerts",
        }
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "yolo_loaded": app.state.yolo is not None,
        "mqtt_connected": app.state.mqtt.is_connected() if app.state.mqtt else False,
        "active_cameras": len(app.state.connected_cameras),
    }
