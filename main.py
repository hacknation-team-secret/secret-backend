import os
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, cast

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from geoalchemy2.elements import WKBElement
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import Point, Polygon
from sqlalchemy import func
from sqlalchemy.orm import Session

import auth
import models
import schemas
from agent import run_detour_agent, run_extract_research, run_plan_generation
from database import engine, get_db
from storage import tigris_client

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def ensure_shared_wallet_tables():
    models.SharedWallet.__table__.create(bind=engine, checkfirst=True)
    models.WalletMember.__table__.create(bind=engine, checkfirst=True)
    models.WalletTransaction.__table__.create(bind=engine, checkfirst=True)


# Helper to convert models.Event to dict for Pydantic
def event_to_dict(db_event: models.Event):
    point = to_shape(cast(WKBElement, db_event.location))
    return {
        "id": db_event.id,
        "title": db_event.title,
        "description": db_event.description,
        "start_time": db_event.start_time,
        "end_time": db_event.end_time,
        "location": [point.x, point.y],
        "owner_type": db_event.owner_type,
        "owner_id": db_event.owner_id,
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
                "event": event_to_dict(de.event),
            }
            for de in db_detour.events
        ],
    }


def _accepted_group_membership(
    db: Session,
    group_id: int,
    user_id: int,
) -> models.GroupMembership | None:
    return (
        db.query(models.GroupMembership)
        .filter(
            models.GroupMembership.group_id == group_id,
            models.GroupMembership.user_id == user_id,
            models.GroupMembership.status == "accepted",
        )
        .first()
    )


def _get_group_for_member(
    db: Session,
    group_id: int,
    user: models.User,
) -> models.Group:
    group = db.query(models.Group).filter(models.Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    if group.owner_id == user.id:
        return group
    if not _accepted_group_membership(db, group_id, cast(int, user.id)):
        raise HTTPException(status_code=403, detail="Not a member of this group")
    return group


def _build_group_research_context(
    db: Session,
    group: models.Group,
) -> str:
    lines = [
        "GROUP TRIP CONTEXT",
        f"Group: {group.name}",
    ]
    if group.description:
        lines.append(f"Planning notes: {group.description}")

    accepted_members = [
        membership.user
        for membership in group.memberships
        if membership.status == "accepted"
    ]
    for member in accepted_members:
        lines.append(f"\nMember: @{member.username}")
        if member.description:
            lines.append(f"Passport/profile: {member.description}")

        attended_titles = [event.title for event in member.attended_events]
        if attended_titles:
            lines.append("Attended events: " + ", ".join(attended_titles[:8]))

        detours = (
            db.query(models.Detour)
            .filter(models.Detour.user_id == member.id)
            .order_by(models.Detour.id.desc())
            .limit(5)
            .all()
        )
        if detours:
            detour_summaries = [
                f"{detour.name}: {detour.description or 'No description'}"
                for detour in detours
            ]
            lines.append("Saved detours: " + " | ".join(detour_summaries))

    favorites = (
        db.query(models.GroupFavorite)
        .filter(models.GroupFavorite.group_id == group.id)
        .all()
    )
    if favorites:
        lines.append("\nGroup favorites and votes:")
        for favorite in favorites:
            cost = (
                f", estimated ${favorite.estimated_cost:.0f} per person"
                if favorite.estimated_cost is not None
                else ""
            )
            lines.append(
                f"- {favorite.title} ({len(favorite.votes)} votes{cost}): "
                f"{favorite.description or 'No description'}"
            )

    budgets = (
        db.query(models.GroupBudget)
        .filter(models.GroupBudget.group_id == group.id)
        .all()
    )
    if budgets:
        per_person = [budget.total_budget for budget in budgets if budget.total_budget]
        average_budget = sum(per_person) / len(per_person) if per_person else 0
        lines.append("\nBudget simulation:")
        lines.append(f"Average target per person: ${average_budget:.0f}")
        for budget in budgets:
            lines.append(
                f"- @{budget.user.username}: {budget.currency} "
                f"{budget.total_budget:.0f}; {budget.notes or 'No notes'}"
            )

    lines.append(
        "\nUse every member's profile, attended events, and saved detours. "
        "Recommend a concrete group itinerary that balances the group's "
        "shared and competing preferences."
    )
    return "\n".join(lines)


def _favorite_to_dict(
    favorite: models.GroupFavorite,
    current_user: models.User,
) -> dict[str, Any]:
    return {
        "id": favorite.id,
        "group_id": favorite.group_id,
        "title": favorite.title,
        "description": favorite.description,
        "category": favorite.category,
        "estimated_cost": favorite.estimated_cost,
        "created_by": favorite.created_by,
        "created_at": favorite.created_at,
        "vote_count": len(favorite.votes),
        "voted_by_me": any(vote.user_id == current_user.id for vote in favorite.votes),
    }


def wallet_to_dict(db_wallet: models.SharedWallet):
    return {
        "id": db_wallet.id,
        "name": db_wallet.name,
        "currency": db_wallet.currency,
        "total_balance_cents": db_wallet.total_balance_cents,
        "spending_limit_cents": db_wallet.spending_limit_cents,
        "alert_threshold_percent": db_wallet.alert_threshold_percent,
        "join_code": db_wallet.join_code,
        "created_by": db_wallet.created_by,
        "created_at": db_wallet.created_at,
        "members": [
            {
                "user": member.user,
                "role": member.role,
                "contributed_cents": member.contributed_cents,
                "spent_cents": member.spent_cents,
                "joined_at": member.joined_at,
            }
            for member in db_wallet.members
        ],
        "transactions": [
            {
                "id": txn.id,
                "wallet_id": txn.wallet_id,
                "type": txn.type,
                "amount_cents": txn.amount_cents,
                "initiated_by": txn.initiated_by,
                "merchant": txn.merchant,
                "category": txn.category,
                "description": txn.description,
                "metadata_json": txn.metadata_json,
                "created_at": txn.created_at,
            }
            for txn in db_wallet.transactions
        ],
    }


def generate_join_code() -> str:
    return secrets.token_urlsafe(6).upper()


def get_wallet_for_member(
    db: Session,
    wallet_id: int,
    user_id: int,
    lock: bool = False,
):
    query = db.query(models.SharedWallet).filter(models.SharedWallet.id == wallet_id)
    if lock:
        query = query.with_for_update()
    wallet = query.first()
    if not wallet:
        raise HTTPException(status_code=404, detail="Shared wallet not found")

    member = next((m for m in wallet.members if m.user_id == user_id), None)
    if not member:
        raise HTTPException(status_code=403, detail="Not authorized for this wallet")
    return wallet, member




@app.get("/docs", include_in_schema=False)
async def scalar_html():
    from scalar_fastapi import get_scalar_api_reference

    return get_scalar_api_reference(
        openapi_url=app.openapi_url,
        title=app.title,
    )


@app.post("/signup", response_model=schemas.User)
async def signup(user: schemas.UserCreate, db: Annotated[Session, Depends(get_db)]):
    db_user = (
        db.query(models.User).filter(models.User.username == user.username).first()
    )
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")

    hashed_password = auth.get_password_hash(user.password)
    api_key = auth.generate_api_key()

    db_user = models.User(
        username=user.username,
        email=user.email,
        hashed_password=hashed_password,
        api_key=api_key,
        is_admin=False,  # Default to non-admin
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


@app.post("/token", response_model=schemas.Token)
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[Session, Depends(get_db)],
):
    user = (
        db.query(models.User).filter(models.User.username == form_data.username).first()
    )
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
    current_user: Annotated[models.User, Depends(auth.get_current_active_user)],
):
    return current_user


