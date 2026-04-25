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
        ]

        for ed in events_data:
            existing = (
                db.query(models.Event)
                .filter(models.Event.title == ed["title"])
                .first()
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
        print("Bootstrap complete!")

    except Exception as e:
        db.rollback()
        print(f"Error during bootstrap: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    bootstrap()
