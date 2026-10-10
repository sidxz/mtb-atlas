"""The fetcher's cache must never hold something that is not the data.

ChEMBL sometimes answers a JSON request with an HTML error page. If that page
were cached it would be served on every rebuild until someone forced a
re-download, and every ingester downstream would fail on it -- or worse, read
it as an empty answer. No network: the transport is faked.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from atlas import fetch as fetching

URL = "https://www.ebi.ac.uk/chembl/api/data/status.json"
HTML = "<!doctype html><html><body>Service temporarily unavailable</body></html>"


@pytest.fixture(autouse=True)
def _sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fetching, "RAW", tmp_path)
    monkeypatch.setattr(fetching.time, "sleep", lambda _: None)


def client(*bodies: str) -> httpx.Client:
    replies = iter(bodies)
    return httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=next(replies)))
    )


def test_an_html_page_in_place_of_json_is_retried(tmp_path: Path) -> None:
    got = fetching.fetch(
        URL, "status.json", source="chembl", json_body=True, client=client(HTML, '{"ok": 1}')
    )
    assert json.loads(got.path.read_text()) == {"ok": 1}


def test_an_html_page_is_never_cached(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        fetching.fetch(
            URL, "status.json", source="chembl", json_body=True, client=client(*[HTML] * 4)
        )
    assert not (tmp_path / "chembl" / "status.json").exists()
