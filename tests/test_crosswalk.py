"""The crosswalk's failure modes, one test per class of disagreement.

Every case here is a real locus taken from the live sources, not an invented one:
if upstream changes its mind about any of them, a fixture refresh will say so.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas import crosswalk, orthologue
from atlas.sources import mycobrowser, uniprot
from atlas.store import read

from .conftest import FIXTURES


def by_rv(store: Path) -> dict[str, dict]:
    """crosswalk.parquet as dicts, keyed by Rv tag."""
    relation = read("crosswalk", store=store)
    columns = relation.columns
    return {
        row[columns.index("rv_id")]: dict(zip(columns, row, strict=True))
        for row in relation.fetchall()
    }


@pytest.fixture(scope="session")
def walk(store: Path) -> dict[str, dict]:
    """The crosswalk built without the network, for the many read-only assertions."""
    crosswalk.build(store=store, with_orthologues=False)
    return by_rv(store)


# --- locus tag parsing -------------------------------------------------------


@pytest.mark.parametrize(
    ("gene_oln", "expected"),
    [
        ("Rv3790", ["Rv3790"]),
        ("Rv0206c", ["Rv0206c"]),
        ("Rv0846c RVBD_0846c", ["Rv0846c"]),  # RVBD_ alias is not an Rv tag
        ("Rv1180/Rv1181", ["Rv1180", "Rv1181"]),
        ("Rv2880c/Rv2879c", ["Rv2880c", "Rv2879c"]),
        ("Rv3423.1", ["Rv3423.1"]),
        ("Rv1706c.1", ["Rv1706c.1"]),
        ("Rv2922.1c", ["Rv2922.1c"]),
        ("Rv0236A", ["Rv0236A"]),
        ("Rv0795; Rv1370c; Rv3474", ["Rv0795", "Rv1370c", "Rv3474"]),
        ("", []),
    ],
)
def test_rv_tags(gene_oln: str, expected: list[str]) -> None:
    assert uniprot.rv_tags(gene_oln) == expected


def test_rv_tags_deduplicates() -> None:
    assert uniprot.rv_tags("Rv0796; Rv0796") == ["Rv0796"]


# --- the gene universe -------------------------------------------------------


def test_universe_is_cds_only() -> None:
    """A locus tag re-used by a regulatory feature must not become a gene.

    Rv0148 appears in the fixture only as a `promoter` row; Mycobrowser also
    emits promoter and -10/-35_signal rows under genes' own locus tags, which
    would otherwise duplicate those loci.
    """
    genes = list(mycobrowser.normalize(FIXTURES / "mycobrowser_h37rv.txt"))
    assert "Rv0148" not in {g["rv_id"] for g in genes}
    assert len({g["rv_id"] for g in genes}) == len(genes), "a locus appears twice"


def test_gene_fields_are_typed() -> None:
    genes = {g["rv_id"]: g for g in mycobrowser.normalize(FIXTURES / "mycobrowser_h37rv.txt")}
    dpre1 = genes["Rv3790"]
    assert dpre1["gene_name"] == "dprE1"
    assert (dpre1["start"], dpre1["stop"], dpre1["strand"]) == (4235779, 4237164, "+")
    assert dpre1["functional_category"] == "lipid metabolism"
    assert dpre1["is_pseudogene"] is False
    assert genes["Rv2099c"]["is_pseudogene"] is True
    assert genes["Rv1484"]["resistance_drugs"] == ["ETH", "INH"]
    # Mycobrowser states no licence, and its curated prose is the part of it most
    # plainly copyrightable; the Function the atlas shows is UniProt's.
    assert "function" not in dpre1


# --- accession resolution ----------------------------------------------------


def test_reference_targets_resolve(walk: dict[str, dict]) -> None:
    """The three targets this project is validated against, end to end."""
    assert walk["Rv3790"]["uniprot_acc"] == "P9WJF1"
    assert walk["Rv1484"]["uniprot_acc"] == "P9WGR1"
    assert walk["Rv0206c"]["uniprot_acc"] == "P9WJV5"
    for rv_id in ("Rv3790", "Rv1484", "Rv0206c"):
        assert walk[rv_id]["acc_status"] == crosswalk.AGREE
        assert walk[rv_id]["conflict"] is False
        assert walk[rv_id]["alphafold_id"] is not None
    assert walk["Rv1484"]["n_pdb"] > walk["Rv3790"]["n_pdb"] > walk["Rv0206c"]["n_pdb"] > 0


def test_accession_disagreement_prefers_uniprot(walk: dict[str, dict]) -> None:
    """Mycobrowser says P0A644 for Rv2879c; the reference proteome says P9WH15.

    UniProt wins, but Mycobrowser's claim is kept rather than dropped, so a
    target page can show both.
    """
    row = walk["Rv2879c"]
    assert row["uniprot_acc"] == "P9WH15"
    assert row["mycobrowser_uniprot_ac"] == "P0A644"
    assert row["acc_status"] == crosswalk.DISAGREEMENT
    assert row["conflict"] is True


def test_mycobrowser_only_accession_is_accepted(walk: dict[str, dict]) -> None:
    """L7N683 is in the proteome but carries no Rv tag, so only Mycobrowser links it."""
    row = walk["Rv2307D"]
    assert row["uniprot_acc"] == "L7N683"
    assert row["acc_status"] == crosswalk.MYCOBROWSER_ONLY
    assert row["conflict"] is False


def test_accession_outside_proteome_is_a_conflict(walk: dict[str, dict]) -> None:
    """Rv2099c's Q79FH7 is not in UP000001584 -- likely withdrawn upstream."""
    row = walk["Rv2099c"]
    assert row["uniprot_acc"] is None
    assert row["mycobrowser_uniprot_ac"] == "Q79FH7"
    assert row["acc_status"] == crosswalk.ACC_NOT_IN_PROTEOME
    assert row["conflict"] is True


