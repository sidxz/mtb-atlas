"""PubChem BioAssay: the public Mtb screening campaigns, with their inactives.

PubChem is the only public source that states an outcome per compound at
screening scale -- AID 1626 deposits 209,843 `Inactive` rows beside its 2,044
actives -- which is what makes "tested and did nothing" a provable answer
rather than an absence.

This half finds the campaigns: the taxonomy search selects the AIDs, the assay
summary supplies the counts, and `normalize_screens` turns each into one row.

Licence: per depositor, not per database. NCBI's policy puts US-government
material in the public domain but explicitly carves PubChem out: "resources
which incorporate material contributed or licensed by individuals, companies,
or organizations ... may be protected by U.S. and foreign copyright laws".
So `depositor` is recorded on every campaign and no blanket licence is claimed.

The zero that means "no call". A deposit with no stated activity threshold
reports `SIDCountActive: 0` against a full tested set, which read literally says
a 65,366-compound screen found nothing. The depositor never stated a cutoff, so
`outcome_stated` is stored, `n_active` is NULL where it is false, and nothing in
this module writes a 0 that means "no call".

Three things about the summary endpoint that are easy to assume wrongly, each
measured on the 28 AIDs of 10,000 or more tested compounds (2026-10-11):

- It carries **no taxonomy**. The search term selects the AIDs; nothing in the
  summary can be tested for Mtb afterwards. A target `Name` or assay `Name` test
  for "tubercul" or "mycobacter" rejects 8 of the 28, among them AID 1671170
  ("Biochemical assay for Mt-TrpRS"). The *Bos taurus* MsrA, *S. aureus* NadD and
  *B. subtilis* Sfp screens that motivated such a test (AIDs 651718, 602163,
  602399, 1490) are not in the taxonomy search at all.
- `Method` describes how the outcome was called (a curve, or one concentration),
  not where the assay sits in a funnel. AID 1626 is the 215,397-compound primary
  screen and PubChem calls it `confirmatory`.
- It has **no PubMed id** and no deposit year.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from ..fetch import fetch

SOURCE = "pubchem"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
PUG = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
# PubChem asks for no more than 5 requests a second.
PACE = 0.25
# Taxonomy 1773 is M. tuberculosis. [ORGN] explodes to the strains beneath it.
MTB_TAXON = "1773"
# The campaigns worth their download. The floor is this atlas's choice: below it
# sit BindingDB's re-postings of PDB affinities, which are measurements and not
# screens, and ChEMBL's re-postings of single assays (all but 172 of the 12,519).
MIN_TESTED = 10_000
# Reproducible: 28 AIDs on 2026-10-11, of 12,519 under `txid1773[ORGN]` alone.
# The floor is in the search because the summaries are the expensive part. Asking
# for all 12,519 is 501 requests, and PubChem answered 429 from the 337th (24 MB
# in) and kept answering it through fetch's backoff, so the build would die.
SEARCH_TERM = f"txid{MTB_TAXON}[ORGN] AND {MIN_TESTED}:100000000[TSC]"
AID_BATCH = 25

# "A total of 216,163 compounds were screened": the depositor's own figure for
# the library, which is not the same claim as the set they deposited.
# ponytail: first "N compounds" in the prose; a description that opens with some
# other count would be misread, so the figure stays beside the deposited n_tested.
_LIBRARY_SIZE = re.compile(r"(\d[\d,]{3,})\s*-?\s*compound", re.I)


def fetch_aids(*, force: bool = False) -> list[str]:
    """Every AID the taxonomy search returns, in the order Entrez gives them."""
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
        raise ValueError(f"esearch matched {result['count']} AIDs but returned {len(aids)}")
    return aids


def fetch_summaries(aids: Sequence[str], *, force: bool = False) -> list[dict[str, Any]]:
    """The assay summary for each AID, which carries the counts and the target."""
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
    return out


def _library_size(summary: Mapping[str, Any]) -> int | None:
    for line in summary.get("Description") or []:
        if match := _LIBRARY_SIZE.search(str(line)):
            return int(match.group(1).replace(",", ""))
    return None


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
    """
    rows = []
    for summary in summaries:
        tested = summary.get("SIDCountAll") or 0
        active = summary.get("SIDCountActive") or 0
        inactive = summary.get("SIDCountInactive") or 0
        inconclusive = summary.get("SIDCountInconclusive") or 0
        stated = bool(active or inactive or inconclusive) and (
            summary.get("SIDCountUnspecified") != tested
        )
        aid = str(summary["AID"])
        rows.append(
            {
                "screen_id": f"pubchem:{aid}",
                "aid": aid,
                "title": summary.get("Name"),
                # Stored as given: AID 2060911's is the bare string "11908".
                "depositor": summary.get("SourceName"),
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
