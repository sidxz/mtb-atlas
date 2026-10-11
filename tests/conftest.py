"""A fixture store built from committed files. No test touches the network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atlas import clinical, crosswalk, summary
from atlas.sources import (
    alphafold,
    chembl,
    clinicaltrials,
    conditional,
    essentiality,
    mtbtndb,
    mycobrowser,
    pdb,
    resistance,
    uniprot,
    vulnerability,
)
from atlas.store import read, stamp, write_parquet, write_stamped

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def store(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The identity stage: three source tables plus the crosswalk they join into."""
    out = tmp_path_factory.mktemp("store")
    write_parquet(
        "genes",
        mycobrowser.normalize(FIXTURES / "mycobrowser_h37rv.txt"),
        source=mycobrowser.SOURCE,
        source_version="release 5 (2024-07-11)",
        retrieved_at="2026-10-09",
        store=out,
    )
    write_parquet(
        "proteins",
        uniprot.normalize(FIXTURES / "uniprot_proteome.tsv"),
        source=uniprot.SOURCE,
        source_version="2026_03 02-September-2026",
        retrieved_at="2026-10-09",
        store=out,
    )
    write_parquet(
        "chembl_targets",
        chembl.normalize(FIXTURES / "chembl_uniprot_mapping.txt"),
        source=chembl.SOURCE,
        source_version=chembl.release(FIXTURES / "chembl_uniprot_mapping.txt"),
        retrieved_at="2026-10-09",
        store=out,
    )
    crosswalk.build(store=out, with_orthologues=False)
    return out


