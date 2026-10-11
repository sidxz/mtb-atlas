"""Has anything moved upstream, and what has to be rebuilt if it has.

`make build` on a warm cache is a no-op and `make build-force` re-downloads
everything -- including the paper supplements and the WHO catalogue that cannot
have changed. Neither answers the question actually worth asking, which is
whether any source has released since the store was built.

Each source is asked by the cheapest route it offers, and the answer is
compared to the `source_version` already stamped on its table. A handful of
small requests, seconds, no writes.

**A probe that fails reports `unknown`, never `current`.** An endpoint being
down says nothing about the data behind it, and "current" is the one answer
that would be actively misleading.

Sources that cannot move are marked frozen rather than left unknown: a paper's
supplementary table is the same file forever, so a permanent question mark
beside each of them would be noise that trains you to ignore the report.

There is one deliberate permanent `unknown`, UniChem. It can move, so it cannot
be frozen, and no table stores a version of it, so it cannot be probed; it is
registered so that `refresh unichem` works, shows no stored version (the table's
belongs to PubChem), and says why on its row. Every other `unknown` is either a
probe that failed, which is a reason to look, or a probe that was not run: RCSB
and the orthologue structures replay a whole search, so they wait for
`--expensive`.
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


def _mtbtndb() -> str:
    """Ask Zenodo's concept DOI which version is newest.

    The ingester pins a *versioned* DOI, so the download is reproducible and
    cannot drift. The concept record is what knows a newer deposit exists --
    there have already been two -- so the probe reads that and the comparison
    is the versioned DOI the store was stamped with.
    """
    from .sources.mtbtndb import CITATION, CONCEPT_ID

    payload = fetch_json(f"https://zenodo.org/api/records/{CONCEPT_ID}")
    doi = (payload or {}).get("doi")
    date = ((payload or {}).get("metadata") or {}).get("publication_date")
    if not doi or not date:
        raise RuntimeError("Zenodo did not state a version")
    return f"Zenodo {doi} ({date}), via {CITATION}"


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
    from .sources.pdb import entity_ids
    from .store import read

    accessions = sorted(
        {row[0] for row in read("crosswalk").project("uniprot_acc").fetchall() if row[0]}
    )
    entries = {str(eid).split("_")[0] for eid in entity_ids(accessions)}
    return f"RCSB Search + Data API, {len(entries)} entries"


def _orthologue_pdb() -> str:
    """Replay the neighbour search and count, the same detector as `rcsb-pdb`.

    The accession set is read back from the table rather than recomputed,
    because the bridge itself only moves when UniProt's sequences do and that
    is what the `uniprot` probe is for. A neighbour that gains its *first*
    structure arrives as a new sequence in the filtered stream, so it shows up
    there too, not here.
    """
    from .sources.orthologue_structures import version_label
    from .sources.pdb import entity_ids
    from .store import read

    accessions = sorted(
        {row[0] for row in read("orthologue_structures").project("via_acc").fetchall() if row[0]}
    )
    entries = {str(eid).split("_")[0] for eid in entity_ids(accessions)}
    return version_label(len(entries))


def _pubchem() -> str:
    """How many AIDs PubChem tags *M. tuberculosis* at the floor, which is the search's answer.

    One E-utilities request with `retmax=0`, so the cost does not grow with the answer,
    and the count moves when a new campaign is deposited, which is the thing worth
    noticing. It is the same search `pubchem.build` ran and the label is the same function:
    the table is stamped with the AIDs the search tagged, not the campaigns it ingested.
    """
    from .sources import pubchem

    response = _get(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        f"?db=pcassay&term={pubchem.SEARCH_TERM}&retmax=0&retmode=json"
    )
    # A reply that is not an answer raises here (see `esearch_count`) and reads `unknown`,
    # where "0 AIDs" would read `stale`: an error shaped like a measurement.
    return pubchem.version_label(pubchem.esearch_count(response.json()["esearchresult"]))


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
    Source("mtbtndb", "conditional_tnseq", "evidence", _mtbtndb),
    # `screens` is PubChem's first and ChEMBL's after, so `provenance()` reads PubChem's.
    Source("pubchem", "screens", "evidence", _pubchem),
    # Registered so `atlas refresh unichem` works, and neither probed nor frozen.
    #
    # Not `frozen`, because it demonstrably moves independently of ChEMBL: its whole
    # directory was regenerated 2026-10-10, five months after ChEMBL 37 (2026-05-01), and
    # `refresh` says a frozen source "cannot bring new data" when this one can.
    #
    # `unknown` rather than probed, because no table stores a UniChem version to compare
    # against: `screen_results` carries PubChem's label and nothing else. The server does
    # send Last-Modified and an ETag, and `fetch.py` keeps them in the raw sidecar, so
    # comparing the live header to the stored one is the right eventual probe -- but
    # `check` reads a stored version from a table only, so it needs its own small change.
    #
    # So it reads `unknown` for ever, which is true (not asked) and not stale to a
    # scheduler, and `check` shows no stored version for it: the table's is PubChem's.
    Source("unichem", "screen_results", "evidence"),
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
    Source(
        "phmmer-paralog",
        "paralogs",
        "evidence",
        frozen="computed here from the same UniProt proteome as phmmer-human",
    ),
    # Not frozen, unlike its two phmmer siblings: the bridge is computed here,
    # but the structures on the far end of it come from RCSB and move weekly.
    Source(
        "orthologue-pdb",
        "orthologue_structures",
        "evidence",
        _orthologue_pdb,
        expensive=True,
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
        if state == "unknown" and source.probe is None:
            # Neither asked nor frozen: this source stamps no table of its own, so the one
            # `stored` came from is another source's, and printing it beside this name
            # would present that version as this source's.
            stored, detail = None, "not asked: no table stores a version of this source"
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


def as_dict(report: Report) -> dict[str, Any]:
    """The shape a scheduler consumes. A contract, so it has a test."""
    return {
        "source": report.source,
        "stored": report.stored,
        "upstream": report.upstream,
        "state": report.state,
        "detail": report.detail,
        "stage": report.stage,
        "rebuilds": list(report.rebuilds),
    }


def any_stale(reports: list[Report]) -> bool:
    """Whether a run found anything worth acting on.

    `unknown` is deliberately not stale: a probe that could not be reached is
    a reason to look, not a reason to rebuild, and a scheduler that refreshed
    on every transient 503 would churn the store for nothing.
    """
    return any(report.state == "stale" for report in reports)
