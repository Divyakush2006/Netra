#ifndef MQTT_HANDLER_H
#define MQTT_HANDLER_H

#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include "config.h"

// ============================================
// Project Netra — MQTT Communication Handler
// ============================================

// Forward declaration for callback
class MQTTHandler;
MQTTHandler* mqttInstance = nullptr;

class MQTTHandler {
private:
    WiFiClient wifiClient;
    PubSubClient mqttClient;
    
    // Callback function pointer for servo commands
    typedef void (*ServoCommandCallback)(const char* direction, int value);
    typedef void (*PatrolCommandCallback)(const char* action, const char* payload);
    typedef void (*EdgeConfigCallback)(const char* payload);
    
    ServoCommandCallback onServoCmd;
    PatrolCommandCallback onPatrolCmd;
    EdgeConfigCallback onEdgeConfig;
    
    unsigned long lastReconnectAttempt;
    unsigned long lastStatusPublish;
    static const unsigned long RECONNECT_INTERVAL = 5000;
    static const unsigned long STATUS_INTERVAL = 10000;

    static void staticCallback(char* topic, byte* payload, unsigned int length) {
        if (mqttInstance) {
            mqttInstance->handleMessage(topic, payload, length);
        }
    }
    
    void handleMessage(char* topic, byte* payload, unsigned int length) {
        // Null-terminate the payload
        char message[length + 1];
        memcpy(message, payload, length);
        message[length] = '\0';
        
        Serial.printf("[MQTT] Received on %s: %s\n", topic, message);
        
        String topicStr(topic);
        
        // --- Servo Commands ---
        if (topicStr == TOPIC_SERVO_CMD) {
            StaticJsonDocument<256> doc;
            DeserializationError error = deserializeJson(doc, message);
            
            if (!error) {
                const char* direction = doc["direction"] | "stop";
                int value = doc["value"] | SERVO_STEP_DEGREES;
                
                if (onServoCmd) {
                    onServoCmd(direction, value);
                }
            }
        }
        // --- Patrol Commands ---
        else if (topicStr == TOPIC_PATROL_CMD) {
            StaticJsonDocument<1024> doc;
            DeserializationError error = deserializeJson(doc, message);
            
            if (!error) {
                const char* action = doc["action"] | "status";
                
                // Serialize waypoints if present
                String waypointsStr = "";
                if (doc.containsKey("waypoints")) {
                    serializeJson(doc["waypoints"], waypointsStr);
                }
                
                if (onPatrolCmd) {
                    onPatrolCmd(action, waypointsStr.c_str());
                }
            }
        }
        // --- Edge Config ---
        else if (topicStr == TOPIC_EDGE_CONFIG) {
            if (onEdgeConfig) {
                onEdgeConfig(message);
            }
        }
    }

public:
    MQTTHandler() : mqttClient(wifiClient), onServoCmd(nullptr), 
                     onPatrolCmd(nullptr), onEdgeConfig(nullptr),
                     lastReconnectAttempt(0), lastStatusPublish(0) {
        mqttInstance = this;
    }
    
    void begin() {
        mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
        mqttClient.setCallback(staticCallback);
        mqttClient.setBufferSize(2048);
        
        Serial.println("[MQTT] Handler initialized");
    }
    
    void setServoCallback(ServoCommandCallback cb) { onServoCmd = cb; }
    void setPatrolCallback(PatrolCommandCallback cb) { onPatrolCmd = cb; }
    void setEdgeConfigCallback(EdgeConfigCallback cb) { onEdgeConfig = cb; }
    
    bool connect() {
        Serial.println("[MQTT] Connecting...");
        
        bool connected;
        if (strlen(MQTT_USER) > 0) {
            connected = mqttClient.connect(MQTT_CLIENT_ID, MQTT_USER, MQTT_PASSWORD);
        } else {
            connected = mqttClient.connect(MQTT_CLIENT_ID);
        }
        
        if (connected) {
            Serial.println("[MQTT] Connected!");
            
            // Subscribe to command topics
            bool s1 = mqttClient.subscribe(TOPIC_SERVO_CMD);
            bool s2 = mqttClient.subscribe(TOPIC_PATROL_CMD);
            bool s3 = mqttClient.subscribe(TOPIC_EDGE_CONFIG);
            Serial.printf("[MQTT] Subscriptions: servo=%d patrol=%d edge=%d\n", s1, s2, s3);
            
            // Publish online status
            publishStatus("online");
            
            return true;
        } else {
            Serial.printf("[MQTT] Connection failed, rc=%d\n", mqttClient.state());
            return false;
        }
    }
    
    void loop() {
        if (!mqttClient.connected()) {
            unsigned long now = millis();
            if (now - lastReconnectAttempt >= RECONNECT_INTERVAL) {
                lastReconnectAttempt = now;
                connect();
            }
        } else {
            mqttClient.loop();
        }
        
        // Periodic status publish
        unsigned long now = millis();
        if (now - lastStatusPublish >= STATUS_INTERVAL) {
            lastStatusPublish = now;
            publishHeartbeat();
        }
    }
    
    // --- Publishing ---
    
    void publishStatus(const char* status) {
        StaticJsonDocument<128> doc;
        doc["node_id"] = NODE_ID;
        doc["status"] = status;
        doc["uptime"] = millis() / 1000;
        
        char buffer[128];
        serializeJson(doc, buffer);
        mqttClient.publish(TOPIC_STATUS, buffer, true);  // retained
    }
    
    void publishHeartbeat() {
        StaticJsonDocument<128> doc;
        doc["node_id"] = NODE_ID;
        doc["heap"] = ESP.getFreeHeap();
        doc["uptime"] = millis() / 1000;
        doc["rssi"] = WiFi.RSSI();
        
        char buffer[128];
        serializeJson(doc, buffer);
        mqttClient.publish(TOPIC_STATUS, buffer);
    }
    
    void publishServoPosition(int pan, int tilt, bool patrolling) {
        StaticJsonDocument<128> doc;
        doc["pan"] = pan;
        doc["tilt"] = tilt;
        doc["patrolling"] = patrolling;
        
        char buffer[128];
        serializeJson(doc, buffer);
        mqttClient.publish(TOPIC_SERVO_STATUS, buffer);
    }
    
    void publishDetection(const char* detectionJson) {
        mqttClient.publish(TOPIC_DETECTION, detectionJson);
    }
    
    void publishMeshEvent(int sourceNode, const char* eventType, 
                          float bearing, const char* objectType) {
        StaticJsonDocument<256> doc;
        doc["source_node"] = sourceNode;
        doc["event"] = eventType;
        doc["bearing"] = bearing;
        doc["object"] = objectType;
        doc["timestamp"] = millis();
        
        char buffer[256];
        serializeJson(doc, buffer);
        mqttClient.publish(TOPIC_MESH_EVENT, buffer);
    }
    
    bool isConnected() { return mqttClient.connected(); }
    
    // Get RSSI for edge-cloud adaptive processing decisions
    int getWiFiRSSI() const { return WiFi.RSSI(); }
    
    // Estimate network quality (0-100)
    int getNetworkQuality() const {
        int rssi = WiFi.RSSI();
        if (rssi >= -50) return 100;
        if (rssi >= -60) return 80;
        if (rssi >= -70) return 60;
        if (rssi >= -80) return 40;
        if (rssi >= -90) return 20;
        return 0;
    }
};

#endif // MQTT_HANDLER_H
