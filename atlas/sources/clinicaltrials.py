"""Interventional tuberculosis trials from ClinicalTrials.gov (API v2).

The clinical end of the atlas: which trials exist for TB, at what phase and
status, testing which interventions. Trials are linked to drugs, and through
them to genes, in `atlas/clinical.py` -- this module only fetches and
normalizes.

**Terms** (ClinicalTrials.gov Terms and Conditions, last modified 2023-01-31):
the data are free to all requesters; anyone publishing or distributing them
should attribute ClinicalTrials.gov, keep them current, clearly display the
date the data were processed by ClinicalTrials.gov, and state any
modifications. That is why `source_version` carries the API's own
`dataTimestamp`, and why the modifications this module makes are stated
wherever the data is shown: a subset of fields, phases mapped to a number for
sorting, studies solely of nontuberculous mycobacteria left out, and nothing
else rewritten.

**Scope:** `query.cond=tuberculosis`, interventional only -- 1,152 studies on
2026-10-10, less the 15 that are about nontuberculous mycobacteria. That
includes vaccine, diagnostic and behavioural studies, which are TB trials in
their own right; they simply link to no drug.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from ..fetch import Fetched, fetch
from ..store import write_parquet

SOURCE = "clinicaltrials-gov"
API = "https://clinicaltrials.gov/api/v2"
QUERY = "query.cond=tuberculosis&filter.advanced=AREA%5BStudyType%5DINTERVENTIONAL"
PAGE = 1000
# Contacts are deliberately not requested: the terms forbid using their email
# addresses, and the atlas has no use for them.
FIELDS = ",".join(
    (
        "NCTId",
        "BriefTitle",
        "OfficialTitle",
        "Acronym",
        "OverallStatus",
        "WhyStopped",
        "Phase",
        "StudyType",
        "StartDate",
        "PrimaryCompletionDate",
        "CompletionDate",
        "EnrollmentCount",
        "LeadSponsorName",
        "LeadSponsorClass",
        "CollaboratorName",
        "Condition",
        "InterventionType",
        "InterventionName",
        "InterventionOtherName",
        "InterventionArmGroupLabel",
        "ArmGroupLabel",
        "ArmGroupType",
        "ArmGroupInterventionName",
        "LocationCountry",
        "HasResults",
        "LastUpdatePostDate",
        "StudyFirstPostDate",
        "DesignAllocation",
        "DesignPrimaryPurpose",
    )
)


def fetch_raw(*, force: bool = False) -> tuple[list[dict[str, Any]], Fetched, Fetched]:
    """Every matching study, page by page, plus the API version record.

    Pages chain through `nextPageToken`, so page n+1's URL depends on page n.
    A cached first page therefore reproduces the same second-page URL and the
    cache holds; a forced re-download refreshes the whole chain.
    """
    release = fetch(f"{API}/version", "version.json", source=SOURCE, force=force, json_body=True)
    studies: list[dict[str, Any]] = []
    token = ""
    first: Fetched | None = None
    for n in range(1000):
        url = f"{API}/studies?{QUERY}&fields={FIELDS}&pageSize={PAGE}"
        if token:
            url += f"&pageToken={token}"
        page = fetch(url, f"studies-{n}.json", source=SOURCE, force=force, json_body=True)
        first = first or page
        payload = json.loads(page.text)
        studies += payload["studies"]
        token = payload.get("nextPageToken") or ""
        if not token:
            break
    assert first is not None
    return studies, first, release


# ClinicalTrials.gov's condition search for "tuberculosis" also returns studies
# of nontuberculous mycobacteria -- "Non-tuberculous" contains the word. A study
# is out of scope only when a listed condition names an NTM disease and none
# names TB: a TB vaccine trial that lists only "Healthy" stays in. On the live
# data this drops 15 studies, all NTM.
_NTM = re.compile(
    r"non-?tubercul|\bNTM\b|abscessus|avium|intracellulare|kansasii|\bMAC\b|xenopi|"
    r"fortuitum|chelonae|marinum|atypical",
    re.IGNORECASE,
)
_TB = re.compile(r"(?<!non)(?<!non-)tubercul|\bTB\b|\bLTBI\b|MDR-?TB|XDR-?TB", re.IGNORECASE)


def nontuberculous_only(conditions: list[str]) -> bool:
    return any(_NTM.search(c) for c in conditions) and not any(_TB.search(c) for c in conditions)


# Numeric phase for sorting and filtering. "NA" (not applicable -- device,
# behavioural and diagnostic studies) maps to nothing rather than to zero.
PHASES = {"EARLY_PHASE1": 0.5, "PHASE1": 1.0, "PHASE2": 2.0, "PHASE3": 3.0, "PHASE4": 4.0}


def version(payload: dict[str, Any]) -> str:
    """The processing date the terms ask every reuse to display."""
    return f"API {payload['apiVersion']}, data processed {payload['dataTimestamp']}"


def _date(module: dict[str, Any], key: str) -> str | None:
    # Kept as given: ClinicalTrials.gov dates are often partial ("2018-06").
    return (module.get(key) or {}).get("date")


def normalize(studies: Iterable[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    """One row per TB study, fields as registered; only the phase gains a number."""
    for study in studies:
        protocol = study["protocolSection"]
        ident = protocol["identificationModule"]
        status = protocol.get("statusModule") or {}
        design = protocol.get("designModule") or {}
        info = design.get("designInfo") or {}
        sponsors = protocol.get("sponsorCollaboratorsModule") or {}
        lead = sponsors.get("leadSponsor") or {}
        arms = protocol.get("armsInterventionsModule") or {}
        locations = (protocol.get("contactsLocationsModule") or {}).get("locations") or []
        conditions = (protocol.get("conditionsModule") or {}).get("conditions") or []
        if nontuberculous_only(conditions):
            continue
        phases = design.get("phases") or []
        numbers = [PHASES[p] for p in phases if p in PHASES]
        yield {
            "nct_id": ident["nctId"],
            "brief_title": ident.get("briefTitle"),
            "official_title": ident.get("officialTitle"),
            "acronym": ident.get("acronym"),
            "phases": phases,
            "phase_max": max(numbers) if numbers else None,
            "status": status.get("overallStatus"),
            "why_stopped": status.get("whyStopped"),
            "start_date": _date(status, "startDateStruct"),
            "primary_completion_date": _date(status, "primaryCompletionDateStruct"),
            "completion_date": _date(status, "completionDateStruct"),
            "first_posted": _date(status, "studyFirstPostDateStruct"),
            "last_update": _date(status, "lastUpdatePostDateStruct"),
            "enrollment": (design.get("enrollmentInfo") or {}).get("count"),
            "allocation": info.get("allocation"),
            "primary_purpose": info.get("primaryPurpose"),
            "lead_sponsor": lead.get("name"),
            "sponsor_class": lead.get("class"),
            "collaborators": [
                c["name"] for c in sponsors.get("collaborators") or [] if c.get("name")
            ],
            "conditions": conditions,
            "interventions": [
                {
                    "type": i.get("type"),
                    "name": i.get("name"),
                    "other_names": i.get("otherNames") or [],
                }
                for i in arms.get("interventions") or []
            ],
            "arms": [
                {
                    "label": a.get("label"),
                    "type": a.get("type"),
                    "interventions": a.get("interventionNames") or [],
                }
                for a in arms.get("armGroups") or []
            ],
            "countries": sorted({loc["country"] for loc in locations if loc.get("country")}),
            "has_results": bool(study.get("hasResults")),
        }


def build(*, force: bool = False) -> Path:
    studies, first, version_file = fetch_raw(force=force)
    return write_parquet(
        "trials",
        normalize(studies),
        source=SOURCE,
        source_version=version(json.loads(version_file.text)),
        retrieved_at=first.retrieved_at,
    )