@pytest.fixture(scope="session")
def evidence_store(store: Path) -> Path:
    """The identity store plus every evidence and clinical table, all from fixtures.

    Built once so the summary roll-up can be tested end to end: the whole-cell
    attribution rule, the structural-gap definition and the drug link levels
    are the parts most likely to drift, and they only exist once the tables
    are joined.
    """
    entries = json.loads((FIXTURES / "rcsb_entries.json").read_text())
    accessions = {
        row[0] for row in read("crosswalk", store=store).project("uniprot_acc").fetchall() if row[0]
    }
    write_parquet(
        "structures",
        pdb.normalize(iter(entries), accessions),
        source=pdb.SOURCE,
        source_version="RCSB fixture",
        retrieved_at="2026-10-09",
        store=store,
    )
    write_parquet(
        "ligands",
        pdb.normalize_chem_comps(json.loads((FIXTURES / "rcsb_chem_comps.json").read_text())),
        source=pdb.SOURCE,
        source_version="RCSB chemical components fixture",
        retrieved_at="2026-10-09",
        store=store,
    )
    write_parquet(
        "predicted_structures",
        alphafold.normalize(json.loads((FIXTURES / "alphafold_predictions.json").read_text())),
        source=alphafold.SOURCE,
        source_version="AlphaFold DB v6",
        retrieved_at="2026-10-09",
        store=store,
    )
    bioactivity = json.loads((FIXTURES / "chembl_bioactivity.json").read_text())
    # Three potency rows on the ClpP1P2 screen, as the live assay has (7 of them,
    # beside its 68,611 percent-inhibition measurements). They give the complex
    # target an assay description, which is what `protein_assay_example` would
    # wrongly offer for a gene that has no assay of its own. The compounds are
    # reused from dprE1's rows; none has a whole-cell measurement.
    bioactivity["activities"] += [
        {
            "activity_id": 9000001 + i,
            "molecule_chembl_id": molecule,
            "target_chembl_id": "CHEMBL4662931",
            "target_organism": "Mycobacterium tuberculosis (strain ATCC 25618 / H37Rv)",
            "evidence": "direct",
            "standard_type": "IC50",
            "standard_relation": "=",
            "standard_value": 1000.0,
            "standard_units": "nM",
            "pchembl_value": 6.0,
            "assay_chembl_id": "CHEMBL4649972",
            "assay_type": "B",
            "assay_description": (
                "in vitro assay to detect presence of AMC directly proportional to the "
                "activity of ClpP1P2.  GHDDI collaboration."
            ),
            "document_chembl_id": "CHEMBL3988442",
            "document_year": 2021,
            "data_validity_comment": None,
            "potential_duplicate": False,
        }
        for i, molecule in enumerate(("CHEMBL4439876", "CHEMBL4453252", "CHEMBL5180878"))
    ]
    write_parquet(
        "activities",
        chembl.annotate_activities(bioactivity["activities"], bioactivity["compounds"]),
        source=chembl.SOURCE,
        source_version="chembl_37",
        retrieved_at="2026-10-09",
        store=store,
    )
    write_parquet(
        "compounds",
        bioactivity["compounds"],
        source=chembl.SOURCE,
        source_version="chembl_37",
        retrieved_at="2026-10-09",
        store=store,
    )
    # The census is derived from the same rows, through the ingester's own
    # aggregation, so the fixture store cannot claim a gene has activities but
    # no assays. Grouped per target, which is how `census_rows` fetches.
    by_target: dict[str, list[dict]] = {}
    for activity in bioactivity["activities"]:
        by_target.setdefault(activity["target_chembl_id"], []).append(activity)
    sizes = [
        row
        for target_id, target_rows in sorted(by_target.items())
        for row in chembl.aggregate_sizes(target_id, target_rows)
    ]
    # Two cases the live store has and this fixture otherwise cannot show.
    # First, a primary screen: it reports percent inhibition, so the census
    # counts it and `activities` (potency rows only) never held it. Without
    # this row nothing distinguishes the census from the potency rows.
    # (The screen filed against the ClpP1P2 complex needs no row here: its
    # three potency rows above already put 3 compounds in the census.)
    # Second, a screen on a target whose type is unknown: CHEMBL5629 reaches
    # Rv3545c only through UniProt's cross-reference, so the crosswalk has no
    # `target_type` for it. It must be shown as not-a-single-protein, never lost.
    sizes += [
        {
            "target_chembl_id": "CHEMBL3804751",
            "assay_chembl_id": "CHEMBL9000001",
            "n_compounds": 5,
            "n_measurements": 5,
            "endpoint_types": ["Percent Effect"],
            "latest_year": 2021,
        },
        {
            "target_chembl_id": "CHEMBL5629",
            "assay_chembl_id": "CHEMBL9000002",
            "n_compounds": 4,
            "n_measurements": 4,
            "endpoint_types": ["Percent Effect"],
            "latest_year": 2021,
        },
    ]
    write_parquet(
        "assay_sizes",
        sizes,
        source=chembl.SOURCE,
        source_version="chembl_37",
        retrieved_at="2026-10-09",
        store=store,
    )
    # The screening layer, through the ingesters' own functions so that the key set cannot
    # drift from the real tables'. The assay ids (CHEMBL91xxxxx) and documents are
    # synthetic; the targets are the fixture genes' own.
    assays = [
        {
            "assay_chembl_id": assay_id,
            "document_chembl_id": document,
            "target_chembl_id": target,
            "description": description,
            "assay_strain": None,
        }
        for assay_id, document, target, description in (
            # A stage on a single protein: dprE1.
            (
                "CHEMBL9100001",
                "CHEMBL_DOC1",
                "CHEMBL3804751",
                "Inhibition of Mycobacterium tuberculosis DprE1",
            ),
            # A second stage of the same campaign on the same protein: a screen is one
            # campaign, however many of its stages reached the gene.
            (
                "CHEMBL9100006",
                "CHEMBL_DOC1",
                "CHEMBL3804751",
                "Confirmation of DprE1 inhibition in a dose-response assay",
            ),
            # A stage on a complex that the crosswalk maps to both subunits.
            (
                "CHEMBL9100002",
                "CHEMBL_DOC1",
                "CHEMBL4662931",
                "Inhibition of Mycobacterium tuberculosis ClpP1P2 protease",
            ),
            # A stage on a target whose type was not looked up (see `targets` below).
            (
                "CHEMBL9100003",
                "CHEMBL_DOC2",
                "CHEMBL5629",
                "Inhibition of Mycobacterium tuberculosis CYP125",
            ),
            # A screen of the *M. smegmatis* MmpL3, which the crosswalk reaches Rv0206c
            # through only when the orthologue bridge is on (it is off in this store).
            (
                "CHEMBL9100007",
                "CHEMBL_DOC2",
                "CHEMBL5465372",
                "Inhibition of Mycobacterium smegmatis MmpL3",
            ),
            # A computed ratio, which `normalize_campaign_assays` calls derived and stageless.
            (
                "CHEMBL9100004",
                "CHEMBL_DOC1",
                None,
                "Selectivity index, ratio of CC50 for Vero cells to MIC for "
                "Mycobacterium tuberculosis H37Rv",
            ),
            # Prose no classifier pattern has seen: modality `other`, stage the default.
            ("CHEMBL9100005", "CHEMBL_DOC2", None, "Assay of a kind no pattern here has seen"),
        )
    ]
    stage_targets = {
        "CHEMBL3804751": {
            "target_type": "SINGLE PROTEIN",
            "organism": "Mycobacterium tuberculosis",
        },
        "CHEMBL4662931": {
            "target_type": "PROTEIN COMPLEX",
            "organism": "Mycobacterium tuberculosis",
        },
        "CHEMBL5465372": {
            "target_type": "SINGLE PROTEIN",
            "organism": "Mycolicibacterium smegmatis (strain ATCC 700084 / mc(2)155)",
        },
    }
    tested = {
        "CHEMBL9100001": 4,
        "CHEMBL9100002": 3,
        "CHEMBL9100003": 4,
        "CHEMBL9100006": 2,
        "CHEMBL9100007": 2,
    }
    stage_activities = [
        {"assay_chembl_id": assay_id, "molecule_chembl_id": f"CHEMBL_M{i}"}
        for assay_id, n in tested.items()
        for i in range(n)
    ]
    chembl_stages = chembl.stamp_stage_counts(
        chembl.normalize_campaign_assays(assays, stage_targets), stage_activities
    )
    documents = {
        document: {"doc_type": "PUBLICATION", "title": "A paper", "year": year, "pubmed_id": None}
        for document, year in (("CHEMBL_DOC1", 2021), ("CHEMBL_DOC2", 2019))
    }
    chembl_screens = chembl.campaign_screens(chembl_stages, stage_activities, documents)
    chembl_label = {
        "source": chembl.SOURCE,
        "source_version": "ChEMBL_37 (2026-05-01)",
        "retrieved_at": "2026-10-09",
    }
    write_stamped("screens", stamp(chembl_screens, **chembl_label), store=store)
    write_stamped("screen_stages", stamp(chembl_stages, **chembl_label), store=store)
    write_parquet(
        "essentiality",
        essentiality.normalize(FIXTURES / "dejesus_supplement.zip"),
        source=essentiality.SOURCE,
        source_version=essentiality.CITATION,
        retrieved_at="2026-10-09",
        store=store,
    )
    write_parquet(
        "conditional_fitness",
        conditional.normalize(FIXTURES / "griffin_supplement.zip"),
        source=conditional.SOURCE,
        source_version=conditional.CITATION,
        retrieved_at="2026-10-09",
        store=store,
    )
    tnseq_archive = FIXTURES / "mtbtndb_transit_outputs.tar.gz"
    write_parquet(
        "conditional_tnseq",
        mtbtndb.normalize(tnseq_archive),
        source=mtbtndb.SOURCE,
        source_version=mtbtndb.SOURCE_VERSION,
        retrieved_at="2026-10-10",
        store=store,
    )
    write_parquet(
        "tnseq_screens",
        mtbtndb.screens(tnseq_archive, mtbtndb.annotation(FIXTURES / "mtbtndb_col_desc.tsv")),
        source=mtbtndb.SOURCE,
        source_version=mtbtndb.SOURCE_VERSION,
        retrieved_at="2026-10-10",
        store=store,
    )
    write_parquet(
        "resistance",
        resistance.normalize(FIXTURES / "who_catalogue.txt"),
        source=resistance.SOURCE,
        source_version=resistance.EDITION,
        retrieved_at="2026-10-09",
        store=store,
    )
    # The clinical-strain sheet is a real slice of the published workbook, so
    # the roll-up's HN878 columns are tested against the numbers in the paper.
    # Only three of its loci are in this gene universe; the rest of the
    # universe is how the roll-up's "never measured in HN878" state is proved.
    write_parquet(
        "strain_vulnerability",
        vulnerability.normalize_strain(FIXTURES / "bosch_vulnerability.xlsx"),
        source=vulnerability.SOURCE,
        source_version=vulnerability.STRAIN_CITATION,
        retrieved_at="2026-10-09",
        store=store,
    )
    extra = json.loads((FIXTURES / "extra_evidence.json").read_text())
    for name, source, version in (
        ("vulnerability", "bosch-2021", "Bosch 2021 Table S3"),
        ("interactions", "string-db", "STRING v12.5"),
        ("homology", "phmmer-human", "phmmer vs reviewed human proteome"),
        ("paralogs", "phmmer-paralog", "phmmer vs the Mtb proteome itself"),
        (
            "orthologue_structures",
            "orthologue-pdb",
            "phmmer vs Mycobacteriaceae with a PDB entry; structures from RCSB",
        ),
        # Real ChEMBL mechanism rows for the fixture loci's own Pfam domains,
        # chosen so every reading of them is covered: inhA's fold carries both
        # its own two approved drugs and the FabI inhibitors from three other
        # organisms, while atpE and rpoB/rpoC carry bedaquiline and the
        # rifamycins against a COMPLEX, which must never be counted.
        ("drug_precedent", "chembl", "ChEMBL_37 (2026-05-01)"),
    ):
        write_parquet(
            name,
            extra[name],
            source=source,
            source_version=version,
            retrieved_at="2026-10-09",
            store=store,
        )

    drug_rows, mechanism_rows = chembl.normalize_drugs(
        json.loads((FIXTURES / "chembl_drugs.json").read_text())
    )
    for name, rows in (("drugs", drug_rows), ("drug_mechanisms", mechanism_rows)):
        write_parquet(
            name,
            rows,
            source=chembl.SOURCE,
            source_version="chembl_37",
            retrieved_at="2026-10-10",
            store=store,
        )
    studies = json.loads((FIXTURES / "clinicaltrials_studies.json").read_text())
    write_parquet(
        "trials",
        clinicaltrials.normalize(studies["studies"]),
        source=clinicaltrials.SOURCE,
        source_version=clinicaltrials.version(studies["version"]),
        retrieved_at="2026-10-10",
        store=store,
    )
    clinical.build(store=store)
    summary.build(store=store)
    return store
