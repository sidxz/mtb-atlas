"""ChEMBL target list, keyed on UniProt accession.

M0 ingests only the accession -> target mapping, which is what the ID crosswalk
needs. Bioactivity lands in M1. Licence: CC BY-SA 3.0, attribution requested;
ChEMBL asks that ChEMBL IDs be preserved and the release number displayed, which
is why `source_version` is parsed from the file rather than hardcoded.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from collections.abc import Iterable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from ..fetch import RAW, Fetched, fetch, fetch_json, fetch_json_many
from ..store import stamp, write_parquet

SOURCE = "chembl"
# Where fetch() put the mapping file, which names the release in its first line.
SOURCE_DIR = SOURCE
MAPPING_FILE = "chembl_uniprot_mapping.txt"
URL = f"https://ftp.ebi.ac.uk/pub/databases/chembl/ChEMBLdb/latest/{MAPPING_FILE}"
API = "https://www.ebi.ac.uk/chembl/api/data"

# Whole-cell Mtb. CHEMBL360 holds the bulk (209k activities); CHEMBL2111188 is
# the H37Rv-specific target and much smaller.
WHOLE_CELL_TARGETS = ("CHEMBL360", "CHEMBL2111188")
PAGE = 1000
# `molecule_chembl_id__in` is verified to accept at least 50 ids per request.
ID_BATCH = 50

# First line is e.g. "# chembl_37 target list, 01/05/2026".
_VERSION = re.compile(r"#\s*(chembl_\S+)\s+target list,\s*(\S+)")


def fetch_raw(*, force: bool = False) -> Fetched:
    return fetch(URL, "chembl_uniprot_mapping.txt", source=SOURCE, min_interval=0.5, force=force)


def release(path: Path) -> str:
    with path.open(encoding="utf-8") as handle:
        match = _VERSION.match(handle.readline())
    return f"{match.group(1)} ({match.group(2)})" if match else "unknown"


def normalize(path: Path) -> Iterator[dict[str, Any]]:
    """The whole table, not just Mycobacterium.

    Keeping every row (~17k) lets the crosswalk resolve both the direct Mtb
    targets and the mycobacterial orthologue targets without this ingester
    needing to know anything about the gene universe.
    """
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("#"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) != 4:
                continue
            accession, target_id, pref_name, target_type = parts
            yield {
                "uniprot_acc": accession,
                "chembl_target_id": target_id,
                "pref_name": pref_name,
                "target_type": target_type,
            }


def build(*, force: bool = False) -> Path:
    raw = fetch_raw(force=force)
    return write_parquet(
        "chembl_targets",
        normalize(raw.path),
        source=SOURCE,
        source_version=release(raw.path),
        retrieved_at=raw.retrieved_at,
    )


# --- bioactivity -------------------------------------------------------------

ACTIVITY_FIELDS = (
    "activity_id,molecule_chembl_id,target_chembl_id,target_organism,standard_type,"
    "standard_relation,standard_value,standard_units,pchembl_value,assay_chembl_id,"
    "assay_type,assay_description,document_chembl_id,document_year,data_validity_comment,"
    "activity_comment,potential_duplicate,canonical_smiles"
)
MOLECULE_FIELDS = (
    "molecule_chembl_id,pref_name,max_phase,molecule_type,first_approval,oral,"
    "molecule_properties,molecule_structures"
)


def _activity_url(query: str, *, offset: int = 0, limit: int = PAGE) -> str:
    return f"{API}/activity.json?{query}&only={ACTIVITY_FIELDS}&limit={limit}&offset={offset}"


def _activity_row(record: dict[str, Any], evidence: str) -> dict[str, Any]:
    def number(key: str) -> float | None:
        value = record.get(key)
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    return {
        "activity_id": record.get("activity_id"),
        "molecule_chembl_id": record.get("molecule_chembl_id"),
        "target_chembl_id": record.get("target_chembl_id"),
        "target_organism": record.get("target_organism"),
        "evidence": evidence,
        "standard_type": record.get("standard_type"),
        "standard_relation": record.get("standard_relation"),
        "standard_value": number("standard_value"),
        "standard_units": record.get("standard_units"),
        "pchembl_value": number("pchembl_value"),
        "assay_chembl_id": record.get("assay_chembl_id"),
        "assay_type": record.get("assay_type"),
        "assay_description": record.get("assay_description"),
        "document_chembl_id": record.get("document_chembl_id"),
        "document_year": record.get("document_year"),
        # ChEMBL's own warning that a value is suspect. Kept rather than
        # filtered, so the UI can show it instead of quietly dropping evidence.
        "data_validity_comment": record.get("data_validity_comment"),
        "potential_duplicate": bool(record.get("potential_duplicate")),
    }


def target_activities(targets: Sequence[tuple[str, str]]) -> list[dict[str, Any]]:
    """Every activity with a pChEMBL value for these (target_id, evidence) pairs."""
    evidence_of = dict(targets)
    first = fetch_json_many(
        [_activity_url(f"target_chembl_id={t}&pchembl_value__isnull=false") for t, _ in targets],
        workers=6,
        min_interval=0.1,
        label="chembl activities",
    )

    rows: list[dict[str, Any]] = []
    overflow: list[str] = []
    for url, payload in first.items():
        target_id = url.split("target_chembl_id=")[1].split("&")[0]
        rows.extend(_activity_row(a, evidence_of[target_id]) for a in payload["activities"])
        total = payload["page_meta"]["total_count"]
        overflow.extend(
            _activity_url(f"target_chembl_id={target_id}&pchembl_value__isnull=false", offset=off)
            for off in range(PAGE, total, PAGE)
        )
    if overflow:
        for url, payload in fetch_json_many(
            overflow, workers=6, min_interval=0.1, label="chembl activities (cont.)"
        ).items():
            target_id = url.split("target_chembl_id=")[1].split("&")[0]
            rows.extend(_activity_row(a, evidence_of[target_id]) for a in payload["activities"])
    return rows


def whole_cell_activities(molecule_ids: Sequence[str]) -> list[dict[str, Any]]:
    """Whole-cell Mtb potency, pulled compound-first.

    Never target-first: CHEMBL360 alone holds 209k activities, and a whole-cell
    number only belongs on a gene page when the same compound already has
    protein-level activity against that gene.
    """
    urls = [
        _activity_url(f"target_chembl_id={target}&molecule_chembl_id__in={','.join(batch)}")
        for target in WHOLE_CELL_TARGETS
        for batch in (molecule_ids[i : i + ID_BATCH] for i in range(0, len(molecule_ids), ID_BATCH))
    ]
    rows: list[dict[str, Any]] = []
    for payload in fetch_json_many(
        urls, workers=6, min_interval=0.1, label="chembl whole-cell"
    ).values():
        rows.extend(_activity_row(a, "whole_cell") for a in payload["activities"])
    return rows


def molecules(molecule_ids: Sequence[str]) -> list[dict[str, Any]]:
    urls = [
        f"{API}/molecule.json?molecule_chembl_id__in={','.join(molecule_ids[i : i + ID_BATCH])}"
        f"&only={MOLECULE_FIELDS}&limit={ID_BATCH}"
        for i in range(0, len(molecule_ids), ID_BATCH)
    ]
    rows: list[dict[str, Any]] = []
    for payload in fetch_json_many(
        urls, workers=6, min_interval=0.1, label="chembl molecules"
    ).values():
        rows.extend(_compound_row(molecule) for molecule in payload["molecules"])
    return rows


def _compound_row(molecule: dict[str, Any]) -> dict[str, Any]:
    properties = molecule.get("molecule_properties") or {}
    structures = molecule.get("molecule_structures") or {}
    return {
        "molecule_chembl_id": molecule["molecule_chembl_id"],
        "pref_name": molecule.get("pref_name"),
        "molecule_type": molecule.get("molecule_type"),
        # ChEMBL serves this as the string "2.0". Stored raw it made
        # `compounds.max_phase` a VARCHAR while `drugs.max_phase` was a DOUBLE
        # -- the same field, one comparing numerically and one lexically.
        "max_phase": _float(molecule.get("max_phase")),
        "first_approval": molecule.get("first_approval"),
        "smiles": structures.get("canonical_smiles"),
        "inchi_key": structures.get("standard_inchi_key"),
        "mw": _float(properties.get("full_mwt")),
        "alogp": _float(properties.get("alogp")),
        "hba": properties.get("hba"),
        "hbd": properties.get("hbd"),
        "psa": _float(properties.get("psa")),
        "rotatable_bonds": properties.get("rtb"),
        "aromatic_rings": properties.get("aromatic_rings"),
        "ro5_violations": properties.get("num_ro5_violations"),
        "qed": _float(properties.get("qed_weighted")),
    }


def _float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def release_from_api() -> str:
    """The release ChEMBL asks to be displayed.

    The status endpoint 500s from time to time, and a version string is not
    worth losing a build over. The mapping file this pipeline has already
    downloaded names the release in its first line, so the fallback is still
    ChEMBL stating its own version rather than a guess. Only with neither is
    "unknown" recorded, which is the rule for a source that will not say.
    """
    try:
        status = fetch_json(f"{API}/status.json")
        return f"{status['chembl_db_version']} ({status['chembl_release_date']})"
    except Exception as error:  # noqa: BLE001 - any failure here means asking elsewhere
        print(f"  chembl: no release from the status endpoint ({error})", file=sys.stderr)
    cached = RAW / SOURCE_DIR / MAPPING_FILE
    if cached.exists() and (version := release(cached)) != "unknown":
        print(f"  chembl: release from the cached mapping file: {version}", file=sys.stderr)
        return version
    return "unknown"


# --- whole-cell potency: the MICs ChEMBL does not give a pChEMBL -------------

# ChEMBL computes `pchembl_value` for affinity endpoints only. It is NULL on
# every MIC row in the store -- 3,870 of them -- because an MIC is a growth
# endpoint, not a binding constant. So a roll-up that reads `pchembl_value`
# reports whole-cell potency from the 78 IC50/EC50 rows that happen to have one
# and silently ignores every MIC, which is the number a TB chemist means by
# "whole-cell". `pmic` is that number, computed here.
#
# MIC family only. `MBC` is bactericidal rather than inhibitory and is a
# different endpoint, so it gets no `pmic`; `pMIC` and `-logMIC` are already
# logs and would be double-logged. The pattern admits MIC, MIC90, `MIC>90`
# (a 90%-inhibition threshold, not a censored value) and the like.
_MIC_TYPE = re.compile(r"^MIC[0-9.>=<]*$")

# Molar units, to mol/L.
_MOLAR = {"M": 1.0, "mM": 1e-3, "uM": 1e-6, "nM": 1e-9, "pM": 1e-12}
# Mass-per-volume units, to mol/L once divided by the molecular weight.
# 1 ug/mL = 1 mg/L = 1e-3 g/L, so M = value * 1e-3 / mw.
# Keys are lower-cased: ChEMBL spells the same unit `ug.mL-1`, `ug ml-1` and
# `microg/ml` across deposits, so the lookup folds case.
_MASS = {
    "ug.ml-1": 1e-3,
    "ug ml-1": 1e-3,
    "ug/ml": 1e-3,
    "microg/ml": 1e-3,
    "mg.l-1": 1e-3,
    "mg/l": 1e-3,
    "mg/ml": 1.0,
    "g/l": 1.0,
}


def pmic(
    standard_type: str | None,
    relation: str | None,
    value: float | None,
    units: str | None,
    mw: float | None,
) -> tuple[float | None, str | None]:
    """-log10(MIC in mol/L), with the conversion that produced it.

    Returns `(None, None)` unless this is an exact MIC in a unit that can be
    made molar. **A `>` relation gets no `pmic`**: "MIC > 64 ug/mL" means the
    compound did not inhibit at the highest concentration tested, which is a
    censored observation, not a potency of 64. Turning it into a number would
    invent the one thing the experiment failed to measure, and because those
    rows are a fifth of the MICs it would drag every aggregate toward a
    potency nobody observed.
    """
    if not standard_type or not _MIC_TYPE.match(standard_type):
        return None, None
    if relation != "=" or value is None or value <= 0 or not units:
        return None, None
    if (factor := _MOLAR.get(units)) is not None:
        return round(-math.log10(value * factor), 3), units
    if (factor := _MASS.get(units.lower())) is not None:
        if not mw or mw <= 0:
            return None, None
        return round(-math.log10(value * factor / mw), 3), f"{units} / MW {mw:.1f}"
    return None, None


# The growth condition an MIC was measured under, from the assay description.
# ChEMBL has no condition field, so this reads the depositor's own prose. The
# order is precedence: the most demanding condition named wins, because
# "activity against Mtb in 7H9 under hypoxia" is a hypoxia result.
#
# `caseum` matches nothing in the current release and is kept deliberately --
# it is the highest-value condition in TB target assessment and a visible zero
# is the honest way to say the public chemistry does not cover it.
_CONDITIONS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("caseum", re.compile(r"caseum|caseous")),
    (
        "intracellular",
        re.compile(r"macrophage|thp-?1|raw 264|j774|bone marrow[- ]derived|infected monocyte"),
    ),
    (
        "non_replicating",
        re.compile(
            r"\blora\b|hypoxi|anaerob|non-?replicat|dormant|stationary phase"
            r"|low[- ]oxygen|starvation|starved"
        ),
    ),
    ("alt_carbon", re.compile(r"cholesterol|butyrate|propionate|gluconeogen|fatty acid as")),
    (
        "nutrient_stress",
        re.compile(
            r"fe-rich|fe-deficient|iron-depleted|iron-rich|low iron|\bph [456]"
            r"|acidic ph|nitric oxide|nitrosative|oxidative stress|hydrogen peroxide"
        ),
    ),
    ("standard_media", re.compile(r"7h9|7h11|7h10|middlebrook|lowenstein|dubos|sauton")),
)

# Orthogonal to the condition: which strain, not which medium. Kept as its own
# flag rather than folded into the enum, because "tested on MDR clinical
# isolates" and "tested under hypoxia" are different claims and a single column
# would make each one hide the other.
_RESISTANT_PANEL = re.compile(
    r"\bmdr\b|multi-?drug[- ]resistant|multidrug-resistant|clinical isolate|clinical strain"
    r"|[a-z]+-resistant mycobacterium|resistant clinical|\bxdr\b"
)


def classify_condition(description: str | None) -> str:
    """The growth condition named in an assay description, or `unspecified`.

    **`unspecified` is not `standard_media`.** Most ChEMBL MICs never state a
    medium, and asserting the default would turn silence into a measurement --
    the same flattening the atlas refuses everywhere else. A gene whose every
    MIC is `unspecified` has a real answer: nobody has published its chemistry
    outside ordinary aerobic growth.
    """
    if not description:
        return "unspecified"
    text = description.lower()
    for label, pattern in _CONDITIONS:
        if pattern.search(text):
            return label
    return "unspecified"


# --- what was measured, and where in the funnel -------------------------------
#
# ChEMBL has no modality or stage field, so these read the depositor's prose
# the same way `classify_condition` does, and carry the same standing: the
# description is stored beside the label so a reader can check it, and the
# table records `stages_source = 'from_prose'` wherever that is what happened.

MODALITIES = (
    "phenotypic_mtb",
    "biochemical_mtb",
    "mammalian_cytotox",
    "adme",
    "in_vivo_efficacy",
    "other_pathogen",
    "other",
)

# A ratio ChEMBL computed from two other rows. 6,577 compounds in the Mtb
# whole-cell literature carry one, and counting them as cytotoxicity readings
# inflated that coverage before they were excluded. The number is real; it is
# just not a measurement, so it is labelled and left out of the counts.
_DERIVED = re.compile(
    r"^\s*(selectivity|therapeutic|resistance)\s+(index|ratio)\b|\bratio of\b", re.I
)

# What classify_modality asks of the prose. Each pattern is narrow on purpose: a
# pattern that over- or under-matches changes a published count, and every one of
# these was widened or narrowed against the 38,335 assays of the Mtb whole-cell papers.
#
# In-vivo efficacy needs all of an animal, a bacterial readout and the organism, and
# no cell culture. "Toxicity in BALB/c mouse" is an animal without a readout, a mouse
# PK curve is ADME, and a mouse macrophage infected with Mtb names an animal, a CFU
# and the organism without being an animal study. `_CULTURE` carries unambiguous culture
# words only: a bare "cells" would exclude a real study that counts "lung cells". The readout
# takes the plural organ ("CFU in lungs") and the spelled-out "colony forming units", which
# a trailing `\b` after `lung` and a bare `cfu` both missed; `RAW264.7` has no space and
# BMDM is the usual abbreviation for a bone-marrow macrophage culture.
_ANIMAL = re.compile(
    r"\b(mice|mouse|murine|guinea[- ]pigs?|marmosets?|rabbits?|rats?|hamsters?|macaques?"
    r"|monkeys?|zebrafish)\b",
    re.I,
)
_BACTERIAL_READOUT = re.compile(
    r"\b(cfu|colony[- ]forming units?|lungs?|spleens?|bacterial load|burden|survival)\b", re.I
)
_CULTURE = re.compile(
    r"macrophage|intracellular|monolayer|thp-?1|j774|raw ?264|bmdm|bone marrow", re.I
)
# ADME. An AUC arrives as AUC, AUC0-24, AUC (0 to 24 hrs), AUClast, AUCinfinity or fAUC, so
# a trailing word boundary alone misses most of them. A CYP isoform is a family digit and a
# subfamily letter (CYP3A4, CYP2D6, CYP2C19), CYP450, or a bare CYP; *M. tuberculosis*' own
# P450s (CYP51, CYP121, CYP125) have no subfamily letter and are binding assays on a
# purified protein, which is not ADME. `_NOT_ADME` removes two shapes that name a
# pharmacokinetic word without being host ADME: the hollow-fibre in-vitro PK/PD model,
# and bacterial clearance inside a macrophage.
_ADME = re.compile(
    r"pharmacokinetic|\bf?auc(?:last|inf|(?![a-z]))|cmax|half[- ]life|\bt1/2\b|bioavailab|"
    r"clearance|microsom|hepatocyte|solubility|permeab|caco|plasma protein|"
    r"metabolic stability|\bcyp(?:[1-4][a-z]|450|\b)",
    re.I,
)
_NOT_ADME = re.compile(r"hollow.fib|macrophage", re.I)
_CYTOTOX = re.compile(r"cytotox|\bcc50\b|cell viability|\bvero\b|hepg2", re.I)
_MTB = re.compile(r"tubercul", re.I)


def is_derived(description: str | None) -> bool:
    """Whether this assay reports a ratio of two other assays' numbers."""
    return bool(description and _DERIVED.search(description))


