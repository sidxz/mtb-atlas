"""Has anything moved upstream, and what has to be rebuilt if it has.

`make build` on a warm cache is a no-op and `make build-force` re-downloads
everything -- including four paper supplements and a WHO catalogue that cannot
have changed. Neither answers the question actually worth asking, which is
whether any source has released since the store was built.

Each source is asked by the cheapest route it offers, and the answer is
compared to the `source_version` already stamped on its table. Six small
requests, seconds, no writes.

**A probe that fails reports `unknown`, never `current`.** An endpoint being
down says nothing about the data behind it, and "current" is the one answer
that would be actively misleading.

Sources that cannot move are marked frozen rather than left unknown: a paper's
supplementary table is the same file forever, so a permanent question mark
beside four of them would be noise that trains you to ignore the report.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from .fetch import USER_AGENT, fetch_json
from .store import built, provenance

# The pipeline runs in this order, and a refresh runs from a source's own stage
# to the end: a later source cannot change an earlier one's input.
STAGES = ("identity", "evidence", "clinical", "summary")


def _get(url: str, headers: dict[str, str] | None = None, **kwargs: Any) -> httpx.Response:
    with httpx.Client(follow_redirects=True, timeout=30.0) as client:
        return client.get(url, headers={"User-Agent": USER_AGENT, **(headers or {})}, **kwargs)


def _chembl() -> str:
    from .sources.chembl import release_from_api

    return release_from_api()


def _uniprot() -> str:
    from .sources.uniprot import URL

    # The stream itself is 4 MB; the headers carry the release and cost nothing.
    headers = _get(URL, headers={"Range": "bytes=0-0"}).headers
    parts = [headers[k] for k in ("x-uniprot-release", "x-uniprot-release-date") if k in headers]
    if not parts:
        raise RuntimeError("UniProt did not state a release")
    return " ".join(parts)


def _clinicaltrials() -> str:
    from .sources.clinicaltrials import API, version

    return version(fetch_json(f"{API}/version"))


def _alphafold() -> str:
    # Any entry carries the database version; DprE1 is one the atlas checks anyway.
    models = fetch_json("https://alphafold.ebi.ac.uk/api/prediction/P9WJF1")
    versions = {m.get("latestVersion") for m in models or [] if m.get("latestVersion")}
    if not versions:
        raise RuntimeError("AlphaFold did not state a version")
    return f"AlphaFold DB v{max(versions)}"


def _mycobrowser() -> str:
    """Probe for the next release, because the file itself cannot reveal one.

    The URL is pinned to a release number, so hashing the download would
    compare release 5 against release 5 forever and report "current" even
    after release 6 shipped. Mycobrowser answers a missing release with 204 and
    an empty body, and an existing one with the 3.5 MB table.
    """
    from .sources.mycobrowser import RELEASE, RELEASE_DATE, URL

    current = f"release {RELEASE} ({RELEASE_DATE})"
    for ahead in (1, 2):
        candidate = int(RELEASE) + ahead
        response = _get(URL.replace(f"/releases/{RELEASE}/", f"/releases/{candidate}/"))
        if response.status_code == 200 and len(response.content) > 1_000_000:
            return f"release {candidate} (not yet ingested)"
    return current


def _string() -> str:
    from .sources.string_db import TAXON

    payload = fetch_json("https://string-db.org/api/json/version")
    live = (payload or [{}])[0].get("string_version")
    if not live:
        raise RuntimeError("STRING did not state a version")
    return f"STRING v{live}, taxon {TAXON}, combined_score >= 700"


def _rcsb() -> str:
    """Re-run the search and count. RCSB publishes no release label.

    The entry count is what the ingester records, so it is also the detector:
    a weekly release that adds an Mtb structure moves it.
    """
    from .sources.pdb import _entity_ids
    from .store import read

    accessions = sorted(
        {row[0] for row in read("crosswalk").project("uniprot_acc").fetchall() if row[0]}
    )
    entries = {str(eid).split("_")[0] for eid in _entity_ids(accessions)}
    return f"RCSB Search + Data API, {len(entries)} entries"


@dataclass(frozen=True)
class Source:
    """One upstream, where its version is stamped, and how to ask it."""

    name: str
    # The table to read the stored version from. It must be one stamped by the
    # same statement the probe reads, or the comparison is a false positive:
    # ChEMBL states its release in the mapping file as `chembl_37 (01/05/2026)`
    # and through the API as `ChEMBL_37 (2026-05-01)`. Both are faithful, and
    # neither is reformatted into the other, so the probe asks the API and
    # compares against a table the API stamped.
    table: str
    stage: str
    probe: Callable[[], str] | None = None
    frozen: str = ""
    # A re-run that costs more than a couple of requests, so `check` skips it
    # unless asked. RCSB has to replay the whole structure search to count.
    expensive: bool = False


SOURCES: tuple[Source, ...] = (
    Source("mycobrowser", "genes", "identity", _mycobrowser),
    Source("uniprot", "proteins", "identity", _uniprot),
    Source("chembl", "activities", "identity", _chembl),
    Source("rcsb-pdb", "structures", "evidence", _rcsb, expensive=True),
    Source("alphafold", "predicted_structures", "evidence", _alphafold),
    Source("string-db", "interactions", "evidence", _string),
    Source("clinicaltrials-gov", "trials", "clinical", _clinicaltrials),
    Source("dejesus-2017", "essentiality", "evidence", frozen="a 2017 paper's supplementary table"),
    Source("bosch-2021", "vulnerability", "evidence", frozen="a 2021 paper's supplementary table"),
    Source(
        "griffin-2011",
        "conditional_fitness",
        "evidence",
        frozen="a 2011 paper's supplementary table",
    ),
    Source(
        "who-catalogue",
        "resistance",
        "evidence",
        frozen="the 2nd edition (2023); a 3rd would be a new file",
    ),
    Source(
        "phmmer-human",
        "homology",
        "evidence",
        frozen="computed here from UniProt; it moves when UniProt does",
    ),
)

BY_NAME = {source.name: source for source in SOURCES}


def state_of(stored: str | None, upstream: str | None, frozen: str = "") -> tuple[str, str]:
    """Classify one source. Pure, because this is the part that must be right."""
    if stored is None:
        return "unbuilt", "no table in this store"
    if frozen:
        return "frozen", frozen
    if upstream is None:
        return "unknown", "could not ask"
    if upstream == stored:
        return "current", ""
    return "stale", f"upstream is {upstream}"


def stages_from(source: str) -> list[str]:
    """The stages to re-run when `source` moves, in order.

    A source can only affect its own stage and the ones after it, so the
    refresh starts there rather than rebuilding the whole pipeline. The roll-up
    always runs last because every table feeds it.
    """
    start = STAGES.index(BY_NAME[source].stage)
    return list(STAGES[start:])


@dataclass(frozen=True)
class Report:
    source: str
    stored: str | None
    upstream: str | None
    state: str
    detail: str
    stage: str
    rebuilds: list[str] = field(default_factory=list)


def check(*, expensive: bool = False, only: str | None = None) -> list[Report]:
    """Ask every source where it stands. Reads the store, writes nothing."""
    reports = []
    for source in SOURCES:
        if only and source.name != only:
            continue
        stored = provenance(source.table)[0] if built(source.table) else None
        skipped = source.expensive and not expensive
        upstream: str | None = None
        if source.probe and not source.frozen and not skipped:
            try:
                upstream = source.probe()
            except Exception as error:  # noqa: BLE001 - a dead endpoint is a result
                print(f"  {source.name}: {str(error)[:90]}", file=sys.stderr)
        state, detail = state_of(stored, upstream, source.frozen)
        reports.append(
            Report(
                source=source.name,
                stored=stored,
                upstream=upstream,
                state=state,
                detail="not asked; pass --expensive" if skipped else detail,
                stage=source.stage,
                rebuilds=stages_from(source.name) if state == "stale" else [],
            )
        )
    return reports
