#ifndef MESH_COMM_H
#define MESH_COMM_H

#include <esp_now.h>
#include <WiFi.h>
#include <ArduinoJson.h>
#include "config.h"

// ============================================
// Project Netra — ESP-NOW Mesh Communication
// Peer-to-peer camera handoff protocol
// ============================================

// Mesh message types
enum MeshMsgType {
    MSG_DETECTION_EVENT = 0x01,   // Object detected, notifying peers
    MSG_HANDOFF_REQUEST = 0x02,   // Requesting target camera to track
    MSG_HANDOFF_ACK     = 0x03,   // Acknowledgment of handoff
    MSG_HEARTBEAT       = 0x04,   // Node alive signal
    MSG_PATROL_SYNC     = 0x05,   // Synchronize patrol schedules
};

// Mesh message structure (max 250 bytes for ESP-NOW)
struct MeshMessage {
    uint8_t  sourceNode;
    uint8_t  targetNode;       // 0xFF = broadcast
    uint8_t  msgType;
    uint8_t  objectClass;      // 0=person, 1=vehicle, 2=animal, etc.
    float    bearing;          // Estimated direction of object (degrees)
    float    confidence;       // Detection confidence
    float    velocity;         // Estimated velocity (relative)
    uint32_t timestamp;        // millis()
    char     extra[64];        // JSON string for additional data
} __attribute__((packed));

// Peer node info
struct PeerNode {
    uint8_t macAddr[6];
    uint8_t nodeId;
    int8_t  rssi;
    uint32_t lastSeen;
    bool    active;
    float   panAngle;          // Known camera orientation
};

class MeshComm {
private:
    PeerNode peers[MAX_MESH_NODES];
    int peerCount;
    bool initialized;
    
    // Callback for received handoff events
    typedef void (*HandoffCallback)(uint8_t sourceNode, float bearing, 
                                     uint8_t objectClass, float confidence);
    HandoffCallback onHandoff;
    
    // Static instance for ESP-NOW callbacks
    static MeshComm* instance;
    
    static void onDataRecv(const esp_now_recv_info_t *info, const uint8_t *data, int len) {
        if (instance && len == sizeof(MeshMessage)) {
            instance->handleReceived(info->src_addr, (MeshMessage*)data);
        }
    }
    
    static void onDataSent(const wifi_tx_info_t *info, esp_now_send_status_t status) {
        if (status != ESP_NOW_SEND_SUCCESS) {
            Serial.println("[MESH] Send failed");
        }
    }
    
    void handleReceived(const uint8_t* mac, MeshMessage* msg) {
        Serial.printf("[MESH] Msg from node %d, type %d\n", msg->sourceNode, msg->msgType);
        
        // Update peer info
        updatePeer(mac, msg->sourceNode);
        
        switch (msg->msgType) {
            case MSG_DETECTION_EVENT:
                Serial.printf("[MESH] Detection: class=%d, bearing=%.1f, conf=%.2f\n",
                              msg->objectClass, msg->bearing, msg->confidence);
                break;
                
            case MSG_HANDOFF_REQUEST:
                Serial.printf("[MESH] Handoff request: bearing=%.1f\n", msg->bearing);
                if (onHandoff) {
                    onHandoff(msg->sourceNode, msg->bearing, 
                              msg->objectClass, msg->confidence);
                }
                // Send acknowledgment
                sendHandoffAck(msg->sourceNode);
                break;
                
            case MSG_HANDOFF_ACK:
                Serial.printf("[MESH] Handoff acknowledged by node %d\n", msg->sourceNode);
                break;
                
            case MSG_HEARTBEAT:
                // Already updated peer in updatePeer()
                break;
                
            case MSG_PATROL_SYNC:
                // Handle patrol synchronization
                break;
        }
    }
    
    void updatePeer(const uint8_t* mac, uint8_t nodeId) {
        for (int i = 0; i < peerCount; i++) {
            if (peers[i].nodeId == nodeId) {
                peers[i].lastSeen = millis();
                peers[i].active = true;
                return;
            }
        }
        
        // New peer
        if (peerCount < MAX_MESH_NODES) {
            memcpy(peers[peerCount].macAddr, mac, 6);
            peers[peerCount].nodeId = nodeId;
            peers[peerCount].lastSeen = millis();
            peers[peerCount].active = true;
            peerCount++;
            
            // Register as ESP-NOW peer
            esp_now_peer_info_t peerInfo = {};
            memcpy(peerInfo.peer_addr, mac, 6);
            peerInfo.channel = 0;
            peerInfo.encrypt = false;
            esp_now_add_peer(&peerInfo);
            
            Serial.printf("[MESH] New peer registered: node %d\n", nodeId);
        }
    }

public:
    MeshComm() : peerCount(0), initialized(false), onHandoff(nullptr) {
        instance = this;
        memset(peers, 0, sizeof(peers));
    }
    
