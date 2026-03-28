"""
Project Netra — MQTT Bridge
Bridges MQTT messages between ESP32 nodes and the FastAPI backend.
"""

import json
import logging
import threading
from typing import Optional, Callable

import paho.mqtt.client as mqtt

logger = logging.getLogger("netra.mqtt")

# Default MQTT settings
MQTT_BROKER = "localhost"
MQTT_PORT = 1883

# Topics
TOPICS = {
    "servo_cmd": "netra/+/servo/cmd",
    "servo_status": "netra/+/servo/status",
    "detection": "netra/+/detection",
    "status": "netra/+/status",
    "patrol_cmd": "netra/+/patrol/cmd",
    "mesh_event": "netra/mesh/event",
    "edge_config": "netra/+/edge/config",
}


class MQTTBridge:
    """
    Bridges MQTT ↔ FastAPI backend.
    Subscribes to ESP32 telemetry, publishes commands.
    """

    def __init__(self, app=None, broker: str = MQTT_BROKER, port: int = MQTT_PORT):
        self.app = app
        self.broker = broker
        self.port = port
        self.client = mqtt.Client(client_id="netra_backend", protocol=mqtt.MQTTv311)
        self.connected = False
        
        # Message handlers
        self._handlers: dict = {}
        
        # Camera status cache
        self.camera_status: dict = {}
        
        # Setup callbacks
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    def connect(self):
        """Connect to MQTT broker in a background thread."""
        try:
            self.client.connect(self.broker, self.port, keepalive=60)
            self.client.loop_start()
            logger.info(f"MQTT connecting to {self.broker}:{self.port}")
        except Exception as e:
            logger.warning(f"MQTT connection failed: {e} — running without MQTT")

    def disconnect(self):
        """Disconnect from MQTT broker."""
        self.client.loop_stop()
        self.client.disconnect()
        self.connected = False
        logger.info("MQTT disconnected")

    def is_connected(self) -> bool:
        return self.connected

    # --- Publishing ---

    def send_servo_command(self, camera_id: int, direction: str, value: int = 5):
        """Send servo move command to a camera node."""
        topic = f"netra/cam{camera_id:02d}/servo/cmd"
        payload = json.dumps({"direction": direction, "value": value})
        self.client.publish(topic, payload)
        logger.info(f"Servo cmd → {topic}: {direction} ({value})")

    def send_patrol_command(self, camera_id: int, action: str, 
                             waypoints: Optional[list] = None):
        """Send patrol command to a camera node."""
        topic = f"netra/cam{camera_id:02d}/patrol/cmd"
        payload = {"action": action}
        if waypoints:
            payload["waypoints"] = waypoints
        self.client.publish(topic, json.dumps(payload))
        logger.info(f"Patrol cmd → {topic}: {action}")

    def send_edge_config(self, camera_id: int, config: dict):
        """Send edge processing config to a camera node."""
        topic = f"netra/cam{camera_id:02d}/edge/config"
        self.client.publish(topic, json.dumps(config))
        logger.info(f"Edge config → {topic}: {config}")

    # --- Message Handlers ---

    def on_camera_status(self, handler: Callable):
        """Register handler for camera status updates."""
        self._handlers["status"] = handler

    def on_detection(self, handler: Callable):
        """Register handler for edge detection events."""
        self._handlers["detection"] = handler

    def on_mesh_event(self, handler: Callable):
        """Register handler for mesh events."""
        self._handlers["mesh"] = handler

    def on_servo_status(self, handler: Callable):
        """Register handler for servo position updates."""
        self._handlers["servo"] = handler

    # --- Internal Callbacks ---

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.connected = True
            logger.info("✅ MQTT connected to broker")
            
            # Subscribe to all relevant topics
            self.client.subscribe("netra/#")
            logger.info("Subscribed to netra/#")
        else:
            logger.error(f"MQTT connection failed: rc={rc}")

    def _on_disconnect(self, client, userdata, rc):
        self.connected = False
        if rc != 0:
            logger.warning(f"MQTT disconnected unexpectedly: rc={rc}")

    def _on_message(self, client, userdata, msg):
        try:
            topic = msg.topic
            payload = json.loads(msg.payload.decode())
            
            # Extract camera ID from topic (netra/camXX/...)
            parts = topic.split("/")
            camera_id = None
            if len(parts) >= 2:
                cam_str = parts[1]
                if cam_str.startswith("cam"):
                    try:
                        camera_id = int(cam_str[3:])
                    except ValueError:
                        pass
            
            # Route to appropriate handler
            if "status" in topic and "servo" not in topic:
                self._handle_status(camera_id, payload)
                if "status" in self._handlers:
                    self._handlers["status"](camera_id, payload)
                    
            elif "servo/status" in topic:
                if "servo" in self._handlers:
                    self._handlers["servo"](camera_id, payload)
                    
            elif "detection" in topic:
                if "detection" in self._handlers:
                    self._handlers["detection"](camera_id, payload)
                    
            elif "mesh/event" in topic:
                if "mesh" in self._handlers:
                    self._handlers["mesh"](payload)
                    
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON on topic {msg.topic}")
        except Exception as e:
            logger.error(f"Error handling MQTT message: {e}")

    def _handle_status(self, camera_id: Optional[int], payload: dict):
        """Update camera status cache."""
        if camera_id is not None:
            self.camera_status[camera_id] = {
                **payload,
                "camera_id": camera_id,
                "online": True,
            }

    def get_camera_status(self, camera_id: int) -> Optional[dict]:
        """Get cached camera status."""
        return self.camera_status.get(camera_id)

    def get_all_cameras(self) -> dict:
        """Get all camera statuses."""
        return self.camera_status
