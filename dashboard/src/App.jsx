import React, { useState, useEffect, useCallback, useRef } from 'react';

const API_BASE = '/api';

// ============================================
// WebSocket Hook
// ============================================
function useWebSocket(url) {
    const [lastMessage, setLastMessage] = useState(null);
    const [isConnected, setIsConnected] = useState(false);
    const wsRef = useRef(null);

    useEffect(() => {
        const connect = () => {
            try {
                const ws = new WebSocket(url);
                wsRef.current = ws;

                ws.onopen = () => setIsConnected(true);
                ws.onclose = () => {
                    setIsConnected(false);
                    setTimeout(connect, 3000);
                };
                ws.onmessage = (event) => {
                    try {
                        setLastMessage(JSON.parse(event.data));
                    } catch (e) { /* ignore */ }
                };
            } catch (e) {
                setTimeout(connect, 3000);
            }
        };

        connect();
        return () => {
            if (wsRef.current) wsRef.current.close();
        };
    }, [url]);

    const sendMessage = useCallback((data) => {
        if (wsRef.current?.readyState === WebSocket.OPEN) {
            wsRef.current.send(JSON.stringify(data));
        }
    }, []);

    return { lastMessage, isConnected, sendMessage };
}

// ============================================
// Live Feed Component — Stream isolated from React renders
// ============================================
function LiveFeed({ cameraIp, detections }) {
    const containerRef = useRef(null);
    const imgRef = useRef(null);
    const currentUrlRef = useRef(null);

    // Imperatively create/manage the <img> element so React NEVER touches it
    useEffect(() => {
        const container = containerRef.current;
        if (!container) return;

        const newUrl = cameraIp ? `http://${cameraIp}:81/stream` : null;
        if (currentUrlRef.current === newUrl && imgRef.current) return;
        currentUrlRef.current = newUrl;

        // Clean up old img
        if (imgRef.current) {
            imgRef.current.src = '';
            imgRef.current.remove();
            imgRef.current = null;
        }

        if (!newUrl) return;

        // Create img element OUTSIDE of React
        const img = document.createElement('img');
        img.alt = 'Live Feed';
        img.src = newUrl;

        // Stall detection — if stream freezes, auto-reconnect
        let stallTimer = null;
        const STALL_TIMEOUT = 4000; // 4 seconds without a new frame = stalled

        const resetStallTimer = () => {
            clearTimeout(stallTimer);
            stallTimer = setTimeout(() => {
                // Stream stalled — force reconnect
                if (img.parentNode) {
                    img.src = '';
                    setTimeout(() => {
                        img.src = `${newUrl}?t=${Date.now()}`;
                    }, 500);
                }
            }, STALL_TIMEOUT);
        };

        // MJPEG streams fire 'load' on each new frame in some browsers
        // Also use a MutationObserver-like approach via polling naturalWidth
        let lastWidth = 0;
        const frameChecker = setInterval(() => {
            if (img.naturalWidth !== lastWidth || img.complete) {
                lastWidth = img.naturalWidth;
                resetStallTimer();
            }
        }, 1000);

        img.onload = resetStallTimer;
        img.onerror = () => {
            setTimeout(() => {
                if (img.parentNode) {
                    img.src = `${newUrl}?t=${Date.now()}`;
                }
            }, 2000);
        };

        resetStallTimer(); // Start initial timer

        container.insertBefore(img, container.firstChild);
        imgRef.current = img;

        return () => {
            clearTimeout(stallTimer);
            clearInterval(frameChecker);
            img.src = '';
            img.remove();
            imgRef.current = null;
            currentUrlRef.current = null;
        };
    }, [cameraIp]);

    return (
        <div className="card">
            <div className="card-header">
                <span className="card-title">
                    <span className="card-title-icon">🎥</span>
                    Live Camera Feed
                </span>
                <span className="card-badge">CAM-01</span>
            </div>
            <div className="live-feed-container" ref={containerRef}>
                {!cameraIp && (
                    <div className="live-feed-placeholder">
                        <span className="icon">📷</span>
                        <span>Camera not connected</span>
                        <span style={{ fontSize: '0.7rem' }}>Configure ESP32-CAM IP in settings</span>
                    </div>
                )}

                <div className="feed-overlay">
                    <span className="feed-tag live">● LIVE</span>
                    <span className="feed-tag recording">⏺ REC</span>
                </div>

                <div className="feed-detections">
                    {detections.map((d, i) => (
                        <span
                            key={i}
                            className={`detection-chip ${d.class_name !== 'person' ? 'vehicle' : ''}`}
                        >
                            {d.class_name === 'person' ? '👤' : '🚗'} {d.class_name}: {(d.confidence * 100).toFixed(0)}%
                        </span>
                    ))}
                </div>
            </div>
        </div>
    );
}

