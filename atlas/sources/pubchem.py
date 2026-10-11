"""PubChem BioAssay: the public Mtb screening campaigns, with their inactives.

PubChem is the only public source that states an outcome per compound at
screening scale -- AID 1626 deposits 209,843 `Inactive` SIDs beside its 2,044
actives -- which is what makes "tested and did nothing" a provable answer
rather than an absence.

Counts here are SIDs (substances, `SIDCountAll`), not compounds: AID 1626 has
215,397 SIDs over 215,098 CIDs, and its prose says 216,163 compounds were
screened. Those are three numbers, and only the first is `n_tested`.

The first half finds the campaigns: the taxonomy search selects the AIDs, the
assay summary supplies the counts, and `normalize_screens` turns each into one row.
The second reads what each campaign found, compound by compound
(`normalize_results`), the project the depositor declared it part of
(`group_projects`), and the gene it aims at (`link_targets`).

Licence: per depositor, not per database. NCBI's policy puts US-government
material in the public domain but explicitly carves PubChem out: "resources
which incorporate material contributed or licensed by individuals, companies,
or organizations ... may be protected by U.S. and foreign copyright laws".
So `depositor` is recorded on every campaign and no blanket licence is claimed.

The zero that means "no call". A deposit with no stated activity threshold
reports `SIDCountActive: 0` against a full tested set, which read literally says
a screen of 65,366 SIDs found nothing. The depositor never stated a cutoff, so
`outcome_stated` is stored and `n_active` is NULL where it is false. A count
PubChem does not send is an error, never a 0: every count a row reports is one
PubChem stated, and `n_unspecified` is stored beside the three call counts so
that a deposit which called only some of its SIDs shows the gap.

Three things about the summary endpoint that are easy to assume wrongly, each
measured on the 28 AIDs of 10,000 or more tested SIDs (2026-10-11):

- It carries **no taxonomy**. The search term selects the AIDs; nothing in the
  summary can be tested for Mtb afterwards. A target `Name` or assay `Name` test
  for "tubercul" or "mycobacter" rejects 8 of the 28, among them AID 1671170
  ("Biochemical assay for Mt-TrpRS"). The *Bos taurus* MsrA, *S. aureus* NadD and
  *B. subtilis* Sfp screens that motivated such a test (AIDs 651718, 602163,
  602399, 1490) are not in the taxonomy search at all.
- `Method` describes how the outcome was called (a curve, or one concentration),
  not where the assay sits in a funnel. AID 1626 is the 215,397-SID primary
  screen and PubChem calls it `confirmatory`.
- It has **no PubMed id** and no deposit year.
"""

from __future__ import annotations

import csv
import json
import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from ..fetch import Fetched, fetch

SOURCE = "pubchem"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
PUG = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
# PubChem asks for no more than 5 requests a second.
PACE = 0.25
# Taxonomy 1773 is M. tuberculosis. [ORGN] explodes to the strains beneath it.
MTB_TAXON = "1773"
# The campaigns worth their download, in SIDs. The floor is this atlas's choice:
# below it sit BindingDB's re-postings of PDB affinities, which are measurements
# and not screens, and the small ChEMBL-deposited AIDs that make up most of the tag.
MIN_TESTED = 10_000
# Reproducible: 28 AIDs on 2026-10-11, of 12,519 under `txid1773[ORGN]` alone.
# The floor is in the search because the summaries are the expensive part. Asking
# for all 12,519 is 501 requests, and PubChem answered 429 from the 337th (24 MB
# in) and kept answering it through fetch's backoff, so the build would die.
SEARCH_TERM = f"txid{MTB_TAXON}[ORGN] AND {MIN_TESTED}:100000000[TSC]"
AID_BATCH = 25
# `fetch` writes its cache file before the checks below run, so a response that
# fails one is kept and every later run fails the same way until it is dropped.
_REMEDY = "run `atlas refresh pubchem`, or pass force=True, to fetch it again."

