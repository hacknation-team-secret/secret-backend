from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, String, Table, Text
from sqlalchemy.orm import relationship
from geoalchemy2 import Geometry

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