def classify_modality(
    description: str | None, target_type: str | None, organism: str | None
) -> str:
    """What this assay measured, from its own target record and its prose.

    Explicit prose beats target typing, and the order below is the whole rule:

    1. An `ORGANISM` target on a mycobacterium other than *M. tuberculosis* is
       `other_pathogen` before any prose is read, since "cytotoxicity" or
       "antitubercular" there describes an NTM study. BCG and *M. bovis* are in the
       M. tuberculosis complex, and ChEMBL names them "Mycobacterium tuberculosis variant ...".
    2. An animal, a bacterial readout and the organism, and no cell culture, is
       `in_vivo_efficacy`. The target is not consulted: ChEMBL files a mouse infection
       study against the *mouse*, so an organism-first rule would lose these studies.
    3. Cytotoxicity prose is `mammalian_cytotox` even on an `ADMET` target, which is how
       ChEMBL types a few hundred cytotoxicity assays.
    4. ADME prose or an `ADMET` target is `adme`. ChEMBL files animal pharmacokinetics
       against the *animal* as an `ORGANISM` target, so an organism-first rule here
       would relabel every one of them `other_pathogen`.
    5. A `CELL-LINE` target with none of that is mammalian. It comes after ADME because
       the endpoint wins over the cell line it ran in: Caco-2 permeability is ADME.
    6. Then the *M. tuberculosis* target types, then any other organism, then `other`.
    """
    text = description or ""
    organism = organism or ""
    is_mtb = organism.startswith("Mycobacterium tuberculosis")
    # "Myco", not "Mycobact": the renamed M. smegmatis is Mycolicibacterium, which
    # contains no "Mycobact" and would slip past the narrower prefix.
    if target_type == "ORGANISM" and organism.startswith("Myco") and not is_mtb:
        return "other_pathogen"
    if (
        _ANIMAL.search(text)
        and _BACTERIAL_READOUT.search(text)
        and _MTB.search(text)
        and not _CULTURE.search(text)
    ):
        return "in_vivo_efficacy"
    if _CYTOTOX.search(text):
        return "mammalian_cytotox"
    if (target_type == "ADMET" or _ADME.search(text)) and not _NOT_ADME.search(text):
        return "adme"
    if target_type == "CELL-LINE":
        return "mammalian_cytotox"
    if is_mtb:
        if target_type == "ORGANISM":
            return "phenotypic_mtb"
        if target_type in ("SINGLE PROTEIN", "PROTEIN COMPLEX", "PROTEIN FAMILY"):
            return "biochemical_mtb"
    if target_type == "ORGANISM":
        return "other_pathogen"
    return "other"


