#ifndef EDGE_DETECT_H
#define EDGE_DETECT_H

#include "esp_camera.h"
#include "config.h"

// ============================================
// Project Netra — Edge Motion Detection
// Lightweight frame differencing for on-device
// motion detection when network is poor
// ============================================

class EdgeDetector {
private:
    uint8_t* prevFrame;
    size_t frameSize;
    bool hasPrevFrame;
    unsigned long lastDetectTime;
    
    // Motion statistics
    int motionPixels;
    float motionPercent;
    bool motionDetected;
    
    // Adaptive threshold
    float baselineMotion;       // Rolling average of motion when "quiet"
    int quietFrameCount;
    static const int BASELINE_FRAMES = 50;
    
    // Zone-based detection (divide frame into grid)
    static const int GRID_COLS = 4;
    static const int GRID_ROWS = 3;
    int zoneMotion[GRID_ROWS][GRID_COLS];  // Motion count per zone
    
public:
    EdgeDetector() : prevFrame(nullptr), frameSize(0), hasPrevFrame(false),
                      lastDetectTime(0), motionPixels(0), motionPercent(0),
                      motionDetected(false), baselineMotion(0), quietFrameCount(0) {
        memset(zoneMotion, 0, sizeof(zoneMotion));
    }
    
    ~EdgeDetector() {
        if (prevFrame) free(prevFrame);
    }
    
    bool begin(size_t width, size_t height) {
        // We work with downscaled grayscale for efficiency
        // Use 1/4 resolution for comparison
        size_t dsWidth = width / 4;
        size_t dsHeight = height / 4;
        frameSize = dsWidth * dsHeight;
        
        prevFrame = (uint8_t*)ps_malloc(frameSize);
        if (!prevFrame) {
            prevFrame = (uint8_t*)malloc(frameSize);
        }
        
        if (!prevFrame) {
            Serial.println("[EDGE] Failed to allocate frame buffer");
            return false;
        }
        
        Serial.printf("[EDGE] Initialized: %dx%d downscaled\n", dsWidth, dsHeight);
        return true;
    }
    
    // Process a grayscale frame for motion detection
    // Returns true if significant motion detected
    bool processFrame(const uint8_t* currentFrame, size_t width, size_t height) {
        unsigned long now = millis();
        if (now - lastDetectTime < FRAME_DIFF_INTERVAL) {
            return motionDetected;  // Rate limit
        }
        lastDetectTime = now;
        
        size_t dsWidth = width / 4;
        size_t dsHeight = height / 4;
        
        if (!hasPrevFrame) {
            // First frame: just store it
            downsampleFrame(currentFrame, width, height, prevFrame, dsWidth, dsHeight);
            hasPrevFrame = true;
            return false;
        }
        
        // Downsample current frame
        uint8_t* dsFrame = (uint8_t*)malloc(frameSize);
        if (!dsFrame) return false;
        
        downsampleFrame(currentFrame, width, height, dsFrame, dsWidth, dsHeight);
        
        // Frame differencing
        motionPixels = 0;
        memset(zoneMotion, 0, sizeof(zoneMotion));
        
        int zoneWidth = dsWidth / GRID_COLS;
        int zoneHeight = dsHeight / GRID_ROWS;
        
        for (size_t i = 0; i < frameSize; i++) {
            int diff = abs((int)dsFrame[i] - (int)prevFrame[i]);
            if (diff > MOTION_THRESHOLD) {
                motionPixels++;
                
                // Determine which zone this pixel belongs to
                int x = i % dsWidth;
                int y = i / dsWidth;
                int zoneCol = min(x / zoneWidth, GRID_COLS - 1);
                int zoneRow = min(y / zoneHeight, GRID_ROWS - 1);
                zoneMotion[zoneRow][zoneCol]++;
            }
        }
        
        // Store current as previous
        memcpy(prevFrame, dsFrame, frameSize);
        free(dsFrame);
        
        // Calculate motion percentage
        motionPercent = (float)motionPixels / frameSize * 100.0f;
        motionDetected = (motionPixels > MOTION_MIN_AREA);
        
        // Update baseline
        if (!motionDetected) {
            quietFrameCount++;
            if (quietFrameCount > BASELINE_FRAMES) {
                baselineMotion = baselineMotion * 0.95 + motionPercent * 0.05;
            }
        } else {
            quietFrameCount = 0;
        }
        
        return motionDetected;
    }
    
    // Get the zone with most motion (for camera auto-aim)
    void getHottestZone(int &col, int &row) const {
        int maxMotion = 0;
        col = GRID_COLS / 2;
        row = GRID_ROWS / 2;
        
        for (int r = 0; r < GRID_ROWS; r++) {
            for (int c = 0; c < GRID_COLS; c++) {
                if (zoneMotion[r][c] > maxMotion) {
                    maxMotion = zoneMotion[r][c];
                    col = c;
                    row = r;
                }
            }
        }
    }
    
    // Convert hottest zone to servo target angles
    void getZoneServoTarget(int zoneCol, int zoneRow, int &panTarget, int &tiltTarget) const {
        // Map zone column (0 to GRID_COLS-1) → pan angle (PAN_MIN to PAN_MAX)
        panTarget = map(zoneCol, 0, GRID_COLS - 1, PAN_MIN + 20, PAN_MAX - 20);
        // Map zone row (0 to GRID_ROWS-1) → tilt angle (TILT_MIN to TILT_MAX)
        tiltTarget = map(zoneRow, 0, GRID_ROWS - 1, TILT_MIN + 10, TILT_MAX - 10);
    }
    
    // Get motion info as JSON
    String getMotionJSON() const {
        String json = "{\"motion\":" + String(motionDetected ? "true" : "false");
        json += ",\"pixels\":" + String(motionPixels);
        json += ",\"percent\":" + String(motionPercent, 1);
        json += ",\"baseline\":" + String(baselineMotion, 1);
        json += ",\"zones\":[";
        for (int r = 0; r < GRID_ROWS; r++) {
            json += "[";
            for (int c = 0; c < GRID_COLS; c++) {
                json += String(zoneMotion[r][c]);
                if (c < GRID_COLS - 1) json += ",";
            }
            json += "]";
            if (r < GRID_ROWS - 1) json += ",";
        }
        json += "]}";
        return json;
    }
    
    float getMotionPercent() const { return motionPercent; }
    bool isMotionDetected() const { return motionDetected; }
    
private:
    // Simple 4x downsampling with averaging
    void downsampleFrame(const uint8_t* src, size_t srcW, size_t srcH,
                          uint8_t* dst, size_t dstW, size_t dstH) {
        for (size_t dy = 0; dy < dstH; dy++) {
            for (size_t dx = 0; dx < dstW; dx++) {
                int sum = 0;
                for (int ky = 0; ky < 4; ky++) {
                    for (int kx = 0; kx < 4; kx++) {
                        size_t sx = dx * 4 + kx;
                        size_t sy = dy * 4 + ky;
                        if (sx < srcW && sy < srcH) {
                            sum += src[sy * srcW + sx];
                        }
                    }
                }
                dst[dy * dstW + dx] = sum / 16;
            }
        }
    }
};

#endif // EDGE_DETECT_H