    bool begin() {
        if (!MESH_ENABLED) {
            Serial.println("[MESH] Mesh disabled in config");
            return false;
        }
        
        if (esp_now_init() != ESP_OK) {
            Serial.println("[MESH] Init failed");
            return false;
        }
        
        esp_now_register_recv_cb(onDataRecv);
        esp_now_register_send_cb(onDataSent);
        
        initialized = true;
        Serial.println("[MESH] ESP-NOW initialized");
        return true;
    }
    
    void setHandoffCallback(HandoffCallback cb) { onHandoff = cb; }
    
    // Add a known peer by MAC address
    void addPeer(uint8_t nodeId, const uint8_t* macAddr) {
        esp_now_peer_info_t peerInfo = {};
        memcpy(peerInfo.peer_addr, macAddr, 6);
        peerInfo.channel = 0;
        peerInfo.encrypt = false;
        
        if (esp_now_add_peer(&peerInfo) == ESP_OK) {
            if (peerCount < MAX_MESH_NODES) {
                memcpy(peers[peerCount].macAddr, macAddr, 6);
                peers[peerCount].nodeId = nodeId;
                peers[peerCount].active = true;
                peers[peerCount].lastSeen = millis();
                peerCount++;
            }
            Serial.printf("[MESH] Peer added: node %d\n", nodeId);
        }
    }
    
    // Broadcast detection event to all peers
    void broadcastDetection(uint8_t objectClass, float bearing, float confidence, float velocity) {
        if (!initialized) return;
        
        MeshMessage msg;
        msg.sourceNode = NODE_ID;
        msg.targetNode = 0xFF;  // Broadcast
        msg.msgType = MSG_DETECTION_EVENT;
        msg.objectClass = objectClass;
        msg.bearing = bearing;
        msg.confidence = confidence;
        msg.velocity = velocity;
        msg.timestamp = millis();
        msg.extra[0] = '\0';
        
        // Send to all registered peers
        for (int i = 0; i < peerCount; i++) {
            if (peers[i].active) {
                esp_now_send(peers[i].macAddr, (uint8_t*)&msg, sizeof(msg));
            }
        }
    }
    
    // Request a specific node to take over tracking
    void requestHandoff(uint8_t targetNode, uint8_t objectClass, 
                         float bearing, float confidence) {
        if (!initialized) return;
        
        MeshMessage msg;
        msg.sourceNode = NODE_ID;
        msg.targetNode = targetNode;
        msg.msgType = MSG_HANDOFF_REQUEST;
        msg.objectClass = objectClass;
        msg.bearing = bearing;
        msg.confidence = confidence;
        msg.velocity = 0;
        msg.timestamp = millis();
        msg.extra[0] = '\0';
        
        // Find peer and send
        for (int i = 0; i < peerCount; i++) {
            if (peers[i].nodeId == targetNode) {
                esp_now_send(peers[i].macAddr, (uint8_t*)&msg, sizeof(msg));
                Serial.printf("[MESH] Handoff requested to node %d\n", targetNode);
                break;
            }
        }
    }
    
    void sendHandoffAck(uint8_t targetNode) {
        MeshMessage msg;
        msg.sourceNode = NODE_ID;
        msg.targetNode = targetNode;
        msg.msgType = MSG_HANDOFF_ACK;
        msg.timestamp = millis();
        
        for (int i = 0; i < peerCount; i++) {
            if (peers[i].nodeId == targetNode) {
                esp_now_send(peers[i].macAddr, (uint8_t*)&msg, sizeof(msg));
                break;
            }
        }
    }
    
    // Send heartbeat to all peers
    void sendHeartbeat() {
        if (!initialized) return;
        
        MeshMessage msg;
        msg.sourceNode = NODE_ID;
        msg.targetNode = 0xFF;
        msg.msgType = MSG_HEARTBEAT;
        msg.timestamp = millis();
        
        for (int i = 0; i < peerCount; i++) {
            if (peers[i].active) {
                esp_now_send(peers[i].macAddr, (uint8_t*)&msg, sizeof(msg));
            }
        }
    }
    
    // Check for stale peers
    void updatePeerStatus() {
        unsigned long now = millis();
        for (int i = 0; i < peerCount; i++) {
            if (peers[i].active && (now - peers[i].lastSeen > 30000)) {
                peers[i].active = false;
                Serial.printf("[MESH] Peer node %d went offline\n", peers[i].nodeId);
            }
        }
    }
    
    int getActivePeerCount() const {
        int count = 0;
        for (int i = 0; i < peerCount; i++) {
            if (peers[i].active) count++;
        }
        return count;
    }
    
    bool isInitialized() const { return initialized; }
};

// Static instance initialization
MeshComm* MeshComm::instance = nullptr;

#endif // MESH_COMM_H
