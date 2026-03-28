/*
 * ============================================
 * Project Netra — Intelligent Adaptive Surveillance
 * ESP32-CAM Main Firmware
 * ============================================
 * 
 * Features:
 * - MJPEG camera streaming over HTTP
 * - Pan/tilt servo control via MQTT
 * - Autonomous patrol mode with waypoints
 * - Edge motion detection (frame differencing)
 * - ESP-NOW mesh communication for multi-camera handoff
 * - Edge-cloud adaptive processing
 */

#include <WiFi.h>
#include <WebServer.h>
#include <esp_task_wdt.h>

#include "config.h"
#include "camera_stream.h"
#include "servo_control.h"
#include "mqtt_handler.h"
#include "edge_detect.h"
#include "mesh_comm.h"

// --- Global Objects ---
CameraStream camera;
ServoController servos;
MQTTHandler mqtt;
EdgeDetector edgeDetect;
MeshComm mesh;

WebServer streamServer(STREAM_PORT);

// --- State ---
bool wifiConnected = false;
bool edgeMode = false;              // True = process locally, False = stream to backend
unsigned long lastMeshHeartbeat = 0;
unsigned long lastEdgeCheck = 0;

// ===========================================
// WiFi Setup
// ===========================================
void setupWiFi() {
    Serial.printf("[WIFI] Connecting to %s", WIFI_SSID);
    WiFi.mode(WIFI_AP_STA);  // AP+STA for ESP-NOW compatibility
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    
    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 30) {
        delay(500);
        Serial.print(".");
        attempts++;
    }
    
    if (WiFi.status() == WL_CONNECTED) {
        wifiConnected = true;
        Serial.printf("\n[WIFI] Connected! IP: %s\n", WiFi.localIP().toString().c_str());
        Serial.printf("[WIFI] RSSI: %d dBm\n", WiFi.RSSI());
    } else {
        Serial.println("\n[WIFI] Connection failed! Running in offline mode.");
        wifiConnected = false;
    }
}

// ===========================================
// MJPEG Stream Handler
// ===========================================
void handleStream() {
    WiFiClient client = streamServer.client();
    
    String response = "HTTP/1.1 200 OK\r\n";
    response += "Content-Type: multipart/x-mixed-replace; boundary=frame\r\n\r\n";
    client.print(response);
    
    while (client.connected()) {
        camera_fb_t *fb = camera.captureFrame();
        if (!fb) {
            continue;
        }
        
        // Send MJPEG frame
        client.printf("--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n", fb->len);
        client.write(fb->buf, fb->len);
        client.print("\r\n");
        
        camera.releaseFrame(fb);
        // No delay — push frames as fast as possible
    }
}

void handleSnapshot() {
    camera_fb_t *fb = camera.captureFrame();
    if (!fb) {
        streamServer.send(500, "text/plain", "Camera capture failed");
        return;
    }
    
    streamServer.sendHeader("Content-Disposition", "inline; filename=snapshot.jpg");
    streamServer.send_P(200, "image/jpeg", (const char*)fb->buf, fb->len);
    camera.releaseFrame(fb);
}

void handleStatus() {
    String json = "{";
    json += "\"node_id\":" + String(NODE_ID);
    json += ",\"wifi_rssi\":" + String(WiFi.RSSI());
    json += ",\"network_quality\":" + String(mqtt.getNetworkQuality());
    json += ",\"heap\":" + String(ESP.getFreeHeap());
    json += ",\"uptime\":" + String(millis() / 1000);
    json += ",\"servo\":" + servos.getStatusJSON();
    json += ",\"edge_mode\":" + String(edgeMode ? "true" : "false");
    json += ",\"mqtt_connected\":" + String(mqtt.isConnected() ? "true" : "false");
    json += ",\"mesh_peers\":" + String(mesh.getActivePeerCount());
    json += "}";
    
    streamServer.sendHeader("Access-Control-Allow-Origin", "*");
    streamServer.send(200, "application/json", json);
}

// ===========================================
// MQTT Command Handlers
// ===========================================
void handleServoCommand(const char* direction, int value) {
    // Stop patrol if manual command received
    if (servos.getPatrolling()) {
        servos.stopPatrol();
    }
    
    String dir(direction);
    if (dir == "left")       servos.moveLeft();
    else if (dir == "right") servos.moveRight();
    else if (dir == "up")    servos.moveUp();
    else if (dir == "down")  servos.moveDown();
    else if (dir == "center") servos.center();
    else if (dir == "goto") {
        // value encodes pan*1000+tilt (e.g., 90045 = pan:90, tilt:45)
        int pan = value / 1000;
        int tilt = value % 1000;
        servos.moveTo(pan, tilt);
    }
    
    // Publish updated position
    mqtt.publishServoPosition(servos.getPan(), servos.getTilt(), servos.getPatrolling());
    Serial.printf("[CMD] Servo: %s → Pan:%d Tilt:%d\n", direction, servos.getPan(), servos.getTilt());
}