# PubChem states the stage; ChEMBL leaves it in the prose. `primary` is what an assay
# is when nothing names another stage -- the function takes no organism, so it is the
# fallback for any description, not only an Mtb one. A paper's MIC table is the first
# time its compounds met the organism.
_COUNTER = re.compile(r"counter[- ]?screen|selectivity against", re.I)
# qHTS is deliberately absent: NCGC's qHTS is a *primary* screen that runs a full
# concentration-response curve across the whole library, so reading it as confirmatory
# is backwards. It matched 0 of 38,335 ChEMBL descriptions and 0 of 124 PubChem titles.
_CONFIRM = re.compile(r"dose[- ]?response|confirmat|retest|titration", re.I)
# What a profiling assay measures is already decided by `classify_modality`, so the
# stage is read from that rather than from a second list of words that has to be edited
# in step with the first.
_PROFILING = ("mammalian_cytotox", "adme", "in_vivo_efficacy")


def classify_stage(
    description: str | None, *, pubchem_type: str | None = None, modality: str | None = None
) -> str:
    """Where in the funnel this assay sits.

    `pubchem_type` wins when it is `Confirmatory` or `Screening`, the two values PubChem
    uses for a stage. Any other value, such as `Summary` or `Other`, falls through.
    Then, in order: counter-screen prose; a cytotoxicity, ADME or in-vivo `modality`,
    which is `profiling` by definition; confirmation prose; else `primary`. Profiling
    comes before confirmation because a cytotoxicity dose-response is still profiling.

    Pass the `modality` you have already computed from the target record. Without one it
    is read from the description alone, which cannot see an `ADMET` or `CELL-LINE` target.
    """
    if pubchem_type:
        stated = pubchem_type.strip().lower()
        if stated == "confirmatory":
            return "confirmatory"
        if stated == "screening":
            return "primary"
    text = description or ""
    if _COUNTER.search(text):
        return "counter_screen"
    if (modality or classify_modality(text, None, None)) in _PROFILING:
        return "profiling"
    if _CONFIRM.search(text):
        return "confirmatory"
    return "primary"


