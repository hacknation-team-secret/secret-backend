from datetime import UTC, datetime

from geoalchemy2 import Geometry
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
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
    research_count = Column(Integer, default=0)

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
    research_threads = relationship("ResearchThread", back_populates="user")
    owned_groups = relationship("Group", back_populates="owner")
    group_memberships = relationship(
        "GroupMembership",
        back_populates="user",
        foreign_keys="GroupMembership.user_id",
    )


class Group(Base):
    __tablename__ = "groups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    description = Column(Text, nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))

    owner = relationship("User", back_populates="owned_groups")
    memberships = relationship(
        "GroupMembership",
        back_populates="group",
        cascade="all, delete-orphan",
    )
    favorites = relationship(
        "GroupFavorite",
        back_populates="group",
        cascade="all, delete-orphan",
    )
    budgets = relationship(
        "GroupBudget",
        back_populates="group",
        cascade="all, delete-orphan",
    )


class GroupMembership(Base):
    __tablename__ = "group_memberships"

    group_id = Column(Integer, ForeignKey("groups.id"), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    invited_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    status = Column(String, default="pending")
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))

    group = relationship("Group", back_populates="memberships")
    user = relationship(
        "User",
        back_populates="group_memberships",
        foreign_keys=[user_id],
    )
    invited_by = relationship("User", foreign_keys=[invited_by_id])


class GroupFavorite(Base):
    __tablename__ = "group_favorites"

    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(Integer, ForeignKey("groups.id"))
    created_by_id = Column(Integer, ForeignKey("users.id"))
    title = Column(String, index=True)
    description = Column(Text, nullable=True)
    category = Column(String, nullable=True)
    estimated_cost = Column(Float, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))

    group = relationship("Group", back_populates="favorites")
    created_by = relationship("User")
    votes = relationship(
        "GroupFavoriteVote",
        back_populates="favorite",
        cascade="all, delete-orphan",
    )


class GroupFavoriteVote(Base):
    __tablename__ = "group_favorite_votes"

    favorite_id = Column(Integer, ForeignKey("group_favorites.id"), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))

    favorite = relationship("GroupFavorite", back_populates="votes")
    user = relationship("User")


class GroupBudget(Base):
    __tablename__ = "group_budgets"

    group_id = Column(Integer, ForeignKey("groups.id"), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    total_budget = Column(Float)
    currency = Column(String, default="USD")
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC))

    group = relationship("Group", back_populates="budgets")
    user = relationship("User")


class ResearchThread(Base):
    __tablename__ = "research_threads"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))

    user = relationship("User", back_populates="research_threads")
    messages = relationship(
        "ResearchMessage", back_populates="thread", cascade="all, delete-orphan"
    )


class ResearchMessage(Base):
    __tablename__ = "research_messages"

    id = Column(Integer, primary_key=True, index=True)
    thread_id = Column(Integer, ForeignKey("research_threads.id"))
    role = Column(String)  # 'user' or 'assistant'
    content = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))

    thread = relationship("ResearchThread", back_populates="messages")


class SharedWallet(Base):
    __tablename__ = "shared_wallets"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    currency = Column(String, default="USD")
    total_balance_cents = Column(Integer, default=0)
    spending_limit_cents = Column(Integer, nullable=True)
    alert_threshold_percent = Column(Integer, default=20)
    join_code = Column(String, unique=True, index=True)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))

    creator = relationship("User")
    members = relationship(
        "WalletMember",
        back_populates="wallet",
        cascade="all, delete-orphan",
    )
    transactions = relationship(
        "WalletTransaction",
        back_populates="wallet",
        cascade="all, delete-orphan",
        order_by="desc(WalletTransaction.created_at)",
    )


class WalletMember(Base):
    __tablename__ = "wallet_members"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    wallet_id = Column(Integer, ForeignKey("shared_wallets.id"), primary_key=True)
    role = Column(String, default="member")
    contributed_cents = Column(Integer, default=0)
    spent_cents = Column(Integer, default=0)
    joined_at = Column(DateTime, default=lambda: datetime.now(UTC))

    user = relationship("User")
    wallet = relationship("SharedWallet", back_populates="members")


class WalletTransaction(Base):
    __tablename__ = "wallet_transactions"

    id = Column(Integer, primary_key=True, index=True)
    wallet_id = Column(Integer, ForeignKey("shared_wallets.id"))
    type = Column(String)  # topup | spend | refund
    amount_cents = Column(Integer)
    initiated_by = Column(Integer, ForeignKey("users.id"))
    merchant = Column(String, nullable=True)
    category = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))

    wallet = relationship("SharedWallet", back_populates="transactions")
    initiator = relationship("User")


class City(Base):
    __tablename__ = "cities"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    boundary = Column(Geometry("POLYGON", srid=4326))

    # Relationships
    admins = relationship(
        "User", secondary=city_admins, back_populates="administered_cities"
    )
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
    events = relationship(
        "DetourEvent", back_populates="detour", order_by="DetourEvent.order"
    )
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


# Association Tables (placed after classes to avoid forward reference issues)
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