void handlePatrolCommand(const char* action, const char* payload) {
    String act(action);
    
    if (act == "start") {
        servos.startPatrol();
    } else if (act == "stop") {
        servos.stopPatrol();
    } else if (act == "set_route") {
        // Parse waypoints from payload JSON
        servos.clearPatrolRoute();
        StaticJsonDocument<1024> doc;
        DeserializationError err = deserializeJson(doc, payload);
        if (!err) {
            JsonArray arr = doc.as<JsonArray>();
            for (JsonObject wp : arr) {
                int pan = wp["pan"] | 90;
                int tilt = wp["tilt"] | 90;
                unsigned long dwell = wp["dwell"] | 2000;
                servos.addWaypoint(pan, tilt, dwell);
            }
            Serial.printf("[CMD] Patrol route set: %d waypoints\n", arr.size());
        }
    }
    
    mqtt.publishServoPosition(servos.getPan(), servos.getTilt(), servos.getPatrolling());
}

void handleEdgeConfig(const char* payload) {
    StaticJsonDocument<256> doc;
    DeserializationError err = deserializeJson(doc, payload);
    if (!err) {
        if (doc.containsKey("edge_mode")) {
            edgeMode = doc["edge_mode"];
            Serial.printf("[CMD] Edge mode: %s\n", edgeMode ? "ON" : "OFF");
        }
        if (doc.containsKey("resolution")) {
            int res = doc["resolution"];
            camera.setResolution((framesize_t)res);
        }
        if (doc.containsKey("quality")) {
            int q = doc["quality"];
            camera.setQuality(q);
        }
    }
}

// ===========================================
// Mesh Handoff Handler
// ===========================================
void handleMeshHandoff(uint8_t sourceNode, float bearing, 
                        uint8_t objectClass, float confidence) {
    Serial.printf("[MESH] Handoff from node %d: bearing=%.1f\n", sourceNode, bearing);
    
    // Convert bearing to servo position
    // Bearing 0-360 maps to pan angle based on camera mounting
    int panTarget = map((int)bearing, 0, 360, PAN_MIN, PAN_MAX);
    servos.moveTo(panTarget, TILT_CENTER);
    
    // Also relay to backend via MQTT
    mqtt.publishMeshEvent(sourceNode, "handoff", bearing, 
                           objectClass == 0 ? "person" : "vehicle");
}

// ===========================================
// Edge-Cloud Adaptive Processing
// ===========================================
void checkEdgeCloudBalance() {
    int networkQuality = mqtt.getNetworkQuality();
    
    if (networkQuality < 30 && !edgeMode) {
        // Network is poor → switch to edge processing
        edgeMode = true;
        camera.setResolution(FRAMESIZE_QVGA);  // Lower res for local processing
        Serial.println("[ECAP] Switched to EDGE mode (poor network)");
    } else if (networkQuality > 70 && edgeMode) {
        // Network is good → switch back to cloud processing
        edgeMode = false;
        camera.setResolution(FRAME_SIZE);       // Full res for backend YOLO
        Serial.println("[ECAP] Switched to CLOUD mode (good network)");
    }
}

// ===========================================
// Setup
// ===========================================
void setup() {
    Serial.begin(115200);
    Serial.println("\n\n=== Project Netra Starting ===\n");
    
    // Status LED
    pinMode(LED_PIN, OUTPUT);
    pinMode(LED_FLASH_PIN, OUTPUT);
    digitalWrite(LED_PIN, LOW);
    
    // Initialize camera (optional — continues without if not available)
    bool cameraAvailable = camera.begin();
    if (!cameraAvailable) {
        Serial.println("[CAM] Camera not found — running in servo-only mode");
        Serial.println("[CAM] Connect ESP32-CAM module to enable video streaming");
    }
    
    // Initialize servos
    servos.begin();
    
    // Connect WiFi
    setupWiFi();
    
    if (wifiConnected) {
        // Initialize MQTT
        mqtt.begin();
        mqtt.setServoCallback(handleServoCommand);
        mqtt.setPatrolCallback(handlePatrolCommand);
        mqtt.setEdgeConfigCallback(handleEdgeConfig);
        mqtt.connect();
        
        // Start MJPEG stream server (only if camera is available)
        if (cameraAvailable) {
            streamServer.on("/stream", HTTP_GET, handleStream);
            streamServer.on("/snapshot", HTTP_GET, handleSnapshot);
        }
        
        // Status endpoint always available
        streamServer.on("/status", HTTP_GET, handleStatus);
        
        // Direct HTTP servo control — INSTANT (no smoothMove blocking)
        streamServer.on("/servo", HTTP_GET, []() {
            streamServer.sendHeader("Access-Control-Allow-Origin", "*");
            
            String dir = streamServer.arg("dir");
            int val = streamServer.arg("val").toInt();
            if (val == 0) val = SERVO_STEP_DEGREES;
            
            // Stop patrol on manual input
            if (servos.getPatrolling()) servos.stopPatrol();
            
            // Direct position write — no smoothMove delay
            servos.instantMove(dir.c_str(), val);
            
            String json = "{\"pan\":" + String(servos.getPan()) + ",\"tilt\":" + String(servos.getTilt()) + "}";
            streamServer.send(200, "application/json", json);
        });
        
        // CORS preflight for all endpoints
        streamServer.on("/servo", HTTP_OPTIONS, []() {
            streamServer.sendHeader("Access-Control-Allow-Origin", "*");
            streamServer.sendHeader("Access-Control-Allow-Methods", "GET");
            streamServer.send(204);
        });
        
        // CORS preflight
        streamServer.on("/status", HTTP_OPTIONS, []() {
            streamServer.sendHeader("Access-Control-Allow-Origin", "*");
            streamServer.sendHeader("Access-Control-Allow-Methods", "GET");
            streamServer.send(204);
        });
        
        streamServer.begin();
        Serial.printf("[STREAM] Server started on port %d\n", STREAM_PORT);
        if (cameraAvailable) {
            Serial.printf("[STREAM] Stream URL: http://%s:%d/stream\n", 
                           WiFi.localIP().toString().c_str(), STREAM_PORT);
        }
    }
    
    // Initialize edge detection (only if camera available)
    if (cameraAvailable) {
        edgeDetect.begin(640, 480);
    }
    
    // Initialize mesh (works alongside WiFi in AP_STA mode)
    if (MESH_ENABLED) {
        mesh.begin();
        mesh.setHandoffCallback(handleMeshHandoff);
    }
    
    // Reconfigure watchdog (already initialized by framework)
    esp_task_wdt_config_t wdt_config = {
        .timeout_ms = WDT_TIMEOUT_S * 1000,
        .idle_core_mask = (1 << 0),
        .trigger_panic = true,
    };
    esp_task_wdt_reconfigure(&wdt_config);
    esp_task_wdt_add(NULL);
    
    // Blink LED to indicate ready
    for (int i = 0; i < 3; i++) {
        digitalWrite(LED_PIN, HIGH);
        delay(200);
        digitalWrite(LED_PIN, LOW);
        delay(200);
    }
    
    Serial.println("\n=== Project Netra Ready ===\n");
}