# "A total of 216,163 compounds were screened": the depositor's own figure for
# the library, which is not the same claim as the set they deposited.
# ponytail: first "N compounds" in the prose; a description that opens with some
# other count would be misread, so the figure stays beside the deposited n_tested.
_LIBRARY_SIZE = re.compile(r"(\d[\d,]{3,})\s*-?\s*compound", re.I)


def fetch_aids(*, force: bool = False) -> list[str]:
    """Every Mtb-tagged AID with at least `MIN_TESTED` SIDs, in the order Entrez gives them."""
    page = fetch(
        f"{EUTILS}/esearch.fcgi?db=pcassay&term={SEARCH_TERM}&retmax=100000&retmode=json",
        "aids.json",
        source=SOURCE,
        min_interval=PACE,
        force=force,
        json_body=True,
    )
    result = json.loads(page.text)["esearchresult"]
    aids = [str(aid) for aid in result["idlist"]]
    # esearch returns at most `retmax` ids and says how many matched; a shorter
    # list would silently drop campaigns.
    if int(result["count"]) != len(aids):
        raise ValueError(
            f"esearch matched {result['count']} AIDs but returned {len(aids)}. The response "
            f"is cached already, so a re-run reads it back: {_REMEDY}"
        )
    return aids


def fetch_summaries(aids: Sequence[str], *, force: bool = False) -> list[dict[str, Any]]:
    """The assay summary for each AID, which carries the counts and the target.

    Raises if any AID comes back without one. PUG-REST skips an AID it cannot find
    and still answers 200 for the rest, so a lost summary would be a campaign
    missing from the atlas with nothing to say so.
    """
    out: list[dict[str, Any]] = []
    for index in range(0, len(aids), AID_BATCH):
        batch = aids[index : index + AID_BATCH]
        page = fetch(
            f"{PUG}/assay/aid/{','.join(batch)}/summary/JSON",
            f"summaries/{index}.json",
            source=SOURCE,
            min_interval=PACE,
            force=force,
            json_body=True,
        )
        out += json.loads(page.text)["AssaySummaries"]["AssaySummary"]
    got = {str(summary["AID"]) for summary in out}
    if missing := [aid for aid in aids if aid not in got]:
        raise ValueError(
            f"PubChem returned no summary for AIDs {', '.join(missing)}. The batch that lacked "
            f"them is cached already, so a re-run reads it back: {_REMEDY}"
        )
    return out


def _library_size(summary: Mapping[str, Any]) -> int | None:
    for line in summary.get("Description") or []:
        if match := _LIBRARY_SIZE.search(str(line)):
            return int(match.group(1).replace(",", ""))
    return None


def _required(summary: Mapping[str, Any], key: str) -> Any:
    """A field the row cannot be honest without. Absent is not zero, and a campaign
    with no depositor has no licence to trace."""
    if summary.get(key) is None:
        raise ValueError(f"AID {summary.get('AID')} summary has no {key}")
    return summary[key]


