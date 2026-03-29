#ifndef CONFIG_H
#define CONFIG_H

// ============================================
// Project Netra — ESP32-CAM Configuration
// ============================================

// --- WiFi Configuration ---
#define WIFI_SSID       "Netra"
#define WIFI_PASSWORD   "12345678"

// --- MQTT Configuration ---
#define MQTT_BROKER     "10.154.46.244"    // Backend server IP
#define MQTT_PORT       1883
#define MQTT_USER       ""                 // Leave empty if no auth
#define MQTT_PASSWORD   ""
#define MQTT_CLIENT_ID  "netra_cam_01"

// --- MQTT Topics ---
#define TOPIC_SERVO_CMD       "netra/cam01/servo/cmd"
#define TOPIC_SERVO_STATUS    "netra/cam01/servo/status"
#define TOPIC_DETECTION       "netra/cam01/detection"
#define TOPIC_STATUS          "netra/cam01/status"
#define TOPIC_PATROL_CMD      "netra/cam01/patrol/cmd"
#define TOPIC_MESH_EVENT      "netra/mesh/event"
#define TOPIC_EDGE_CONFIG     "netra/cam01/edge/config"

// --- Camera Configuration ---
#define CAMERA_MODEL_AI_THINKER
#define FRAME_SIZE      FRAMESIZE_VGA     // 640x480
#define JPEG_QUALITY    12                 // 0-63 (lower = better quality)
#define STREAM_PORT     81

// --- Servo Pin Configuration (MG90S Metal Gear Servos) ---
#define SERVO_PAN_PIN   18                // GPIO for pan servo (D18)
#define SERVO_TILT_PIN  19                // GPIO for tilt servo (D19)

// --- Servo Limits (degrees) ---
#define PAN_MIN         0
#define PAN_MAX         180
#define PAN_CENTER      90
#define TILT_MIN        30                // Prevent over-tilt
#define TILT_MAX        150
#define TILT_CENTER     90

// --- Servo Speed (MG90S: metal gears, slightly slower response) ---
#define SERVO_STEP_DEGREES    3           // Degrees per movement command (lower = faster response)
#define SERVO_MOVE_DELAY_MS   8           // ms between steps (reduced for snappier joystick control)

// --- Edge Detection ---
#define MOTION_THRESHOLD      30          // Pixel difference threshold
#define MOTION_MIN_AREA       500         // Min changed pixels to trigger
#define FRAME_DIFF_INTERVAL   200         // ms between frame comparisons

// --- ESP-NOW Mesh ---
#define MESH_ENABLED          true
#define NODE_ID               1           // Unique ID for this node
#define MAX_MESH_NODES        8

// --- PIR Sensor (Optional) ---
#define PIR_PIN               13          // GPIO for PIR sensor
#define PIR_ENABLED           false

// --- Status LED ---
#define LED_PIN               33          // Built-in LED on AI-Thinker
#define LED_FLASH_PIN         4           // Flash LED

// --- Watchdog ---
#define WDT_TIMEOUT_S         30          // Watchdog timer seconds

// --- Buffer ---
#define MAX_FRAME_BUFFER      3           // Frames to buffer when network is poor

#endif // CONFIG_H
