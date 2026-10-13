"""The one-container entry point, and the paths it takes from the environment."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from atlas import api, serve, store, summary


def _store_seen_with(env: dict[str, str]) -> str:
    # A fresh interpreter, because STORE is read once at import.
    result = subprocess.run(
        [sys.executable, "-c", "from atlas.fetch import STORE; print(STORE)"],
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def test_atlas_store_moves_where_the_store_is_read(tmp_path: Path) -> None:
    assert _store_seen_with({"ATLAS_STORE": str(tmp_path)}) == str(tmp_path)


def test_without_atlas_store_the_store_is_where_it_always_was() -> None:
    env = {k: v for k, v in os.environ.items() if k != "ATLAS_STORE"}
    seen = subprocess.run(
        [sys.executable, "-c", "from atlas.fetch import STORE; print(STORE)"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert seen.endswith(os.path.join("data", "store"))


@pytest.fixture
def site(evidence_store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    for module in (api, store, summary):
        monkeypatch.setattr(module, "STORE", evidence_store)
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text('<!doctype html><div id="root"></div>')
    (dist / "assets" / "index-3f9a1c.js").write_text("console.log('atlas')")
    return TestClient(serve.create_app(dist))


def test_the_api_is_under_api(site: TestClient) -> None:
    assert site.get("/api/meta").status_code == 200


def test_a_router_path_is_the_page(site: TestClient) -> None:
    for path in ("/", "/genome/Rv3790", "/clinical/drug/CHEMBL64", "/about/privacy"):
        page = site.get(path)
        assert page.status_code == 200, path
        assert 'id="root"' in page.text
        assert page.headers["cache-control"] == "no-cache"


def test_hashed_assets_are_cached_for_a_year(site: TestClient) -> None:
    asset = site.get("/assets/index-3f9a1c.js")
    assert asset.status_code == 200
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_a_missing_asset_is_404_not_the_page(site: TestClient) -> None:
    assert site.get("/assets/gone-000000.js").status_code == 404


def test_an_unknown_api_route_is_404_not_the_page(site: TestClient) -> None:
    assert site.get("/api/no-such-route").status_code == 404
