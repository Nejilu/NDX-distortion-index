from fastapi.testclient import TestClient

from api import _database_for_path, app, get_database
from database import SnapshotDatabase
from snapshot_service import recompute_all_snapshots, recompute_snapshot


def test_sample_snapshot_roundtrip(tmp_path):
    path = tmp_path / "snapshots.sqlite3"
    outcome = recompute_snapshot(mode="sample", db_path=path)
    database = SnapshotDatabase(path)

    current = database.get_current()
    components = database.get_components()

    assert current is not None
    assert current["snapshot_id"] == outcome.snapshot_id
    assert current["universe"] == "non_ucits"
    assert current["status"] == "sample_fallback"
    assert len(components) == 5
    assert any(row["data_status"] == "missing_float" for row in components)


def test_minimal_api(tmp_path, monkeypatch):
    path = tmp_path / "api.sqlite3"
    monkeypatch.setenv("NDX_DB_PATH", str(path))
    client = TestClient(app)

    response = client.post("/api/recompute", json={"mode": "sample", "universe": "all"})
    assert response.status_code == 201
    payload = response.json()["snapshots"]
    assert set(payload) == {"non_ucits", "ucits"}
    assert payload["ucits"]["snapshot_status"] == "sample_fallback"

    current_response = client.get("/api/current")
    assert current_response.status_code == 200
    assert set(current_response.json()["snapshots"]) == {"non_ucits", "ucits"}
    assert client.get("/api/current?universe=ucits").json()["reference_fund"] == "SAMPLE_CNDX"
    assert len(client.get("/api/history").json()) == 2
    components = client.get("/api/components?universe=ucits").json()
    assert len(components) == 5
    contributors = client.get(
        "/api/components?universe=non_ucits&ranking=contributors&limit=3"
    ).json()
    assert len(contributors) == 3
    assert contributors[0]["distortion_contribution"] >= contributors[1]["distortion_contribution"]

    total_response = client.post(
        "/api/recompute",
        json={"mode": "sample", "universe": "all", "weighting_basis": "total"},
    )
    assert total_response.status_code == 201
    total_current = client.get(
        "/api/current?universe=ucits&weighting_basis=total"
    ).json()
    assert total_current["weighting_basis"] == "total"
    total_components = client.get(
        "/api/components?universe=ucits&weighting_basis=total"
    ).json()
    assert all(row["counterfactual_weight"] is not None for row in total_components)


def test_both_universes_are_persisted_separately(tmp_path):
    path = tmp_path / "both.sqlite3"
    outcomes = recompute_all_snapshots(mode="sample", db_path=path)
    database = SnapshotDatabase(path)

    assert {outcome.universe for outcome in outcomes} == {"non_ucits", "ucits"}
    current = database.get_current_by_universe()
    assert current["non_ucits"]["reference_fund"] == "SAMPLE_QQQ"
    assert current["ucits"]["reference_fund"] == "SAMPLE_CNDX"
    assert current["non_ucits"]["ndx_wdi"] != current["ucits"]["ndx_wdi"]


def test_total_basis_is_persisted_and_queried_separately(tmp_path):
    path = tmp_path / "basis.sqlite3"
    recompute_all_snapshots(mode="sample", db_path=path, weighting_basis="float")
    total_outcomes = recompute_all_snapshots(
        mode="sample", db_path=path, weighting_basis="total"
    )
    database = SnapshotDatabase(path)

    total = database.get_current_by_universe("total")
    floating = database.get_current_by_universe("float")
    components = database.get_components(universe="ucits", weighting_basis="total")

    assert {outcome.result.weighting_basis for outcome in total_outcomes} == {"total"}
    assert total["ucits"]["weighting_basis"] == "total"
    assert floating["ucits"]["weighting_basis"] == "float"
    assert total["ucits"]["snapshot_id"] != floating["ucits"]["snapshot_id"]
    assert all(row["counterfactual_weight"] is not None for row in components)
    assert all(row["float_weight"] is None for row in components)


def test_api_database_is_cached_per_configured_path(tmp_path, monkeypatch):
    first_path = tmp_path / "first.sqlite3"
    second_path = tmp_path / "second.sqlite3"
    _database_for_path.cache_clear()
    try:
        monkeypatch.setenv("NDX_DB_PATH", str(first_path))
        first = get_database()
        assert get_database() is first

        monkeypatch.setenv("NDX_DB_PATH", str(second_path))
        second = get_database()
        assert second is not first
        assert get_database() is second
    finally:
        _database_for_path.cache_clear()
