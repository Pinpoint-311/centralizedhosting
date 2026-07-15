#!/usr/bin/env python3
"""Seed the panel with realistic demo data for a walkthrough.

Region-agnostic: pass --regions to label the geography however the audience
expects. Creates municipalities across a few regions, provisions them, sets
county-level 311 telemetry (so the region-only Analytics view is populated),
cost/usage, uptime history, a couple of alerts, an announcement, a pending
self-service request, and a legal hold — everything the demo touches.

Usage (against a running panel):
  PANEL_DATABASE_URL=sqlite:///./panel.db PANEL_SECRET_KEY=... \
  python scripts/seed_demo.py

It writes directly to the panel DB via the orchestrator models, so point
PANEL_DATABASE_URL at the same DB the panel uses.
"""

import argparse
import datetime
import math
import random

from orchestrator.db import SessionLocal, init_db
from orchestrator import managed_settings
from orchestrator.key_catalog import normalize_assignments
from orchestrator.provisioner import set_platform_secret
from orchestrator.security import generate_secret
from orchestrator.models import (
    Alert, Announcement, CategoryMapping, ServiceCategory, TelemetrySnapshot,
    Tenant, TenantStatus, TownRequest, utcnow,
)

# (name, slug, region, lat, lon, population)
TOWNS = [
    ("Riverton", "riverton", "Alpha County", 40.72, -74.10, 41000),
    ("Fairhaven", "fairhaven", "Alpha County", 40.66, -74.20, 28000),
    ("Oakdale", "oakdale", "Alpha County", 40.80, -74.02, 63000),
    ("Millbrook", "millbrook", "Bergen Region", 40.92, -74.05, 15000),
    ("Cedar Falls", "cedar-falls", "Bergen Region", 40.98, -74.11, 22000),
    ("Kingsport", "kingsport", "Bergen Region", 41.02, -74.30, 88000),
    ("Lakeside", "lakeside", "Mercer Region", 40.28, -74.72, 34000),
    ("Groveton", "groveton", "Mercer Region", 40.22, -74.76, 19000),
    ("Hamilton Square", "hamilton-square", "Mercer Region", 40.22, -74.65, 26000),
]

LOCAL_CATS = {
    "Pothole": "road_pothole", "Street Light Out": "street_light",
    "Missed Trash": "trash_missed", "Water Main": "water_leak",
    "Noise": "noise", "Tree Down": "tree", "Graffiti": "graffiti",
}


def _synthetic_boundary(lat: float, lon: float, rnd: random.Random) -> dict:
    """An irregular closed polygon around a centroid — stands in for a real
    municipal boundary on the map. Production pulls the true polygon from
    OpenStreetMap via the boundary picker; this just makes the demo map show
    real-looking town shapes without a live network call.

    Longitude is scaled by cos(lat) so the shape isn't stretched at NJ
    latitudes, and each vertex radius is jittered so towns look distinct.
    """
    n = rnd.randint(11, 16)
    base = rnd.uniform(0.020, 0.045)  # ~1.5–3 mi across
    coslat = math.cos(math.radians(lat)) or 1.0
    ring = []
    for i in range(n):
        ang = 2 * math.pi * i / n
        r = base * rnd.uniform(0.72, 1.28)
        ring.append([
            round(lon + (r * math.cos(ang)) / coslat, 6),
            round(lat + r * math.sin(ang), 6),
        ])
    ring.append(ring[0])  # close the ring
    return {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"synthetic": True},
             "geometry": {"type": "Polygon", "coordinates": [ring]}}
        ],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="wipe existing tenants first")
    args = ap.parse_args()

    init_db()
    db = SessionLocal()
    rnd = random.Random(311)

    if args.reset:
        for tbl in (TelemetrySnapshot, CategoryMapping, Alert, Announcement, TownRequest, Tenant):
            db.query(tbl).delete()
        db.commit()

    for name, slug, region, lat, lon, pop in TOWNS:
        if db.query(Tenant).filter_by(slug=slug).first():
            continue
        t = Tenant(
            name=name, slug=slug, subdomain=slug, county=region,
            latitude=lat, longitude=lon, status=TenantStatus.ACTIVE,
            running_version="1.4.0", target_version="1.4.0",
            kms_key_ref=f"kms://state-shared/keyRings/pinpoint311/cryptoKeys/{slug}",
            db_name=f"pp311_{slug.replace('-', '_')}",
            storage_bucket=f"pp311-{slug}-uploads",
            backend_port=9300, frontend_port=9800,
            key_assignments=normalize_assignments({}),
            managed_settings=managed_settings.defaults(),
            contact_name="Town Clerk", contact_email=f"clerk@{slug}.gov",
            boundary=_synthetic_boundary(lat, lon, rnd),
        )
        db.add(t)
        db.flush()
        # one-time setup password the state hands to the town admin
        set_platform_secret(db, t.id, "INITIAL_ADMIN_PASSWORD", generate_secret(12))
        # category mappings + 311 telemetry
        for local, canon in LOCAL_CATS.items():
            db.add(CategoryMapping(tenant_id=t.id, local_key=local.lower(), canonical_code=canon))
        by_cat = {local: rnd.randint(20, 400) for local in LOCAL_CATS}
        total = sum(by_cat.values())
        closed = int(total * rnd.uniform(0.7, 0.97))
        # a few days of uptime history (mostly up)
        for d in range(6):
            up = not (slug == "groveton" and d == 0)  # one town flapping
            db.add(TelemetrySnapshot(
                tenant_id=t.id,
                collected_at=utcnow() - datetime.timedelta(hours=d * 4),
                reachable=up, version="1.4.0",
                payload={
                    "version": "1.4.0",
                    "api_usage": {
                        "maps_geocode": {"calls": rnd.randint(2000, 9000)},
                        "translation": {"characters": rnd.randint(100000, 800000)},
                    },
                    "request_stats": {"total": total, "closed": closed, "by_category": by_cat},
                },
            ))
    db.commit()

    # legal hold on one town (litigation demo)
    lakeside = db.query(Tenant).filter_by(slug="lakeside").first()
    if lakeside:
        ms = dict(lakeside.managed_settings)
        ms["legal_hold"] = True
        lakeside.managed_settings = ms

    # a drift + a down alert
    db.add(Alert(tenant_id=lakeside.id, tenant_slug="lakeside", kind="drift",
                 severity="warning", message="Lakeside runs 1.3.0; latest is 1.4.0."))
    groveton = db.query(Tenant).filter_by(slug="groveton").first()
    db.add(Alert(tenant_id=groveton.id, tenant_slug="groveton", kind="down",
                 severity="critical", message="Groveton is not reachable."))

    db.add(Announcement(title="Planned maintenance Sat 2–4am ET",
                        severity="maintenance", created_by="ops@program.gov"))
    db.add(TownRequest(
        ref_code="REQ-DEMO01", name="Westfield", requested_slug="westfield",
        county="Mercer Region", contact_name="M. Rivera",
        contact_email="clerk@westfield.gov", contact_phone="555-0142",
        details={"population": 30000, "current_system": "spreadsheet", "timeline": "this fall"},
        key_preferences={"maps": "town", "identity_sso": "town"},
    ))
    db.commit()
    print(f"Seeded {db.query(Tenant).count()} municipalities, "
          f"{db.query(TelemetrySnapshot).count()} telemetry snapshots, "
          f"{db.query(Alert).count()} alerts, 1 pending request.")
    db.close()


if __name__ == "__main__":
    main()
