"""The hosting organization's own jurisdiction boundary.

Looked up on OpenStreetMap the same way a town's is, and drawn as the base
outline the participating municipalities sit inside on the coverage map.
"""

from tests.conftest import HEADERS, make_tenant

SQUARE = {
    "type": "Polygon",
    "coordinates": [[[-75.6, 38.9], [-73.9, 38.9], [-73.9, 41.4], [-75.6, 41.4], [-75.6, 38.9]]],
}


def test_no_boundary_by_default(client):
    r = client.get("/api/platform/boundary", headers=HEADERS).json()
    assert r["has_boundary"] is False and r["boundary"] is None and r["label"] is None


def test_set_and_clear_boundary(client):
    r = client.put("/api/platform/boundary",
                   json={"geojson": SQUARE, "name": "State of New Jersey"}, headers=HEADERS).json()
    assert r["has_boundary"] is True and r["label"] == "State of New Jersey"

    got = client.get("/api/platform/boundary", headers=HEADERS).json()
    # Raw geometry is normalised to a FeatureCollection, as town boundaries are.
    assert got["boundary"]["type"] == "FeatureCollection"
    assert len(got["boundary"]["features"]) == 1

    client.delete("/api/platform/boundary", headers=HEADERS)
    assert client.get("/api/platform/boundary", headers=HEADERS).json()["has_boundary"] is False


def test_map_includes_jurisdiction_as_a_base_layer(client):
    client.put("/api/platform/boundary", json={"geojson": SQUARE, "name": "New Jersey"}, headers=HEADERS)
    make_tenant(client, slug="springfield", name="Springfield, NJ")

    fc = client.get("/api/gis/map", headers=HEADERS).json()
    kinds = [f["properties"].get("kind") for f in fc["features"]]
    assert kinds[0] == "jurisdiction"  # drawn first so it sits beneath the towns
    assert fc["features"][0]["properties"]["name"] == "New Jersey"

    # It must not be counted as a placed municipality.
    assert fc["placed"] == 0  # the town has neither boundary nor coordinates yet
    assert fc["total"] == 1


def test_map_without_jurisdiction_is_unchanged(client):
    make_tenant(client, slug="nomap", name="No Map, NJ")
    fc = client.get("/api/gis/map", headers=HEADERS).json()
    assert all(f["properties"].get("kind") != "jurisdiction" for f in fc["features"])


def test_invalid_geojson_rejected(client):
    r = client.put("/api/platform/boundary", json={"geojson": {"type": "Nonsense"}}, headers=HEADERS)
    assert r.status_code == 422
