from geoalchemy2 import Geometry
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
)
from sqlalchemy.orm import relationship

from database import Base

# Association Tables
city_admins = Table(
    "city_admins",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("city_id", Integer, ForeignKey("cities.id"), primary_key=True),
)

vendor_admins = Table(
    "vendor_admins",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("vendor_id", Integer, ForeignKey("vendors.id"), primary_key=True),
)

vendor_cities = Table(
    "vendor_cities",
    Base.metadata,
    Column("vendor_id", Integer, ForeignKey("vendors.id"), primary_key=True),
    Column("city_id", Integer, ForeignKey("cities.id"), primary_key=True),
)


class Item(Base):
    __tablename__ = "items"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    description = Column(Text, nullable=True)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True, nullable=True)
    hashed_password = Column(String)
    api_key = Column(String, unique=True, index=True)
    is_admin = Column(Boolean, default=False)
    description = Column(Text, nullable=True)

    # Relationships
    administered_cities = relationship(
        "City", secondary=city_admins, back_populates="admins"
    )
    administered_vendors = relationship(
        "Vendor", secondary=vendor_admins, back_populates="admins"
    )
    attended_events = relationship(
        "Event", secondary="event_attendance", back_populates="attendees"
    )
    detours = relationship("Detour", back_populates="owner")
    shared_detours = relationship(
        "Detour", secondary="detour_shares", back_populates="shared_with"
    )


class City(Base):
    __tablename__ = "cities"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    boundary = Column(Geometry("POLYGON", srid=4326))

    # Relationships
    admins = relationship("User", secondary=city_admins, back_populates="administered_cities")
    authorized_vendors = relationship(
        "Vendor", secondary=vendor_cities, back_populates="authorized_cities"
    )


class Vendor(Base):
    __tablename__ = "vendors"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)

    # Relationships
    admins = relationship(
        "User", secondary=vendor_admins, back_populates="administered_vendors"
    )
    authorized_cities = relationship(
        "City", secondary=vendor_cities, back_populates="authorized_vendors"
    )


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    description = Column(Text, nullable=True)
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    location = Column(Geometry("POINT", srid=4326))

    owner_type = Column(String)  # 'city' or 'vendor'
    owner_id = Column(Integer)

    # Relationships
    attendees = relationship(
        "User", secondary="event_attendance", back_populates="attended_events"
    )


class Detour(Base):
    __tablename__ = "detours"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    description = Column(Text, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"))

    # Relationships
    owner = relationship("User", back_populates="detours")
    events = relationship("DetourEvent", back_populates="detour", order_by="DetourEvent.order")
    shared_with = relationship(
        "User", secondary="detour_shares", back_populates="shared_detours"
    )


class DetourEvent(Base):
    __tablename__ = "detour_events"

    detour_id = Column(Integer, ForeignKey("detours.id"), primary_key=True)
    event_id = Column(Integer, ForeignKey("events.id"), primary_key=True)
    order = Column(Integer, primary_key=True)

    # Relationships
    detour = relationship("Detour", back_populates="events")
    event = relationship("Event")


# Association Tables (placed after classes to avoid forward reference issues if needed, though SQLAlchemy strings work too)
event_attendance = Table(
    "event_attendance",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("event_id", Integer, ForeignKey("events.id"), primary_key=True),
)

detour_shares = Table(
    "detour_shares",
    Base.metadata,
    Column("detour_id", Integer, ForeignKey("detours.id"), primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
)
