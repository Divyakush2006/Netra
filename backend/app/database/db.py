"""
Project Netra — Database Models & Connection
SQLAlchemy async database with SQLite for event logging.
"""

import os
from datetime import datetime
from sqlalchemy import Column, Integer, Float, String, Boolean, DateTime, Text, JSON
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# Database URL
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./netra.db")

# Engine & Session
engine = create_async_engine(DATABASE_URL, echo=False)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


# ==========================================
# Models
# ==========================================

class DetectionEvent(Base):
    __tablename__ = "detection_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    camera_id = Column(Integer, index=True)
    class_name = Column(String(50))
    confidence = Column(Float)
    bbox_x1 = Column(Float)
    bbox_y1 = Column(Float)
    bbox_x2 = Column(Float)
    bbox_y2 = Column(Float)
    track_id = Column(Integer, nullable=True)


class AlertRecord(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    camera_id = Column(Integer, index=True)
    alert_type = Column(String(50))
    threat_level = Column(String(20))
    score = Column(Float)
    message = Column(Text)
    track_id = Column(Integer, nullable=True)
    acknowledged = Column(Boolean, default=False)
    snapshot_path = Column(String(255), nullable=True)


class HeatMapRecord(Base):
    __tablename__ = "heatmap_data"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    camera_id = Column(Integer, index=True)
    zone_row = Column(Integer)
    zone_col = Column(Integer)
    detection_count = Column(Integer, default=0)
    time_bucket = Column(String(20))  # morning, afternoon, evening, night


class PatrolHistory(Base):
    __tablename__ = "patrol_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    camera_id = Column(Integer, index=True)
    waypoints = Column(JSON)
    mode = Column(String(20))
    duration_seconds = Column(Integer, nullable=True)


class CameraNode(Base):
    __tablename__ = "camera_nodes"

    id = Column(Integer, primary_key=True)
    node_id = Column(Integer, unique=True, index=True)
    name = Column(String(100))
    ip_address = Column(String(45))
    mac_address = Column(String(17), nullable=True)
    location_x = Column(Float, nullable=True)
    location_y = Column(Float, nullable=True)
    orientation = Column(Float, default=0)  # degrees
    fov = Column(Float, default=60)  # field of view degrees
    active = Column(Boolean, default=True)
    last_seen = Column(DateTime, nullable=True)


# ==========================================
# Database Initialization
# ==========================================

async def init_db():
    """Create all tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:
    """Get a database session."""
    async with async_session() as session:
        yield session
