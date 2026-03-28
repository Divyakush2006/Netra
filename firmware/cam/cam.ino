/*
 * ============================================
 * Project Netra — ESP32-CAM Camera Firmware
 * Ultra low-latency MJPEG streaming server
 * ============================================
 *
 * Optimized for maximum FPS & minimum latency:
 *   - Dedicated FreeRTOS streaming task on Core 0
 *   - Chunked TCP writes (avoids large blocking writes)
 *   - CIF resolution (400x296) — sweet spot for ESP32 bandwidth
 *   - JPEG quality 15 — small frames, good enough for surveillance
 *   - TCP_NODELAY + Wi-Fi sleep disabled
 *   - Reduced XCLK (16MHz) to lower heat generation
 *   - Stack-allocated headers (no heap churn)
 *   - CAMERA_GRAB_LATEST (skips stale frames)
 *
 * Endpoints:
 *   Port 81  →  MJPEG live stream
 *   Port 82  →  /snapshot & /status
 */

#include "esp_camera.h"
#include <WiFi.h>
#include <WebServer.h>

// --- WiFi (same network as ESP32 DevKit) ---
const char* ssid = "Netra";
const char* password = "12345678";

// --- AI-Thinker ESP32-CAM Pin Definition ---
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

#define LED_GPIO_NUM       4   // Flash LED

// --- Streaming config ---
#define STREAM_CHUNK_SIZE  1024   // Write JPEG in 1KB chunks to avoid blocking
#define FRAME_RATE_CAP     25     // Max FPS cap (prevent overheating)

// --- Servers ---
WiFiServer streamServer(81);
WebServer  utilServer(82);

// --- FPS tracking ---
volatile unsigned long lastFPSTime = 0;
volatile unsigned int  frameCount  = 0;
volatile float         currentFPS  = 0;

// --- Stream task handle ---
TaskHandle_t streamTaskHandle = NULL;

// ==========================================
// Camera Init
// ==========================================
bool initCamera() {
    camera_config_t config;
    config.ledc_channel = LEDC_CHANNEL_0;
    config.ledc_timer = LEDC_TIMER_0;
    config.pin_d0 = Y2_GPIO_NUM;
    config.pin_d1 = Y3_GPIO_NUM;
    config.pin_d2 = Y4_GPIO_NUM;
    config.pin_d3 = Y5_GPIO_NUM;
    config.pin_d4 = Y6_GPIO_NUM;
    config.pin_d5 = Y7_GPIO_NUM;
    config.pin_d6 = Y8_GPIO_NUM;
    config.pin_d7 = Y9_GPIO_NUM;
    config.pin_xclk = XCLK_GPIO_NUM;
    config.pin_pclk = PCLK_GPIO_NUM;
    config.pin_vsync = VSYNC_GPIO_NUM;
    config.pin_href = HREF_GPIO_NUM;
    config.pin_sccb_sda = SIOD_GPIO_NUM;
    config.pin_sccb_scl = SIOC_GPIO_NUM;
    config.pin_pwdn = PWDN_GPIO_NUM;
    config.pin_reset = RESET_GPIO_NUM;
    config.xclk_freq_hz = 16000000;       // 16MHz — reduced from 20MHz to lower heat
    config.pixel_format = PIXFORMAT_JPEG;
    config.grab_mode = CAMERA_GRAB_LATEST; // Always grab newest frame, skip stale ones

    if (psramFound()) {
        config.frame_size = FRAMESIZE_QVGA;    // 320x240 — smallest viable res, pushes 20+ FPS
        config.jpeg_quality = 15;              // Smaller frames = faster TCP writes = higher FPS
        config.fb_count = 2;                   // Double buffer — one captures while one sends
        Serial.println("[CAM] PSRAM found — QVGA 320x240, dual buffer");
    } else {
        config.frame_size = FRAMESIZE_QVGA;    // 320x240
        config.jpeg_quality = 18;
        config.fb_count = 1;
        Serial.println("[CAM] No PSRAM — QVGA 320x240, single buffer");
    }

    esp_err_t err = esp_camera_init(&config);
    if (err != ESP_OK) {
        Serial.printf("[CAM] Init failed: 0x%x\n", err);
        return false;
    }

    // Minimal sensor tweaks — avoid heavy processing that heats the chip
    sensor_t *s = esp_camera_sensor_get();
    if (s) {
        s->set_brightness(s, 1);
        s->set_contrast(s, 1);
        s->set_saturation(s, 0);
        s->set_whitebal(s, 1);
        s->set_awb_gain(s, 1);
        s->set_wb_mode(s, 0);
        s->set_aec2(s, 1);
        s->set_ae_level(s, 0);
        s->set_gainceiling(s, (gainceiling_t)6);
    }

    Serial.println("[CAM] Camera initialized!");
    return true;
}

