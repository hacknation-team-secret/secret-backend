from datetime import UTC, datetime, timedelta
from typing import Any, cast

from dotenv import load_dotenv
from geoalchemy2.shape import from_shape
from shapely.geometry import Point, Polygon
from sqlalchemy.orm import Session

import models
from database import SessionLocal

# Load environment variables
load_dotenv()


def bootstrap():
    db: Session = SessionLocal()
    try:
        # 1. Create a Super Admin if not exists
        admin_user = (
            db.query(models.User).filter(models.User.username == "admin").first()
        )
        if not admin_user:
            print("Creating admin user...")
            from auth import get_password_hash

            admin_user = models.User(
                username="admin",
                email="admin@example.com",
                hashed_password=get_password_hash("admin123"),
                api_key="super-secret-admin-key",
                is_admin=True,
                description="System Administrator",
            )
            db.add(admin_user)
            db.commit()
            db.refresh(admin_user)

        from auth import generate_api_key, get_password_hash

        mock_users = [
            {
                "username": "maya",
                "email": "maya@example.com",
                "description": (
                    "KNOWHERE PASSPORT\nTraveler style: slow mornings, independent "
                    "bookstores, design hotels, vegetarian food, and low-noise cafes. "
                    "Budget: mid-range. Avoids packed nightlife."
                ),
            },
            {
                "username": "leo",
                "email": "leo@example.com",
                "description": (
                    "KNOWHERE PASSPORT\nTraveler style: live music, street food, urban "
                    "photography, late dinners, and transit-first exploring. "
                    "Budget: flexible."
                ),
            },
            {
                "username": "nina",
                "email": "nina@example.com",
                "description": (
                    "KNOWHERE PASSPORT\nTraveler style: museums, architecture walks, "
                    "accessible routes, seafood, and one high-end meal per trip. "
                    "Prefers a relaxed pace."
                ),
            },
            {
                "username": "omar",
                "email": "omar@example.com",
                "description": (
                    "KNOWHERE PASSPORT\nTraveler style: biking, waterfront views, "
                    "local markets, craft coffee, and active afternoons. "
                    "Budget-conscious."
                ),
            },
            {
                "username": "sara",
                "email": "sara@example.com",
                "description": (
                    "KNOWHERE PASSPORT\nTraveler style: family-friendly plans, parks, "
                    "hands-on workshops, bakeries, and early evenings. Needs "
                    "gluten-free options."
                ),
            },
        ]

        users_by_name = {"admin": admin_user}
        for user_data in mock_users:
            user = (
                db.query(models.User)
                .filter(models.User.username == user_data["username"])
                .first()
            )
            if not user:
                print(f"Creating mock user: {user_data['username']}...")
                user = models.User(
                    username=user_data["username"],
                    email=user_data["email"],
                    hashed_password=get_password_hash("password123"),
                    api_key=generate_api_key(),
                    is_admin=False,
                    description=user_data["description"],
                )
                db.add(user)
                db.commit()
                db.refresh(user)
            users_by_name[cast(str, user.username)] = user

        # 2. Create Cities
        # San Francisco
        sf = db.query(models.City).filter(models.City.name == "San Francisco").first()
        if not sf:
            print("Adding San Francisco...")
            # Approximate SF boundary
            sf_poly = Polygon(
                [
                    (-122.514, 37.708),
                    (-122.514, 37.833),
                    (-122.356, 37.833),
                    (-122.356, 37.708),
                    (-122.514, 37.708),
                ]
            )
            sf = models.City(
                name="San Francisco", boundary=from_shape(sf_poly, srid=4326)
            )
            db.add(sf)
            sf.admins.append(admin_user)

        # New York
        ny = db.query(models.City).filter(models.City.name == "New York").first()
        if not ny:
            print("Adding New York...")
            # Approximate Manhattan/Central Park area boundary
            ny_poly = Polygon(
                [
                    (-74.020, 40.700),
                    (-74.020, 40.850),
                    (-73.900, 40.850),
                    (-73.900, 40.700),
                    (-74.020, 40.700),
                ]
            )
            ny = models.City(name="New York", boundary=from_shape(ny_poly, srid=4326))
            db.add(ny)
            ny.admins.append(admin_user)

        db.commit()
        db.refresh(sf)
        db.refresh(ny)

        # 3. Create Vendors
        v1 = (
            db.query(models.Vendor)
            .filter(models.Vendor.name == "Bay Area Adventures")
            .first()
        )
        if not v1:
            print("Adding Vendor: Bay Area Adventures...")
            v1 = models.Vendor(name="Bay Area Adventures")
            db.add(v1)
            v1.admins.append(admin_user)
            v1.authorized_cities.append(sf)

        v2 = (
            db.query(models.Vendor)
            .filter(models.Vendor.name == "NYC Urban Explorers")
            .first()
        )
        if not v2:
            print("Adding Vendor: NYC Urban Explorers...")
            v2 = models.Vendor(name="NYC Urban Explorers")
            db.add(v2)
            v2.admins.append(admin_user)
            v2.authorized_cities.append(ny)

        db.commit()
        db.refresh(v1)
        db.refresh(v2)

        # 4. Create Events
        now = datetime.now(UTC)

        events_data = [
            {
                "title": "Parasailing in the Bay",
                "description": (
                    "Experience breathtaking views of the "
                    "Golden Gate Bridge while parasailing."
                ),
                "start_time": now + timedelta(days=1),
                "end_time": now + timedelta(days=1, hours=2),
                "location": Point(-122.419, 37.808),  # Near Fisherman's Wharf
                "owner_type": "vendor",
                "owner_id": v1.id,
            },
            {
                "title": "SF Foodie Tour",
                "description": "A guided tour through the best dim sum spots.",
                "start_time": now + timedelta(days=2),
                "end_time": now + timedelta(days=2, hours=3),
                "location": Point(-122.406, 37.794),
                "owner_type": "city",
                "owner_id": sf.id,
            },
            {
                "title": "Central Park Morning Yoga",
                "description": "Start your day with zen in the heart of Manhattan.",
                "start_time": now + timedelta(days=1, hours=8),
                "end_time": now + timedelta(days=1, hours=9),
                "location": Point(-73.965, 40.782),
                "owner_type": "city",
                "owner_id": ny.id,
            },
            {
                "title": "Broadway Behind the Scenes",
                "description": "Exclusive access to the sets of a Broadway production.",
                "start_time": now + timedelta(days=3),
                "end_time": now + timedelta(days=3, hours=4),
                "location": Point(-73.986, 40.758),
                "owner_type": "vendor",
                "owner_id": v2.id,
            },
            {
                "title": "Mission Murals and Taquerias Walk",
                "description": (
                    "Street art, local history, and a vegetarian-friendly taco crawl."
                ),
                "start_time": now + timedelta(days=4, hours=11),
                "end_time": now + timedelta(days=4, hours=14),
                "location": Point(-122.414, 37.759),
                "owner_type": "city",
                "owner_id": sf.id,
            },
            {
                "title": "Ferry Building Market Morning",
                "description": (
                    "Coffee, bakeries, seafood counters, and maker stalls by the bay."
                ),
                "start_time": now + timedelta(days=5, hours=9),
                "end_time": now + timedelta(days=5, hours=12),
                "location": Point(-122.393, 37.795),
                "owner_type": "city",
                "owner_id": sf.id,
            },
            {
                "title": "Golden Gate Park Bike Picnic",
                "description": (
                    "Easy bike route through gardens with a flexible picnic stop."
                ),
                "start_time": now + timedelta(days=6, hours=13),
                "end_time": now + timedelta(days=6, hours=16),
                "location": Point(-122.486, 37.769),
                "owner_type": "vendor",
                "owner_id": v1.id,
            },
            {
                "title": "Chelsea Gallery and High Line Loop",
                "description": (
                    "Contemporary galleries, architecture stops, and a sunset walk."
                ),
                "start_time": now + timedelta(days=4, hours=15),
                "end_time": now + timedelta(days=4, hours=18),
                "location": Point(-74.004, 40.748),
                "owner_type": "city",
                "owner_id": ny.id,
            },
            {
                "title": "Lower East Side Music Crawl",
                "description": (
                    "Small venues, late bites, and street photography between sets."
                ),
                "start_time": now + timedelta(days=5, hours=20),
                "end_time": now + timedelta(days=5, hours=23),
                "location": Point(-73.989, 40.721),
                "owner_type": "vendor",
                "owner_id": v2.id,
            },
            {
                "title": "Brooklyn Bridge Family Sketch Walk",
                "description": "Accessible skyline walk with hands-on sketching.",
                "start_time": now + timedelta(days=6, hours=10),
                "end_time": now + timedelta(days=6, hours=12),
                "location": Point(-73.996, 40.706),
                "owner_type": "city",
                "owner_id": ny.id,
            },
        ]

        for ed in events_data:
            existing = (
                db.query(models.Event).filter(models.Event.title == ed["title"]).first()
            )
            if not existing:
                print(f"Adding Event: {ed['title']}...")
                event = models.Event(
                    title=ed["title"],
                    description=ed["description"],
                    start_time=ed["start_time"],
                    end_time=ed["end_time"],
                    location=from_shape(cast(Any, ed["location"]), srid=4326),
                    owner_type=ed["owner_type"],
                    owner_id=ed["owner_id"],
                )
                db.add(event)

        db.commit()

        events_by_title = {
            cast(str, event.title): event
            for event in db.query(models.Event)
            .filter(models.Event.title.in_([ed["title"] for ed in events_data]))
            .all()
        }

        attendance = {
            "maya": [
                "SF Foodie Tour",
                "Mission Murals and Taquerias Walk",
                "Chelsea Gallery and High Line Loop",
            ],
            "leo": [
                "Lower East Side Music Crawl",
                "Broadway Behind the Scenes",
                "Mission Murals and Taquerias Walk",
            ],
            "nina": [
                "Broadway Behind the Scenes",
                "Chelsea Gallery and High Line Loop",
                "Ferry Building Market Morning",
            ],
            "omar": [
                "Parasailing in the Bay",
                "Golden Gate Park Bike Picnic",
                "Ferry Building Market Morning",
            ],
            "sara": [
                "Central Park Morning Yoga",
                "Brooklyn Bridge Family Sketch Walk",
                "Ferry Building Market Morning",
            ],
        }
        for username, titles in attendance.items():
            user = users_by_name[username]
            for title in titles:
                event = events_by_title.get(title)
                if event and event not in user.attended_events:
                    user.attended_events.append(event)

        detours_data = [
            {
                "username": "maya",
                "name": "Quiet Creative SF Day",
                "description": (
                    "Murals, vegetarian lunch, and a cafe reset before sunset."
                ),
                "events": [
                    "Mission Murals and Taquerias Walk",
                    "Ferry Building Market Morning",
                ],
            },
            {
                "username": "leo",
                "name": "Late Night NYC Pulse",
                "description": (
                    "Galleries first, then live music and street food after dark."
                ),
                "events": [
                    "Chelsea Gallery and High Line Loop",
                    "Lower East Side Music Crawl",
                ],
            },
            {
                "username": "nina",
                "name": "Accessible Arts Weekend",
                "description": (
                    "Architecture, museums, seafood, and a relaxed walking pace."
                ),
                "events": [
                    "Broadway Behind the Scenes",
                    "Chelsea Gallery and High Line Loop",
                ],
            },
            {
                "username": "omar",
                "name": "Waterfront Active Loop",
                "description": "Bay views, bikes, markets, and casual food stops.",
                "events": ["Parasailing in the Bay", "Golden Gate Park Bike Picnic"],
            },
            {
                "username": "sara",
                "name": "Family Friendly City Morning",
                "description": "Early outdoor activities with flexible food options.",
                "events": [
                    "Central Park Morning Yoga",
                    "Brooklyn Bridge Family Sketch Walk",
                ],
            },
        ]
        for detour_data in detours_data:
            user = users_by_name[cast(str, detour_data["username"])]
            detour = (
                db.query(models.Detour)
                .filter(
                    models.Detour.user_id == user.id,
                    models.Detour.name == detour_data["name"],
                )
                .first()
            )
            if not detour:
                print(f"Adding Detour: {detour_data['name']}...")
                detour = models.Detour(
                    name=detour_data["name"],
                    description=detour_data["description"],
                    user_id=user.id,
                )
                db.add(detour)
                db.flush()
                for order, title in enumerate(detour_data["events"]):
                    event = events_by_title.get(title)
                    if event:
                        db.add(
                            models.DetourEvent(
                                detour_id=detour.id,
                                event_id=event.id,
                                order=order,
                            )
                        )

        group = (
            db.query(models.Group)
            .filter(models.Group.name == "Spring City Sampler")
            .first()
        )
        if not group:
            print("Adding Group: Spring City Sampler...")
            group = models.Group(
                name="Spring City Sampler",
                description=(
                    "A mixed-preference long weekend with food, music, art, "
                    "accessible routes, and one active outdoor block."
                ),
                owner_id=users_by_name["maya"].id,
            )
            db.add(group)
            db.flush()

        group_members = {
            "maya": "accepted",
            "leo": "accepted",
            "nina": "accepted",
            "omar": "pending",
        }
        for username, member_status in group_members.items():
            user = users_by_name[username]
            membership = (
                db.query(models.GroupMembership)
                .filter(
                    models.GroupMembership.group_id == group.id,
                    models.GroupMembership.user_id == user.id,
                )
                .first()
            )
            if not membership:
                db.add(
                    models.GroupMembership(
                        group_id=group.id,
                        user_id=user.id,
                        invited_by_id=users_by_name["maya"].id,
                        status=member_status,
                    )
                )

        db.flush()

        favorites_data = [
            {
                "title": "Ferry Building breakfast crawl",
                "description": (
                    "Low-friction morning with coffee, bakeries, and bay views."
                ),
                "category": "food",
                "estimated_cost": 38.0,
                "created_by": "maya",
                "votes": ["maya", "nina", "omar"],
            },
            {
                "title": "Lower East Side music night",
                "description": (
                    "Small venues and late street food for the high-energy block."
                ),
                "category": "music",
                "estimated_cost": 72.0,
                "created_by": "leo",
                "votes": ["leo", "maya"],
            },
            {
                "title": "Accessible gallery loop",
                "description": "Architecture, galleries, and an easy sunset route.",
                "category": "culture",
                "estimated_cost": 25.0,
                "created_by": "nina",
                "votes": ["nina", "maya", "leo"],
            },
        ]
        for favorite_data in favorites_data:
            favorite = (
                db.query(models.GroupFavorite)
                .filter(
                    models.GroupFavorite.group_id == group.id,
                    models.GroupFavorite.title == favorite_data["title"],
                )
                .first()
            )
            if not favorite:
                favorite = models.GroupFavorite(
                    group_id=group.id,
                    created_by_id=users_by_name[
                        cast(str, favorite_data["created_by"])
                    ].id,
                    title=favorite_data["title"],
                    description=favorite_data["description"],
                    category=favorite_data["category"],
                    estimated_cost=favorite_data["estimated_cost"],
                )
                db.add(favorite)
                db.flush()

            for voter in cast(list[str], favorite_data["votes"]):
                user = users_by_name[voter]
                vote = (
                    db.query(models.GroupFavoriteVote)
                    .filter(
                        models.GroupFavoriteVote.favorite_id == favorite.id,
                        models.GroupFavoriteVote.user_id == user.id,
                    )
                    .first()
                )
                if not vote:
                    db.add(
                        models.GroupFavoriteVote(
                            favorite_id=favorite.id,
                            user_id=user.id,
                        )
                    )

        budgets_data = [
            {
                "username": "maya",
                "total_budget": 260.0,
                "notes": "Prefer one splurge meal.",
            },
            {"username": "leo", "total_budget": 340.0, "notes": "Flexible for music."},
            {
                "username": "nina",
                "total_budget": 300.0,
                "notes": "Prioritize accessible transit.",
            },
            {
                "username": "omar",
                "total_budget": 180.0,
                "notes": "Keep activities budget-conscious.",
            },
        ]
        for budget_data in budgets_data:
            user = users_by_name[cast(str, budget_data["username"])]
            budget = (
                db.query(models.GroupBudget)
                .filter(
                    models.GroupBudget.group_id == group.id,
                    models.GroupBudget.user_id == user.id,
                )
                .first()
            )
            if not budget:
                db.add(
                    models.GroupBudget(
                        group_id=group.id,
                        user_id=user.id,
                        total_budget=budget_data["total_budget"],
                        currency="USD",
                        notes=budget_data["notes"],
                    )
                )

        db.commit()
        print("Bootstrap complete!")

    except Exception as e:
        db.rollback()
        print(f"Error during bootstrap: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    bootstrap()
