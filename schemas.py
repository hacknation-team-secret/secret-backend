
from datetime import datetime
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

    model_config = ConfigDict(from_attributes=True)

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    username: str | None = None


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
