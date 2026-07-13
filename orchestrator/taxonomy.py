"""Canonical, cross-town service taxonomy.

Town service categories are non-standard (one town's "Pothole" is another's
"Road Damage"), so cross-town analytics need a shared vocabulary. This is a
seed of common civic-311 categories (compatible with Open311 service codes);
the state can edit/extend it, and each town's local categories map onto it via
CategoryMapping. Unmapped local categories roll up as "other".
"""

# code, label, group
CANONICAL_SEED = [
    ("road_pothole", "Pothole / road surface", "Streets & transport"),
    ("street_light", "Street light out", "Streets & transport"),
    ("traffic_signal", "Traffic signal / sign", "Streets & transport"),
    ("sidewalk", "Sidewalk / curb", "Streets & transport"),
    ("snow_ice", "Snow / ice removal", "Streets & transport"),
    ("parking", "Parking / abandoned vehicle", "Streets & transport"),
    ("trash_missed", "Missed / illegal trash", "Sanitation"),
    ("recycling", "Recycling", "Sanitation"),
    ("bulk_pickup", "Bulk / large-item pickup", "Sanitation"),
    ("illegal_dumping", "Illegal dumping", "Sanitation"),
    ("water_leak", "Water leak / main break", "Water & sewer"),
    ("sewer_storm", "Sewer / storm drain", "Water & sewer"),
    ("flooding", "Flooding", "Water & sewer"),
    ("tree", "Tree / vegetation", "Parks & environment"),
    ("park", "Park / recreation", "Parks & environment"),
    ("noise", "Noise complaint", "Quality of life"),
    ("property_maintenance", "Property maintenance / blight", "Quality of life"),
    ("animal", "Animal control", "Quality of life"),
    ("graffiti", "Graffiti", "Quality of life"),
    ("code_enforcement", "Code enforcement / zoning", "Code & permits"),
    ("permit", "Permit / licensing", "Code & permits"),
    ("public_safety", "Public safety (non-emergency)", "Public safety"),
    ("housing", "Housing / tenant", "Housing"),
    ("general", "General inquiry / other", "Other"),
    ("other", "Unmapped / other", "Other"),
]


def seed(db) -> int:
    from orchestrator.models import ServiceCategory

    existing = {c.code for c in db.query(ServiceCategory).all()}
    added = 0
    for code, label, group in CANONICAL_SEED:
        if code not in existing:
            db.add(ServiceCategory(code=code, label=label, group=group))
            added += 1
    if added:
        db.commit()
    return added