// ============================================
// Camera Controls Component
// ============================================
function CameraControls({ onServoCmd, mode, setMode, trackingStatus }) {
    const [speed, setSpeed] = useState(80);

    const handleMove = (direction) => {
        onServoCmd({ type: 'servo_cmd', camera_id: 1, direction, value: Math.round(speed / 10) });
    };

    const handleModeChange = async (newMode) => {
        if (newMode === 'auto') {
            // Start YOLO auto-tracking
            try {
                await fetch(`${API_BASE}/camera/tracking/start`, { method: 'POST' });
            } catch (e) { /* ignore */ }
        } else if (mode === 'auto' && newMode !== 'auto') {
            // Stop auto-tracking when leaving auto mode
            try {
                await fetch(`${API_BASE}/camera/tracking/stop`, { method: 'POST' });
            } catch (e) { /* ignore */ }
        }
        setMode(newMode);
    };

    return (
        <div className="card">
            <div className="card-header">
                <span className="card-title">
                    <span className="card-title-icon">🕹️</span>
                    Camera Controls
                </span>
                {mode === 'auto' && trackingStatus?.target_locked && (
                    <span className="card-badge" style={{ background: '#22c55e', color: '#000' }}>🎯 LOCKED</span>
                )}
            </div>
            <div className="card-body controls-grid">
                {/* Mode Toggle */}
                <div className="mode-selector">
                    {['Manual', 'Auto', 'Adaptive'].map((m) => (
                        <button
                            key={m}
                            className={`mode-btn ${mode === m.toLowerCase() ? 'active' : ''}`}
                            onClick={() => handleModeChange(m.toLowerCase())}
                        >
                            {m}
                        </button>
                    ))}
                </div>

                {/* Joystick */}
                <div className="joystick-container">
                    <div className="joy-btn empty" />
                    <button className="joy-btn" onClick={() => handleMove('up')} title="Tilt Up">▲</button>
                    <div className="joy-btn empty" />
                    <button className="joy-btn" onClick={() => handleMove('left')} title="Pan Left">◄</button>
                    <button className="joy-btn center" onClick={() => handleMove('center')} title="Center">⊙</button>
                    <button className="joy-btn" onClick={() => handleMove('right')} title="Pan Right">►</button>
                    <div className="joy-btn empty" />
                    <button className="joy-btn" onClick={() => handleMove('down')} title="Tilt Down">▼</button>
                    <div className="joy-btn empty" />
                </div>

                {/* Speed */}
                <div className="speed-control">
                    <span className="speed-label">Speed</span>
                    <input
                        type="range"
                        className="speed-slider"
                        min="10"
                        max="100"
                        value={speed}
                        onChange={(e) => setSpeed(Number(e.target.value))}
                    />
                    <span className="speed-value">{speed}%</span>
                </div>

                {/* Quick Actions */}
                <div style={{ display: 'flex', gap: '6px' }}>
                    <button
                        className="btn btn-primary btn-sm"
                        style={{ flex: 1 }}
                        onClick={() => onServoCmd({ type: 'patrol_cmd', camera_id: 1, action: 'start' })}
                    >
                        ▶ Start Patrol
                    </button>
                    <button
                        className="btn btn-danger btn-sm"
                        style={{ flex: 1 }}
                        onClick={() => onServoCmd({ type: 'patrol_cmd', camera_id: 1, action: 'stop' })}
                    >
                        ⏹ Stop
                    </button>
                </div>
            </div>
        </div>
    );
}

