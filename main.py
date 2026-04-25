from datetime import timedelta
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import Point, Polygon
from sqlalchemy import func
from sqlalchemy.orm import Session

import auth
import models
import schemas
from database import get_db

# Hardcoded Supabase credentials
SUPABASE_URL = "https://qokprjircewixfxchqje.supabase.co"
SUPABASE_KEY = "sOqHMVaJVPASREQC"

app = FastAPI(
    title="knowhere",
    description="A secure backend API with geo-fencing and complex RBAC.",
    version="1.1.0",
    docs_url=None,
    redoc_url=None,
)

# Helper to convert models.Event to dict for Pydantic
def event_to_dict(db_event: models.Event):
    point = to_shape(db_event.location)
    return {
        "id": db_event.id,
        "title": db_event.title,
        "description": db_event.description,
        "start_time": db_event.start_time,
        "end_time": db_event.end_time,
        "location": [point.x, point.y],
        "owner_type": db_event.owner_type,
        "owner_id": db_event.owner_id
    }

def detour_to_dict(db_detour: models.Detour):
    return {
        "id": db_detour.id,
        "name": db_detour.name,
        "description": db_detour.description,
        "user_id": db_detour.user_id,
        "events": [
            {
                "event_id": de.event_id,
                "order": de.order,
                "event": event_to_dict(de.event)
            } for de in db_detour.events
        ]
    }

@app.get("/docs", include_in_schema=False)
async def scalar_html():
    from scalar_fastapi import get_scalar_api_reference
    return get_scalar_api_reference(
        openapi_url=app.openapi_url,
        title=app.title,
    )

@app.post("/signup", response_model=schemas.User)
async def signup(user: schemas.UserCreate, db: Annotated[Session, Depends(get_db)]):
    db_user = db.query(models.User).filter(models.User.username == user.username).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")

    hashed_password = auth.get_password_hash(user.password)
    api_key = auth.generate_api_key()

    db_user = models.User(
        username=user.username,
        email=user.email,
        hashed_password=hashed_password,
        api_key=api_key,
        is_admin=False  # Default to non-admin
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

@app.post("/token", response_model=schemas.Token)
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[Session, Depends(get_db)]
):
    user = db.query(models.User).filter(models.User.username == form_data.username).first()
    if not user or not auth.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=auth.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = auth.create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/users/me", response_model=schemas.User)
async def read_users_me(
    current_user: Annotated[models.User, Depends(auth.get_current_active_user)]
):
    return current_user

@app.put("/users/me/description")
async def update_description(
    desc_data: schemas.UserUpdateDescription,
    current_user: Annotated[models.User, Depends(auth.get_current_active_user)],
    db: Annotated[Session, Depends(get_db)]
):
    current_user.description = desc_data.description
    db.commit()
    return {"message": "Description updated successfully"}

