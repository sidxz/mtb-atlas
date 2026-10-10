"""The build, in two stages.

Identity first, evidence second. The crosswalk has to exist before the evidence
ingesters run, because PDB, AlphaFold and ChEMBL are keyed on UniProt accession
or ChEMBL target id rather than on the Rv tag, and the crosswalk is what maps
those back to a gene. An evidence ingester may therefore read the crosswalk for
its key set; it must never read another source's raw cache.
"""

from __future__ import annotations

import sys
from pathlib import Path

from . import crosswalk, summary
from .sources import (
    alphafold,
    chembl,
    essentiality,
    homology,
    mycobrowser,
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
    _say("[evidence] predicted structures (AlphaFold)")
    paths.append(alphafold.build(predicted, retrieved_at=retrieved_at, force=force))
    _say("[evidence] bioactivity (ChEMBL)")
    paths += chembl.build_bioactivity(targets, retrieved_at=retrieved_at)
    _say("[evidence] essentiality (DeJesus 2017)")
    paths.append(essentiality.build(force=force))
    _say("[evidence] resistance (WHO catalogue)")
    paths.append(resistance.build(force=force))
    _say("[evidence] vulnerability (Bosch 2021 CRISPRi)")
    paths.append(vulnerability.build(force=force))
    _say("[evidence] interactions (STRING)")
    paths.append(string_db.build(force=force))
    _say("[evidence] human homology (phmmer vs human proteome)")
    paths.append(homology.build(retrieved_at=retrieved_at, force=force))
    _say("[summary] target_summary")
    paths.append(summary.build())
    return paths


def build_all(*, force: bool = False) -> list[Path]:
    return build_identity(force=force) + build_evidence(force=force)
