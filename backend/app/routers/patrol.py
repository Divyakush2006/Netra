"""
Project Netra — Patrol Router
Endpoints for patrol route management and heat map visualization.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Request, HTTPException
from app.models.schemas import PatrolConfig, PatrolWaypoint

logger = logging.getLogger("netra.api.patrol")
router = APIRouter()


@router.get("/route/{camera_id}")
async def get_patrol_route(camera_id: int, request: Request):
    """Get current or optimized patrol route for a camera."""
    optimizer = request.app.state.patrol
    route = optimizer.generate_route(camera_id)
    return {
        "camera_id": camera_id,
        "route": route,
        "waypoint_count": len(route),
        "stats": optimizer.get_stats(),
    }


@router.post("/route/{camera_id}")
async def set_patrol_route(camera_id: int, config: PatrolConfig, request: Request):
    """Set custom patrol route or mode."""
    mqtt = request.app.state.mqtt
    
    if config.mode == "adaptive":
        # Generate optimized route from heat map
        optimizer = request.app.state.patrol
        waypoints = optimizer.generate_route(camera_id)
    elif config.mode == "auto" and config.waypoints:
        waypoints = [w.dict() for w in config.waypoints]
    else:
        waypoints = None
    
    if mqtt and mqtt.is_connected():
        if config.mode == "manual":
            mqtt.send_patrol_command(camera_id, "stop")
        else:
            mqtt.send_patrol_command(camera_id, "set_route", waypoints)
            mqtt.send_patrol_command(camera_id, "start")
        
        return {"status": "patrol_configured", "mode": config.mode, "waypoints": len(waypoints) if waypoints else 0}
    else:
        raise HTTPException(503, "MQTT not connected")


@router.post("/start/{camera_id}")
async def start_patrol(camera_id: int, request: Request):
    """Start patrol on a camera."""
    mqtt = request.app.state.mqtt
    if mqtt and mqtt.is_connected():
        mqtt.send_patrol_command(camera_id, "start")
        return {"status": "patrol_started", "camera_id": camera_id}
    raise HTTPException(503, "MQTT not connected")


@router.post("/stop/{camera_id}")
async def stop_patrol(camera_id: int, request: Request):
    """Stop patrol on a camera."""
    mqtt = request.app.state.mqtt
    if mqtt and mqtt.is_connected():
        mqtt.send_patrol_command(camera_id, "stop")
        return {"status": "patrol_stopped", "camera_id": camera_id}
    raise HTTPException(503, "MQTT not connected")


# ==========================================
# Heat Map
# ==========================================

@router.get("/heatmap")
async def get_heatmap(request: Request, time_bucket: Optional[str] = None):
    """Get heat map data for a specific time bucket (or current)."""
    optimizer = request.app.state.patrol
    return optimizer.get_heat_map(time_bucket)


@router.get("/heatmap/all")
async def get_all_heatmaps(request: Request):
    """Get heat maps for all time buckets."""
    optimizer = request.app.state.patrol
    return optimizer.get_all_heat_maps()


@router.get("/stats")
async def patrol_stats(request: Request):
    """Get patrol optimizer statistics."""
    optimizer = request.app.state.patrol
    return optimizer.get_stats()
