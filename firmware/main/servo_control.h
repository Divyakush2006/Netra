#ifndef SERVO_CONTROL_H
#define SERVO_CONTROL_H

#include <ESP32Servo.h>
#include "config.h"

// ============================================
// Project Netra — Pan/Tilt Servo Controller
// ============================================

class ServoController {
private:
    Servo panServo;
    Servo tiltServo;
    int currentPan;
    int currentTilt;
    bool isPatrolling;
    
    // Patrol waypoints
    struct Waypoint {
        int pan;
        int tilt;
        unsigned long dwellMs;  // How long to stay at this position
    };
    
    static const int MAX_WAYPOINTS = 16;
    Waypoint patrolRoute[MAX_WAYPOINTS];
    int waypointCount;
    int currentWaypoint;
    unsigned long lastWaypointTime;
    
    // Smooth movement
    void smoothMove(Servo &servo, int current, int target, int pin) {
        int step = (target > current) ? 1 : -1;
        for (int pos = current; pos != target; pos += step) {
            servo.write(pos);
            delay(SERVO_MOVE_DELAY_MS);
        }
        servo.write(target);
    }

public:
    ServoController() : currentPan(PAN_CENTER), currentTilt(TILT_CENTER),
                         isPatrolling(false), waypointCount(0), currentWaypoint(0) {}
    
    void begin() {
        panServo.attach(SERVO_PAN_PIN);
        tiltServo.attach(SERVO_TILT_PIN);
        
        // Move to center position
        panServo.write(PAN_CENTER);
        tiltServo.write(TILT_CENTER);
        currentPan = PAN_CENTER;
        currentTilt = TILT_CENTER;
        
        Serial.println("[SERVO] Initialized at center position");
    }
    
    // --- Manual Control ---
    
    void moveLeft() {
        int target = max(PAN_MIN, currentPan - SERVO_STEP_DEGREES);
        smoothMove(panServo, currentPan, target, SERVO_PAN_PIN);
        currentPan = target;
    }
    
    void moveRight() {
        int target = min(PAN_MAX, currentPan + SERVO_STEP_DEGREES);
        smoothMove(panServo, currentPan, target, SERVO_PAN_PIN);
        currentPan = target;
    }
    
    void moveUp() {
        int target = max(TILT_MIN, currentTilt - SERVO_STEP_DEGREES);
        smoothMove(tiltServo, currentTilt, target, SERVO_TILT_PIN);
        currentTilt = target;
    }
    
    void moveDown() {
        int target = min(TILT_MAX, currentTilt + SERVO_STEP_DEGREES);
        smoothMove(tiltServo, currentTilt, target, SERVO_TILT_PIN);
        currentTilt = target;
    }
    
    void moveTo(int pan, int tilt) {
        pan = constrain(pan, PAN_MIN, PAN_MAX);
        tilt = constrain(tilt, TILT_MIN, TILT_MAX);
        
        smoothMove(panServo, currentPan, pan, SERVO_PAN_PIN);
        smoothMove(tiltServo, currentTilt, tilt, SERVO_TILT_PIN);
        
        currentPan = pan;
        currentTilt = tilt;
    }
    
    void center() {
        moveTo(PAN_CENTER, TILT_CENTER);
    }
    
    // --- Patrol Mode ---
    
    void clearPatrolRoute() {
        waypointCount = 0;
        currentWaypoint = 0;
    }
    
    bool addWaypoint(int pan, int tilt, unsigned long dwellMs) {
        if (waypointCount >= MAX_WAYPOINTS) return false;
        
        patrolRoute[waypointCount] = {
            constrain(pan, PAN_MIN, PAN_MAX),
            constrain(tilt, TILT_MIN, TILT_MAX),
            dwellMs
        };
        waypointCount++;
        return true;
    }
    
    void setDefaultPatrolRoute() {
        clearPatrolRoute();
        // Default: sweep left-center-right at two tilt levels
        addWaypoint(30,  90,  2000);
        addWaypoint(90,  90,  2000);
        addWaypoint(150, 90,  2000);
        addWaypoint(150, 60,  2000);
        addWaypoint(90,  60,  2000);
        addWaypoint(30,  60,  2000);
    }
    
    void startPatrol() {
        if (waypointCount == 0) {
            setDefaultPatrolRoute();
        }
        isPatrolling = true;
        currentWaypoint = 0;
        lastWaypointTime = millis();
        Serial.println("[SERVO] Patrol started");
    }
    
    void stopPatrol() {
        isPatrolling = false;
        Serial.println("[SERVO] Patrol stopped");
    }
    
    // Call this in loop() — non-blocking patrol update
    void updatePatrol() {
        if (!isPatrolling || waypointCount == 0) return;
        
        unsigned long now = millis();
        Waypoint &wp = patrolRoute[currentWaypoint];
        
        // Check if dwell time has elapsed
        if (now - lastWaypointTime >= wp.dwellMs) {
            // Move to next waypoint
            currentWaypoint = (currentWaypoint + 1) % waypointCount;
            Waypoint &nextWp = patrolRoute[currentWaypoint];
            
            moveTo(nextWp.pan, nextWp.tilt);
            lastWaypointTime = now;
        }
    }
    
    
    // --- Instant Move (for HTTP joystick — no smoothMove delay) ---
    
    void instantMove(const char* direction, int step = SERVO_STEP_DEGREES) {
        String dir(direction);
        if (dir == "left") {
            currentPan = max(PAN_MIN, currentPan - step);
            panServo.write(currentPan);
        } else if (dir == "right") {
            currentPan = min(PAN_MAX, currentPan + step);
            panServo.write(currentPan);
        } else if (dir == "up") {
            currentTilt = max(TILT_MIN, currentTilt - step);
            tiltServo.write(currentTilt);
        } else if (dir == "down") {
            currentTilt = min(TILT_MAX, currentTilt + step);
            tiltServo.write(currentTilt);
        } else if (dir == "center") {
            currentPan = PAN_CENTER;
            currentTilt = TILT_CENTER;
            panServo.write(currentPan);
            tiltServo.write(currentTilt);
        }
    }
    
    // --- Getters ---
    
    int getPan() const { return currentPan; }
    int getTilt() const { return currentTilt; }
    bool getPatrolling() const { return isPatrolling; }
    
    // Get status as JSON string
    String getStatusJSON() const {
        return "{\"pan\":" + String(currentPan) + 
               ",\"tilt\":" + String(currentTilt) + 
               ",\"patrolling\":" + String(isPatrolling ? "true" : "false") + "}";
    }
};

#endif // SERVO_CONTROL_H
