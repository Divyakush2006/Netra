"""
Project Netra — Alerts Router
Endpoints for alert management, history, and notifications.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Request, HTTPException
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.db import async_session, AlertRecord
from app.models.schemas import Alert, ThreatLevel

logger = logging.getLogger("netra.api.alerts")
router = APIRouter()


@router.get("/")
async def get_alerts(
    limit: int = 50,
    threat_level: Optional[str] = None,
    acknowledged: Optional[bool] = None,
    hours: int = 24,
):
    """Get recent alerts with optional filters."""
    async with async_session() as session:
        query = select(AlertRecord).order_by(desc(AlertRecord.timestamp))
        
        # Time filter
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        query = query.where(AlertRecord.timestamp >= cutoff)
        
        # Threat level filter
        if threat_level:
            query = query.where(AlertRecord.threat_level == threat_level)
        
        # Acknowledged filter
        if acknowledged is not None:
            query = query.where(AlertRecord.acknowledged == acknowledged)
        
        query = query.limit(limit)
        
        result = await session.execute(query)
        alerts = result.scalars().all()
        
        return {
            "alerts": [
                {
                    "id": a.id,
                    "timestamp": a.timestamp.isoformat(),
                    "camera_id": a.camera_id,
                    "alert_type": a.alert_type,
                    "threat_level": a.threat_level,
                    "score": a.score,
                    "message": a.message,
                    "track_id": a.track_id,
                    "acknowledged": a.acknowledged,
                }
                for a in alerts
            ],
            "count": len(alerts),
        }


@router.post("/create")
async def create_alert(alert: Alert):
    """Create a new alert (usually called internally)."""
    async with async_session() as session:
        record = AlertRecord(
            timestamp=alert.timestamp,
            camera_id=alert.camera_id,
            alert_type=alert.alert_type.value,
            threat_level=alert.threat_level.value,
            score=alert.score,
            message=alert.message,
            track_id=alert.track_id,
            acknowledged=False,
        )
        session.add(record)
        await session.commit()
        
        return {"id": record.id, "status": "created"}


@router.post("/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: int):
    """Acknowledge (dismiss) an alert."""
    async with async_session() as session:
        result = await session.execute(
            select(AlertRecord).where(AlertRecord.id == alert_id)
        )
        alert = result.scalar_one_or_none()
        
        if not alert:
            raise HTTPException(404, f"Alert {alert_id} not found")
        
        alert.acknowledged = True
        await session.commit()
        
        return {"id": alert_id, "status": "acknowledged"}


@router.post("/acknowledge/all")
async def acknowledge_all():
    """Acknowledge all unacknowledged alerts."""
    async with async_session() as session:
        result = await session.execute(
            select(AlertRecord).where(AlertRecord.acknowledged == False)
        )
        alerts = result.scalars().all()
        
        for alert in alerts:
            alert.acknowledged = True
        
        await session.commit()
        
        return {"acknowledged_count": len(alerts)}


@router.get("/summary")
async def alert_summary():
    """Get alert summary statistics."""
    async with async_session() as session:
        # Last 24 hours
        cutoff = datetime.utcnow() - timedelta(hours=24)
        
        result = await session.execute(
            select(AlertRecord).where(AlertRecord.timestamp >= cutoff)
        )
        alerts = result.scalars().all()
        
        # Count by threat level
        by_level = {"low": 0, "medium": 0, "high": 0, "critical": 0}
        by_type = {}
        unacknowledged = 0
        
        for a in alerts:
            by_level[a.threat_level] = by_level.get(a.threat_level, 0) + 1
            by_type[a.alert_type] = by_type.get(a.alert_type, 0) + 1
            if not a.acknowledged:
                unacknowledged += 1
        
        return {
            "total_24h": len(alerts),
            "unacknowledged": unacknowledged,
            "by_threat_level": by_level,
            "by_type": by_type,
        }
