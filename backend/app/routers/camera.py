"""
Project Netra — Camera Router
Endpoints for camera control, streaming, and status.
"""

import json
import logging
import subprocess
import httpx
from typing import Optional

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.models.schemas import ServoCommand, CameraConfig, CameraStatus

logger = logging.getLogger("netra.api.camera")
router = APIRouter()


class IPConfig(BaseModel):
    camera_ip: str = ""
    servo_ip: str = ""

MOSQUITTO_PUB = r"C:\Program Files\mosquitto\mosquitto_pub.exe"


def publish_mqtt_direct(topic: str, payload: dict):
    """Publish MQTT message directly via mosquitto_pub (reliable fallback)."""
    try:
        msg = json.dumps(payload)
        subprocess.run(
            [MOSQUITTO_PUB, "-h", "localhost", "-t", topic, "-m", msg],
            timeout=3, capture_output=True
        )
        logger.info(f"MQTT direct -> {topic}: {msg}")
        return True
    except Exception as e:
        logger.error(f"MQTT direct publish failed: {e}")
        return False


def send_servo(camera_id: int, direction: str, value: int = 5):
    """Send servo command via direct MQTT publish."""
    topic = f"netra/cam{camera_id:02d}/servo/cmd"
    payload = {"direction": direction, "value": value}
    return publish_mqtt_direct(topic, payload)


# ==========================================
# Camera Discovery & Status
# ==========================================

@router.get("/list")
async def list_cameras(request: Request):
    """List all known camera nodes."""
    mqtt = request.app.state.mqtt
    cameras = mqtt.get_all_cameras() if mqtt else {}
    return {"cameras": cameras, "count": len(cameras)}


# ==========================================
# Auto-Tracking (YOLO-powered)
# ==========================================

@router.post("/tracking/start")
async def start_tracking(request: Request):
    """Start YOLO auto-tracking — camera follows detected person."""
    tracker = getattr(request.app.state, 'auto_tracker', None)
    if not tracker:
        raise HTTPException(500, "Auto-tracker not initialized")
    tracker.start()
    return {"status": "started", "message": "YOLO auto-tracking active"}


@router.post("/tracking/stop")
async def stop_tracking(request: Request):
    """Stop YOLO auto-tracking."""
    tracker = getattr(request.app.state, 'auto_tracker', None)
    if not tracker:
        raise HTTPException(500, "Auto-tracker not initialized")
    tracker.stop()
    return {"status": "stopped"}


@router.get("/tracking/status")
async def tracking_status(request: Request):
    """Get auto-tracking status."""
    tracker = getattr(request.app.state, 'auto_tracker', None)
    if not tracker:
        return {"running": False}
    return tracker.get_status()


@router.get("/{camera_id}/status")
async def camera_status(camera_id: int, request: Request):
    """Get status of a specific camera."""
    mqtt = request.app.state.mqtt
    status = mqtt.get_camera_status(camera_id) if mqtt else None
    
    if status is None:
        return {"camera_id": camera_id, "status": "unknown", "message": "Camera not reporting via MQTT"}
    
    return status


@router.post("/register")
async def register_camera(camera_id: int, ip_address: str, name: str = "Camera"):
    """Manually register a camera node."""
    return {
        "camera_id": camera_id,
        "ip_address": ip_address,
        "name": name,
        "registered": True,
    }

# ==========================================
# IP Configuration (Camera + Servo)
# ==========================================

@router.get("/config/ips")
async def get_ip_config(request: Request):
    """Get current camera and servo ESP32 IPs."""
    return {
        "camera_ip": getattr(request.app.state, 'camera_ip', ''),
        "servo_ip": getattr(request.app.state, 'servo_ip', ''),
    }


@router.put("/config/ips")
async def set_ip_config(config: IPConfig, request: Request):
    """Set camera and servo ESP32 IPs at runtime."""
    if config.camera_ip:
        request.app.state.camera_ip = config.camera_ip
    if config.servo_ip:
        request.app.state.servo_ip = config.servo_ip
    logger.info(f"IPs updated — camera: {request.app.state.camera_ip}, servo: {request.app.state.servo_ip}")
    return {
        "status": "updated",
        "camera_ip": request.app.state.camera_ip,
        "servo_ip": request.app.state.servo_ip,
    }


# ==========================================
# Servo Control
# ==========================================