// ==========================================
// Chunked write — sends JPEG in small pieces
// to avoid blocking the TCP stack for too long
// ==========================================
bool chunkedWrite(WiFiClient &client, const uint8_t *buf, size_t len) {
    size_t offset = 0;
    while (offset < len) {
        if (!client.connected()) return false;

        size_t toWrite = min((size_t)STREAM_CHUNK_SIZE, len - offset);
        size_t written = client.write(buf + offset, toWrite);

        if (written == 0) {
            // TCP buffer full — yield briefly and retry
            delay(1);
            written = client.write(buf + offset, toWrite);
            if (written == 0) return false;  // Client gone
        }

        offset += written;
    }
    return true;
}

// ==========================================
// Stream one client (runs inside FreeRTOS task)
// ==========================================
void streamToClient(WiFiClient &client) {
    client.setNoDelay(true);
    client.setTimeout(3);

    // Send MJPEG HTTP headers
    const char* headers =
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: multipart/x-mixed-replace; boundary=frame\r\n"
        "Access-Control-Allow-Origin: *\r\n"
        "Cache-Control: no-cache, no-store, must-revalidate\r\n"
        "Connection: keep-alive\r\n"
        "\r\n";
    client.print(headers);

    char partBuf[80];
    unsigned long minFrameTime = 1000 / FRAME_RATE_CAP;  // ms per frame cap

    Serial.println("[STREAM] Client connected — streaming");

    while (client.connected()) {
        unsigned long frameStart = millis();

        camera_fb_t *fb = esp_camera_fb_get();
        if (!fb) {
            delay(5);
            continue;
        }

        // Build boundary + header
        int partLen = snprintf(partBuf, sizeof(partBuf),
                               "--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n",
                               fb->len);

        // Write header (small, won't block)
        client.write(partBuf, partLen);

        // Write JPEG in chunks (prevents long blocking writes)
        bool ok = chunkedWrite(client, fb->buf, fb->len);
        client.write("\r\n", 2);

        esp_camera_fb_return(fb);

        if (!ok) break;  // Client disconnected during write

        // FPS tracking
        frameCount++;
        unsigned long now = millis();
        if (now - lastFPSTime >= 5000) {
            currentFPS = frameCount * 1000.0f / (now - lastFPSTime);
            Serial.printf("[STREAM] %.1f FPS | Frame: %u bytes | RSSI: %d dBm | Heap: %u\n",
                          currentFPS, fb->len, WiFi.RSSI(), ESP.getFreeHeap());
            frameCount = 0;
            lastFPSTime = now;
        }

        // Frame rate cap — prevents CPU from running flat-out and overheating
        unsigned long elapsed = millis() - frameStart;
        if (elapsed < minFrameTime) {
            delay(minFrameTime - elapsed);
        }
    }

    Serial.println("[STREAM] Client disconnected");
}

// ==========================================
// FreeRTOS task — runs stream on Core 0
// (Core 1 handles WiFi stack + utility server)
// ==========================================
void streamTask(void *param) {
    for (;;) {
        WiFiClient client = streamServer.available();
        if (client) {
            streamToClient(client);
        }
        delay(10);  // Check for new clients every 10ms
    }
}

