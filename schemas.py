from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ItemBase(BaseModel):
    name: str
    description: str | None = None


class ItemCreate(ItemBase):
    pass


class Item(ItemBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


class UserBase(BaseModel):
    username: str
    email: str | None = None


class UserCreate(UserBase):
    password: str


class UserUpdatePassword(BaseModel):
    old_password: str
    new_password: str


class UserUpdateDescription(BaseModel):
    description: str


class User(UserBase):
    id: int
    is_admin: bool
    api_key: str
    description: str | None = None
    research_count: int

    model_config = ConfigDict(from_attributes=True)


class UserPublic(UserBase):
    id: int
    description: str | None = None
    research_count: int

    model_config = ConfigDict(from_attributes=True)


class GroupCreate(BaseModel):
    name: str
    description: str | None = None


class GroupInvite(BaseModel):
    username: str


class GroupFavoriteCreate(BaseModel):
    title: str
    description: str | None = None
    category: str | None = None
    estimated_cost: float | None = None


class GroupFavorite(BaseModel):
    id: int
    group_id: int
    title: str
    description: str | None = None
    category: str | None = None
    estimated_cost: float | None = None
    created_by: UserPublic
    created_at: datetime
    vote_count: int
    voted_by_me: bool


class GroupBudgetUpsert(BaseModel):
    total_budget: float
    currency: str = "USD"
    notes: str | None = None


class GroupBudget(BaseModel):
    group_id: int
    user: UserPublic
    total_budget: float
    currency: str
    notes: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class GroupMembership(BaseModel):
    user: UserPublic
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class Group(BaseModel):
    id: int
    name: str
    description: str | None = None
    owner_id: int
    created_at: datetime
    memberships: list[GroupMembership]

    model_config = ConfigDict(from_attributes=True)


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: str | None = None


class PublicUser(BaseModel):
    id: int
    username: str
    email: str | None = None
    description: str | None = None
    research_count: int

    model_config = ConfigDict(from_attributes=True)


# New Entity Schemas
class CityBase(BaseModel):
    name: str
    boundary: list[list[list[float]]]  # GeoJSON Polygon coordinates style


class CityCreate(CityBase):
    pass


class City(CityBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


class VendorBase(BaseModel):
    name: str


class VendorCreate(VendorBase):
    pass


class Vendor(VendorBase):
    id: int

    model_config = ConfigDict(from_attributes=True)


class EventBase(BaseModel):
    title: str
    description: str | None = None
    start_time: datetime
    end_time: datetime
    location: list[float]  # [longitude, latitude]


class EventCreate(EventBase):
    owner_type: str  # 'city' or 'vendor'
    owner_id: int


class Event(EventBase):
    id: int
    owner_type: str
    owner_id: int

    model_config = ConfigDict(from_attributes=True)


class DetourEventBase(BaseModel):
    event_id: int
    order: int


class DetourEvent(DetourEventBase):
    event: Event

    model_config = ConfigDict(from_attributes=True)


class DetourBase(BaseModel):
    name: str
    description: str | None = None


class DetourCreate(DetourBase):
    event_ids: list[int]


class Detour(DetourBase):
    id: int
    user_id: int
    events: list[DetourEvent]

    model_config = ConfigDict(from_attributes=True)


class Passport(BaseModel):
    username: str
    description: str | None = None
    attended_events: list[Event]

    model_config = ConfigDict(from_attributes=True)


class ResearchMessageBase(BaseModel):
    role: str
    content: str


class ResearchMessage(ResearchMessageBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ResearchThreadBase(BaseModel):
    title: str | None = None


class ResearchThreadCreate(ResearchThreadBase):
    pass


class ResearchThread(ResearchThreadBase):
    id: int
    created_at: datetime
    messages: list[ResearchMessage]

    model_config = ConfigDict(from_attributes=True)


class ResearchRequest(BaseModel):
    query: str
    thread_id: int | None = None
    group_id: int | None = None


class ResearchResponse(BaseModel):
    answer: str
    thread_id: int


class ResearchCaptureRequest(BaseModel):
    thread_id: int
    image_url: str | None = None


class ResearchExtractRequest(BaseModel):
    url: str
    query: str | None = None
    extract_depth: Literal["basic", "advanced"] = "advanced"
    include_images: bool = True


class InstagramProfileData(BaseModel):
    username: str | None = None
    display_name: str | None = None
    bio: str | None = None
    post_count: int | None = None
    follower_count: int | None = None
    following_count: int | None = None
    external_url: str | None = None
    profile_image_url: str | None = None


class ResearchExtractResponse(BaseModel):
    url: str
    platform: str
    extract_depth: Literal["basic", "advanced"]
    raw_content: str | None = None
    images: list[str] = Field(default_factory=list)
    favicon: str | None = None
    profile: InstagramProfileData | None = None
    failed: bool = False
    error: str | None = None
    tavily_request_id: str | None = None
    tavily_response_time: float | None = None


class WalletMember(BaseModel):
    user: PublicUser
    role: str
    contributed_cents: int
    spent_cents: int
    joined_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WalletTransaction(BaseModel):
    id: int
    wallet_id: int
    type: str
    amount_cents: int
    initiated_by: int
    merchant: str | None = None
    category: str | None = None
    description: str | None = None
    metadata_json: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SharedWalletBase(BaseModel):
    name: str
    currency: str = "USD"
    spending_limit_cents: int | None = None
    alert_threshold_percent: int = 20


class SharedWalletCreate(SharedWalletBase):
    pass


class SharedWalletUpdate(BaseModel):
    spending_limit_cents: int | None = None
    alert_threshold_percent: int | None = None


class SharedWalletJoinRequest(BaseModel):
    join_code: str


class SharedWalletFundRequest(BaseModel):
    amount_cents: int
    payment_method: str
    description: str | None = None


class SharedWalletSpendRequest(BaseModel):
    amount_cents: int
    merchant: str
    category: str | None = None
    description: str | None = None
    metadata_json: str | None = None


class SharedWalletResponse(BaseModel):
    id: int
    name: str
    currency: str
    total_balance_cents: int
    spending_limit_cents: int | None = None
    alert_threshold_percent: int
    join_code: str
    created_by: int
    created_at: datetime
    members: list[WalletMember]
    transactions: list[WalletTransaction] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)