@router.post("/{camera_id}/servo")
async def control_servo(camera_id: int, command: ServoCommand, request: Request):
    """Send servo movement command to camera."""
    success = send_servo(camera_id, command.direction, command.value)
    if success:
        return {"status": "sent", "command": command.dict()}
    raise HTTPException(503, "Failed to send MQTT command")


@router.post("/{camera_id}/servo/center")
async def center_servo(camera_id: int, request: Request):
    """Center camera to default position."""
    success = send_servo(camera_id, "center", 0)
    if success:
        return {"status": "centered"}
    raise HTTPException(503, "Failed to send MQTT command")


# ==========================================
# Camera Configuration
# ==========================================

@router.post("/{camera_id}/config")
async def configure_camera(camera_id: int, config: CameraConfig, request: Request):
    """Update camera configuration."""
    topic = f"netra/cam{camera_id:02d}/edge/config"
    success = publish_mqtt_direct(topic, config.dict(exclude_none=True))
    if success:
        return {"status": "config_sent", "config": config.dict(exclude_none=True)}
    raise HTTPException(503, "Failed to send MQTT command")



# ==========================================
# Stream Proxy
# ==========================================

@router.get("/{camera_id}/stream")
async def proxy_stream(camera_id: int, request: Request):
    """Proxy MJPEG stream from ESP32-CAM through backend."""
    ip = getattr(request.app.state, 'camera_ip', '') or f"192.168.1.{100 + camera_id}"
    stream_url = f"http://{ip}:81/stream"
    logger.info(f"Proxying stream from {stream_url}")
    
    async def stream_generator():
        async with httpx.AsyncClient() as client:
            try:
                async with client.stream("GET", stream_url, timeout=None) as response:
                    async for chunk in response.aiter_bytes(chunk_size=4096):
                        yield chunk
            except httpx.ConnectError:
                yield b"Camera not reachable"
    
    return StreamingResponse(
        stream_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


@router.get("/{camera_id}/snapshot")
async def get_snapshot(camera_id: int, request: Request):
    """Get single frame from camera."""
    ip = getattr(request.app.state, 'camera_ip', '') or f"192.168.1.{100 + camera_id}"
    snapshot_url = f"http://{ip}:81/snapshot"
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(snapshot_url, timeout=5)
            return StreamingResponse(
                iter([response.content]),
                media_type="image/jpeg"
            )
        except httpx.ConnectError:
            raise HTTPException(503, f"Camera {camera_id} not reachable at {ip}")


@router.get("/{camera_id}/servo-direct")
async def proxy_servo_direct(camera_id: int, dir: str, val: int = 5, request: Request = None):
    """Proxy servo command via direct HTTP to the servo ESP32."""
    servo_ip = getattr(request.app.state, 'servo_ip', '') if request else ''
    if not servo_ip:
        raise HTTPException(400, "Servo IP not configured")
    
    servo_url = f"http://{servo_ip}:81/servo?dir={dir}&val={val}"
    logger.info(f"Proxying servo command to {servo_url}")
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(servo_url, timeout=5)
            return response.json()
        except httpx.ConnectError:
            raise HTTPException(503, f"Servo ESP32 not reachable at {servo_ip}")
        except Exception as e:
            raise HTTPException(500, f"Servo command failed: {str(e)}")


# ==========================================
# WebSocket for Real-time Updates
# ==========================================

@router.websocket("/ws")
async def camera_websocket(websocket: WebSocket):
    """WebSocket for real-time camera updates and detections."""
    await websocket.accept()
    
    app = websocket.app
    if hasattr(app.state, 'ws_clients'):
        app.state.ws_clients.add(websocket)
    
    logger.info(f"WebSocket client connected. Total: {len(app.state.ws_clients)}")
    
    try:
        while True:
            data = await websocket.receive_json()
            
            if data.get("type") == "servo_cmd":
                send_servo(
                    data.get("camera_id", 1),
                    data["direction"],
                    data.get("value", 5)
                )
            
            elif data.get("type") == "patrol_cmd":
                topic = f"netra/cam{data.get('camera_id', 1):02d}/patrol/cmd"
                payload = {"action": data["action"]}
                if data.get("waypoints"):
                    payload["waypoints"] = data["waypoints"]
                publish_mqtt_direct(topic, payload)
                    
    except WebSocketDisconnect:
        if hasattr(app.state, 'ws_clients'):
            app.state.ws_clients.discard(websocket)
        logger.info(f"WebSocket client disconnected. Total: {len(app.state.ws_clients)}")