def normalize_screens(summaries: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """One campaign row per AID.

    `outcome_stated` is stored rather than derived because the alternative is
    reading `SIDCountActive: 0` as a finding. It is false when PubChem says every
    tested SID is `Unspecified` (`SIDCountUnspecified` equals `SIDCountAll`), and
    also when no call count is above zero. The first test matters: six of the
    eight ChEMBL deposits report a few actives (1 to 90, the IC50 rows) beside
    an all-`Unspecified` set, and "any call count above zero" would publish those
    actives with a 0 for inactives that means "never called". `n_active`,
    `n_inactive` and `n_inconclusive` are NULL wherever it is false.

    Where it is true, each is the number of SIDs the depositor called that way,
    and a deposit that called only some of its SIDs (a partial one: 1,912 of the
    8,391 small AIDs fetched, none of the 28 large) has `n_unspecified` for the rest.
    """
    rows = []
    for summary in summaries:
        tested = _required(summary, "SIDCountAll")
        active = _required(summary, "SIDCountActive")
        inactive = _required(summary, "SIDCountInactive")
        inconclusive = _required(summary, "SIDCountInconclusive")
        unspecified = _required(summary, "SIDCountUnspecified")
        stated = bool(active or inactive or inconclusive) and unspecified != tested
        aid = str(summary["AID"])
        rows.append(
            {
                "screen_id": f"pubchem:{aid}",
                "aid": aid,
                "title": summary.get("Name"),
                # Stored as given: AID 2060911's is the bare string "11908".
                "depositor": _required(summary, "SourceName"),
                "deposit_kind": "dataset",
                # The depositor names the library in prose or not at all;
                # PubChem has no field for it.
                "library_name": None,
                "library_size_stated": _library_size(summary),
                # `LastDataChange` is a revision date, not a deposit year.
                "year": None,
                # `project_declared` is set by `build` once the project links are read.
                "n_stages": 1,
                "n_tested": tested,
                "n_active": active if stated else None,
                "n_inactive": inactive if stated else None,
                "n_inconclusive": inconclusive if stated else None,
                # PubChem's own count of SIDs with no call, so it is never a
                # zero standing in for one.
                "n_unspecified": unspecified,
                "outcome_stated": stated,
                # What PubChem states is how the outcome was called, kept under
                # its own name. The stage comes from the project structure and
                # the title, so it is read from prose.
                "outcome_method": summary.get("Method"),
                "stages_source": "from_prose",
                "project_declared": False,
                "modalities": [],
                "document_chembl_id": None,
                # No PubMed id in the summary, and the description endpoint's
                # xrefs do not say which citation is the paper and which a method.
                "pubmed_id": None,
                # Verbatim, and empty for a whole-cell campaign. The accession is
                # a UniProt id, a RefSeq NP_, an EMBL id or a PDB chain; the name
                # can be a gene symbol and is never matched against one.
                "targets": [
                    {"accession": target.get("Accession"), "name": target.get("Name")}
                    for target in summary.get("Target") or []
                ],
                "licence": "per depositor; see docs/data-sources.md",
            }
        )
    return rows


# --- the per-compound results ------------------------------------------------
#
# Not PUG-REST, which refuses above 10,000 SIDs with
# "PUGREST.BadRequest: Too many SIDs". This route is uncapped: AID 1626
# returns all 215,397 rows as a 30 MB CSV.
RESULTS = (
    "https://pubchem.ncbi.nlm.nih.gov/assay/pcget.cgi"
    "?query=download&record_type=datatable&actvty=all&response_type=save&aid="
)
# The depositor's own call. `Unspecified` is not a fourth outcome -- it is the
# absence of one, and it must not become "inactive". A label that is not here
# raises: PubChem also counts `Probe`, and reading an unknown call as no call
# would be the same false zero.
OUTCOMES = {
    "active": "active",
    "inactive": "inactive",
    "inconclusive": "inconclusive",
    "unspecified": None,
    "": None,
}
RESULT_COLUMNS = ("PUBCHEM_RESULT_TAG", "PUBCHEM_ACTIVITY_OUTCOME")


def fetch_results(aid: str, *, force: bool = False) -> Fetched:
    return fetch(
        f"{RESULTS}{aid}",
        f"results/{aid}.csv",
        source=SOURCE,
        min_interval=PACE,
        force=force,
        timeout=600.0,
    )


def _number(value: str | None) -> float | None:
    try:
        return float(value) if value else None
    except ValueError:
        return None


def _text(value: str | None) -> str | None:
    return (value or "").strip() or None


def normalize_results(
    path: Path, aid: str, chembl_by_cid: Mapping[str, str], *, screen_id: str | None = None
) -> Iterator[dict[str, Any]]:
    """One row per result row PubChem deposits: a SID, not a compound.

    A CID can appear under several SIDs that disagree (11 CIDs in AID 1626 are
    `Active` as one SID and `Inconclusive` as another), and a SID can appear
    twice (AID 1671170: 65,646 rows over 65,366 SIDs, mostly an `IC50` beside the
    single-point `Percent Effect`). Neither is collapsed here, because the choice
    of which row wins would be silent.

    `screen_id` is the campaign the AID belongs to when it is part of a declared
    project (see `group_projects`); the stage stays the assay.

    The three-to-five rows after the header are PubChem's column metadata
    (`RESULT_TYPE`, `RESULT_DESCR`, `RESULT_UNIT`, ...); only a numeric
    `PUBCHEM_RESULT_TAG` is a result.

    Only the columns every AID shares are read, plus `Standard Type`, `Standard
    Relation`, `Standard Value` and `Standard Units` where the deposit has them.
    ChEMBL's deposits do (AID 1671170: 612 IC50 rows beside 65,034 `Percent
    Effect`); the depositors' own columns (`H37Rv IC90`, `Percent_Inhibition`) are
    different in every AID and stay in the raw file. The four keys are NULL, not
    absent, where the deposit has none.
    """
    with path.open(encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle)
        if missing := [name for name in RESULT_COLUMNS if name not in (reader.fieldnames or [])]:
            raise ValueError(
                f"AID {aid}: {path.name} has no {', '.join(missing)} column, so it is not a "
                f"PubChem result table (an error page is cached under the same name). "
                f"{_REMEDY}"
            )
        for row in reader:
            if not (row["PUBCHEM_RESULT_TAG"] or "").strip().isdigit():
                continue
            label = (row["PUBCHEM_ACTIVITY_OUTCOME"] or "").strip()
            if label.lower() not in OUTCOMES:
                raise ValueError(f"unrecognised outcome {label!r} in AID {aid}")
            cid = _text(row.get("PUBCHEM_CID"))
            score = _text(row.get("PUBCHEM_ACTIVITY_SCORE"))
            yield {
                "stage_id": f"pubchem:{aid}",
                "screen_id": screen_id or f"pubchem:{aid}",
                "pubchem_cid": cid,
                "pubchem_sid": _text(row.get("PUBCHEM_SID")),
                "molecule_chembl_id": chembl_by_cid.get(cid) if cid else None,
                "outcome": OUTCOMES[label.lower()],
                "activity_score": int(score) if score else None,
                "endpoint": _text(row.get("Standard Type")),
                "standard_value": _number(row.get("Standard Value")),
                "standard_units": _text(row.get("Standard Units")),
                "standard_relation": _text(row.get("Standard Relation")),
            }


# --- the declared ladder -----------------------------------------------------
#
# PubChem's project links are the funnel as the depositor stated it: AID
# 449775 groups 39 members including the primary (327,669 tested), the
# confirmatory dose-response (2,262) and a Vero cytotoxicity counter-screen.
# 10 of the 20 largest non-ChEMBL Mtb campaigns declare one; the other 10 --
# including TAACF 1626 and 1949 -- declare nothing, and that is not the same
# statement as having had no follow-up.
PROJECT_LINK = (
    f"{EUTILS}/elink.fcgi?dbfrom=pcassay&db=pcassay"
    "&linkname=pcassay_pcassay_same_assay_project_list&retmode=json&id="
)


def fetch_project(aid: str, *, force: bool = False) -> dict[str, Any]:
    page = fetch(
        f"{PROJECT_LINK}{aid}",
        f"projects/{aid}.json",
        source=SOURCE,
        min_interval=PACE,
        force=force,
        json_body=True,
    )
    return json.loads(page.text)


def _members(payload: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    for linkset in payload.get("linksets") or []:
        for db in linkset.get("linksetdbs") or []:
            out += [str(link) for link in db.get("links") or []]
    return sorted(set(out), key=int)


def group_projects(payloads: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    """AID -> the campaign it belongs to.

    A declared project becomes one campaign named for its lowest member AID,
    so every member resolves to the same id whichever one was asked (the
    lowest member of AID 449762's project is 435019, not 449762). An AID with
    no declared siblings, or whose project lists only itself, is its own campaign.
    """
    grouped: dict[str, str] = {}
    for aid, payload in payloads.items():
        members = _members(payload)
        grouped[aid] = f"pubchem:project:{members[0]}" if len(members) > 1 else f"pubchem:{aid}"
    return grouped


# --- the gene a campaign aims at ---------------------------------------------
#
# A campaign reaches a gene through the accession in its summary's `Target`, and
# depositors write four different things there: of 18 accessions over 16 AIDs, 7
# are UniProt, 8 RefSeq `NP_`, 2 EMBL and 1 a PDB chain. The crosswalk joins on
# UniProt, so UniProt ones join directly, RefSeq ones are bridged through UniProt's
# own cross-references, and the rest stay unmatched. The target `Name` is never
# matched against a gene symbol: "bioA" is a symbol, and a screen lands on the
# wrong locus that way.
UNIPROT_SEARCH = "https://rest.uniprot.org/uniprotkb/search"
_UNIPROT = re.compile(r"[OPQ][0-9][A-Z0-9]{3}[0-9]|[A-NR-Z][0-9]([A-Z][A-Z0-9]{2}[0-9]){1,2}")
_REFSEQ = re.compile(r"NP_[0-9]+")


def accession_kind(accession: str | None) -> str:
    """`uniprot`, `refseq` (an `NP_` protein) or `other` (EMBL, a PDB chain, ...)."""
    accession = accession or ""
    if _UNIPROT.fullmatch(accession):
        return "uniprot"
    return "refseq" if _REFSEQ.fullmatch(accession) else "other"


def fetch_refseq(accession: str, *, force: bool = False) -> list[str]:
    """The UniProt accessions whose entries cross-reference this RefSeq protein.

    Not an Mtb lookup: RefSeq `NP_` spans every organism, so what comes back may
    be another species' protein. The crosswalk, which is H37Rv only, is what
    decides whether it reaches a locus.
    """
    if not _REFSEQ.fullmatch(accession):
        raise ValueError(f"{accession!r} is not a RefSeq NP_ accession")
    page = fetch(
        f"{UNIPROT_SEARCH}?query=xref:refseq-{accession}&fields=accession&format=json",
        f"refseq/{accession}.json",
        source="uniprot",
        force=force,
        json_body=True,
    )
    return [hit["primaryAccession"] for hit in json.loads(page.text)["results"]]


def link_targets(
    targets: Iterable[Mapping[str, Any]],
    rv_by_acc: Mapping[str, Sequence[str]],
    *,
    force: bool = False,
) -> list[dict[str, Any]]:
    """Each target as the depositor stated it, plus the loci it reaches.

    `rv_by_acc` is the crosswalk's UniProt accession -> Rv ids. An accession that
    reaches no locus has `rv_ids == []` and keeps its accession and name, so the
    absence is visible. One that reaches several (55 loci share an accession with
    a sibling) keeps all of them and says `shared_accession`; none is picked.
    """
    out = []
    for target in targets:
        accession = target.get("accession")
        kind = accession_kind(accession)
        if kind == "uniprot":
            uniprot = [accession]
        elif kind == "refseq":
            uniprot = fetch_refseq(accession, force=force)
        else:
            uniprot = []
        rv_ids = sorted({rv for acc in uniprot for rv in rv_by_acc.get(acc, ())})
        out.append(
            {
                "accession": accession,
                "name": target.get("name"),
                "accession_kind": kind,
                "uniprot_accessions": uniprot,
                "rv_ids": rv_ids,
                "shared_accession": len(rv_ids) > 1,
            }
        )
    return out
