"""The one-container entry point, and the paths it takes from the environment."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


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