@app.post("/users/me/password")
async def change_password(
    password_data: schemas.UserUpdatePassword,
    current_user: Annotated[models.User, Depends(auth.get_current_active_user)],
    db: Annotated[Session, Depends(get_db)]
):
    if not auth.verify_password(password_data.old_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect old password")

    current_user.hashed_password = auth.get_password_hash(password_data.new_password)
    db.commit()
    return {"message": "Password updated successfully"}

@app.post("/users/me/api-key")
async def regenerate_api_key(
    current_user: Annotated[models.User, Depends(auth.get_current_active_user)],
    db: Annotated[Session, Depends(get_db)]
):
    current_user.api_key = auth.generate_api_key()
    db.commit()
    db.refresh(current_user)
    return {"api_key": current_user.api_key}

# --- Cities Management ---

@app.post("/cities", response_model=schemas.City)
async def create_city(
    city: schemas.CityCreate,
    current_user: Annotated[models.User, Depends(auth.get_admin_user)],
    db: Annotated[Session, Depends(get_db)]
):
    # Convert GeoJSON coordinates to WKT/Geometry
    # boundary is list[list[list[float]]]
    poly = Polygon(city.boundary[0])
    db_city = models.City(
        name=city.name,
        boundary=from_shape(poly, srid=4326)
    )
    db.add(db_city)
    db.commit()
    db.refresh(db_city)

    # Manually construct response because GeoAlchemy2 objects don't serialize easily to GeoJSON in Pydantic
    return {
        "id": db_city.id,
        "name": db_city.name,
        "boundary": city.boundary
    }

@app.post("/cities/{city_id}/admins")
async def add_city_admin(
    city_id: int,
    username: str,
    current_user: Annotated[models.User, Depends(auth.get_admin_user)],
    db: Annotated[Session, Depends(get_db)]
):
    city = db.query(models.City).filter(models.City.id == city_id).first()
    if not city:
        raise HTTPException(status_code=404, detail="City not found")

    user_to_add = db.query(models.User).filter(models.User.username == username).first()
    if not user_to_add:
        raise HTTPException(status_code=404, detail="User not found")

    if user_to_add not in city.admins:
        city.admins.append(user_to_add)
        db.commit()
    return {"message": f"User {username} is now an admin of {city.name}"}

# --- Vendors Management ---

@app.post("/vendors", response_model=schemas.Vendor)
async def create_vendor(
    vendor: schemas.VendorCreate,
    current_user: Annotated[models.User, Depends(auth.get_current_active_user)],
    db: Annotated[Session, Depends(get_db)]
):
    db_vendor = models.Vendor(name=vendor.name)
    db_vendor.admins.append(current_user) # Creator is admin
    db.add(db_vendor)
    db.commit()
    db.refresh(db_vendor)
    return db_vendor

@app.post("/vendors/{vendor_id}/authorize/{city_id}")
async def authorize_vendor_in_city(
    vendor_id: int,
    city_id: int,
    current_user: Annotated[models.User, Depends(auth.get_current_user_flexible)],
    db: Annotated[Session, Depends(get_db)]
):
    vendor = db.query(models.Vendor).filter(models.Vendor.id == vendor_id).first()
    city = db.query(models.City).filter(models.City.id == city_id).first()
    if not vendor or not city:
        raise HTTPException(status_code=404, detail="Vendor or City not found")

    # Check if super admin or city admin
    is_city_admin = db.query(models.city_admins).filter_by(user_id=current_user.id, city_id=city_id).first()
    if not current_user.is_admin and not is_city_admin:
        raise HTTPException(status_code=403, detail="Not authorized to authorize vendors in this city")

    if city not in vendor.authorized_cities:
        vendor.authorized_cities.append(city)
        db.commit()
    return {"message": f"Vendor {vendor.name} is now authorized in {city.name}"}

@app.post("/vendors/{vendor_id}/admins")
async def add_vendor_admin(
    vendor_id: int,
    username: str,
    current_user: Annotated[models.User, Depends(auth.get_current_user_flexible)],
    db: Annotated[Session, Depends(get_db)]
):
    vendor = db.query(models.Vendor).filter(models.Vendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    # Super admins or City admins of a city where the vendor is authorized
    is_authorized_city_admin = False
    if not current_user.is_admin:
        # Check if user is admin of any city where this vendor is authorized
        authorized_cities_ids = [c.id for c in vendor.authorized_cities]
        is_authorized_city_admin = db.query(models.city_admins).filter(
            models.city_admins.c.user_id == current_user.id,
            models.city_admins.c.city_id.in_(authorized_cities_ids)
        ).first() is not None

    if not current_user.is_admin and not is_authorized_city_admin:
        raise HTTPException(status_code=403, detail="Not authorized to manage this vendor's admins")

    user_to_add = db.query(models.User).filter(models.User.username == username).first()
    if not user_to_add:
        raise HTTPException(status_code=404, detail="User not found")

    if user_to_add not in vendor.admins:
        vendor.admins.append(user_to_add)
        db.commit()
    return {"message": f"User {username} is now an admin of vendor {vendor.name}"}

# --- Events Management ---

@app.post("/events", response_model=schemas.Event)
async def create_event(
    event: schemas.EventCreate,
    current_user: Annotated[models.User, Depends(auth.get_current_user_flexible)],
    db: Annotated[Session, Depends(get_db)]
):
    point = from_shape(Point(event.location[0], event.location[1]), srid=4326)

    if event.owner_type == "city":
        # Check if current_user is admin of this city
        is_city_admin = db.query(models.city_admins).filter_by(
            user_id=current_user.id, city_id=event.owner_id
        ).first()
        if not is_city_admin and not current_user.is_admin:
            raise HTTPException(status_code=403, detail="Not a city admin for this city")

        # Check geo-fence
        city = db.query(models.City).filter(models.City.id == event.owner_id).first()
        is_inside = db.scalar(func.ST_Contains(city.boundary, point))
        if not is_inside:
            raise HTTPException(status_code=400, detail="Event location is outside the city boundary")

    elif event.owner_type == "vendor":
        # Check if current_user is admin of this vendor
        is_vendor_admin = db.query(models.vendor_admins).filter_by(
            user_id=current_user.id, vendor_id=event.owner_id
        ).first()
        if not is_vendor_admin and not current_user.is_admin:
            raise HTTPException(status_code=403, detail="Not a vendor admin for this vendor")

        # Check if vendor is authorized in any city that contains this point
        vendor = db.query(models.Vendor).filter(models.Vendor.id == event.owner_id).first()
        authorized_cities = vendor.authorized_cities
        is_inside_authorized_city = False
        for city in authorized_cities:
            if db.scalar(func.ST_Contains(city.boundary, point)):
                is_inside_authorized_city = True
                break

        if not is_inside_authorized_city:
            raise HTTPException(status_code=400, detail="Vendor is not authorized to post events at this location")
    else:
        raise HTTPException(status_code=400, detail="Invalid owner_type")

    db_event = models.Event(
        title=event.title,
        description=event.description,
        start_time=event.start_time,
        end_time=event.end_time,
        location=point,
        owner_type=event.owner_type,
        owner_id=event.owner_id
    )
    db.add(db_event)
    db.commit()
    db.refresh(db_event)

    return {
        "id": db_event.id,
        "title": db_event.title,
        "description": db_event.description,
        "start_time": db_event.start_time,
        "end_time": db_event.end_time,
        "location": event.location,
        "owner_type": db_event.owner_type,
        "owner_id": db_event.owner_id
    }


# --- Passport & Attendance ---

@app.post("/events/{event_id}/attend")
async def attend_event(
    event_id: int,
    current_user: Annotated[models.User, Depends(auth.get_current_active_user)],
    db: Annotated[Session, Depends(get_db)]
):
    event = db.query(models.Event).filter(models.Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    if event not in current_user.attended_events:
        current_user.attended_events.append(event)
        db.commit()
    return {"message": "Event added to attended history"}


@app.get("/users/{username}/passport", response_model=schemas.Passport)
async def get_passport(
    username: str,
    db: Annotated[Session, Depends(get_db)]
):
    user = db.query(models.User).filter(models.User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "username": user.username,
        "description": user.description,
        "attended_events": [event_to_dict(e) for e in user.attended_events]
    }


# --- Detours Management ---

@app.post("/detours", response_model=schemas.Detour)
async def create_detour(
    detour_in: schemas.DetourCreate,
    current_user: Annotated[models.User, Depends(auth.get_current_active_user)],
    db: Annotated[Session, Depends(get_db)]
):
    db_detour = models.Detour(
        name=detour_in.name,
        description=detour_in.description,
        user_id=current_user.id
    )
    db.add(db_detour)
    db.flush()

    for index, event_id in enumerate(detour_in.event_ids):
        # Verify event exists
        event = db.query(models.Event).filter(models.Event.id == event_id).first()
        if not event:
            raise HTTPException(status_code=404, detail=f"Event {event_id} not found")

        db_detour_event = models.DetourEvent(
            detour_id=db_detour.id,
            event_id=event_id,
            order=index
        )
        db.add(db_detour_event)

    db.commit()
    db.refresh(db_detour)
    return detour_to_dict(db_detour)


@app.get("/detours/me", response_model=list[schemas.Detour])
async def get_my_detours(
    current_user: Annotated[models.User, Depends(auth.get_current_active_user)],
    db: Annotated[Session, Depends(get_db)]
):
    return [detour_to_dict(d) for d in current_user.detours]


@app.get("/detours/shared", response_model=list[schemas.Detour])
async def get_shared_detours(
    current_user: Annotated[models.User, Depends(auth.get_current_active_user)],
    db: Annotated[Session, Depends(get_db)]
):
    return [detour_to_dict(d) for d in current_user.shared_detours]


@app.get("/detours/{detour_id}", response_model=schemas.Detour)
async def get_detour(
    detour_id: int,
    current_user: Annotated[models.User, Depends(auth.get_current_user_flexible)],
    db: Annotated[Session, Depends(get_db)]
):
    detour = db.query(models.Detour).filter(models.Detour.id == detour_id).first()
    if not detour:
        raise HTTPException(status_code=404, detail="Detour not found")

    # Check if owner or shared with or admin
    is_shared = db.query(models.detour_shares).filter_by(
        detour_id=detour_id, user_id=current_user.id
    ).first() is not None

    if not current_user.is_admin and detour.user_id != current_user.id and not is_shared:
        raise HTTPException(status_code=403, detail="Not authorized to view this detour")

    return detour_to_dict(detour)


@app.post("/detours/{detour_id}/share")
async def share_detour(
    detour_id: int,
    username: str,
    current_user: Annotated[models.User, Depends(auth.get_current_active_user)],
    db: Annotated[Session, Depends(get_db)]
):
    detour = db.query(models.Detour).filter(models.Detour.id == detour_id).first()
    if not detour:
        raise HTTPException(status_code=404, detail="Detour not found")

    if detour.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Only the owner can share this detour")

    user_to_share_with = db.query(models.User).filter(models.User.username == username).first()
    if not user_to_share_with:
        raise HTTPException(status_code=404, detail="User not found")

    if user_to_share_with not in detour.shared_with:
        detour.shared_with.append(user_to_share_with)
        db.commit()

    return {"message": f"Detour shared with {username}"}


@app.get("/items", response_model=list[schemas.Item])
async def get_items(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(auth.get_current_user_flexible)]
):
    return db.query(models.Item).all()

@app.post("/items", response_model=schemas.Item)
async def create_item(
    item: schemas.ItemCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(auth.get_current_user_flexible)]
):
    db_item = models.Item(name=item.name, description=item.description)
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item

@app.get("/")
async def root():
    return {"message": "Hello from knowhere!"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
