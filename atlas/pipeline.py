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

import json
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from . import clinical, crosswalk, summary
from .sources import (
    alphafold,
    chembl,
    chemreps,
    clinicaltrials,
    conditional,
    essentiality,
    genome,
    homology,
    mtbtndb,
    mycobrowser,
    orthologue_structures,
    paralogs,
    pdb,
    precedent,
    pubchem,
    resistance,
    string_db,
    unichem,
    uniprot,
    vulnerability,
)
from .store import provenance, read

IDENTITY = (mycobrowser, uniprot, chembl, genome)


def _say(message: str) -> None:
    print(message, file=sys.stderr)


# Runs `<module>.build(**kwargs)` and prints the path or paths it wrote as JSON, last.
_STAGE = (
    "import json, sys; from importlib import import_module; "
    "out = import_module(sys.argv[1]).build(**json.loads(sys.argv[2])); "
    "print(json.dumps([str(p) for p in out] if isinstance(out, list) else str(out)))"
)


def _isolated(module: str, **kwargs: Any) -> Path | list[Path]:
    """Run one stage's `build` in a fresh interpreter and return the path(s) it wrote.

    The phmmer stages take 1-3 GB each on every core, and that memory is not handed back
    when a stage ends, so in one process they stacked: the build peaked at 5.75 GB
    (2026-10-12) where the largest stage alone takes 2.83 GB. A process per stage returns
    it all on exit. A plain `python -c`, not multiprocessing: `spawn` re-imports the
    calling script, so a caller without a `__main__` guard ran the whole build again in
    every child. This imports the stage's own module and nothing else.
    """
    result = subprocess.run(
        [sys.executable, "-c", _STAGE, module, json.dumps(kwargs)],
        stdout=subprocess.PIPE,  # the stage's progress goes to stderr, which passes through
        text=True,
        check=True,
    )
    out = json.loads(result.stdout.strip().splitlines()[-1])
    return [Path(p) for p in out] if isinstance(out, list) else Path(out)


def build_identity(*, force: bool = False) -> list[Path]:
    paths = []
    for source in IDENTITY:
        _say(f"[identity] {source.SOURCE}")
        paths.append(source.build(force=force))
    paths.append(mycobrowser.build_regulatory(force=force))
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
    # The Pfam domains this proteome carries, which is the key set for the drug
    # precedent bridge the way the accessions are for the structures.
    domains = sorted(
        {
            domain
            for (ids,) in read("proteins").project("pfam_ids").fetchall()
            for domain in ids or []
        }
    )
    _, retrieved_at = provenance("crosswalk")
    retrieved_at = str(retrieved_at)
    _say(
        f"[evidence] {len(accessions)} accessions, {len(predicted)} predicted models, "
        f"{len(targets)} ChEMBL targets, {len(domains)} Pfam domains"
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
    paths += chembl.build_bioactivity(targets, retrieved_at=retrieved_at, force=force)
    _say("[evidence] essentiality (DeJesus 2017)")
    paths.append(essentiality.build(force=force))
    _say("[evidence] resistance (WHO catalogue)")
    paths.append(resistance.build(force=force))
    _say("[evidence] conditional fitness (Griffin 2011, cholesterol)")
    paths.append(conditional.build(force=force))
    _say("[evidence] conditional TnSeq, 136 screens (MtbTnDB)")
    # 1 GB of parsed TRANSIT output that a shared process would keep.
    paths += _isolated(mtbtndb.__name__, force=force)
    _say("[evidence] vulnerability (Bosch 2021 CRISPRi, H37Rv)")
    paths.append(vulnerability.build(force=force))
    _say("[evidence] vulnerability in a clinical strain (Bosch 2021, HN878)")
    paths.append(vulnerability.build_strain(force=force))
    _say("[evidence] interactions (STRING)")
    paths.append(string_db.build(force=force))
    _say("[evidence] human homology (phmmer vs human proteome)")
    paths.append(_isolated(homology.__name__, retrieved_at=retrieved_at, force=force))
    _say("[evidence] paralogs (phmmer vs the Mtb proteome itself)")
    paths.append(_isolated(paralogs.__name__, retrieved_at=retrieved_at, force=force))
    _say("[evidence] orthologue structures (mycobacterial neighbours with a PDB entry)")
    paths.append(_isolated(orthologue_structures.__name__, retrieved_at=retrieved_at, force=force))
    _say("[evidence] screening campaigns (ChEMBL literature, PubChem depositions)")
    rv_by_acc = defaultdict(list)
    for accession, rv_id in walk.project("uniprot_acc, rv_id").fetchall():
        if accession:
            rv_by_acc[accession].append(rv_id)
    # Publications only, and the filter runs inside `build_campaigns` before any activity
    # is fetched. Of the datasets and patents among them, only Dundee's reaches the store
    # (through PubChem); GSK's TB set, the Malaria Box, the Pathogen Box and a patent do not.
    whole_cell = [
        {"evidence": "whole_cell", "document_chembl_id": document}
        for (document,) in read("activities")
        .filter("evidence = 'whole_cell'")
        .project("document_chembl_id")
        .distinct()
        .fetchall()
    ]
    screens, stages, results = chembl.build_campaigns(
        whole_cell, retrieved_at=retrieved_at, force=force
    )
    paths += pubchem.build(
        retrieved_at=retrieved_at,
        bridge=unichem.fetch_raw(force=force).path,
        rv_by_acc=rv_by_acc,
        extra_screens=screens,
        extra_stages=stages,
        extra_results=results,
        force=force,
    )
    # Every ChEMBL id the store references, so that `compound_structures` can say of each
    # one whether it was found; an id outside this set has no row, which means not looked up.
    wanted = {
        molecule
        for table in ("screen_results", "compounds")
        for (molecule,) in read(table)
        .filter("molecule_chembl_id IS NOT NULL")
        .project("molecule_chembl_id")
        .distinct()
        .fetchall()
    }
    _say(f"[evidence] structures for {len(wanted):,} compounds (ChEMBL chemreps)")
    paths.append(chemreps.build(wanted, force=force))
    _say(f"[evidence] drug precedent for {len(domains)} Pfam domains (ChEMBL mechanisms)")
    paths.append(precedent.build(domains, retrieved_at=retrieved_at, force=force))
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