@app.get("/users", response_model=list[schemas.UserPublic])
async def list_users(
    current_user: Annotated[models.User, Depends(auth.get_current_active_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return (
        db.query(models.User)
        .filter(models.User.id != current_user.id)
        .order_by(models.User.username.asc())
        .all()
    )


@app.put("/users/me/description")
async def update_description(
    desc_data: schemas.UserUpdateDescription,
    current_user: Annotated[models.User, Depends(auth.get_current_active_user)],
    db: Annotated[Session, Depends(get_db)],
):
    current_user.description = cast(Any, desc_data.description)
    db.commit()
    return {"message": "Description updated successfully"}


@app.post("/users/me/password")
async def change_password(
    password_data: schemas.UserUpdatePassword,
    current_user: Annotated[models.User, Depends(auth.get_current_active_user)],
    db: Annotated[Session, Depends(get_db)],
):
    if not auth.verify_password(
        password_data.old_password, current_user.hashed_password
    ):
        raise HTTPException(status_code=400, detail="Incorrect old password")

    current_user.hashed_password = auth.get_password_hash(password_data.new_password)
    db.commit()
    return {"message": "Password updated successfully"}


@app.post("/users/me/api-key")
async def regenerate_api_key(
    current_user: Annotated[models.User, Depends(auth.get_current_active_user)],
    db: Annotated[Session, Depends(get_db)],
):
    current_user.api_key = auth.generate_api_key()
    db.commit()
    db.refresh(current_user)
    return {"api_key": current_user.api_key}


# --- Group Trip Planning ---


@app.post("/groups", response_model=schemas.Group)
async def create_group(
    group_in: schemas.GroupCreate,
    current_user: Annotated[models.User, Depends(auth.get_current_active_user)],
    db: Annotated[Session, Depends(get_db)],
):
    db_group = models.Group(
        name=group_in.name,
        description=group_in.description,
        owner_id=current_user.id,
    )
    db.add(db_group)
    db.flush()
    db.add(
        models.GroupMembership(
            group_id=db_group.id,
            user_id=current_user.id,
            invited_by_id=current_user.id,
            status="accepted",
        )
    )
    db.commit()
    db.refresh(db_group)
    return db_group


@app.get("/groups", response_model=list[schemas.Group])
async def list_groups(
    current_user: Annotated[models.User, Depends(auth.get_current_active_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return (
        db.query(models.Group)
        .join(models.GroupMembership)
        .filter(models.GroupMembership.user_id == current_user.id)
        .order_by(models.Group.created_at.desc())
        .all()
    )


@app.post("/groups/{group_id}/invite", response_model=schemas.Group)
async def invite_group_member(
    group_id: int,
    invite: schemas.GroupInvite,
    current_user: Annotated[models.User, Depends(auth.get_current_active_user)],
    db: Annotated[Session, Depends(get_db)],
):
    group = _get_group_for_member(db, group_id, current_user)
    user_to_invite = (
        db.query(models.User).filter(models.User.username == invite.username).first()
    )
    if not user_to_invite:
        raise HTTPException(status_code=404, detail="User not found")

    membership = (
        db.query(models.GroupMembership)
        .filter(
            models.GroupMembership.group_id == group_id,
            models.GroupMembership.user_id == user_to_invite.id,
        )
        .first()
    )
    if membership:
        if membership.status == "accepted":
            raise HTTPException(status_code=400, detail="User is already in group")
        membership.invited_by_id = cast(Any, current_user.id)
        membership.status = cast(Any, "pending")
    else:
        db.add(
            models.GroupMembership(
                group_id=group_id,
                user_id=user_to_invite.id,
                invited_by_id=current_user.id,
                status="pending",
            )
        )

    db.commit()
    db.refresh(group)
    return group


@app.post("/groups/{group_id}/accept", response_model=schemas.Group)
async def accept_group_invite(
    group_id: int,
    current_user: Annotated[models.User, Depends(auth.get_current_active_user)],
    db: Annotated[Session, Depends(get_db)],
):
    membership = (
        db.query(models.GroupMembership)
        .filter(
            models.GroupMembership.group_id == group_id,
            models.GroupMembership.user_id == current_user.id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=404, detail="Invite not found")
    membership.status = cast(Any, "accepted")
    db.commit()

    group = db.query(models.Group).filter(models.Group.id == group_id).first()
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    return group


@app.get("/groups/{group_id}/favorites", response_model=list[schemas.GroupFavorite])
async def list_group_favorites(
    group_id: int,
    current_user: Annotated[models.User, Depends(auth.get_current_active_user)],
    db: Annotated[Session, Depends(get_db)],
):
    _get_group_for_member(db, group_id, current_user)
    favorites = (
        db.query(models.GroupFavorite)
        .filter(models.GroupFavorite.group_id == group_id)
        .order_by(models.GroupFavorite.created_at.desc())
        .all()
    )
    return [_favorite_to_dict(favorite, current_user) for favorite in favorites]


@app.post("/groups/{group_id}/favorites", response_model=schemas.GroupFavorite)
async def create_group_favorite(
    group_id: int,
    favorite_in: schemas.GroupFavoriteCreate,
    current_user: Annotated[models.User, Depends(auth.get_current_active_user)],
    db: Annotated[Session, Depends(get_db)],
):
    _get_group_for_member(db, group_id, current_user)
    favorite = models.GroupFavorite(
        group_id=group_id,
        created_by_id=current_user.id,
        title=favorite_in.title,
        description=favorite_in.description,
        category=favorite_in.category,
        estimated_cost=favorite_in.estimated_cost,
    )
    db.add(favorite)
    db.flush()
    db.add(models.GroupFavoriteVote(favorite_id=favorite.id, user_id=current_user.id))
    db.commit()
    db.refresh(favorite)
    return _favorite_to_dict(favorite, current_user)


@app.post("/groups/{group_id}/favorites/{favorite_id}/vote")
async def toggle_group_favorite_vote(
    group_id: int,
    favorite_id: int,
    current_user: Annotated[models.User, Depends(auth.get_current_active_user)],
    db: Annotated[Session, Depends(get_db)],
):
    _get_group_for_member(db, group_id, current_user)
    favorite = (
        db.query(models.GroupFavorite)
        .filter(
            models.GroupFavorite.id == favorite_id,
            models.GroupFavorite.group_id == group_id,
        )
        .first()
    )
    if not favorite:
        raise HTTPException(status_code=404, detail="Favorite not found")

    vote = (
        db.query(models.GroupFavoriteVote)
        .filter(
            models.GroupFavoriteVote.favorite_id == favorite_id,
            models.GroupFavoriteVote.user_id == current_user.id,
        )
        .first()
    )
    if vote:
        db.delete(vote)
        voted = False
    else:
        db.add(
            models.GroupFavoriteVote(
                favorite_id=favorite_id,
                user_id=current_user.id,
            )
        )
        voted = True
    db.commit()
    return {"voted": voted}


@app.get("/groups/{group_id}/budgets", response_model=list[schemas.GroupBudget])
async def list_group_budgets(
    group_id: int,
    current_user: Annotated[models.User, Depends(auth.get_current_active_user)],
    db: Annotated[Session, Depends(get_db)],
):
    _get_group_for_member(db, group_id, current_user)
    return (
        db.query(models.GroupBudget)
        .filter(models.GroupBudget.group_id == group_id)
        .order_by(models.GroupBudget.total_budget.asc())
        .all()
    )


@app.put("/groups/{group_id}/budget", response_model=schemas.GroupBudget)
async def upsert_group_budget(
    group_id: int,
    budget_in: schemas.GroupBudgetUpsert,
    current_user: Annotated[models.User, Depends(auth.get_current_active_user)],
    db: Annotated[Session, Depends(get_db)],
):
    _get_group_for_member(db, group_id, current_user)
    budget = (
        db.query(models.GroupBudget)
        .filter(
            models.GroupBudget.group_id == group_id,
            models.GroupBudget.user_id == current_user.id,
        )
        .first()
    )
    if budget:
        budget.total_budget = cast(Any, budget_in.total_budget)
        budget.currency = cast(Any, budget_in.currency)
        budget.notes = cast(Any, budget_in.notes)
        budget.updated_at = cast(Any, datetime.now(UTC))
    else:
        budget = models.GroupBudget(
            group_id=group_id,
            user_id=current_user.id,
            total_budget=budget_in.total_budget,
            currency=budget_in.currency,
            notes=budget_in.notes,
        )
        db.add(budget)
    db.commit()
    db.refresh(budget)
    return budget


<<<<<<< HEAD
@app.post(
    "/groups/{group_id}/city-guide-plan",
    response_model=schemas.CityGuidePlanResponse,
)
=======
@app.post("/groups/{group_id}/city-guide-plan", response_model=schemas.CityGuidePlanResponse)
>>>>>>> 9e8040b (Add POST /groups/{group_id}/city-guide-plan endpoint)
async def create_city_guide_plan(
    group_id: int,
    current_user: Annotated[models.User, Depends(auth.get_current_active_user)],
    db: Annotated[Session, Depends(get_db)],
):
    group = _get_group_for_member(db, group_id, current_user)
    group_context = _build_group_research_context(db, group)
<<<<<<< HEAD
    query = (
        f"Create a detour for my group '{group.name}'. "
        f"Here is our group context:\n{group_context}"
    )

    created_ids: list[int] = []
    await run_detour_agent(query, db, current_user, created_detour_ids=created_ids)

    if not created_ids:
        raise HTTPException(status_code=500, detail="Agent did not create a detour")

    detour = db.query(models.Detour).filter(models.Detour.id == created_ids[-1]).first()
    if not detour:
        raise HTTPException(status_code=500, detail="Detour not found after creation")

    for membership in group.memberships:
        if membership.status == "accepted" and membership.user not in detour.shared_with:
            detour.shared_with.append(membership.user)
    db.commit()
    db.refresh(detour)

    steps = [
        {
            "phase": "agent",
            "title": "REACT Agent Planning",
            "detail": "Used Tavily search and platform events to build your group detour.",
        }
    ]
    return {"steps": steps, "detour": detour_to_dict(detour)}
=======

    try:
        steps = await run_plan_generation(group_context)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Plan generation failed: {e}") from e

    db_detour = models.Detour(
        name=f"{group.name} City Guide",
        description=f"AI-generated group plan for {group.name}",
        user_id=current_user.id,
    )
    db.add(db_detour)
    db.commit()
    db.refresh(db_detour)

    return {"steps": steps, "detour": detour_to_dict(db_detour)}
>>>>>>> 9e8040b (Add POST /groups/{group_id}/city-guide-plan endpoint)


# --- Cities Management ---


@app.post("/cities", response_model=schemas.City)
async def create_city(
    city: schemas.CityCreate,
    current_user: Annotated[models.User, Depends(auth.get_admin_user)],
    db: Annotated[Session, Depends(get_db)],
):
    # Convert GeoJSON coordinates to WKT/Geometry
    # boundary is list[list[list[float]]]
    poly = Polygon(city.boundary[0])
    db_city = models.City(name=city.name, boundary=from_shape(poly, srid=4326))
    db.add(db_city)
    db.commit()
    db.refresh(db_city)

    # Manually construct response because GeoAlchemy2 objects
    # don't serialize easily to GeoJSON in Pydantic
    return {"id": db_city.id, "name": db_city.name, "boundary": city.boundary}


@app.post("/cities/{city_id}/admins")
async def add_city_admin(
    city_id: int,
    username: str,
    current_user: Annotated[models.User, Depends(auth.get_admin_user)],
    db: Annotated[Session, Depends(get_db)],
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
    db: Annotated[Session, Depends(get_db)],
):
    db_vendor = models.Vendor(name=vendor.name)
    db_vendor.admins.append(current_user)  # Creator is admin
    db.add(db_vendor)
    db.commit()
    db.refresh(db_vendor)
    return db_vendor


@app.post("/vendors/{vendor_id}/authorize/{city_id}")
async def authorize_vendor_in_city(
    vendor_id: int,
    city_id: int,
    current_user: Annotated[models.User, Depends(auth.get_current_user_flexible)],
    db: Annotated[Session, Depends(get_db)],
):
    vendor = db.query(models.Vendor).filter(models.Vendor.id == vendor_id).first()
    city = db.query(models.City).filter(models.City.id == city_id).first()
    if not vendor or not city:
        raise HTTPException(status_code=404, detail="Vendor or City not found")

    # Check if super admin or city admin
    is_city_admin = (
        db.query(models.city_admins)
        .filter_by(user_id=current_user.id, city_id=city_id)
        .first()
    )
    if not current_user.is_admin and not is_city_admin:
        raise HTTPException(
            status_code=403, detail="Not authorized to authorize vendors in this city"
        )

    if city not in vendor.authorized_cities:
        vendor.authorized_cities.append(city)
        db.commit()
    return {"message": f"Vendor {vendor.name} is now authorized in {city.name}"}


@app.post("/vendors/{vendor_id}/admins")
async def add_vendor_admin(
    vendor_id: int,
    username: str,
    current_user: Annotated[models.User, Depends(auth.get_current_user_flexible)],
    db: Annotated[Session, Depends(get_db)],
):
    vendor = db.query(models.Vendor).filter(models.Vendor.id == vendor_id).first()
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    # Super admins or City admins of a city where the vendor is authorized
    is_authorized_city_admin = False
    if not current_user.is_admin:
        # Check if user is admin of any city where this vendor is authorized
        authorized_cities_ids = [c.id for c in vendor.authorized_cities]
        is_authorized_city_admin = (
            db.query(models.city_admins)
            .filter(
                models.city_admins.c.user_id == current_user.id,
                models.city_admins.c.city_id.in_(authorized_cities_ids),
            )
            .first()
            is not None
        )

    if not current_user.is_admin and not is_authorized_city_admin:
        raise HTTPException(
            status_code=403, detail="Not authorized to manage this vendor's admins"
        )

    user_to_add = db.query(models.User).filter(models.User.username == username).first()
    if not user_to_add:
        raise HTTPException(status_code=404, detail="User not found")

    if user_to_add not in vendor.admins:
        vendor.admins.append(user_to_add)
        db.commit()
    return {"message": f"User {username} is now an admin of vendor {vendor.name}"}


# --- Events Management ---


@app.get("/events", response_model=list[schemas.Event])
async def list_events(db: Annotated[Session, Depends(get_db)]):
    return [event_to_dict(event) for event in db.query(models.Event).all()]


@app.post("/events", response_model=schemas.Event)
async def create_event(
    event: schemas.EventCreate,
    current_user: Annotated[models.User, Depends(auth.get_current_user_flexible)],
    db: Annotated[Session, Depends(get_db)],
):
    point = from_shape(Point(event.location[0], event.location[1]), srid=4326)

    if event.owner_type == "city":
        # Check if current_user is admin of this city
        is_city_admin = (
            db.query(models.city_admins)
            .filter_by(user_id=current_user.id, city_id=event.owner_id)
            .first()
        )
        if not is_city_admin and not current_user.is_admin:
            raise HTTPException(
                status_code=403, detail="Not a city admin for this city"
            )

        # Check geo-fence
        city = db.query(models.City).filter(models.City.id == event.owner_id).first()
        if not city:
            raise HTTPException(status_code=404, detail="City not found")
        is_inside = db.scalar(func.ST_Contains(city.boundary, point))
        if not is_inside:
            raise HTTPException(
                status_code=400, detail="Event location is outside the city boundary"
            )

    elif event.owner_type == "vendor":
        # Check if current_user is admin of this vendor
        is_vendor_admin = (
            db.query(models.vendor_admins)
            .filter_by(user_id=current_user.id, vendor_id=event.owner_id)
            .first()
        )
        if not is_vendor_admin and not current_user.is_admin:
            raise HTTPException(
                status_code=403, detail="Not a vendor admin for this vendor"
            )

        # Check if vendor is authorized in any city that contains this point
        vendor = (
            db.query(models.Vendor).filter(models.Vendor.id == event.owner_id).first()
        )
        if not vendor:
            raise HTTPException(status_code=404, detail="Vendor not found")
        authorized_cities = vendor.authorized_cities
        is_inside_authorized_city = False
        for city_obj in authorized_cities:
            if db.scalar(func.ST_Contains(city_obj.boundary, point)):
                is_inside_authorized_city = True
                break

        if not is_inside_authorized_city:
            raise HTTPException(
                status_code=400,
                detail="Vendor is not authorized to post events at this location",
            )
    else:
        raise HTTPException(status_code=400, detail="Invalid owner_type")

    db_event = models.Event(
        title=event.title,
        description=event.description,
        start_time=event.start_time,
        end_time=event.end_time,
        location=point,
        owner_type=event.owner_type,
        owner_id=event.owner_id,
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
        "owner_id": db_event.owner_id,
    }


# --- Passport & Attendance ---


@app.post("/events/{event_id}/attend")
async def attend_event(
    event_id: int,
    current_user: Annotated[models.User, Depends(auth.get_current_active_user)],
    db: Annotated[Session, Depends(get_db)],
):
    event = db.query(models.Event).filter(models.Event.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    if event not in current_user.attended_events:
        current_user.attended_events.append(event)
        db.commit()
    return {"message": "Event added to attended history"}


@app.get("/users/{username}/passport", response_model=schemas.Passport)
async def get_passport(username: str, db: Annotated[Session, Depends(get_db)]):
    user = db.query(models.User).filter(models.User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "username": user.username,
        "description": user.description,
        "attended_events": [event_to_dict(e) for e in user.attended_events],
    }


# --- Detours Management ---


@app.post("/detours", response_model=schemas.Detour)
async def create_detour(
    detour_in: schemas.DetourCreate,
    current_user: Annotated[models.User, Depends(auth.get_current_active_user)],
    db: Annotated[Session, Depends(get_db)],
):
    db_detour = models.Detour(
        name=detour_in.name,
        description=detour_in.description,
        user_id=current_user.id,
    )
    db.add(db_detour)
    db.flush()

    for index, event_id in enumerate(detour_in.event_ids):
        # Verify event exists
        event = db.query(models.Event).filter(models.Event.id == event_id).first()
        if not event:
            raise HTTPException(status_code=404, detail=f"Event {event_id} not found")

        db_detour_event = models.DetourEvent(
            detour_id=db_detour.id, event_id=event_id, order=index
        )
        db.add(db_detour_event)

    db.commit()
    db.refresh(db_detour)
    return detour_to_dict(db_detour)


@app.get("/detours/me", response_model=list[schemas.Detour])
async def get_my_detours(
    current_user: Annotated[models.User, Depends(auth.get_current_active_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return [detour_to_dict(d) for d in current_user.detours]


@app.get("/detours/shared", response_model=list[schemas.Detour])
async def get_shared_detours(
    current_user: Annotated[models.User, Depends(auth.get_current_active_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return [detour_to_dict(d) for d in current_user.shared_detours]


@app.get("/detours/{detour_id}", response_model=schemas.Detour)
async def get_detour(
    detour_id: int,
    current_user: Annotated[models.User, Depends(auth.get_current_user_flexible)],
    db: Annotated[Session, Depends(get_db)],
):
    detour = db.query(models.Detour).filter(models.Detour.id == detour_id).first()
    if not detour:
        raise HTTPException(status_code=404, detail="Detour not found")

    is_shared = (
        db.query(models.detour_shares)
        .filter_by(detour_id=detour_id, user_id=current_user.id)
        .first()
        is not None
    )

    if (
        not current_user.is_admin
        and detour.user_id != current_user.id
        and not is_shared
    ):
        raise HTTPException(
            status_code=403, detail="Not authorized to view this detour"
        )

    return detour_to_dict(detour)


@app.post("/detours/{detour_id}/share")
async def share_detour(
    detour_id: int,
    username: str,
    current_user: Annotated[models.User, Depends(auth.get_current_active_user)],
    db: Annotated[Session, Depends(get_db)],
):
    detour = db.query(models.Detour).filter(models.Detour.id == detour_id).first()
    if not detour:
        raise HTTPException(status_code=404, detail="Detour not found")

    if detour.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(
            status_code=403, detail="Only the owner can share this detour"
        )

    user_to_share_with = (
        db.query(models.User).filter(models.User.username == username).first()
    )
    if not user_to_share_with:
        raise HTTPException(status_code=404, detail="User not found")

    if user_to_share_with not in detour.shared_with:
        detour.shared_with.append(user_to_share_with)
        db.commit()

    return {"message": f"Detour shared with {username}"}


@app.get("/items", response_model=list[schemas.Item])
async def get_items(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(auth.get_current_user_flexible)],
):
    return db.query(models.Item).all()


@app.post("/items", response_model=schemas.Item)
async def create_item(
    item: schemas.ItemCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[models.User, Depends(auth.get_current_user_flexible)],
):
    db_item = models.Item(name=item.name, description=item.description)
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item


# --- Shared Wallets ---


@app.get("/wallets/shared", response_model=list[schemas.SharedWalletResponse])
async def list_shared_wallets(
    current_user: Annotated[models.User, Depends(auth.get_current_active_user)],
    db: Annotated[Session, Depends(get_db)],
):
    wallets = (
        db.query(models.SharedWallet)
        .join(
            models.WalletMember,
            models.WalletMember.wallet_id == models.SharedWallet.id,
        )
        .filter(models.WalletMember.user_id == current_user.id)
        .all()
    )
    return [wallet_to_dict(wallet) for wallet in wallets]


@app.post("/wallets/shared", response_model=schemas.SharedWalletResponse)
async def create_shared_wallet(
    wallet_in: schemas.SharedWalletCreate,
    current_user: Annotated[models.User, Depends(auth.get_current_active_user)],
    db: Annotated[Session, Depends(get_db)],
):
    join_code = generate_join_code()
    while (
        db.query(models.SharedWallet)
        .filter(models.SharedWallet.join_code == join_code)
        .first()
    ):
        join_code = generate_join_code()

    wallet = models.SharedWallet(
        name=wallet_in.name,
        currency=wallet_in.currency,
        spending_limit_cents=wallet_in.spending_limit_cents,
        alert_threshold_percent=wallet_in.alert_threshold_percent,
        join_code=join_code,
        created_by=current_user.id,
    )
    db.add(wallet)
    db.flush()
    db.add(
        models.WalletMember(
            user_id=current_user.id,
            wallet_id=wallet.id,
            role="admin",
        )
    )
    db.commit()
    db.refresh(wallet)
    return wallet_to_dict(wallet)


@app.post("/wallets/shared/join", response_model=schemas.SharedWalletResponse)
async def join_shared_wallet(
    join_in: schemas.SharedWalletJoinRequest,
    current_user: Annotated[models.User, Depends(auth.get_current_active_user)],
    db: Annotated[Session, Depends(get_db)],
):
    wallet = (
        db.query(models.SharedWallet)
        .filter(models.SharedWallet.join_code == join_in.join_code.upper())
        .first()
    )
    if not wallet:
        raise HTTPException(status_code=404, detail="Shared wallet not found")

    existing = (
        db.query(models.WalletMember)
        .filter_by(wallet_id=wallet.id, user_id=current_user.id)
        .first()
    )
    if not existing:
        db.add(
            models.WalletMember(
                user_id=current_user.id,
                wallet_id=wallet.id,
                role="member",
            )
        )
        db.commit()
        db.refresh(wallet)
    return wallet_to_dict(wallet)


@app.get("/wallets/{wallet_id}", response_model=schemas.SharedWalletResponse)
async def get_shared_wallet(
    wallet_id: int,
    current_user: Annotated[models.User, Depends(auth.get_current_active_user)],
    db: Annotated[Session, Depends(get_db)],
):
    wallet, _member = get_wallet_for_member(db, wallet_id, cast(int, current_user.id))
    return wallet_to_dict(wallet)


@app.patch("/wallets/{wallet_id}", response_model=schemas.SharedWalletResponse)
async def update_shared_wallet(
    wallet_id: int,
    wallet_in: schemas.SharedWalletUpdate,
    current_user: Annotated[models.User, Depends(auth.get_current_active_user)],
    db: Annotated[Session, Depends(get_db)],
):
    wallet, member = get_wallet_for_member(
        db,
        wallet_id,
        cast(int, current_user.id),
        lock=True,
    )
    if member.role != "admin":
        raise HTTPException(
            status_code=403,
            detail="Only admins can update wallet settings",
        )

    if wallet_in.alert_threshold_percent is not None:
        wallet.alert_threshold_percent = wallet_in.alert_threshold_percent
    if wallet_in.spending_limit_cents is not None:
        wallet.spending_limit_cents = wallet_in.spending_limit_cents
    db.commit()
    db.refresh(wallet)
    return wallet_to_dict(wallet)


@app.get(
    "/wallets/{wallet_id}/transactions",
    response_model=list[schemas.WalletTransaction],
)
async def list_wallet_transactions(
    wallet_id: int,
    current_user: Annotated[models.User, Depends(auth.get_current_active_user)],
    db: Annotated[Session, Depends(get_db)],
):
    wallet, _member = get_wallet_for_member(db, wallet_id, cast(int, current_user.id))
    return wallet.transactions


@app.post("/wallets/{wallet_id}/fund", response_model=schemas.SharedWalletResponse)
async def fund_shared_wallet(
    wallet_id: int,
    fund_in: schemas.SharedWalletFundRequest,
    current_user: Annotated[models.User, Depends(auth.get_current_active_user)],
    db: Annotated[Session, Depends(get_db)],
):
    if fund_in.amount_cents <= 0:
        raise HTTPException(status_code=400, detail="Funding amount must be positive")

    wallet, member = get_wallet_for_member(
        db,
        wallet_id,
        cast(int, current_user.id),
        lock=True,
    )
    wallet.total_balance_cents += fund_in.amount_cents
    member.contributed_cents += fund_in.amount_cents
    db.add(
        models.WalletTransaction(
            wallet_id=wallet.id,
            type="topup",
            amount_cents=fund_in.amount_cents,
            initiated_by=current_user.id,
            merchant=fund_in.payment_method,
            description=fund_in.description or f"Funded via {fund_in.payment_method}",
            metadata_json=f'{{"payment_method":"{fund_in.payment_method}"}}',
        )
    )
    db.commit()
    db.refresh(wallet)
    return wallet_to_dict(wallet)


@app.post("/wallets/{wallet_id}/spend", response_model=schemas.SharedWalletResponse)
async def spend_shared_wallet(
    wallet_id: int,
    spend_in: schemas.SharedWalletSpendRequest,
    current_user: Annotated[models.User, Depends(auth.get_current_active_user)],
    db: Annotated[Session, Depends(get_db)],
):
    if spend_in.amount_cents <= 0:
        raise HTTPException(status_code=400, detail="Spend amount must be positive")

    wallet, member = get_wallet_for_member(
        db,
        wallet_id,
        cast(int, current_user.id),
        lock=True,
    )
    if wallet.total_balance_cents < spend_in.amount_cents:
        raise HTTPException(
            status_code=400,
            detail="Insufficient shared wallet balance",
        )

    projected_balance = wallet.total_balance_cents - spend_in.amount_cents
    if (
        wallet.spending_limit_cents is not None
        and spend_in.amount_cents > wallet.spending_limit_cents
    ):
        raise HTTPException(
            status_code=400,
            detail="Spend exceeds wallet spending limit",
        )

    wallet.total_balance_cents = projected_balance
    member.spent_cents += spend_in.amount_cents
    db.add(
        models.WalletTransaction(
            wallet_id=wallet.id,
            type="spend",
            amount_cents=spend_in.amount_cents,
            initiated_by=current_user.id,
            merchant=spend_in.merchant,
            category=spend_in.category,
            description=spend_in.description,
            metadata_json=spend_in.metadata_json,
        )
    )
    db.commit()
    db.refresh(wallet)
    return wallet_to_dict(wallet)


# --- AI Research & Storage ---


@app.post("/research/threads", response_model=schemas.ResearchThread)
async def create_research_thread(
    thread_in: schemas.ResearchThreadCreate,
    current_user: Annotated[models.User, Depends(auth.get_current_active_user)],
    db: Annotated[Session, Depends(get_db)],
):
    db_thread = models.ResearchThread(
        title=thread_in.title or "New Research", user_id=current_user.id
    )
    db.add(db_thread)
    db.commit()
    db.refresh(db_thread)
    return db_thread


@app.get("/research/threads", response_model=list[schemas.ResearchThread])
async def list_research_threads(
    current_user: Annotated[models.User, Depends(auth.get_current_active_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return (
        db.query(models.ResearchThread)
        .filter(models.ResearchThread.user_id == current_user.id)
        .all()
    )


@app.post("/research", response_model=schemas.ResearchResponse)
async def research(
    request: schemas.ResearchRequest,
    current_user: Annotated[models.User, Depends(auth.get_current_active_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Perform a web research query. Supports threading for conversation history.
    """
    try:
        thread_id = request.thread_id
        history = []

        if thread_id:
            db_thread = (
                db.query(models.ResearchThread)
                .filter(
                    models.ResearchThread.id == thread_id,
                    models.ResearchThread.user_id == current_user.id,
                )
                .first()
            )
            if not db_thread:
                raise HTTPException(status_code=404, detail="Thread not found")

            # Load last 10 messages for context
            db_messages = (
                db.query(models.ResearchMessage)
                .filter(models.ResearchMessage.thread_id == thread_id)
                .order_by(models.ResearchMessage.created_at.asc())
                .limit(10)
                .all()
            )

            history = [{"role": m.role, "content": m.content} for m in db_messages]
        else:
            # Create a new thread if none provided
            db_thread = models.ResearchThread(
                title=request.query[:50] + "...", user_id=current_user.id
            )
            db.add(db_thread)
            db.commit()
            db.refresh(db_thread)
            thread_id = db_thread.id

        research_query = request.query
        if request.group_id:
            group = _get_group_for_member(db, request.group_id, current_user)
            group_context = _build_group_research_context(db, group)
            research_query = f"{request.query}\n\n{group_context}"

        # Run agent with history
        answer = await run_detour_agent(research_query, db, current_user, history)

        # Save messages
        user_msg = models.ResearchMessage(
            thread_id=thread_id, role="user", content=request.query
        )
        asst_msg = models.ResearchMessage(
            thread_id=thread_id, role="assistant", content=answer
        )
        db.add(user_msg)
        db.add(asst_msg)

        # Increment usage count
        current_user.research_count += 1
        db.commit()

        return {"answer": answer, "thread_id": thread_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/research/extract", response_model=schemas.ResearchExtractResponse)
async def research_extract(
    request: schemas.ResearchExtractRequest,
    current_user: Annotated[models.User, Depends(auth.get_current_active_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Extract structured content from a known URL using Tavily Extract.
    """
    try:
        current_user.research_count += 1
        db.commit()

        extraction = await run_extract_research(
            url=request.url,
            query=request.query,
            extract_depth=request.extract_depth,
            include_images=request.include_images,
        )
        return extraction
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/research/capture")
async def capture_research_to_passport(
    request: schemas.ResearchCaptureRequest,
    current_user: Annotated[models.User, Depends(auth.get_current_active_user)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Captures a research thread and updates the user's passport
    (description) with Markdown.
    """
    db_thread = (
        db.query(models.ResearchThread)
        .filter(
            models.ResearchThread.id == request.thread_id,
            models.ResearchThread.user_id == current_user.id,
        )
        .first()
    )

    if not db_thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    markdown = f"\n\n### Research: {db_thread.title}\n"
    if request.image_url:
        markdown += f"![Research Image]({request.image_url})\n\n"

    for msg in db_thread.messages:
        role = "User" if msg.role == "user" else "Assistant"
        markdown += f"**{role}**: {msg.content}\n\n"

    if current_user.description:
        new_desc = str(current_user.description) + markdown
        cast(Any, current_user).description = new_desc
    else:
        cast(Any, current_user).description = markdown

    db.commit()
    return {"message": "Thread captured to passport successfully"}


@app.post("/storage/upload")
async def upload_image(
    current_user: Annotated[models.User, Depends(auth.get_current_active_user)],
    file: Annotated[UploadFile, File(...)],
):
    """
    Upload an image to Tigris and return the public URL.
    """
    if not tigris_client:
        raise HTTPException(status_code=500, detail="Tigris client not configured")

    bucket_name = os.getenv("TIGRIS_STORAGE_BUCKET")
    if not bucket_name:
        raise HTTPException(status_code=500, detail="TIGRIS_STORAGE_BUCKET not set")

    file_extension = file.filename.split(".")[-1] if file.filename else "jpg"
    object_name = f"uploads/{current_user.id}/{uuid.uuid4()}.{file_extension}"

    try:
        content = await file.read()
        tigris_client.put_object(
            Bucket=bucket_name,
            Key=object_name,
            Body=content,
            ContentType=file.content_type,
        )

        endpoint = os.getenv("TIGRIS_STORAGE_ENDPOINT")
        url = f"{endpoint}/{bucket_name}/{object_name}"
        return {"url": url, "object_name": object_name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}") from e


@app.get("/")
async def root():
    return {"message": "Hello from knowhere!"}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


@app.get("/storage/test")
async def test_storage():
    """
    Test the Tigris storage connection by listing buckets.
    """
    if not tigris_client:
        raise HTTPException(
            status_code=500, detail="Tigris client not configured. Check env variables."
        )
    try:
        response = tigris_client.list_buckets()
        return {"buckets": [bucket["Name"] for bucket in response.get("Buckets", [])]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Tigris error: {str(e)}") from e


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
