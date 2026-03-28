# 🛡️ Project Netra — Intelligent Adaptive Surveillance System

An AI-powered surveillance system built with ESP32-CAM, servo motors, YOLOv8, and a real-time dashboard. Designed for adaptive predictive patrolling, behavioral anomaly detection, and multi-camera cooperative tracking.

## Architecture

```
ESP32-CAM (Edge)  →  MQTT/WebSocket  →  FastAPI Backend (YOLO + Tracking)  →  React Dashboard
     ↕ ESP-NOW                              ↕ SQLite/PostgreSQL
ESP32-CAM Node 2                        Anomaly Engine + Patrol Optimizer
```

## Quick Start

### 1. Backend
```bash
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 2. Dashboard
```bash
cd dashboard
npm install
npm run dev
```

### 3. ESP32 Firmware
- Open `firmware/main/main.ino` in Arduino IDE or PlatformIO
- Update `config.h` with your WiFi credentials and MQTT broker IP
- Flash to ESP32-CAM

## Features

- 🎥 Live MJPEG camera feed with YOLO detection overlay
- 🕹️ Manual pan/tilt camera control via joystick UI
- 🧭 Adaptive Predictive Patrol — learns high-risk zones
- 🧠 Behavioral Anomaly Scoring — loitering, speed, zone violations
- 🗺️ Digital Twin Map — real-time 2D spatial visualization
- 🕸️ Multi-camera mesh network with object handoff
- ⚡ Edge-cloud adaptive processing

## Tech Stack

| Component | Technology |
|-----------|-----------|
| MCU | ESP32-CAM (AI-Thinker) |
| Servos | SG90 × 2 (pan/tilt) |
| Backend | FastAPI (Python 3.10+) |
| Detection | YOLOv8n (Ultralytics) |
| Tracking | DeepSORT |
| Frontend | React + Vite |
| Messaging | MQTT (Mosquitto) |
| Database | SQLite |

## License

MIT — MPMC Course Project