// ============================================
// Anomaly Score Component
// ============================================
function AnomalyScore({ score }) {
    const s = score || { overall_score: 0, factors: {}, threat_level: 'low', description: 'No data' };
    const percent = (s.overall_score / 10) * 100;

    const getFactorClass = (value) => {
        if (value >= 5) return 'danger';
        if (value >= 2) return 'warn';
        return 'safe';
    };

    return (
        <div className="card">
            <div className="card-header">
                <span className="card-title">
                    <span className="card-title-icon">🧠</span>
                    Anomaly Score
                </span>
                <span className={`card-badge ${s.threat_level === 'critical' || s.threat_level === 'high' ? 'danger' : s.threat_level === 'low' ? 'success' : ''}`}>
                    {s.threat_level.toUpperCase()}
                </span>
            </div>
            <div className="card-body anomaly-container">
                <div className="anomaly-score-bar">
                    <div
                        className={`anomaly-score-fill ${s.threat_level}`}
                        style={{ width: `${Math.max(percent, 8)}%` }}
                    >
                        {s.overall_score.toFixed(1)} / 10
                    </div>
                </div>

                <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                    {s.description}
                </div>

                <div className="anomaly-factors">
                    {Object.entries(s.factors || {}).map(([key, val]) => (
                        <div key={key} className="factor-item">
                            <span className="factor-name">
                                {key === 'dwell' ? '⏱ Dwell' :
                                    key === 'speed' ? '💨 Speed' :
                                        key === 'curvature' ? '🔄 Path' :
                                            key === 'direction' ? '↩ Direction' :
                                                key === 'zone' ? '🚧 Zone' :
                                                    key === 'time' ? '🕐 Time' : key}
                            </span>
                            <span className={`factor-value ${getFactorClass(val)}`}>
                                {val.toFixed(1)}
                            </span>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
}

// ============================================
// Heat Map Component
// ============================================
function HeatMap({ data }) {
    const heatData = data || { grid_rows: 3, grid_cols: 4, cells: [], bucket: 'unknown' };
    const cells = heatData.cells || [];

    const getHeatColor = (normalized) => {
        if (normalized === 0) return 'rgba(148, 163, 184, 0.1)';
        const r = Math.round(normalized * 239 + (1 - normalized) * 59);
        const g = Math.round((1 - normalized) * 130 + normalized * 68);
        const b = Math.round((1 - normalized) * 246 + normalized * 68);
        return `rgba(${r}, ${g}, ${b}, ${0.3 + normalized * 0.7})`;
    };

    return (
        <div className="card">
            <div className="card-header">
                <span className="card-title">
                    <span className="card-title-icon">🗺️</span>
                    Detection Heat Map
                </span>
                <span className="card-badge">{heatData.bucket}</span>
            </div>
            <div className="card-body">
                <div
                    className="heatmap-grid"
                    style={{
                        gridTemplateColumns: `repeat(${heatData.grid_cols}, 1fr)`,
                        gridTemplateRows: `repeat(${heatData.grid_rows}, 1fr)`,
                    }}
                >
                    {cells.map((cell, i) => (
                        <div
                            key={i}
                            className="heatmap-cell"
                            style={{
                                background: getHeatColor(cell.normalized),
                                color: cell.normalized > 0.5 ? 'white' : 'var(--text-muted)',
                            }}
                            title={`Zone (${cell.row},${cell.col}): ${cell.value} detections`}
                        >
                            {cell.value > 0 ? cell.value.toFixed(0) : ''}
                        </div>
                    ))}
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.65rem', color: 'var(--text-muted)', marginTop: '8px' }}>
                    <span>Total: {heatData.total_detections || 0} detections</span>
                    <span style={{ display: 'flex', gap: '12px' }}>
                        <span>🟢 Low</span>
                        <span>🟡 Medium</span>
                        <span>🔴 High</span>
                    </span>
                </div>
            </div>
        </div>
    );
}

// ============================================
// Alert Center Component
// ============================================
function AlertCenter({ alerts }) {
    const alertList = alerts || [];

    const formatTime = (timestamp) => {
        const d = new Date(timestamp);
        return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
    };

    return (
        <div className="card">
            <div className="card-header">
                <span className="card-title">
                    <span className="card-title-icon">🔔</span>
                    Alert Center
                </span>
                {alertList.length > 0 && (
                    <span className="card-badge danger">{alertList.length} Active</span>
                )}
            </div>
            <div className="card-body">
                {alertList.length === 0 ? (
                    <div style={{ textAlign: 'center', padding: '30px 0', color: 'var(--text-muted)' }}>
                        <div style={{ fontSize: '2rem', marginBottom: '8px', opacity: 0.3 }}>✓</div>
                        <div style={{ fontSize: '0.8rem' }}>No active alerts</div>
                        <div style={{ fontSize: '0.7rem' }}>System is monitoring normally</div>
                    </div>
                ) : (
                    <div className="alerts-list">
                        {alertList.map((alert, i) => (
                            <div key={i} className={`alert-item ${alert.threat_level} slide-in`} style={{ animationDelay: `${i * 50}ms` }}>
                                <div className={`alert-dot ${alert.threat_level}`} />
                                <div className="alert-content">
                                    <div className="alert-message">{alert.message || alert.description}</div>
                                    <div className="alert-meta">
                                        <span>{formatTime(alert.timestamp || Date.now())}</span>
                                        <span>•</span>
                                        <span>CAM-{String(alert.camera_id || 1).padStart(2, '0')}</span>
                                        <span>•</span>
                                        <span className="alert-score" style={{ color: alert.threat_level === 'critical' ? 'var(--accent-red)' : 'var(--accent-amber)' }}>
                                            Score: {(alert.score || alert.overall_score || 0).toFixed(1)}
                                        </span>
                                    </div>
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}

// ============================================
// Digital Twin Map Component
// ============================================
function DigitalTwinMap({ trackedObjects, cameras }) {
    const objects = trackedObjects || [];
    const cams = cameras || [{ id: 1, x: 15, y: 20 }, { id: 2, x: 80, y: 70 }];

    return (
        <div className="card">
            <div className="card-header">
                <span className="card-title">
                    <span className="card-title-icon">🗺️</span>
                    Digital Twin — Surveillance Map
                </span>
                <span className="card-badge success">{objects.length} Objects</span>
            </div>
            <div className="card-body">
                <div className="map-container">
                    {/* Grid overlay */}
                    <div className="map-grid">
                        {Array.from({ length: 32 }, (_, i) => (
                            <div key={i} className="map-grid-cell" />
                        ))}
                    </div>

                    {/* Camera icons */}
                    {cams.map((cam) => (
                        <div
                            key={cam.id}
                            className="map-camera"
                            style={{ left: `${cam.x}%`, top: `${cam.y}%`, transform: 'translate(-50%, -50%)' }}
                            title={`Camera ${cam.id}`}
                        >
                            📹
                            <div className="fov" />
                        </div>
                    ))}

                    {/* Tracked objects */}
                    {objects.map((obj) => {
                        const x = (obj.center?.[0] || 0) / 640 * 100;
                        const y = (obj.center?.[1] || 0) / 480 * 100;
                        const isAlert = (obj.anomaly_score || 0) >= 5;

                        return (
                            <div
                                key={obj.track_id}
                                className={`map-object ${isAlert ? 'alert' : ''}`}
                                style={{
                                    left: `${Math.min(95, Math.max(5, x))}%`,
                                    top: `${Math.min(95, Math.max(5, y))}%`,
                                    transform: 'translate(-50%, -50%)',
                                }}
                                title={`${obj.class_name} #${obj.track_id} — Score: ${(obj.anomaly_score || 0).toFixed(1)}`}
                            />
                        );
                    })}

                    {/* Legend */}
                    <div className="map-legend">
                        <div className="legend-item">
                            <div className="legend-dot" style={{ background: 'var(--accent-blue)' }} />
                            Camera
                        </div>
                        <div className="legend-item">
                            <div className="legend-dot" style={{ background: 'var(--accent-emerald)' }} />
                            Object
                        </div>
                        <div className="legend-item">
                            <div className="legend-dot" style={{ background: 'var(--accent-red)' }} />
                            Alert
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}

// ============================================
// System Status Component
// ============================================
function SystemStatus({ wsConnected, mqttConnected, stats }) {
    return (
        <div className="card">
            <div className="card-header">
                <span className="card-title">
                    <span className="card-title-icon">⚡</span>
                    System Status
                </span>
            </div>
            <div className="card-body">
                <div className="sys-stats">
                    <div className="sys-stat">
                        <div className="sys-stat-value">{stats.activeCameras || 0}</div>
                        <div className="sys-stat-label">Cameras Online</div>
                    </div>
                    <div className="sys-stat">
                        <div className="sys-stat-value">{stats.totalDetections || 0}</div>
                        <div className="sys-stat-label">Detections</div>
                    </div>
                    <div className="sys-stat">
                        <div className="sys-stat-value">{stats.activeAlerts || 0}</div>
                        <div className="sys-stat-label">Active Alerts</div>
                    </div>
                    <div className="sys-stat">
                        <div className="sys-stat-value">{stats.avgInference || '—'}</div>
                        <div className="sys-stat-label">Avg YOLO ms</div>
                    </div>
                </div>

                <div style={{ marginTop: '14px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    <div className="header-status">
                        <span className={`status-dot ${wsConnected ? 'online' : 'offline'}`} />
                        WebSocket {wsConnected ? 'Connected' : 'Disconnected'}
                    </div>
                    <div className="header-status">
                        <span className={`status-dot ${mqttConnected ? 'online' : 'offline'}`} />
                        MQTT Broker {mqttConnected ? 'Connected' : 'Disconnected'}
                    </div>
                </div>
            </div>
        </div>
    );
}

// ============================================
// Main App
// ============================================
export default function App() {
    // WebSocket
    const wsUrl = `ws://${window.location.hostname}:8000/api/camera/ws`;
    const { lastMessage, isConnected, sendMessage } = useWebSocket(wsUrl);

    // State
    const [mode, setMode] = useState('manual');
    const [cameraIp, setCameraIp] = useState('');
    const [servoIp, setServoIp] = useState('');
    const [detections, setDetections] = useState([]);
    const [trackedObjects, setTrackedObjects] = useState([]);
    const [anomalyScore, setAnomalyScore] = useState(null);
    const [alerts, setAlerts] = useState([]);
    const [heatMapData, setHeatMapData] = useState(null);
    const [stats, setStats] = useState({
        activeCameras: 0,
        totalDetections: 0,
        activeAlerts: 0,
        avgInference: '—',
    });
    const [settingsOpen, setSettingsOpen] = useState(false);
    const [mqttConnected, setMqttConnected] = useState(false);
    const [trackingStatus, setTrackingStatus] = useState({ running: false, target_locked: false });

    // Process WebSocket messages
    useEffect(() => {
        if (!lastMessage) return;

        if (lastMessage.type === 'detection') {
            const d = lastMessage.data;
            setDetections(d.detections || []);
            setTrackedObjects(d.tracked_objects || []);
            if (d.anomaly_scores?.[0]) {
                setAnomalyScore(d.anomaly_scores[0]);
            }
            if (d.alerts?.length > 0) {
                setAlerts((prev) => [...d.alerts, ...prev].slice(0, 20));
            }
            setStats((prev) => ({
                ...prev,
                totalDetections: prev.totalDetections + (d.detections?.length || 0),
            }));
        }

        // YOLO auto-tracking updates
        if (lastMessage.type === 'tracking') {
            const t = lastMessage.data;
            setTrackingStatus({ running: true, target_locked: t.locked, offset_x: t.offset_x, offset_y: t.offset_y });
            setDetections(t.detections || []);
        }
    }, [lastMessage]);

    // Fetch initial data + load stored IPs
    useEffect(() => {
        const fetchData = async () => {
            try {
                const res = await fetch(`${API_BASE}/patrol/heatmap`);
                if (res.ok) {
                    const data = await res.json();
                    setHeatMapData(data);
                }
            } catch (e) { /* Backend not running */ }

            try {
                const res = await fetch(`${API_BASE}/detection/stats`);
                if (res.ok) {
                    const data = await res.json();
                    setStats((prev) => ({
                        ...prev,
                        avgInference: data.yolo?.avg_inference_ms || '—',
                    }));
                }
            } catch (e) { /* Backend not running */ }

            try {
                const res = await fetch('/health');
                if (res.ok) {
                    const data = await res.json();
                    setMqttConnected(data.mqtt_connected || false);
                }
            } catch (e) { /* Backend not running */ }
        };

        // Load stored IPs from backend
        const loadIps = async () => {
            try {
                const res = await fetch(`${API_BASE}/camera/config/ips`);
                if (res.ok) {
                    const data = await res.json();
                    setCameraIp(data.camera_ip || '');
                    setServoIp(data.servo_ip || '');
                }
            } catch (e) { /* Backend not running */ }
        };
        loadIps();

        fetchData();
        const interval = setInterval(fetchData, 10000);
        return () => clearInterval(interval);
    }, []);

    // Generate demo data for showcase
    useEffect(() => {
        // Only populate demo data if no real data exists
        if (detections.length === 0 && !anomalyScore) {
            setAnomalyScore({
                overall_score: 3.2,
                threat_level: 'medium',
                description: 'Demo mode — connect camera for live data',
                factors: {
                    dwell: 2.0,
                    speed: 0.0,
                    curvature: 1.5,
                    direction: 0.5,
                    zone: 0.0,
                    time: 5.0,
                },
            });

            setHeatMapData({
                grid_rows: 3,
                grid_cols: 4,
                bucket: 'afternoon',
                total_detections: 42,
                cells: [
                    { row: 0, col: 0, value: 3, normalized: 0.2 },
                    { row: 0, col: 1, value: 8, normalized: 0.53 },
                    { row: 0, col: 2, value: 2, normalized: 0.13 },
                    { row: 0, col: 3, value: 0, normalized: 0 },
                    { row: 1, col: 0, value: 12, normalized: 0.8 },
                    { row: 1, col: 1, value: 15, normalized: 1.0 },
                    { row: 1, col: 2, value: 5, normalized: 0.33 },
                    { row: 1, col: 3, value: 1, normalized: 0.07 },
                    { row: 2, col: 0, value: 4, normalized: 0.27 },
                    { row: 2, col: 1, value: 7, normalized: 0.47 },
                    { row: 2, col: 2, value: 0, normalized: 0 },
                    { row: 2, col: 3, value: 0, normalized: 0 },
                ],
            });

            setAlerts([
                {
                    threat_level: 'high',
                    message: 'Person loitering in Zone A for 4min 23s',
                    timestamp: Date.now() - 300000,
                    camera_id: 1,
                    score: 7.2,
                },
                {
                    threat_level: 'medium',
                    message: 'Unusual movement pattern detected — erratic path',
                    timestamp: Date.now() - 600000,
                    camera_id: 1,
                    score: 5.4,
                },
                {
                    threat_level: 'low',
                    message: 'Vehicle entered monitored parking zone',
                    timestamp: Date.now() - 1200000,
                    camera_id: 1,
                    score: 2.1,
                },
            ]);
        }
    }, []);

    const handleServoCmd = (cmd) => {
        if (cmd.type === 'servo_cmd') {
            if (servoIp) {
                // Direct HTTP to servo ESP32 — instant, no conflict
                // (servo is a DIFFERENT device from camera, its port 81 isn't blocked)
                fetch(`http://${servoIp}:81/servo?dir=${cmd.direction}&val=${cmd.value}`, {
                    mode: 'no-cors',
                }).catch(() => { });
            } else {
                // Fallback: route through backend → MQTT
                fetch(`${API_BASE}/camera/${cmd.camera_id}/servo`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ direction: cmd.direction, value: cmd.value }),
                }).catch(() => { });
            }
        } else {
            sendMessage(cmd);
        }
    };

    const handleSaveIps = async () => {
        try {
            await fetch(`${API_BASE}/camera/config/ips`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ camera_ip: cameraIp, servo_ip: servoIp }),
            });
        } catch (e) { /* Backend not running */ }
        setSettingsOpen(false);
    };

    return (
        <div className="app">
            {/* Header */}
            <header className="header">
                <div className="header-brand">
                    <div className="header-logo">🛡️</div>
                    <div>
                        <div className="header-title">Project Netra</div>
                        <div className="header-subtitle">Intelligent Adaptive Surveillance</div>
                    </div>
                </div>

                <div className="header-actions">
                    <div className="header-status">
                        <span className={`status-dot ${isConnected ? 'online' : 'offline'}`} />
                        {isConnected ? 'Connected' : 'Offline'}
                    </div>

                    <button className="btn btn-sm" onClick={() => setSettingsOpen(!settingsOpen)}>
                        ⚙️ Settings
                    </button>
                </div>
            </header>

            {/* Settings Bar */}
            {settingsOpen && (
                <div style={{
                    padding: '12px 24px',
                    background: 'var(--bg-secondary)',
                    borderBottom: '1px solid var(--border-color)',
                    display: 'flex',
                    gap: '16px',
                    alignItems: 'center',
                    flexWrap: 'wrap',
                }}
                    className="fade-in"
                >
                    <label style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
                        Camera IP:
                    </label>
                    <input
                        type="text"
                        value={cameraIp}
                        onChange={(e) => setCameraIp(e.target.value)}
                        placeholder="10.154.46.161"
                        style={{
                            padding: '6px 12px',
                            background: 'var(--bg-input)',
                            border: '1px solid var(--border-color)',
                            borderRadius: 'var(--radius-sm)',
                            color: 'var(--text-primary)',
                            fontFamily: 'var(--font-mono)',
                            fontSize: '0.78rem',
                            width: '150px',
                        }}
                    />
                    <label style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
                        Servo IP:
                    </label>
                    <input
                        type="text"
                        value={servoIp}
                        onChange={(e) => setServoIp(e.target.value)}
                        placeholder="10.154.46.39"
                        style={{
                            padding: '6px 12px',
                            background: 'var(--bg-input)',
                            border: '1px solid var(--border-color)',
                            borderRadius: 'var(--radius-sm)',
                            color: 'var(--text-primary)',
                            fontFamily: 'var(--font-mono)',
                            fontSize: '0.78rem',
                            width: '150px',
                        }}
                    />
                    <button className="btn btn-primary btn-sm" onClick={handleSaveIps}>
                        Apply
                    </button>
                </div>
            )}

            {/* Dashboard Grid */}
            <main className="dashboard">
                {/* Left Column: Live Feed */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--gap-lg)' }}>
                    <LiveFeed cameraIp={cameraIp} detections={detections} />
                    <AnomalyScore score={anomalyScore} />
                </div>

                {/* Right Column: Controls & Alerts */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--gap-lg)' }}>
                    <CameraControls onServoCmd={handleServoCmd} mode={mode} setMode={setMode} trackingStatus={trackingStatus} />
                    <AlertCenter alerts={alerts} />
                    <SystemStatus
                        wsConnected={isConnected}
                        mqttConnected={mqttConnected}
                        stats={stats}
                    />
                </div>

                {/* Bottom Section: Map + Heat Map */}
                <div className="bottom-section">
                    <DigitalTwinMap trackedObjects={trackedObjects} />
                    <HeatMap data={heatMapData} />
                </div>
            </main>
        </div>
    );
}