# --- campaigns: the document, and every assay in it --------------------------
#
# A campaign's cytotoxicity, microsome and animal assays are filed against
# CELL-LINE, ADMET and non-molecular targets, so a target-keyed query cannot
# see them: these documents hold 11,686 assays on Mtb targets and 38,335 in
# total. The document is therefore the unit of the second fetch.
#
# Only publications are campaigns here. ChEMBL also files whole-cell activity
# under DATASET documents, which are deposited screening libraries rather than
# papers: CHEMBL3988442 (Dundee's Small-Polar-MMV library) alone holds 1,413,047
# activity rows, a 1,414-page walk that would also make one deposit's non-Mtb
# assays most of `screen_results`. Of the 977 documents behind whole-cell
# activity, 972 are publications, 4 are datasets and 1 is a patent. Nothing is
# lost by the filter: a campaign with a PubChem AID is ingested from PubChem,
# and that deposit is there as AIDs 1671154-1671185.

CAMPAIGN_ASSAY_FIELDS = (
    "assay_chembl_id,document_chembl_id,target_chembl_id,description,assay_strain"
)
CAMPAIGN_ACTIVITY_FIELDS = (
    "activity_id,assay_chembl_id,document_chembl_id,molecule_chembl_id,standard_type,"
    "standard_relation,standard_value,standard_units,pchembl_value,activity_comment"
)
CAMPAIGN_DOC_FIELDS = "document_chembl_id,doc_type,year,title,pubmed_id"
# Ten documents per request, not fifty: an activity query pages at PAGE rows, so a
# smaller batch bounds how deep any one request has to walk.
DOC_BATCH = 10


def campaign_documents(activities: Iterable[Mapping[str, Any]]) -> list[str]:
    """The candidate campaigns: documents that reported whole-cell Mtb activity.

    A paper that measured growth inhibition is the unit a screening record is
    organised by, and whatever else it measured on the same compounds is its hit
    profiling. These are candidates only: `campaign_publications` keeps the papers,
    once `campaign_document_meta` has said which they are. Sorted and unique, so
    that the batches built from this list are the same on every build.

    Not every document ChEMBL has whole-cell Mtb data for: the rows come from
    `activities`, whose whole-cell half is pulled compound-first, for compounds that
    already have a protein-level pChEMBL value. Measured 2026-10-11, 977 documents
    arrive here of the 1,932 that have a whole-cell assay on CHEMBL360 or
    CHEMBL2111188; the 955 absent (954 publications) are in no campaign.
    """
    return sorted(
        {
            row["document_chembl_id"]
            for row in activities
            if row.get("evidence") == "whole_cell" and row.get("document_chembl_id")
        }
    )


