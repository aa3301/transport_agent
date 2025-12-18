"""
SQLAlchemy ORM models for MySQL database.

Purpose:
- Define Bus, Route, Subscription, Driver, and User tables
- Use SQLAlchemy async-compatible models
- Support migrations via Alembic

Production notes:
- Add indexes on frequently queried columns (bus_id, user_id, route_id)
- Add timestamps (created_at, updated_at) for audit trails
- Use proper constraints and foreign keys for data integrity
- Consider partitioning high-volume tables (e.g., bus events) by date/bus_id
"""

from sqlalchemy import Column, Integer, String, Float, DateTime, JSON, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from core.db import Base
from datetime import datetime

class Bus(Base):
    """
    Represents a bus in the fleet.
    
    Columns:
    - bus_id: unique identifier (e.g., "B1")
    - lat/lon: current GPS location
    - speed_kmph: current speed
    - route_id: foreign key to Route
    - status: on_time, delayed, breakdown, maintenance
    - status_message: human-readable status description
    - created_at/updated_at: audit timestamps
    """
    __tablename__ = "buses"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    bus_id = Column(String(50), unique=True, index=True, nullable=False)
    lat = Column(Float, nullable=True)
    lon = Column(Float, nullable=True)
    speed_kmph = Column(Float, default=0.0)
    route_id = Column(String(50), ForeignKey("routes.route_id"), nullable=True, index=True)
    status = Column(String(50), default="on_time", index=True)
    status_message = Column(String(500), nullable=True)
    metadata_json = Column(JSON, nullable=True)  # flexible storage for extra fields
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # --- relationships ---
    # One Route -> many Buses
    route = relationship("Route", back_populates="buses", lazy="joined")
    # One Bus -> many Drivers (usually one active at a time)
    drivers = relationship("Driver", back_populates="bus", lazy="selectin")
    # NOTE: we intentionally do NOT declare Bus.subscriptions here to avoid FK errors,
    # because subscriptions.bus_id is a plain string without a real ForeignKey.


class Route(Base):
    """
    Represents a bus route (collection of stops).
    
    Columns:
    - route_id: unique identifier (e.g., "R1")
    - stops: JSON array of stop definitions (id, name, lat, lon)
    - created_at/updated_at: audit timestamps
    """
    __tablename__ = "routes"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    route_id = Column(String(50), unique=True, index=True, nullable=False)
    stops = Column(JSON, nullable=True)  # [{id: S1, name: Office, lat: 22.57, lon: 88.37}, ...]
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # --- relationships ---
    # One Route -> many Buses
    buses = relationship("Bus", back_populates="route", lazy="selectin")


class Subscription(Base):
    """
    Represents a user subscription to bus arrival notifications.
    
    Columns:
    - user_id: subscriber identifier
    - bus_id: subscribed bus
    - stop_id: target stop
    - notify_before_sec: send alert N seconds before arrival
    - policy: JSON for notification rules (notify_once, delay_threshold, etc.)
    - channel: delivery channel (console, email, sms, webhook)
    - is_active: soft delete flag
    - created_at/updated_at: audit timestamps
    """
    __tablename__ = "subscriptions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    # user_id here is a business key, matching users.user_id (string), not users.id
    user_id = Column(String(100), index=True, nullable=False)
    bus_id = Column(String(50), index=True, nullable=False)
    stop_id = Column(String(50), nullable=False)
    notify_before_sec = Column(Integer, default=300)
    policy = Column(JSON, nullable=True)
    channel = Column(String(50), default="console")
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        # In production, enforce that a user cannot subscribe to the same bus/stop twice:
        # UniqueConstraint("user_id", "bus_id", "stop_id", name="ux_subscription_user_bus_stop"),
    )

    # --- relationships ---
    # Link to User by business key (user_id string). viewonly so no real FK required.
    user = relationship(
        "User",
        primaryjoin="foreign(Subscription.user_id) == User.user_id",
        back_populates="subscriptions",
        lazy="joined",
        viewonly=True,
    )
    # NOTE: we remove Subscription.bus relationship to avoid SQLAlchemy trying to
    # auto-join buses<->subscriptions without a real ForeignKey.


class Driver(Base):
    """
    Represents a driver (optional; can expand with shifts, ratings, etc.)
    """
    __tablename__ = "drivers"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    driver_id = Column(String(50), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=True)
    phone = Column(String(20), nullable=True)
    bus_id = Column(String(50), ForeignKey("buses.bus_id"), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # --- relationships ---
    # Many Drivers -> one Bus
    bus = relationship("Bus", back_populates="drivers", lazy="joined")


class User(Base):
    """
    Represents a user (customer, admin, driver).
    """
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(100), unique=True, index=True, nullable=False)
    role = Column(String(50), default="user", index=True)  # user, driver, admin
    name = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True, unique=True, index=True)
    phone = Column(String(20), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # --- relationships ---
    # One User -> many Subscriptions (by user_id business key)
    subscriptions = relationship(
        "Subscription",
        primaryjoin="User.user_id == foreign(Subscription.user_id)",
        back_populates="user",
        lazy="selectin",
        viewonly=True,
    )
