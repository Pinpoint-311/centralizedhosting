"""GIS / mapping for the State Map.

Municipal boundaries are public geography (never resident data). They are
sourced from OpenStreetMap/Nominatim — the same flow the Pinpoint app's admin
console uses — and stored per-town as a GeoJSON FeatureCollection. The map
endpoint returns every onboarded town as one FeatureCollection so the frontend
can drop it straight onto a `google.maps.Data` layer.
"""

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from orchestrator import audit
from orchestrator.db import get_db
from orchestrator.models import Tenant, TenantStatus
from orchestrator.security import require_operator, require_panel_token

router = APIRouter(prefix="/api", tags=["gis"])

_NOMINATIM = "https://nominatim.openstreetmap.org/search"
_OSM_POLYGONS = "https://polygons.openstreetmap.fr/get_geojson.py"
_USER_AGENT = "Pinpoint311-Orchestrator/1.0 (centralized-hosting-panel)"


def _normalize_feature_collection(geojson: dict, name: str | None = None) -> dict:
    """Coerce a raw Polygon/MultiPolygon/Feature into a FeatureCollection so
    every stored boundary has the same shape (matches the app's normalization)."""
    if not isinstance(geojson, dict) or "type" not in geojson:
        raise HTTPException(422, "Not a GeoJSON object")
    t = geojson["type"]
    if t == "FeatureCollection":
        return geojson
    if t == "Feature":
        return {"type": "FeatureCollection", "features": [geojson]}
    if t in ("Polygon", "MultiPolygon"):
        return {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "geometry": geojson, "properties": {"name": name or "Boundary"}}
            ],
        }
    raise HTTPException(422, f"Unsupported GeoJSON type: {t}")


def _first_geometry(fc: dict) -> dict | None:
    feats = fc.get("features") if isinstance(fc, dict) else None
    if feats:
        return feats[0].get("geometry")
    return None


@router.get("/gis/map")
def map_boundaries(db: Session = Depends(get_db), _: str = Depends(require_panel_token)):
    """Every onboarded municipality as a single GeoJSON FeatureCollection —
    each town's public boundary polygon when set, else a point at its location.
    Properties carry the metadata the map needs to style + link each town."""
    from orchestrator.models import PlatformConfig

    tenants = db.execute(
        select(Tenant).where(Tenant.status != TenantStatus.DECOMMISSIONED)
    ).scalars().all()
    features = []
    placed = 0

    # The hosting organization's own outline goes in first so it draws beneath
    # the towns — the base the participating municipalities sit inside.
    cfg = db.get(PlatformConfig, "default")
    jurisdiction_geom = _first_geometry(cfg.boundary) if (cfg and cfg.boundary) else None
    if jurisdiction_geom:
        features.append({
            "type": "Feature",
            "geometry": jurisdiction_geom,
            "properties": {
                "kind": "jurisdiction",
                "name": cfg.boundary_label or "Jurisdiction",
            },
        })
    for t in tenants:
        props = {
            "id": t.id, "name": t.name, "slug": t.slug,
            "status": t.status, "county": t.county,
            "has_boundary": bool(t.boundary),
        }
        geom = _first_geometry(t.boundary) if t.boundary else None
        if geom:
            features.append({"type": "Feature", "geometry": geom, "properties": props})
            placed += 1
        elif t.latitude is not None and t.longitude is not None:
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [t.longitude, t.latitude]},
                "properties": props,
            })
            placed += 1
    return {
        "type": "FeatureCollection",
        "features": features,
        "placed": placed,
        "total": len(tenants),
    }


@router.get("/gis/osm/search")
def osm_search(query: str, _: str = Depends(require_operator)):
    """Search OpenStreetMap/Nominatim for a municipality boundary (relations
    only). Returns candidates with inline boundary GeoJSON to preview + save."""
    if not query.strip():
        raise HTTPException(422, "query is required")
    params = {
        "q": query, "format": "json", "limit": "6", "addressdetails": "1",
        "polygon_geojson": "1", "polygon_threshold": "0.001",
    }
    try:
        with httpx.Client(timeout=30.0, headers={"User-Agent": _USER_AGENT}) as client:
            resp = client.get(_NOMINATIM, params=params)
    except httpx.RequestError as exc:
        raise HTTPException(502, f"Could not reach OpenStreetMap: {exc}")
    if resp.status_code != 200:
        raise HTTPException(502, "OpenStreetMap search failed")
    results = []
    for r in resp.json():
        if r.get("osm_type") != "relation":
            continue
        results.append({
            "osm_id": r.get("osm_id"),
            "display_name": r.get("display_name"),
            "type": r.get("type"),
            "class": r.get("class"),
            "lat": r.get("lat"),
            "lon": r.get("lon"),
            "geojson": r.get("geojson"),
        })
    return {"results": results}