// ===========================================
// Main Loop
// ===========================================
void loop() {
    // Feed watchdog
    esp_task_wdt_reset();
    
    // Handle MQTT
    if (wifiConnected) {
        mqtt.loop();
        streamServer.handleClient();
    }
    
    // Update servo patrol
    servos.updatePatrol();
    
    // Edge motion detection (runs periodically)
    unsigned long now = millis();
    if (now - lastEdgeCheck >= FRAME_DIFF_INTERVAL) {
        lastEdgeCheck = now;
        
        if (edgeMode) {
            camera_fb_t *fb = camera.captureFrame();
            if (fb) {
                bool motion = edgeDetect.processFrame(fb->buf, fb->width, fb->height);
                
                if (motion) {
                    Serial.printf("[EDGE] Motion! %.1f%% pixels changed\n", 
                                   edgeDetect.getMotionPercent());
                    
                    // Auto-aim at motion zone
                    int zoneCol, zoneRow;
                    edgeDetect.getHottestZone(zoneCol, zoneRow);
                    
                    int panTarget, tiltTarget;
                    edgeDetect.getZoneServoTarget(zoneCol, zoneRow, panTarget, tiltTarget);
                    
                    if (!servos.getPatrolling()) {
                        servos.moveTo(panTarget, tiltTarget);
                    }
                    
                    // Publish motion event
                    mqtt.publishDetection(edgeDetect.getMotionJSON().c_str());
                    
                    // Broadcast to mesh peers
                    if (mesh.isInitialized()) {
                        float bearing = map(panTarget, PAN_MIN, PAN_MAX, 0, 360);
                        mesh.broadcastDetection(0, bearing, 
                                                 edgeDetect.getMotionPercent() / 100.0, 0);
                    }
                }
                
                camera.releaseFrame(fb);
            }
        }
    }
    
    // Mesh heartbeat (every 10 seconds)
    if (mesh.isInitialized() && now - lastMeshHeartbeat >= 10000) {
        lastMeshHeartbeat = now;
        mesh.sendHeartbeat();
        mesh.updatePeerStatus();
    }
    
    // Edge-cloud balance check (every 5 seconds)
    static unsigned long lastBalanceCheck = 0;
    if (now - lastBalanceCheck >= 5000) {
        lastBalanceCheck = now;
        checkEdgeCloudBalance();
    }
    
    // Serial command processing (for testing without MQTT)
    if (Serial.available()) {
        char cmd = Serial.read();
        switch (cmd) {
            case 'l': case 'L': servos.moveLeft();  Serial.printf("[SERIAL] Left → Pan:%d\n", servos.getPan()); break;
            case 'r': case 'R': servos.moveRight(); Serial.printf("[SERIAL] Right → Pan:%d\n", servos.getPan()); break;
            case 'u': case 'U': servos.moveUp();    Serial.printf("[SERIAL] Up → Tilt:%d\n", servos.getTilt()); break;
            case 'd': case 'D': servos.moveDown();  Serial.printf("[SERIAL] Down → Tilt:%d\n", servos.getTilt()); break;
            case 'c': case 'C': servos.center();    Serial.println("[SERIAL] Center"); break;
        }
    }
    
    // Small yield for WiFi/system tasks
    delay(1);
}