def campaign_document_meta(documents: Sequence[str]) -> dict[str, dict[str, Any]]:
    """Type, year and title for each document. Not cached, like `campaign_targets`."""
    out: dict[str, dict[str, Any]] = {}
    urls = [
        f"{API}/document.json?document_chembl_id__in={batch}"
        f"&only={CAMPAIGN_DOC_FIELDS}&limit={ID_BATCH}"
        for batch in batches(list(documents))
    ]
    for payload in fetch_json_many(
        urls, workers=6, min_interval=0.1, label="chembl campaign documents"
    ).values():
        for document in payload["documents"]:
            out[document["document_chembl_id"]] = {
                "doc_type": document.get("doc_type"),
                "title": document.get("title"),
                "year": document.get("year"),
                "pubmed_id": str(document["pubmed_id"]) if document.get("pubmed_id") else None,
            }
    return out


def campaign_publications(
    documents: Sequence[str], meta: Mapping[str, Mapping[str, Any]]
) -> list[str]:
    """The candidates that are papers, in the order given.

    A candidate with no record is an error rather than a non-publication:
    `fetch_json_many` skips a batch that fails, and reading its documents as
    "not a paper" would drop their campaigns without a word.
    """
    missing = [d for d in documents if d not in meta]
    if missing:
        raise RuntimeError(
            f"no document record for {len(missing)} campaign candidates, first {missing[0]}: "
            "a metadata batch failed, and their type is unknown"
        )
    return [d for d in documents if meta[d].get("doc_type") == "PUBLICATION"]


def _batch_name(batch: Sequence[str], fields: str) -> str:
    """A cache name that follows what the batch holds, not where it sits in the list.

    The document list comes from live fetches and differs between builds, so a
    positional name would serve one batch's pages to another. The columns asked
    for are part of what a page holds, so they are part of the name.
    """
    return hashlib.sha1(f"{','.join(batch)}|{fields}".encode()).hexdigest()[:10]


def campaign_assays(documents: Sequence[str], *, force: bool = False) -> list[dict[str, Any]]:
    """Every assay in these documents, whatever it was run against."""
    rows: list[dict[str, Any]] = []
    for index in range(0, len(documents), DOC_BATCH):
        batch = documents[index : index + DOC_BATCH]
        rows += pages(
            "assay",
            f"document_chembl_id__in={','.join(batch)}&only={CAMPAIGN_ASSAY_FIELDS}",
            "assays",
            f"campaigns/assays-{_batch_name(batch, CAMPAIGN_ASSAY_FIELDS)}",
            force=force,
        )
    return rows


def campaign_activities(documents: Sequence[str], *, force: bool = False) -> list[dict[str, Any]]:
    """Every activity in these documents, which is the per-compound coverage."""
    rows: list[dict[str, Any]] = []
    for index in range(0, len(documents), DOC_BATCH):
        batch = documents[index : index + DOC_BATCH]
        rows += pages(
            "activity",
            f"document_chembl_id__in={','.join(batch)}&only={CAMPAIGN_ACTIVITY_FIELDS}",
            "activities",
            f"campaigns/activities-{_batch_name(batch, CAMPAIGN_ACTIVITY_FIELDS)}",
            force=force,
        )
    return rows