@router.get("/gis/osm/boundary/{osm_id}")
def osm_boundary(osm_id: int, _: str = Depends(require_operator)):
    """Fetch full-detail boundary GeoJSON for an OSM relation."""
    if osm_id < 1 or osm_id > 999_999_999:  # SSRF guard — bound the id
        raise HTTPException(400, "Invalid OSM id")
    try:
        with httpx.Client(timeout=60.0, headers={"User-Agent": _USER_AGENT}) as client:
            resp = client.get(_OSM_POLYGONS, params={"id": osm_id, "params": 0})
    except httpx.RequestError as exc:
        raise HTTPException(502, f"Could not reach OpenStreetMap: {exc}")
    if resp.status_code != 200:
        raise HTTPException(502, "Boundary not available from OpenStreetMap")
    return {"osm_id": osm_id, "geojson": resp.json()}


class BoundaryUpdate(BaseModel):
    geojson: dict
    name: str | None = None
    center_lat: float | None = None
    center_lng: float | None = None


@router.get("/platform/boundary")
def get_platform_boundary(db: Session = Depends(get_db), _: str = Depends(require_panel_token)):
    """The hosting organization's own jurisdiction outline (e.g. the state)."""
    from orchestrator.models import PlatformConfig

    cfg = db.get(PlatformConfig, "default")
    return {
        "boundary": cfg.boundary if cfg else None,
        "has_boundary": bool(cfg and cfg.boundary),
        "label": cfg.boundary_label if cfg else None,
    }


@router.put("/platform/boundary")
def set_platform_boundary(body: BoundaryUpdate, db: Session = Depends(get_db),
                          actor: str = Depends(require_operator)):
    """Set the organization's jurisdiction boundary, normally picked from the
    OpenStreetMap search. It becomes the base outline on the coverage map."""
    from orchestrator.models import PlatformConfig

    cfg = db.get(PlatformConfig, "default")
    if cfg is None:
        cfg = PlatformConfig(id="default")
        db.add(cfg)
    label = body.name or "Jurisdiction"
    cfg.boundary = _normalize_feature_collection(body.geojson, label)
    cfg.boundary_label = label
    audit.record(db, actor, "platform.boundary_set", None, label=label)
    db.commit()
    return {"status": "ok", "has_boundary": True, "label": label}


@router.delete("/platform/boundary")
def clear_platform_boundary(db: Session = Depends(get_db), actor: str = Depends(require_operator)):
    from orchestrator.models import PlatformConfig

    cfg = db.get(PlatformConfig, "default")
    if cfg:
        cfg.boundary = None
        cfg.boundary_label = None
        audit.record(db, actor, "platform.boundary_cleared", None)
        db.commit()
    return {"status": "ok", "has_boundary": False}


@router.get("/tenants/{tenant_id}/boundary")
def get_boundary(tenant_id: str, db: Session = Depends(get_db), _: str = Depends(require_panel_token)):
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant not found")
    return {"boundary": tenant.boundary, "has_boundary": bool(tenant.boundary)}


@router.put("/tenants/{tenant_id}/boundary")
def set_boundary(
    tenant_id: str,
    body: BoundaryUpdate,
    db: Session = Depends(get_db),
    actor: str = Depends(require_operator),
):
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant not found")
    fc = _normalize_feature_collection(body.geojson, body.name or tenant.name)
    tenant.boundary = fc
    if body.center_lat is not None and body.center_lng is not None:
        tenant.latitude = body.center_lat
        tenant.longitude = body.center_lng
    audit.record(db, actor, "tenant.boundary_set", tenant_id,
                 features=len(fc.get("features", [])))
    db.commit()
    return {"status": "ok", "has_boundary": True}


@router.delete("/tenants/{tenant_id}/boundary")
def clear_boundary(
    tenant_id: str,
    db: Session = Depends(get_db),
    actor: str = Depends(require_operator),
):
    tenant = db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant not found")
    tenant.boundary = None
    audit.record(db, actor, "tenant.boundary_cleared", tenant_id)
    db.commit()
    return {"status": "ok", "has_boundary": False}
