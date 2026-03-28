"""
Project Netra — Continuous Frame Grabber
Pulls MJPEG frames from ESP32-CAM and runs the full detection pipeline:
YOLO Detection → Object Tracking → Anomaly Scoring → Patrol Update → WebSocket Broadcast

Runs as an asyncio background task during FastAPI lifespan.
"""

import asyncio
import time
import logging
from typing import Optional

import cv2
import numpy as np
import httpx

logger = logging.getLogger("netra.grabber")


class FrameGrabber:
    """
    Continuously grabs frames from ESP32-CAM MJPEG stream and
    processes them through the full Netra detection pipeline.
    """

    def __init__(self, app):
        self.app = app
        self._task: Optional[asyncio.Task] = None
        self._running = False

        # Performance tracking
        self.fps = 0.0
        self.frame_count = 0
        self.total_detections = 0
        self.last_fps_time = time.time()

        # Configuration
        self.target_fps = 10          # Max frames to process per second
        self.confidence = 0.4         # YOLO confidence threshold
        self.skip_empty_frames = True # Don't broadcast if no detections

    def start(self):
        """Start the frame grabber background task."""
        if self._task is None or self._task.done():
            self._running = True
            self._task = asyncio.create_task(self._run_loop())
            logger.info("🎬 Frame grabber started")

    def stop(self):
        """Stop the frame grabber."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("🛑 Frame grabber stopped")

    @property
    def is_running(self) -> bool:
        return self._running and self._task is not None and not self._task.done()

    async def _run_loop(self):
        """Main loop: connect to MJPEG stream, grab frames, process."""
        min_frame_interval = 1.0 / self.target_fps  # seconds between frames

        while self._running:
            camera_ip = getattr(self.app.state, 'camera_ip', '')
            if not camera_ip:
                logger.debug("No camera IP configured — waiting...")
                await asyncio.sleep(3)
                continue

            stream_url = f"http://{camera_ip}:81/stream"
            logger.info(f"📡 Connecting to MJPEG stream: {stream_url}")

            try:
                await self._stream_and_process(stream_url, min_frame_interval)
            except httpx.ConnectError:
                logger.warning(f"Cannot reach camera at {camera_ip} — retrying in 5s")
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                logger.info("Frame grabber cancelled")
                break
            except Exception as e:
                logger.error(f"Frame grabber error: {e} — retrying in 3s")
                await asyncio.sleep(3)

    async def _stream_and_process(self, stream_url: str, min_interval: float):
        """Connect to MJPEG stream and process frames."""
        async with httpx.AsyncClient(timeout=httpx.Timeout(10, read=None)) as client:
            async with client.stream("GET", stream_url) as response:
                logger.info("✅ Connected to camera stream")
                buffer = b""

                async for chunk in response.aiter_bytes(chunk_size=4096):
                    if not self._running:
                        break

                    buffer += chunk

                    # Find JPEG frame boundaries in MJPEG stream
                    # JPEG starts with FFD8, ends with FFD9
                    start = buffer.find(b'\xff\xd8')
                    end = buffer.find(b'\xff\xd9')

                    if start != -1 and end != -1 and end > start:
                        # Extract complete JPEG frame
                        jpeg_bytes = buffer[start:end + 2]
                        buffer = buffer[end + 2:]

                        # Rate limit processing
                        frame_start = time.time()

                        # Process frame through pipeline
                        await self._process_frame(jpeg_bytes)

                        # FPS tracking
                        self.frame_count += 1
                        now = time.time()
                        if now - self.last_fps_time >= 3.0:
                            self.fps = self.frame_count / (now - self.last_fps_time)
                            logger.info(
                                f"📊 Pipeline: {self.fps:.1f} FPS | "
                                f"Total detections: {self.total_detections}"
                            )
                            self.frame_count = 0
                            self.last_fps_time = now

                        # Throttle to target FPS
                        elapsed = time.time() - frame_start
                        sleep_time = min_interval - elapsed
                        if sleep_time > 0:
                            await asyncio.sleep(sleep_time)

    async def _process_frame(self, jpeg_bytes: bytes):
        """Run full detection pipeline on a single JPEG frame."""
        yolo = self.app.state.yolo
        tracker = self.app.state.tracker
        anomaly = self.app.state.anomaly
        patrol = self.app.state.patrol

        if not yolo:
            return

        # Decode JPEG → numpy array (run in executor to avoid blocking event loop)
        loop = asyncio.get_event_loop()
        frame = await loop.run_in_executor(
            None, self._decode_and_detect, jpeg_bytes, yolo
        )

        if frame is None:
            return

        detections, np_frame = frame

        # Step 2: Update object tracker
        tracked_objects = tracker.update(detections)

        # Step 3: Anomaly scoring
        anomaly_scores = anomaly.score_all_tracks(tracked_objects)

        # Step 4: Record detections for patrol heat map
        for det in detections:
            bbox = det["bbox"]
            center_x = (bbox[0] + bbox[2]) / 2
            pan_estimate = int(center_x / np_frame.shape[1] * 180)
            tilt_estimate = 90
            patrol.record_detection(
                pan_estimate, tilt_estimate,
                det["class_name"], det["confidence"], camera_id=1
            )

        # Step 5: Get alerts
        alerts = anomaly.get_alerts(tracked_objects)

        self.total_detections += len(detections)

        # Step 6: Broadcast to all WebSocket clients
        if detections or not self.skip_empty_frames:
            await self._broadcast_ws({
                "type": "detection",
                "data": {
                    "camera_id": 1,
                    "detections": detections,
                    "tracked_objects": tracked_objects,
                    "anomaly_scores": anomaly_scores,
                    "alerts": alerts,
                    "timestamp": time.time(),
                    "fps": round(self.fps, 1),
                }
            })

    def _decode_and_detect(self, jpeg_bytes: bytes, yolo) -> tuple:
        """Decode JPEG and run YOLO detection (runs in thread executor)."""
        nparr = np.frombuffer(jpeg_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if frame is None:
            return None

        detections = yolo.detect(frame, self.confidence)
        return (detections, frame)

    async def _broadcast_ws(self, data: dict):
        """Send data to all connected WebSocket clients."""
        ws_clients = getattr(self.app.state, 'ws_clients', set())
        if not ws_clients:
            return

        disconnected = set()
        for ws in ws_clients:
            try:
                await ws.send_json(data)
            except Exception:
                disconnected.add(ws)

        # Clean up dead connections
        for ws in disconnected:
            ws_clients.discard(ws)

    def get_stats(self) -> dict:
        """Get frame grabber performance stats."""
        return {
            "running": self.is_running,
            "fps": round(self.fps, 1),
            "target_fps": self.target_fps,
            "total_detections": self.total_detections,
            "confidence_threshold": self.confidence,
        }