// ==========================================
// Snapshot Handler (port 82)
// ==========================================
void handleSnapshot() {
    camera_fb_t *fb = esp_camera_fb_get();
    if (!fb) {
        utilServer.send(500, "text/plain", "Capture failed");
        return;
    }

    utilServer.sendHeader("Access-Control-Allow-Origin", "*");
    utilServer.sendHeader("Cache-Control", "no-cache");
    utilServer.sendHeader("Content-Disposition", "inline; filename=snapshot.jpg");
    utilServer.send_P(200, "image/jpeg", (const char*)fb->buf, fb->len);
    esp_camera_fb_return(fb);
}

// ==========================================
// Status Handler (port 82)
// ==========================================
void handleStatus() {
    utilServer.sendHeader("Access-Control-Allow-Origin", "*");
    char json[160];
    snprintf(json, sizeof(json),
             "{\"cam\":\"online\",\"ip\":\"%s\",\"rssi\":%d,\"heap\":%u,\"fps\":%.1f}",
             WiFi.localIP().toString().c_str(), WiFi.RSSI(), ESP.getFreeHeap(), currentFPS);
    utilServer.send(200, "application/json", json);
}

// ==========================================
// Setup
// ==========================================
void setup() {
    Serial.begin(115200);
    Serial.println("\n\n=== Project Netra CAM Starting ===\n");

    // Flash LED off
    pinMode(LED_GPIO_NUM, OUTPUT);
    digitalWrite(LED_GPIO_NUM, LOW);

    // Init camera
    if (!initCamera()) {
        Serial.println("[FATAL] Camera init failed!");
        while (true) {
            digitalWrite(LED_GPIO_NUM, HIGH);
            delay(500);
            digitalWrite(LED_GPIO_NUM, LOW);
            delay(500);
        }
    }

    // Connect WiFi
    WiFi.mode(WIFI_STA);
    WiFi.setSleep(false);                     // Disable modem sleep — critical for latency
    WiFi.setTxPower(WIFI_POWER_19_5dBm);      // Max transmit power

    Serial.printf("[WIFI] Connecting to %s", ssid);
    WiFi.begin(ssid, password);

    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 30) {
        delay(500);
        Serial.print(".");
        attempts++;
    }

    if (WiFi.status() == WL_CONNECTED) {
        Serial.printf("\n[WIFI] Connected! IP: %s  RSSI: %d dBm\n",
                      WiFi.localIP().toString().c_str(), WiFi.RSSI());
    } else {
        Serial.println("\n[WIFI] Connection failed!");
        while (true) {
            digitalWrite(LED_GPIO_NUM, HIGH);
            delay(200);
            digitalWrite(LED_GPIO_NUM, LOW);
            delay(200);
        }
    }

    // Start stream server
    streamServer.begin();
    streamServer.setNoDelay(true);

    // Start utility server
    utilServer.on("/snapshot", HTTP_GET, handleSnapshot);
    utilServer.on("/status",  HTTP_GET, handleStatus);
    utilServer.begin();

    // Launch stream handler on Core 0 (separate from WiFi/main loop on Core 1)
    xTaskCreatePinnedToCore(
        streamTask,         // Function
        "StreamTask",       // Name
        8192,               // Stack size (bytes)
        NULL,               // Parameter
        1,                  // Priority (1 = normal)
        &streamTaskHandle,  // Task handle
        0                   // Core 0 (Core 1 = main loop + WiFi events)
    );

    Serial.printf("[STREAM] Stream:   http://%s:81/stream\n", WiFi.localIP().toString().c_str());
    Serial.printf("[UTIL]   Snapshot: http://%s:82/snapshot\n", WiFi.localIP().toString().c_str());
    Serial.printf("[UTIL]   Status:   http://%s:82/status\n", WiFi.localIP().toString().c_str());
    Serial.println("\n=== Project Netra CAM Ready ===\n");

    lastFPSTime = millis();
}

// ==========================================
// Loop (Core 1 — handles utility server only)
// ==========================================
void loop() {
    utilServer.handleClient();
    delay(5);
}