def campaign_targets(assays: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Target type and organism for every target these assays name. Not cached."""
    ids = sorted({a["target_chembl_id"] for a in assays if a.get("target_chembl_id")})
    out: dict[str, dict[str, Any]] = {}
    urls = [
        f"{API}/target.json?target_chembl_id__in={batch}"
        f"&only=target_chembl_id,target_type,organism&limit={ID_BATCH}"
        for batch in batches(ids)
    ]
    for payload in fetch_json_many(
        urls, workers=6, min_interval=0.1, label="chembl campaign targets"
    ).values():
        for target in payload["targets"]:
            out[target["target_chembl_id"]] = {
                "target_type": target.get("target_type"),
                "organism": target.get("organism"),
            }
    return out


def normalize_campaign_assays(
    assays: Iterable[Mapping[str, Any]], targets: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """One stage row per assay, with what it measured and where in the funnel."""
    rows = []
    for assay in assays:
        target = targets.get(assay.get("target_chembl_id") or "", {})
        description = assay.get("description")
        organism = target.get("organism")
        target_type = target.get("target_type")
        derived = is_derived(description)
        modality = "other" if derived else classify_modality(description, target_type, organism)
        rows.append(
            {
                "stage_id": f"chembl:{assay['assay_chembl_id']}",
                "screen_id": f"chembl:{assay['document_chembl_id']}",
                "assay_chembl_id": assay["assay_chembl_id"],
                "document_chembl_id": assay["document_chembl_id"],
                # modality travels with it: `classify_stage` derives `profiling`
                # from it, so that the two axes cannot drift apart. Passing the
                # description alone reintroduces the disagreement Task 3 fixed.
                # A derived index is a ratio of two other assays and holds no
                # position in a funnel, so its stage is NULL rather than `primary`.
                "stage": None if derived else classify_stage(description, modality=modality),
                "modality": modality,
                "description": description,
                "target_chembl_id": assay.get("target_chembl_id"),
                "target_type": target_type,
                "target_organism": organism,
                "derived": derived,
                # Only a whole-cell stage has a growth condition; purified
                # protein has no medium to speak of. Same rule as `activities`.
                "assay_condition": (
                    classify_condition(description) if modality == "phenotypic_mtb" else None
                ),
                "strain": assay.get("assay_strain"),
                # Filled by `stamp_stage_counts` once the activities are in
                # hand. Present here so both sources emit one key set for
                # `screen_stages` -- a column missing from half the rows types
                # as NULL for all of them.
                "n_tested": None,
                "n_active": None,
            }
        )
    return rows


def _tested(
    stages: Iterable[Mapping[str, Any]], activities: Iterable[Mapping[str, Any]]
) -> dict[str, set[str]]:
    """Stage id -> the compounds with an activity recorded in it, for the stages given.

    An activity in an assay that is not one of the stages is dropped: the document query
    can return assays the stage list does not hold, and they belong to no campaign here.
    """
    tested: dict[str, set[str]] = {stage["stage_id"]: set() for stage in stages}
    for row in activities:
        stage_id = f"chembl:{row.get('assay_chembl_id')}"
        if stage_id in tested and row.get("molecule_chembl_id"):
            tested[stage_id].add(row["molecule_chembl_id"])
    return tested


def unplaced(
    stages: Iterable[Mapping[str, Any]], activities: Iterable[Mapping[str, Any]]
) -> tuple[int, int]:
    """(activities in an assay that is not a stage, activities with no compound).

    Both are left out of the tables, so they are counted: if an assay page were lost, its
    activities would vanish and read as compounds that were never tested, which is the one
    reading this layer must not produce by accident.
    """
    known = {stage["stage_id"] for stage in stages}
    outside = nameless = 0
    for row in activities:
        if f"chembl:{row.get('assay_chembl_id')}" not in known:
            outside += 1
        elif not row.get("molecule_chembl_id"):
            nameless += 1
    return outside, nameless


def stamp_stage_counts(
    stages: Sequence[dict[str, Any]], activities: Iterable[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Fill each stage's `n_tested`. `n_active` stays None: ChEMBL states no calls.

    Left unset by `normalize_campaign_assays`, which has not seen the activities yet.
    A stage with no activity on record has tested no compound that ChEMBL knows of: 0.
    """
    tested = _tested(stages, activities)
    for stage in stages:
        stage["n_tested"] = len(tested[stage["stage_id"]])
    return list(stages)


def campaign_screens(
    stages: Sequence[Mapping[str, Any]],
    activities: Iterable[Mapping[str, Any]],
    documents: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """One campaign row per document.

    `outcome_stated` is false for every ChEMBL campaign: ChEMBL stores values, not
    activity calls, so `n_active` is NULL rather than 0 here. What exists is a count of
    compounds tested, which is a count of rows and not a claim about what worked, and
    all of them are `n_unspecified`: that is what keeps the four outcome counts summing
    to `n_tested` here, as on a PubChem campaign of one assay (and not on one of several:
    see `pubchem.campaign_row`).

    The key set is `pubchem.normalize_screens`'s, with the PubChem-only fields NULL or
    empty, so that the two fill one table. A document with no record raises: a missing
    one is a lost fetch, and a campaign with a guessed title and type is not a campaign.
    """
    tested = _tested(stages, activities)
    by_screen: dict[str, list[Mapping[str, Any]]] = {}
    for stage in stages:
        by_screen.setdefault(stage["screen_id"], []).append(stage)

    rows = []
    for screen_id, members in sorted(by_screen.items()):
        document_id = members[0]["document_chembl_id"]
        if document_id not in documents:
            raise KeyError(
                f"no document record for {document_id}, the document of {screen_id}: "
                "a metadata batch was lost, so its type and title are unknown"
            )
        document = documents[document_id]
        compounds = set().union(*(tested[stage["stage_id"]] for stage in members))
        rows.append(
            {
                "screen_id": screen_id,
                "aid": None,
                "title": document.get("title"),
                "depositor": "Scientific Literature",
                "deposit_kind": (document.get("doc_type") or "").lower() or None,
                "library_name": None,
                "library_size_stated": None,
                "year": document.get("year"),
                "n_stages": len(members),
                "n_tested": len(compounds),
                "n_active": None,
                "n_inactive": None,
                "n_inconclusive": None,
                "n_unspecified": len(compounds),
                "outcome_stated": False,
                # PubChem's `Method`, which ChEMBL has no equivalent of.
                "outcome_method": None,
                "stages_source": "from_prose",
                "project_declared": False,
                "modalities": sorted({stage["modality"] for stage in members}),
                "document_chembl_id": document_id,
                "pubmed_id": document.get("pubmed_id"),
                "targets": [],
                "licence": "CC BY-SA 3.0",
            }
        )
    return rows


def campaign_results(
    stages: Sequence[Mapping[str, Any]], activities: Iterable[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """One row per activity ChEMBL records in a campaign's assay.

    ChEMBL states no outcome, so `outcome` is NULL. The key set is
    `pubchem.normalize_results`'s, the PubChem columns empty, and a row is told from its
    neighbours by `activity_id`. `standard_value` is converted: the API sends a string.
    """
    stage_screen = {stage["stage_id"]: stage["screen_id"] for stage in stages}
    rows = []
    for row in activities:
        stage_id = f"chembl:{row.get('assay_chembl_id')}"
        if stage_id not in stage_screen or not row.get("molecule_chembl_id"):
            continue
        rows.append(
            {
                "stage_id": stage_id,
                "screen_id": stage_screen[stage_id],
                "pubchem_cid": None,
                "pubchem_sid": None,
                "molecule_chembl_id": row["molecule_chembl_id"],
                "outcome": None,
                "activity_score": None,
                "endpoint": row.get("standard_type"),
                "standard_value": _float(row.get("standard_value")),
                "standard_units": row.get("standard_units"),
                "standard_relation": row.get("standard_relation"),
                "result_tag": None,
                "activity_id": row.get("activity_id"),
                # ChEMBL's own comment on the activity, kept rather than dropped: "Not
                # Determined" is a measurement that failed, and it comes with no value.
                "activity_comment": row.get("activity_comment"),
            }
        )
    return rows


def build_campaigns(
    activities: Iterable[Mapping[str, Any]], *, retrieved_at: str, force: bool = False
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """The literature campaigns as (screens, stages, results), stamped as ChEMBL's.

    `activities` are rows with `evidence` and `document_chembl_id`; the documents that
    reported whole-cell activity are the candidates. Publications only, and the filter
    runs before any activity is fetched: a dataset can hold 1.4 million rows. The
    rest are PubChem's to bring in. The rows are stamped here, not by the table's
    writer, because `screens` is shared with PubChem and one stamp would be wrong for
    one of them.
    """
    candidates = campaign_documents(activities)
    meta = campaign_document_meta(candidates)
    documents = campaign_publications(candidates, meta)
    assays = campaign_assays(documents, force=force)
    acts = campaign_activities(documents, force=force)
    stages = stamp_stage_counts(normalize_campaign_assays(assays, campaign_targets(assays)), acts)
    outside, nameless = unplaced(stages, acts)
    print(
        f"  chembl campaigns: {len(documents)} of {len(candidates)} candidate documents are "
        f"publications ({len(candidates) - len(documents)} are datasets or patents), "
        f"{len(stages)} stages, {len(acts):,} activities; not carried: {outside:,} in assays "
        f"outside the campaigns, {nameless:,} with no compound",
        file=sys.stderr,
    )
    label = {"source": SOURCE, "source_version": release_from_api(), "retrieved_at": retrieved_at}
    return (
        list(stamp(campaign_screens(stages, acts, meta), **label)),
        list(stamp(stages, **label)),
        list(stamp(campaign_results(stages, acts), **label)),
    )


def annotate_activities(
    rows: Iterable[dict[str, Any]], compounds: Iterable[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Stamp `pmic`, `pmic_basis`, `assay_condition` and `resistant_panel` on each row.

    Needs the compounds for their molecular weights, so it runs after both
    pulls rather than inside `_activity_row`.
    """
    weights = {
        c["molecule_chembl_id"]: c.get("mw")
        for c in compounds
        if c.get("molecule_chembl_id") is not None
    }
    out = []
    for row in rows:
        value, basis = pmic(
            row.get("standard_type"),
            row.get("standard_relation"),
            row.get("standard_value"),
            row.get("standard_units"),
            weights.get(row.get("molecule_chembl_id")),
        )
        description = row.get("assay_description")
        out.append(
            row
            | {
                "pmic": value,
                "pmic_basis": basis,
                # Only whole-cell rows have a growth condition; a biochemical
                # assay on purified protein has no medium to speak of.
                "assay_condition": (
                    classify_condition(description) if row.get("evidence") == "whole_cell" else None
                ),
                "resistant_panel": bool(
                    row.get("evidence") == "whole_cell"
                    and description
                    and _RESISTANT_PANEL.search(description.lower())
                ),
            }
        )
    return out


def build_bioactivity(
    targets: Iterable[tuple[str, str]], *, retrieved_at: str, force: bool = False
) -> list[Path]:
    """Activities, compounds, and the unfiltered assay census."""
    targets = sorted(set(targets))
    version = release_from_api()

    rows = target_activities(targets)
    molecule_ids = sorted({r["molecule_chembl_id"] for r in rows if r["molecule_chembl_id"]})
    rows += whole_cell_activities(molecule_ids)
    compounds = molecules(molecule_ids)
    rows = annotate_activities(rows, compounds)

    sizes: list[dict[str, Any]] = []
    for target_id, _ in targets:
        sizes += aggregate_sizes(target_id, census_rows(target_id, force=force))

    return [
        write_parquet(
            "activities", rows, source=SOURCE, source_version=version, retrieved_at=retrieved_at
        ),
        write_parquet(
            "compounds", compounds, source=SOURCE, source_version=version, retrieved_at=retrieved_at
        ),
        write_parquet(
            "assay_sizes", sizes, source=SOURCE, source_version=version, retrieved_at=retrieved_at
        ),
    ]


# --- the assay census: how big was the assay, not how potent was the hit -----

# `activities` carries only rows with a pchembl_value, because that is the
# potency evidence. A primary screen reports percent inhibition and gets no
# pchembl, so counting assays or their compounds from that table measures the
# follow-ups and misses the campaign. ChEMBL files 276,472 of the 296,225
# activity rows on Mtb protein targets as `Percent Effect`, which carries no
# pchembl value. The census is the same query without the filter and with only
# the fields a count needs.
CENSUS_FIELDS = "assay_chembl_id,molecule_chembl_id,standard_type,document_year"


def census_rows(target_id: str, *, force: bool = False) -> list[dict[str, Any]]:
    """Every activity on one target, unfiltered, cached page by page."""
    return pages(
        "activity",
        f"target_chembl_id={target_id}&only={CENSUS_FIELDS}",
        "activities",
        f"census/{target_id}",
        force=force,
    )


def aggregate_sizes(target_id: str, rows: Iterable[Mapping[str, Any]]) -> Iterator[dict[str, Any]]:
    """One row per assay: distinct compounds, measurements, endpoints, latest year.

    Distinct compounds is the number that answers "is there a tractable screen
    here"; measurements is kept beside it because the two differing is normal
    and their ratio is the only hint that an assay was re-run.
    """
    by_assay: dict[str, dict[str, Any]] = {}
    for row in rows:
        assay = row.get("assay_chembl_id")
        if not assay:
            continue
        entry = by_assay.setdefault(
            assay, {"compounds": set(), "types": set(), "measurements": 0, "year": None}
        )
        entry["measurements"] += 1
        if molecule := row.get("molecule_chembl_id"):
            entry["compounds"].add(molecule)
        if endpoint := row.get("standard_type"):
            entry["types"].add(endpoint)
        year = row.get("document_year")
        if year is not None and (entry["year"] is None or year > entry["year"]):
            entry["year"] = year
    for assay, entry in sorted(by_assay.items()):
        yield {
            "target_chembl_id": target_id,
            "assay_chembl_id": assay,
            "n_compounds": len(entry["compounds"]),
            "n_measurements": entry["measurements"],
            "endpoint_types": sorted(entry["types"]),
            "latest_year": entry["year"],
        }


# --- TB drugs and clinical candidates ----------------------------------------

# A molecule is in the drug layer when ChEMBL records a tuberculosis indication
# for it: a MeSH heading containing "Tuberculosis" (plain, Pulmonary,
# Multidrug-Resistant, Meningeal in ChEMBL 37). "Mycobacterium Infections" and
# the MAC headings are broader than TB and stay out.
TB_INDICATIONS = "mesh_heading__icontains=tuberculosis"
DRUG_MOLECULE_FIELDS = (
    "molecule_chembl_id,pref_name,molecule_type,max_phase,first_approval,oral,"
    "atc_classifications,molecule_synonyms,molecule_hierarchy,molecule_properties,"
    "molecule_structures"
)


def batches(ids: Sequence[str]) -> list[str]:
    return [",".join(ids[i : i + ID_BATCH]) for i in range(0, len(ids), ID_BATCH)]


def pages(endpoint: str, query: str, key: str, dest: str, *, force: bool) -> list[dict[str, Any]]:
    """Every record of one ChEMBL list query, each page cached as `<dest>-<offset>.json`.

    Public because `precedent.py` walks the whole mechanism table the same way.
    """
    records: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = fetch(
            f"{API}/{endpoint}.json?{query}&limit={PAGE}&offset={offset}",
            f"{dest}-{offset}.json",
            source=SOURCE,
            force=force,
            json_body=True,
        )
        payload = json.loads(page.text)
        records += payload[key]
        offset += PAGE
        if offset >= payload["page_meta"]["total_count"]:
            return records


def fetch_drugs(*, force: bool = False) -> tuple[dict[str, list[dict[str, Any]]], Fetched]:
    """The raw ChEMBL records behind the drug layer, plus the cached release status.

    Indications first, because they define the molecule set; then molecules and
    mechanisms for every molecule an indication names (salts as well as
    parents); then the targets those mechanisms point at, for their organism
    and component accessions.
    """
    status = fetch(
        f"{API}/status.json", "drugs/status.json", source=SOURCE, force=force, json_body=True
    )
    indications = pages(
        "drug_indication", TB_INDICATIONS, "drug_indications", "drugs/indications", force=force
    )
    ids = sorted(
        {i["molecule_chembl_id"] for i in indications}
        | {i["parent_molecule_chembl_id"] for i in indications}
    )
    molecules: list[dict[str, Any]] = []
    mechanisms: list[dict[str, Any]] = []
    for n, batch in enumerate(batches(ids)):
        molecules += pages(
            "molecule",
            f"molecule_chembl_id__in={batch}&only={DRUG_MOLECULE_FIELDS}",
            "molecules",
            f"drugs/molecules-{n}",
            force=force,
        )
        mechanisms += pages(
            "mechanism",
            f"molecule_chembl_id__in={batch}",
            "mechanisms",
            f"drugs/mechanisms-{n}",
            force=force,
        )
    target_ids = sorted({m["target_chembl_id"] for m in mechanisms if m["target_chembl_id"]})
    targets: list[dict[str, Any]] = []
    for n, batch in enumerate(batches(target_ids)):
        targets += pages(
            "target", f"target_chembl_id__in={batch}", "targets", f"drugs/targets-{n}", force=force
        )
    payloads = {
        "indications": indications,
        "molecules": molecules,
        "mechanisms": mechanisms,
        "targets": targets,
    }
    return payloads, status


# Taxonomy ids, never organism strings (see the module docstring of orthologue.py):
# M. tuberculosis, H37Rv, CDC1551 and H37Ra are all filed as Mtb targets.
MTB_TAXA = frozenset({1773, 83332, 83331, 419947})
HUMAN = 9606


def normalize_drugs(
    payloads: dict[str, list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(drugs, drug_mechanisms): one drug row per parent molecule, salts folded in.

    `max_phase_tb` comes from the TB indications alone. `max_phase` is ChEMBL's
    phase for any indication, kept beside it because linezolid -- approved, and
    phase 3 for TB -- is exactly the confusion a single phase column invites.
    """
    targets = {t["target_chembl_id"]: t for t in payloads["targets"]}
    parent_of = {
        m["molecule_chembl_id"]: (m.get("molecule_hierarchy") or {}).get("parent_chembl_id")
        or m["molecule_chembl_id"]
        for m in payloads["molecules"]
    }
    for indication in payloads["indications"]:
        parent_of[indication["molecule_chembl_id"]] = indication["parent_molecule_chembl_id"]

    mechanisms: dict[tuple, dict[str, Any]] = {}
    for record in payloads["mechanisms"]:
        parent = record.get("parent_molecule_chembl_id") or parent_of.get(
            record["molecule_chembl_id"], record["molecule_chembl_id"]
        )
        target = targets.get(record.get("target_chembl_id")) or {}
        row = {
            "molecule_chembl_id": parent,
            "mechanism_of_action": record.get("mechanism_of_action"),
            "action_type": record.get("action_type"),
            # Where ChEMBL says a prodrug needs activating, and by what (EthA).
            "mechanism_comment": record.get("mechanism_comment"),
            "direct_interaction": bool(record.get("direct_interaction")),
            "disease_efficacy": bool(record.get("disease_efficacy")),
            "target_chembl_id": record.get("target_chembl_id"),
            "target_name": target.get("pref_name"),
            "target_type": target.get("target_type"),
            "target_organism": target.get("organism"),
            "target_tax_id": target.get("tax_id"),
            "component_accessions": [
                c["accession"] for c in target.get("target_components") or [] if c.get("accession")
            ],
            "refs": [
                {"type": r.get("ref_type"), "id": r.get("ref_id"), "url": r.get("ref_url")}
                for r in record.get("mechanism_refs") or []
            ],
        }
        mechanisms[(parent, row["target_chembl_id"], row["mechanism_of_action"])] = row

    by_parent: dict[str, list[dict[str, Any]]] = {}
    for indication in payloads["indications"]:
        by_parent.setdefault(indication["parent_molecule_chembl_id"], []).append(indication)
    molecules = {m["molecule_chembl_id"]: m for m in payloads["molecules"]}

    drugs = []
    for parent, indications in sorted(by_parent.items()):
        forms = [m for mid, m in molecules.items() if parent_of.get(mid) == parent]
        names = {
            name
            for form in forms
            for name in [
                form.get("pref_name"),
                *(s["molecule_synonym"] for s in form.get("molecule_synonyms") or []),
            ]
            if name
        }
        refs = [r for i in indications for r in i.get("indication_refs") or []]
        acting = [m for m in mechanisms.values() if m["molecule_chembl_id"] == parent]
        molecule = molecules.get(parent) or {"molecule_chembl_id": parent}
        drugs.append(
            {
                **_compound_row(molecule),
                "max_phase": _float(molecule.get("max_phase")),
                "max_phase_tb": max(
                    (
                        p
                        for i in indications
                        if (p := _float(i.get("max_phase_for_ind"))) is not None
                    ),
                    default=None,
                ),
                "synonyms": sorted(names),
                "salt_chembl_ids": sorted(
                    mid for mid, p in parent_of.items() if p == parent and mid != parent
                ),
                "tb_indications": sorted({i["mesh_heading"] for i in indications}),
                "atc_codes": sorted(molecule.get("atc_classifications") or []),
                "oral": molecule.get("oral"),
                # ChEMBL packs every trial behind an indication into one ref,
                # comma-separated.
                "nct_ids": sorted(
                    {
                        nct.strip()
                        for r in refs
                        if r["ref_type"] == "ClinicalTrials"
                        for nct in r["ref_id"].split(",")
                        if nct.strip()
                    }
                ),
                # Labels and approvals: DailyMed, FDA, EMA, ATC.
                "label_refs": [
                    {"type": t, "id": i, "url": u}
                    for t, i, u in sorted(
                        {
                            (r["ref_type"], r["ref_id"], r.get("ref_url"))
                            for r in refs
                            if r["ref_type"] != "ClinicalTrials"
                        }
                    )
                ],
                "mechanisms_of_action": sorted(
                    {m["mechanism_of_action"] for m in acting if m["mechanism_of_action"]}
                ),
                "target_organisms": sorted(
                    {m["target_organism"] for m in acting if m["target_organism"]}
                ),
                "acts_on_mtb": any(m["target_tax_id"] in MTB_TAXA for m in acting),
                "host_targeted": any(m["target_tax_id"] == HUMAN for m in acting),
            }
        )
    return drugs, list(mechanisms.values())


def build_drugs(*, force: bool = False) -> list[Path]:
    payloads, status = fetch_drugs(force=force)
    drugs, mechanisms = normalize_drugs(payloads)
    state = json.loads(status.text)
    version = f"{state['chembl_db_version']} ({state['chembl_release_date']})"
    return [
        write_parquet(
            name, rows, source=SOURCE, source_version=version, retrieved_at=status.retrieved_at
        )
        for name, rows in (("drugs", drugs), ("drug_mechanisms", mechanisms))
    ]
