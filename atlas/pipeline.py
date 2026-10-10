"""The build, in three stages and a roll-up.

Identity first, evidence second, clinical third. The crosswalk has to exist
before the evidence ingesters run, because PDB, AlphaFold and ChEMBL are keyed
on UniProt accession or ChEMBL target id rather than on the Rv tag, and the
crosswalk is what maps those back to a gene. An evidence ingester may therefore
read the crosswalk for its key set; it must never read another source's raw
cache.

The clinical stage comes last because its links reach genes through the
crosswalk, Bosch 2021 and the WHO catalogue, all of which must already be in
the store. The per-gene summary rolls up everything, so it runs once at the end.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from . import clinical, crosswalk, summary
from .sources import (
    alphafold,
    chembl,
    clinicaltrials,
    conditional,
    essentiality,
    homology,
    mtbtndb,
    mycobrowser,
    paralogs,
    pdb,
    resistance,
    string_db,
    uniprot,
    vulnerability,
)
from .store import provenance, read

IDENTITY = (mycobrowser, uniprot, chembl)


def _say(message: str) -> None:
    print(message, file=sys.stderr)


def build_identity(*, force: bool = False) -> list[Path]:
    paths = []
    for source in IDENTITY:
        _say(f"[identity] {source.SOURCE}")
        paths.append(source.build(force=force))
    _say("[identity] crosswalk")
    paths.append(crosswalk.build())
    return paths


def build_evidence(*, force: bool = False) -> list[Path]:
    walk = read("crosswalk")
    accessions = sorted({row[0] for row in walk.project("uniprot_acc").fetchall() if row[0]})
    predicted = sorted(
        {
            row[0]
            for row in walk.filter("alphafold_id IS NOT NULL").project("alphafold_id").fetchall()
        }
    )
    targets = sorted(
        {
            (target["target_id"], target["evidence"])
            for (chembl_targets,) in walk.project("chembl_targets").fetchall()
            for target in chembl_targets or []
        }
    )
    _, retrieved_at = provenance("crosswalk")
    retrieved_at = str(retrieved_at)
    _say(
        f"[evidence] {len(accessions)} accessions, {len(predicted)} predicted models, "
        f"{len(targets)} ChEMBL targets"
    )

    paths = []
    _say("[evidence] structures (RCSB PDB)")
    paths.append(pdb.build(accessions, retrieved_at=retrieved_at, force=force))
    _say("[evidence] ligand identity (RCSB chemical components)")
    paths.append(
        pdb.build_ligands(
            sorted(
                {
                    row[0]
                    for row in read("structures")
                    .project("unnest(list_concat(ligand_ids, ligand_ids_elsewhere))")
                    .fetchall()
                }
            ),
            retrieved_at=retrieved_at,
        )
    )
    _say("[evidence] predicted structures (AlphaFold)")
    paths.append(alphafold.build(predicted, retrieved_at=retrieved_at, force=force))
    _say("[evidence] bioactivity (ChEMBL)")
    paths += chembl.build_bioactivity(targets, retrieved_at=retrieved_at)
    _say("[evidence] essentiality (DeJesus 2017)")
    paths.append(essentiality.build(force=force))
    _say("[evidence] resistance (WHO catalogue)")
    paths.append(resistance.build(force=force))
    _say("[evidence] conditional fitness (Griffin 2011, cholesterol)")
    paths.append(conditional.build(force=force))
    _say("[evidence] conditional TnSeq, 136 screens (MtbTnDB)")
    paths += mtbtndb.build(force=force)
    _say("[evidence] vulnerability (Bosch 2021 CRISPRi, H37Rv)")
    paths.append(vulnerability.build(force=force))
    _say("[evidence] vulnerability in a clinical strain (Bosch 2021, HN878)")
    paths.append(vulnerability.build_strain(force=force))
    _say("[evidence] interactions (STRING)")
    paths.append(string_db.build(force=force))
    _say("[evidence] human homology (phmmer vs human proteome)")
    paths.append(homology.build(retrieved_at=retrieved_at, force=force))
    _say("[evidence] paralogs (phmmer vs the Mtb proteome itself)")
    paths.append(paralogs.build(retrieved_at=retrieved_at, force=force))
    return paths


def build_clinical(*, force: bool = False) -> list[Path]:
    _say("[clinical] TB drugs, indications and mechanisms (ChEMBL)")
    paths = chembl.build_drugs(force=force)
    _say("[clinical] interventional TB trials (ClinicalTrials.gov)")
    paths.append(clinicaltrials.build(force=force))
    _say("[clinical] drug -> gene and trial -> drug links")
    paths += clinical.build()
    return paths


def relink_clinical() -> list[Path]:
    """Re-join drugs and trials onto whatever the store now holds.

    The links reach genes through the crosswalk, Bosch 2021 and the WHO
    catalogue, so an evidence rebuild leaves them stale. This touches no
    upstream service; where the clinical stage has never run, there is nothing
    to re-join and the roll-up reports the layer as unbuilt.
    """
    if not all(summary.built(name) for name in ("drugs", "trials", "ligands")):
        _say("[clinical] not built in this store; skipping the re-link")
        return []
    _say("[clinical] re-linking drugs and trials to the rebuilt evidence")
    return clinical.build()


def build_summary() -> Path:
    _say("[summary] target_summary")
    return summary.build()


def build_all(*, force: bool = False) -> list[Path]:
    return [
        *build_identity(force=force),
        *build_evidence(force=force),
        *build_clinical(force=force),
        build_summary(),
    ]


STAGE_RUNNERS = {
    "identity": build_identity,
    "evidence": build_evidence,
    "clinical": build_clinical,
}


def snapshot() -> Path | None:
    """Copy the store aside so `atlas diff` has something to compare against.

    A rebuild overwrites in place, so without this the previous numbers are
    gone the moment the new ones land and nobody can say what moved.
    """
    from .store import STORE

    if not STORE.exists():
        return None
    previous = STORE.parent / "store.prev"
    shutil.rmtree(previous, ignore_errors=True)
    shutil.copytree(STORE, previous)
    _say(f"[refresh] previous store copied to {previous.name} for `atlas diff`")
    return previous


def refresh(source: str, *, force: bool = True) -> list[Path]:
    """Re-download one source and rebuild only what depends on it.

    `force` here drops that source's raw cache rather than setting the global
    re-download flag, because the flag is per run and this is per source:
    everything else stays warm, so refreshing ClinicalTrials.gov does not
    re-fetch ChEMBL's thousands of molecules.

    The stages run from the source's own stage to the end. A source cannot
    change an earlier stage's input, and the roll-up always runs last.
    """
    from .fetch import RAW
    from .freshness import BY_NAME, stages_from

    if source not in BY_NAME:
        raise KeyError(f"{source} is not a source; try one of {', '.join(sorted(BY_NAME))}")
    snapshot()
    cache = RAW / source
    if force and cache.exists():
        _say(f"[refresh] dropping the raw cache for {source}")
        shutil.rmtree(cache)

    stages = stages_from(source)
    _say(f"[refresh] {source} -> {' -> '.join(stages)}")
    paths: list[Path] = []
    for stage in stages:
        if stage == "summary":
            paths.append(build_summary())
        else:
            paths += STAGE_RUNNERS[stage](force=False)
        # An evidence rebuild moves the genes the clinical links point at.
        if stage == "evidence" and "clinical" not in stages:
            paths += relink_clinical()
    return paths
