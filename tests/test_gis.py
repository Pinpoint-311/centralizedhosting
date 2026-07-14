"""State Map / GIS: boundary lifecycle + the aggregate map feed.

The OSM/Nominatim fetch itself needs the network, so these cover the parts the
panel owns: normalization, storage, the map FeatureCollection, and input guards.
"""

from tests.conftest import HEADERS, make_tenant

POLYGON = {
    "type": "Polygon",
    "coordinates": [[[-74.1, 40.7], [-74.0, 40.7], [-74.0, 40.8], [-74.1, 40.8], [-74.1, 40.7]]],
}


def test_map_feed_uses_point_without_boundary_then_polygon(client):
    t = make_tenant(client, slug="mapville", name="Mapville", latitude=40.75, longitude=-74.05)

    # No boundary yet -> the town appears as a Point at its lat/lng.
    fc = client.get("/api/gis/map", headers=HEADERS).json()
    assert fc["type"] == "FeatureCollection"
    feat = next(f for f in fc["features"] if f["properties"]["slug"] == "mapville")
    assert feat["geometry"]["type"] == "Point"
    assert feat["properties"]["has_boundary"] is False
    assert feat["properties"]["id"] == t["id"]

    # Attach a boundary -> the same town is now a Polygon feature.
    r = client.put(f"/api/tenants/{t['id']}/boundary", json={"geojson": POLYGON}, headers=HEADERS)
    assert r.status_code == 200, r.text
    assert r.json()["has_boundary"] is True

    fc = client.get("/api/gis/map", headers=HEADERS).json()
    feat = next(f for f in fc["features"] if f["properties"]["slug"] == "mapville")
    assert feat["geometry"]["type"] == "Polygon"
    assert feat["properties"]["has_boundary"] is True


def test_boundary_is_normalized_to_feature_collection(client):
    t = make_tenant(client, slug="normville", name="Normville")
    client.put(f"/api/tenants/{t['id']}/boundary", json={"geojson": POLYGON}, headers=HEADERS)
    stored = client.get(f"/api/tenants/{t['id']}/boundary", headers=HEADERS).json()
    assert stored["has_boundary"] is True
    assert stored["boundary"]["type"] == "FeatureCollection"
    assert stored["boundary"]["features"][0]["geometry"]["type"] == "Polygon"


def test_boundary_can_be_cleared(client):
    t = make_tenant(client, slug="clearville", name="Clearville")
    client.put(f"/api/tenants/{t['id']}/boundary", json={"geojson": POLYGON}, headers=HEADERS)
    r = client.delete(f"/api/tenants/{t['id']}/boundary", headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["has_boundary"] is False
    assert client.get(f"/api/tenants/{t['id']}/boundary", headers=HEADERS).json()["has_boundary"] is False


def test_boundary_rejects_non_geojson(client):
    t = make_tenant(client, slug="badville", name="Badville")
    r = client.put(f"/api/tenants/{t['id']}/boundary", json={"geojson": {"nope": 1}}, headers=HEADERS)
    assert r.status_code == 422


def test_osm_search_requires_a_query(client):
    r = client.get("/api/gis/osm/search?query=%20%20", headers=HEADERS)
    assert r.status_code == 422


def test_osm_boundary_rejects_out_of_range_id(client):
    r = client.get("/api/gis/osm/boundary/0", headers=HEADERS)
    assert r.status_code == 400


def test_map_feed_requires_token(client):
    assert client.get("/api/gis/map").status_code in (401, 403, 422)
