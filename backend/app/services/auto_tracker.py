"""
Project Netra — YOLO Auto-Tracking Service
Grabs frames from ESP32-CAM, runs YOLO detection,
and sends servo commands to keep the camera centered on a person.
"""

import asyncio
import logging
import time
import json
from typing import Optional

import httpx
import numpy as np
import cv2

logger = logging.getLogger("netra.tracker")


class AutoTracker:
    """
    Continuously grabs frames from ESP32-CAM, runs YOLO person detection,
    and adjusts servo pan/tilt to keep the target centered in frame.
    """

    # Frame dimensions (QVGA from ESP32-CAM)
    FRAME_W = 320
    FRAME_H = 240

    # Dead zone — don't move servo if target is within this % of center
    DEAD_ZONE_X = 0.12  # 12% of frame width
    DEAD_ZONE_Y = 0.12  # 12% of frame height

    # Servo step sizes (proportional control)
    MAX_STEP = 8       # Max servo step per adjustment
    MIN_STEP = 2       # Min servo step
    GAIN_X = 0.06      # Proportional gain for pan
    GAIN_Y = 0.06      # Proportional gain for tilt

    # Tracking interval
    TRACK_INTERVAL = 0.5  # seconds between tracking updates (2 FPS tracking)

    def __init__(self, app):
        self.app = app
        self.running = False
        self.task: Optional[asyncio.Task] = None

        # State
        self.target_locked = False
        self.last_detection = None
        self.frame_count = 0
        self.track_count = 0

    @property
    def camera_ip(self) -> str:
        return getattr(self.app.state, 'camera_ip', '')

    @property
    def servo_ip(self) -> str:
        return getattr(self.app.state, 'servo_ip', '')

    @property
    def yolo(self):
        return getattr(self.app.state, 'yolo', None)

    @property
    def mqtt(self):
        return getattr(self.app.state, 'mqtt', None)

    def start(self):
        """Start the auto-tracking loop."""
        if self.running:
            logger.warning("Auto-tracker already running")
            return

        self.running = True
        self.task = asyncio.create_task(self._tracking_loop())
        logger.info("🎯 Auto-tracker STARTED")

    def stop(self):
        """Stop the auto-tracking loop."""
        self.running = False
        self.target_locked = False
        if self.task:
            self.task.cancel()
            self.task = None
        logger.info("🛑 Auto-tracker STOPPED")

    async def _tracking_loop(self):
        """Main tracking loop — grab frame, detect, adjust servo."""
        logger.info(f"Tracking loop started — camera: {self.camera_ip}")
        loop = asyncio.get_event_loop()

        while self.running:
            try:
                # 1. Grab a snapshot from the ESP32-CAM
                frame = await self._grab_frame()
                if frame is None:
                    logger.debug("No frame captured, retrying...")
                    await asyncio.sleep(1)
                    continue

                self.frame_count += 1

                # 2. Run YOLO detection in thread pool (CPU-bound, don't block event loop)
                detections = await loop.run_in_executor(
                    None, self.yolo.detect, frame, 0.35
                )

                # 3. Find the best person to track
                person = self._pick_target(detections, frame.shape)

                # 4. Calculate servo adjustment
                if person:
                    self.target_locked = True
                    self.last_detection = person
                    self.track_count += 1

                    # Calculate offset from center
                    h, w = frame.shape[:2]
                    bbox = person["bbox"]
                    cx = (bbox[0] + bbox[2]) / 2  # Person center X
                    cy = (bbox[1] + bbox[3]) / 2  # Person center Y

                    # Normalize to [-1, 1] where 0 = center
                    offset_x = (cx - w / 2) / (w / 2)
                    offset_y = (cy - h / 2) / (h / 2)

                    # Send servo commands if outside dead zone
                    await self._adjust_servo(offset_x, offset_y)

                    # Push detection to dashboard via WebSocket
                    await self._broadcast_tracking(person, offset_x, offset_y, detections)

                    logger.info(f"🎯 Person at ({offset_x:+.2f}, {offset_y:+.2f}) — {len(detections)} detections")
                else:
                    if self.target_locked:
                        logger.info("❌ Target lost")
                    self.target_locked = False

                # Wait before next frame
                await asyncio.sleep(self.TRACK_INTERVAL)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Tracking error: {e}", exc_info=True)
                await asyncio.sleep(1)

        logger.info("Tracking loop ended")

    async def _grab_frame(self) -> Optional[np.ndarray]:
        """Grab a single JPEG frame from the ESP32-CAM snapshot endpoint."""
        if not self.camera_ip:
            return None

        # Try port 82 first (utility server), fall back to port 81
        urls = [
            f"http://{self.camera_ip}:82/snapshot",
            f"http://{self.camera_ip}:81/snapshot",
        ]

        async with httpx.AsyncClient() as client:
            for url in urls:
                try:
                    response = await client.get(url, timeout=3)
                    if response.status_code == 200:
                        nparr = np.frombuffer(response.content, np.uint8)
                        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                        return frame
                except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout):
                    continue

        return None

    def _pick_target(self, detections: list, frame_shape: tuple) -> Optional[dict]:
        """Pick the best person to track from detections."""
        persons = [d for d in detections if d["class_name"] == "person"]
        if not persons:
            return None

        # Pick the largest person (closest to camera)
        def bbox_area(d):
            b = d["bbox"]
            return (b[2] - b[0]) * (b[3] - b[1])

        return max(persons, key=bbox_area)

    async def _adjust_servo(self, offset_x: float, offset_y: float):
        """Send servo commands based on target offset from center."""
        # Dead zone check
        move_x = abs(offset_x) > self.DEAD_ZONE_X
        move_y = abs(offset_y) > self.DEAD_ZONE_Y

        if not move_x and not move_y:
            return  # Target is centered enough

        if move_x:
            # Proportional step size
            step = int(abs(offset_x) * self.MAX_STEP * self.GAIN_X / 0.06)
            step = max(self.MIN_STEP, min(step, self.MAX_STEP))

            direction = "right" if offset_x > 0 else "left"
            await self._send_servo_cmd(direction, step)

        if move_y:
            step = int(abs(offset_y) * self.MAX_STEP * self.GAIN_Y / 0.06)
            step = max(self.MIN_STEP, min(step, self.MAX_STEP))

            direction = "down" if offset_y > 0 else "up"
            await self._send_servo_cmd(direction, step)

    async def _send_servo_cmd(self, direction: str, value: int):
        """Send servo command — direct HTTP to servo ESP32 (fast) or MQTT (fallback)."""
        # Try direct HTTP to servo ESP32 first (faster)
        if self.servo_ip:
            try:
                async with httpx.AsyncClient() as client:
                    url = f"http://{self.servo_ip}:81/servo?dir={direction}&val={value}"
                    await client.get(url, timeout=1)
                    return
            except Exception:
                pass  # Fall through to MQTT

        # Fallback: MQTT
        if self.mqtt and self.mqtt.is_connected():
            self.mqtt.send_servo_command(1, direction, value)

    async def _broadcast_tracking(self, target: dict, offset_x: float,
                                    offset_y: float, all_detections: list):
        """Push tracking data to dashboard via WebSocket."""
        msg = {
            "type": "tracking",
            "data": {
                "target": target,
                "offset_x": round(offset_x, 3),
                "offset_y": round(offset_y, 3),
                "locked": True,
                "detections": all_detections,
                "frame_count": self.frame_count,
                "track_count": self.track_count,
            }
        }

        ws_clients = getattr(self.app.state, 'ws_clients', set())
        dead = set()
        for ws in ws_clients:
            try:
                await ws.send_json(msg)
            except Exception:
                dead.add(ws)
        ws_clients -= dead

    def get_status(self) -> dict:
        """Get tracker status."""
        return {
            "running": self.running,
            "target_locked": self.target_locked,
            "frame_count": self.frame_count,
            "track_count": self.track_count,
            "last_detection": self.last_detection,
        }
