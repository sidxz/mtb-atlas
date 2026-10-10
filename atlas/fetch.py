"""Cached, rate-limited, resumable HTTP fetching.

Every ingester downloads through `fetch`, so the cache, the User-Agent, the
retry policy and the rate limit are decided in exactly one place. Downloads
land in `data/raw/<source>/` and are gitignored; a `.meta.json` sidecar records
where each file came from and when, which is what the provenance columns in the
Parquet store are built from.
"""

from __future__ import annotations

import hashlib
import json
import sys
import threading
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

# AlphaFold's /files/ endpoint returns 403 to requests without a User-Agent, and
# it is polite to identify ourselves to the others. See docs/data-sources.md.
USER_AGENT = "mtb-target-atlas/0.1 (+https://github.com/sidxz/mtb-target-atlas)"

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
STORE = ROOT / "data" / "store"

_last_request: dict[str, float] = {}
_throttle_lock = threading.Lock()


@dataclass(frozen=True)
class Fetched:
    """A file on disk plus the provenance of how it got there."""

    path: Path
    url: str
    retrieved_at: str
    sha256: str
    from_cache: bool
    headers: Mapping[str, str]

    @property
    def text(self) -> str:
        return self.path.read_text(encoding="utf-8", errors="replace")

    def version(self, *keys: str, default: str = "unknown") -> str:
        """Read a source's release label out of the response headers.

        UniProt reports its release this way (`x-uniprot-release`); sources that
        report nothing fall back to `default`, which is then recorded verbatim in
        the store rather than guessed at.
        """
        values = [self.headers[k] for k in keys if k in self.headers]
        return " ".join(values) if values else default


def _throttle(host: str, min_interval: float) -> None:
    """Hold the per-host request rate, including across concurrent workers.

    The slot is reserved under the lock and slept for outside it, so eight
    workers queue up behind each other instead of all reading the same stale
    timestamp and firing at once.
    """
    with _throttle_lock:
        elapsed = time.monotonic() - _last_request.get(host, 0.0)
        wait = max(0.0, min_interval - elapsed)
        _last_request[host] = time.monotonic() + wait
    if wait:
        time.sleep(wait)


def fetch(
    url: str,
    dest: str | Path,
    *,
    source: str,
    min_interval: float = 0.2,
    force: bool = False,
    attempts: int = 4,
    timeout: float = 120.0,
    client: httpx.Client | None = None,
) -> Fetched:
    """Download `url` to `data/raw/<source>/<dest>` unless already cached.

    Idempotent: a cached file is returned untouched, so re-running a pipeline
    costs nothing and a part-finished run resumes where it stopped. Pass
    `force=True` to re-download and pick up an upstream release.
    """
    path = RAW / source / dest
    meta_path = path.with_suffix(path.suffix + ".meta.json")

    if path.exists() and meta_path.exists() and not force:
        meta = json.loads(meta_path.read_text())
        return Fetched(
            path, meta["url"], meta["retrieved_at"], meta["sha256"], True, meta["headers"]
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    host = httpx.URL(url).host
    owns_client = client is None
    client = client or httpx.Client(follow_redirects=True, timeout=timeout)
    try:
        for attempt in range(1, attempts + 1):
            _throttle(host, min_interval)
            try:
                response = client.get(url, headers={"User-Agent": USER_AGENT})
                # 429/5xx are transient; anything else is a bug in our request.
                if response.status_code in (429, 500, 502, 503, 504):
                    response.raise_for_status()
                response.raise_for_status()
                break
            except (httpx.HTTPError, httpx.StreamError):
                if attempt == attempts:
                    raise
                time.sleep(2.0**attempt)
    finally:
        if owns_client:
            client.close()

    # Write to a temp name first so an interrupted run never leaves a truncated
    # file looking like a complete cache hit.
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(response.content)
    tmp.replace(path)

    fetched = Fetched(
        path=path,
        url=url,
        retrieved_at=datetime.now(UTC).strftime("%Y-%m-%d"),
        sha256=hashlib.sha256(response.content).hexdigest(),
        from_cache=False,
        # Kept whole: this is where a source states its release (UniProt) or
        # declines to (Mycobrowser serves no ETag or Last-Modified on its TSV, so
        # the sha256 is the only way to tell a new release from a re-download).
        headers=dict(response.headers),
    )
    meta_path.write_text(
        json.dumps(
            {
                "url": fetched.url,
                "retrieved_at": fetched.retrieved_at,
                "sha256": fetched.sha256,
                "bytes": len(response.content),
                "headers": fetched.headers,
            },
            indent=2,
        )
    )
    return fetched


def fetch_json(
    url: str,
    *,
    min_interval: float = 0.2,
    timeout: float = 120.0,
    client: httpx.Client | None = None,
    attempts: int = 3,
) -> object:
    """GET JSON without caching, for the many small lookups that make up a crosswalk."""
    owns_client = client is None
    client = client or httpx.Client(follow_redirects=True, timeout=timeout)
    try:
        for attempt in range(1, attempts + 1):
            _throttle(httpx.URL(url).host, min_interval)
            try:
                response = client.get(url, headers={"User-Agent": USER_AGENT})
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPError, ValueError):
                if attempt == attempts:
                    raise
                time.sleep(2.0**attempt)
    finally:
        if owns_client:
            client.close()
    raise AssertionError("unreachable")


def post_json(
    url: str,
    payload: object,
    *,
    min_interval: float = 0.2,
    timeout: float = 180.0,
    attempts: int = 3,
) -> object:
    """POST JSON, for the batch endpoints (RCSB search and GraphQL)."""
    with httpx.Client(follow_redirects=True, timeout=timeout) as client:
        for attempt in range(1, attempts + 1):
            _throttle(httpx.URL(url).host, min_interval)
            try:
                response = client.post(url, json=payload, headers={"User-Agent": USER_AGENT})
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPError, ValueError):
                if attempt == attempts:
                    raise
                time.sleep(2.0**attempt)
    raise AssertionError("unreachable")


def fetch_json_many(
    urls: Sequence[str],
    *,
    workers: int = 8,
    min_interval: float = 0.1,
    timeout: float = 60.0,
    label: str = "",
) -> dict[str, object]:
    """GET many small JSON endpoints concurrently, skipping the ones that fail.

    AlphaFold and ChEMBL are keyed per accession or per target, so a build means
    thousands of tiny requests. Eight in flight against a shared throttle keeps
    this to minutes without being rude. Failures are reported and skipped rather
    than aborting a long build.
    """
    out: dict[str, object] = {}
    failures: list[tuple[str, str]] = []
    with (
        httpx.Client(follow_redirects=True, timeout=timeout) as client,
        ThreadPoolExecutor(max_workers=workers) as pool,
    ):
        jobs = {
            pool.submit(
                fetch_json, url, min_interval=min_interval, timeout=timeout, client=client
            ): url
            for url in urls
        }
        for done, future in enumerate(as_completed(jobs), 1):
            url = jobs[future]
            try:
                out[url] = future.result()
            except Exception as error:  # noqa: BLE001 - one bad key must not end a build
                failures.append((url, str(error)[:120]))
            if label and (done % 200 == 0 or done == len(jobs)):
                print(f"  {label} {done}/{len(jobs)}", file=sys.stderr)
    if failures:
        print(f"  {label}: {len(failures)} failed, e.g. {failures[0]}", file=sys.stderr)
    return out
