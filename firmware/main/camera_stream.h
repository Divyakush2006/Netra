#ifndef CAMERA_STREAM_H
#define CAMERA_STREAM_H

#include "esp_camera.h"
#include "config.h"

// ============================================
// Project Netra — MJPEG Camera Streaming
// ============================================

// AI-Thinker ESP32-CAM pin definitions
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

class CameraStream {
private:
    bool initialized;
    
public:
    CameraStream() : initialized(false) {}
    
    bool begin() {
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
        config.pin_sscb_sda = SIOD_GPIO_NUM;
        config.pin_sscb_scl = SIOC_GPIO_NUM;
        config.pin_pwdn = PWDN_GPIO_NUM;
        config.pin_reset = RESET_GPIO_NUM;
        config.xclk_freq_hz = 20000000;
        config.pixel_format = PIXFORMAT_JPEG;
        
        // Use PSRAM if available for higher resolution
        if (psramFound()) {
            config.frame_size = FRAME_SIZE;
            config.jpeg_quality = JPEG_QUALITY;
            config.fb_count = 2;
            Serial.println("[CAM] PSRAM found, using dual frame buffer");
        } else {
            config.frame_size = FRAMESIZE_SVGA;
            config.jpeg_quality = 15;
            config.fb_count = 1;
            Serial.println("[CAM] No PSRAM, using single frame buffer");
        }
        
        // Initialize camera
        esp_err_t err = esp_camera_init(&config);
        if (err != ESP_OK) {
            Serial.printf("[CAM] Init failed: 0x%x\n", err);
            return false;
        }
        
        // Adjust sensor settings for better surveillance quality
        sensor_t *s = esp_camera_sensor_get();
        if (s) {
            s->set_brightness(s, 1);      // Slightly brighter
            s->set_contrast(s, 1);        // Higher contrast
            s->set_saturation(s, 0);      // Normal saturation
            s->set_whitebal(s, 1);        // Auto white balance
            s->set_awb_gain(s, 1);        // AWB gain on
            s->set_wb_mode(s, 0);         // Auto WB mode
            s->set_exposure_ctrl(s, 1);   // Auto exposure
            s->set_aec2(s, 1);            // AEC DSP
            s->set_gain_ctrl(s, 1);       // Auto gain
            s->set_agc_gain(s, 0);        // AGC gain 0
            s->set_gainceiling(s, (gainceiling_t)6);
            s->set_bpc(s, 1);             // Black pixel correction
            s->set_wpc(s, 1);             // White pixel correction
            s->set_raw_gma(s, 1);         // Gamma correction
            s->set_lenc(s, 1);            // Lens correction
            s->set_dcw(s, 1);             // Downsize enable
        }
        
        initialized = true;
        Serial.println("[CAM] Camera initialized successfully");
        return true;
    }
    
    // Capture a single JPEG frame
    camera_fb_t* captureFrame() {
        if (!initialized) return nullptr;
        return esp_camera_fb_get();
    }
    
    // Release frame buffer
    void releaseFrame(camera_fb_t *fb) {
        if (fb) {
            esp_camera_fb_return(fb);
        }
    }
    
    // Set resolution dynamically (for edge-cloud adaptive processing)
    void setResolution(framesize_t size) {
        sensor_t *s = esp_camera_sensor_get();
        if (s) {
            s->set_framesize(s, size);
            Serial.printf("[CAM] Resolution changed to %d\n", size);
        }
    }
    
    // Set JPEG quality dynamically
    void setQuality(int quality) {
        sensor_t *s = esp_camera_sensor_get();
        if (s) {
            s->set_quality(s, quality);
            Serial.printf("[CAM] Quality changed to %d\n", quality);
        }
    }
    
    // Toggle flash LED
    void setFlash(bool on) {
        digitalWrite(LED_FLASH_PIN, on ? HIGH : LOW);
    }
    
    bool isInitialized() const { return initialized; }
};

#endif // CAMERA_STREAM_H