def test_unmapped_gene_is_a_conflict(walk: dict[str, dict]) -> None:
    row = walk["Rv0947c"]
    assert (row["uniprot_acc"], row["mycobrowser_uniprot_ac"]) == (None, None)
    assert row["acc_status"] == crosswalk.NO_ACCESSION
    assert row["conflict"] is True


# --- many-to-one accessions --------------------------------------------------


def test_shared_accession_is_flagged_both_ways(walk: dict[str, dict]) -> None:
    """Rv1180 and Rv1181 share A0A089QRB9.

    Without the flag each locus would claim the other's structures and ligands
    as its own.
    """
    assert walk["Rv1180"]["uniprot_acc"] == walk["Rv1181"]["uniprot_acc"] == "A0A089QRB9"
    assert walk["Rv1180"]["shared_accession"] is True
    assert walk["Rv1180"]["shares_accession_with"] == ["Rv1181"]
    assert walk["Rv1181"]["shares_accession_with"] == ["Rv1180"]


def test_unshared_accession_is_not_flagged(walk: dict[str, dict]) -> None:
    assert walk["Rv3790"]["shared_accession"] is False
    assert walk["Rv3790"]["shares_accession_with"] == []


def test_transposase_shares_across_many_loci(walk: dict[str, dict]) -> None:
    """P9WKH9 (IS6110 transposase) covers 16 loci; the fixture holds two of them."""
    assert walk["Rv0796"]["uniprot_acc"] == walk["Rv1369c"]["uniprot_acc"] == "P9WKH9"
    assert walk["Rv0796"]["shared_accession"] is True
    assert walk["Rv0796"]["shares_accession_with"] == ["Rv1369c"]
    # A neighbouring locus shares a *different* transposase accession; the two
    # groups must not bleed into each other.
    assert walk["Rv0795"]["shares_accession_with"] == ["Rv1370c"]


# --- ChEMBL targets ----------------------------------------------------------


def test_direct_chembl_target(walk: dict[str, dict]) -> None:
    targets = walk["Rv3790"]["chembl_targets"]
    assert [t["target_id"] for t in targets] == ["CHEMBL3804751"]
    assert targets[0]["evidence"] == "direct"
    assert targets[0]["target_type"] == "SINGLE PROTEIN"
    assert walk["Rv3790"]["chembl_evidence"] == "direct"


def test_chembl_target_missing_from_uniprot_xrefs_is_still_found(walk: dict[str, dict]) -> None:
    """Rv2266 (cyp124) has a ChEMBL target that UniProt's xrefs do not mention.

    The crosswalk unions UniProt's cross-references with ChEMBL's own mapping
    file, so neither source's omission loses a target.
    """
    assert [t["target_id"] for t in walk["Rv2266"]["chembl_targets"]] == ["CHEMBL6195688"]


def test_gene_without_chembl_target_reports_nothing(walk: dict[str, dict]) -> None:
    """Honest zero: this is what drives 'essential, has a structure, no ligands'."""
    assert walk["Rv0206c"]["chembl_targets"] == []
    assert walk["Rv0206c"]["n_chembl_targets"] == 0
    assert walk["Rv0206c"]["chembl_evidence"] is None


# --- the orthologue bridge ---------------------------------------------------


def test_orthologue_bridge_gives_mmpl3_its_ligands(store: Path, monkeypatch) -> None:
    """MmpL3's inhibitors are assayed against the M. smegmatis orthologue.

    The link is stubbed here (the real one needs UniRef); what is under test is
    that it reaches Rv0206c and arrives labelled, with the identity level and
    source organism attached rather than passed off as direct evidence.
    """
    link = orthologue.Link(
        mtb_acc="P9WJV5",
        chembl_target_id="CHEMBL5465372",
        via_accession="A0QP27",
        via_organism="Mycolicibacterium smegmatis (strain ATCC 700084 / mc(2)155)",
        via_gene="mmpL3",
        uniref_cluster="UniRef50_A0QP27",
        identity_level="0.5",
        cluster_size=611,
    )
    monkeypatch.setattr(orthologue, "build_links", lambda _accessions: [link])
    crosswalk.build(store=store, with_orthologues=True)

    row = by_rv(store)["Rv0206c"]
    (target,) = row["chembl_targets"]
    assert target["target_id"] == "CHEMBL5465372"
    assert target["evidence"] == "orthologue"
    assert target["identity_level"] == "0.5"
    assert target["via_organism"].startswith("Mycolicibacterium smegmatis")
    assert row["chembl_evidence"] == "orthologue"


def test_direct_evidence_beats_orthologue(store: Path, monkeypatch) -> None:
    """A gene with its own Mtb target must not be diluted by orthologue guesses."""
    link = orthologue.Link(
        mtb_acc="P9WJF1",
        chembl_target_id="CHEMBL5465372",
        via_accession="A0QP27",
        via_organism="Mycolicibacterium smegmatis",
        via_gene="mmpL3",
        uniref_cluster="UniRef50_A0QP27",
        identity_level="0.5",
        cluster_size=611,
    )
    monkeypatch.setattr(orthologue, "build_links", lambda _accessions: [link])
    crosswalk.build(store=store, with_orthologues=True)

    assert [t["evidence"] for t in by_rv(store)["Rv3790"]["chembl_targets"]] == ["direct"]


# --- provenance and idempotence ---------------------------------------------


def test_every_record_carries_provenance(store: Path) -> None:
    for name in ("genes", "proteins", "chembl_targets", "crosswalk"):
        relation = read(name, store=store)
        assert {"source", "source_version", "retrieved_at"} <= set(relation.columns), name
        row = dict(zip(relation.columns, relation.fetchone(), strict=True))
        assert row["source"] and row["source_version"] and row["retrieved_at"]


def test_crosswalk_names_the_versions_it_was_built_from(store: Path) -> None:
    crosswalk.build(store=store, with_orthologues=False)
    relation = read("crosswalk", store=store)
    version = dict(zip(relation.columns, relation.fetchone(), strict=True))["source_version"]
    assert "genes=release 5" in version
    assert "proteins=2026_03" in version
    assert "chembl_targets=chembl_" in version


def test_rebuilding_is_idempotent(store: Path) -> None:
    """Re-running the pipeline over unchanged inputs must not change the store."""
    first = crosswalk.build(store=store, with_orthologues=False).read_bytes()
    second = crosswalk.build(store=store, with_orthologues=False).read_bytes()
    assert first == second
