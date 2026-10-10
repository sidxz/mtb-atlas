"""The evidence ingesters, against committed slices of the real files.

Each case is something the live APIs actually do: a homodimer listing one
polymer entity per chain, a supplementary table whose header is on row two, a
catalogue where most "resistance" is not a residue change at all.
"""

from __future__ import annotations

import json

import pytest

from atlas.sources import alphafold, essentiality, pdb, resistance, uniprot

from .conftest import FIXTURES

# --- RCSB PDB ----------------------------------------------------------------


@pytest.fixture(scope="session")
def entries() -> list[dict]:
    return json.loads((FIXTURES / "rcsb_entries.json").read_text())


@pytest.fixture(scope="session")
def structures(entries: list[dict]) -> dict[tuple[str, str], dict]:
    accessions = {"P9WJF1", "P9WGR1", "P9WJV5", "P9WIE5"}
    rows = list(pdb.normalize(iter(entries), accessions))
    return {(r["pdb_id"], r["uniprot_acc"]): r for r in rows}


@pytest.mark.parametrize(
    ("comp_id", "role"),
    [
        ("1W6", "ligand"),  # a real benzothiazinone inhibitor
        ("ZID", "ligand"),
        ("FAD", "cofactor"),
        ("HEM", "cofactor"),
        ("NAD", "cofactor"),
        ("GOL", "incidental"),  # cryoprotectant
        ("IMD", "incidental"),  # buffer
        ("HOH", "incidental"),
        ("SO4", "incidental"),
    ],
)
def test_component_roles(comp_id: str, role: str) -> None:
    """A glycerol is not chemical matter and a cofactor is not a lead."""
    assert pdb.classify(comp_id) == role


def test_structure_metadata(structures: dict) -> None:
    dpre1 = structures[("4KW5", "P9WJF1")]
    assert dpre1["method"] == "X-RAY DIFFRACTION"
    assert dpre1["resolution"] == pytest.approx(2.612, abs=0.01)
    assert dpre1["released"] == "2013-07-10"


def test_ligands_exclude_additives(structures: dict) -> None:
    """4KW5 carries 1W6, FAD, GOL and IMD; only one of those is a ligand.

    `rcsb_entry_info.nonpolymer_bound_components` is null for this entry, which
    is why components are read off the nonpolymer entities instead.
    """
    dpre1 = structures[("4KW5", "P9WJF1")]
    assert dpre1["ligand_ids"] == ["1W6"]
    assert dpre1["n_ligands"] == 1
    roles = {c["comp_id"]: c["role"] for c in dpre1["components"]}
    assert roles == {"IMD": "incidental", "GOL": "incidental", "1W6": "ligand", "FAD": "cofactor"}


def test_a_ligand_on_another_subunits_chain_is_not_this_proteins(entries: list[dict]) -> None:
    """5UHB is the RNA polymerase holoenzyme: rifampicin is modelled on chain C, rpoB.

    Every subunit of a complex shares the entry's component list, so without
    checking chains rpoC would report rifampicin as a ligand of its own.
    """
    rows = {r["uniprot_acc"]: r for r in pdb.normalize(iter(entries), {"P9WGY9", "P9WGY7"})}
    rpob, rpoc = rows["P9WGY9"], rows["P9WGY7"]
    assert rpob["ligand_ids"] == ["RFP"]
    assert rpob["n_ligands"] == 1
    assert rpoc["ligand_ids"] == []
    assert rpoc["n_ligands"] == 0
    # Shown, not counted: the entry does hold it, bound to a neighbour.
    assert rpoc["ligand_ids_elsewhere"] == ["RFP"]


def test_components_say_which_chain_they_sit_on(entries: list[dict]) -> None:
    rows = {r["uniprot_acc"]: r for r in pdb.normalize(iter(entries), {"P9WGY9", "P9WGY7"})}
    roles = {c["comp_id"]: c["on_chain"] for c in rows["P9WGY7"]["components"]}
    assert roles == {"RFP": False, "ZN": True, "MG": True}  # the metals are on chain D, rpoC


def test_a_ligand_on_this_proteins_chain_still_counts(structures: dict) -> None:
    """4KW5: TCA1 is modelled on chains A and B, which are DprE1's own."""
    dpre1 = structures[("4KW5", "P9WJF1")]
    assert dpre1["ligand_ids"] == ["1W6"]
    assert dpre1["ligand_ids_elsewhere"] == []


def test_one_row_per_entry_and_accession(entries: list[dict], structures: dict) -> None:
    """A homodimer lists a polymer entity per chain group; the entry belongs once.

    Without this, KatG's 8W1X appeared twice in the viewer's structure picker.
    """
    rows = list(pdb.normalize(iter(entries), {"P9WJF1", "P9WGR1", "P9WJV5", "P9WIE5"}))
    assert len(rows) == len({(r["pdb_id"], r["uniprot_acc"]) for r in rows})
    assert ("2CCA", "P9WIE5") in structures


def test_unknown_accessions_are_dropped(entries: list[dict]) -> None:
    assert list(pdb.normalize(iter(entries), {"NOTANACCESSION"})) == []


# --- AlphaFold ---------------------------------------------------------------


@pytest.fixture(scope="session")
def predictions() -> dict[str, dict]:
    payloads = json.loads((FIXTURES / "alphafold_predictions.json").read_text())
    return {r["uniprot_acc"]: r for r in alphafold.normalize(payloads)}


def test_prediction_fields(predictions: dict) -> None:
    mmpl3 = predictions["P9WJV5"]
    assert mmpl3["entry_id"] == "AF-P9WJV5-F1"
    assert mmpl3["plddt_mean"] == pytest.approx(79.31, abs=0.5)
    assert mmpl3["cif_url"].endswith(".cif")


def test_confidence_bands_are_kept_separately(predictions: dict) -> None:
    """A membrane transporter's mean hides a disordered fifth; the bands do not."""
    mmpl3 = predictions["P9WJV5"]
    total = sum(
        mmpl3[k] for k in ("plddt_very_high", "plddt_confident", "plddt_low", "plddt_very_low")
    )
    assert total == pytest.approx(1.0, abs=0.02)
    assert mmpl3["plddt_very_low"] > 0.1
    assert predictions["P9WGR1"]["plddt_very_low"] < 0.05


def test_empty_payload_is_skipped() -> None:
    assert list(alphafold.normalize({"https://x/api/prediction/NOPE": []})) == []


# --- essentiality ------------------------------------------------------------


@pytest.fixture(scope="session")
def calls() -> dict[str, dict]:
    rows = essentiality.normalize(FIXTURES / "dejesus_supplement.zip")
    return {r["rv_id"]: r for r in rows}


def test_reads_past_the_caption_row(calls: dict) -> None:
    """Row 1 of Table S3 is a title; the header is row 2."""
    assert calls["Rv3790"]["call"] == "ES"
    assert calls["Rv3790"]["ta_sites"] == 28


def test_essential_excludes_growth_defect(calls: dict) -> None:
    """`essential` must not quietly mean "any fitness cost" -- that is 135 extra genes."""
    assert calls["Rv1484"]["essential"] is True  # ES
    assert calls["Rv0206c"]["essential"] is True  # ESD: part of MmpL3 is essential
    assert calls["Rv1908c"]["essential"] is False  # NE: katG activates a prodrug
    for row in calls.values():
        if row["essential"]:
            assert row["fitness_cost"] is True


def test_call_labels_are_spelled_out(calls: dict) -> None:
    assert calls["Rv0206c"]["call_label"] == "Essential domain"


def test_condition_is_recorded(calls: dict) -> None:
    """One in vitro condition. The store keys on (rv_id, source) for this reason."""
    assert calls["Rv3790"]["condition"] == "in vitro, 7H9 broth"
    assert "DeJesus" in calls["Rv3790"]["citation"]


# --- resistance --------------------------------------------------------------


@pytest.fixture(scope="session")
def variants() -> list[dict]:
    return list(resistance.normalize(FIXTURES / "who_catalogue.txt"))


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("p.Ser315Thr", (315, "S315T")),
        ("p.Trp328Leu", (328, "W328L")),
        ("p.Ser94Ala", (94, "S94A")),
        ("c.-777C>T", (None, None)),  # promoter
        ("p.Leu203fs", (None, None)),  # frameshift
        ("p.Trp191Ter", (None, None)),  # the 3-letter stop is not a substitution
        ("", (None, None)),
    ],
)
def test_residue_parsing(mutation: str, expected: tuple) -> None:
    assert resistance.residue(mutation) == expected


def test_associated_excludes_uncertain(variants: list[dict]) -> None:
    """Gradings 3-5 are uncertain or not-associated and must not count."""
    gradings = {v["grading"] for v in variants if v["associated"]}
    assert gradings <= set(resistance.ASSOCIATED)
    assert any(not v["associated"] for v in variants), "fixture should hold uncertain rows too"


def test_most_resistance_is_not_a_residue_change(variants: list[dict]) -> None:
    """The headline finding: a structure cannot show most of a gene's resistance.

    Promoter variants, frameshifts and stop codons are real resistance and have
    no residue to draw, so they are kept and marked rather than dropped.
    """
    associated = [v for v in variants if v["associated"]]
    mappable = [v for v in associated if v["residue_position"] is not None]
    assert 0 < len(mappable) < len(associated)
    unmappable_effects = {v["effect"] for v in associated if v["residue_position"] is None}
    assert "upstream_gene_variant" in unmappable_effects


def test_rna_gene_variants_survive(variants: list[dict]) -> None:
    """rrs is why the gene universe includes RNA genes at all."""
    rrs = [v for v in variants if v["gene"] == "rrs" and v["associated"]]
    assert rrs
    assert all(v["residue_position"] is None for v in rrs)


# --- UniProt protein context -----------------------------------------------------


@pytest.fixture(scope="session")
def proteins() -> dict[str, dict]:
    rows = uniprot.normalize(FIXTURES / "uniprot_proteome.tsv")
    return {r["uniprot_acc"]: r for r in rows}


def test_curated_text_loses_its_evidence_codes(proteins: dict) -> None:
    """UniProt prefixes each comment and tags it with {ECO:...} codes; a page wants prose."""
    function = proteins["P9WJF1"]["function"]
    assert function.startswith("Component of the DprE1-DprE2 complex")
    assert "{ECO" not in function
    assert "FUNCTION:" not in function


def test_membrane_topology_is_counted(proteins: dict) -> None:
    assert proteins["P9WJV5"]["n_transmembrane"] == 12  # MmpL3, a 12-helix RND transporter
    assert proteins["P9WJF1"]["n_transmembrane"] == 0
    assert "Cell inner membrane" in proteins["P9WJV5"]["locations"]
    assert proteins["P9WJF1"]["locations"] == ["Periplasm"]


def test_pathway_and_catalysis(proteins: dict) -> None:
    inha = proteins["P9WGR1"]
    assert inha["pathways"] == ["Lipid metabolism; mycolic acid biosynthesis"]
    assert "RHEA:10240" in inha["rhea_ids"]
    assert any("NADH" in reaction for reaction in inha["reactions"])
    assert "mycolic acid biosynthetic process" in inha["go_process"]


def test_disruption_phenotype_and_references(proteins: dict) -> None:
    assert "essential" in proteins["P9WJF1"]["disruption_phenotype"]
    assert proteins["P9WGR1"]["n_references"] == len(proteins["P9WGR1"]["pubmed_ids"]) > 20


def test_absent_comments_are_none_not_empty_strings(proteins: dict) -> None:
    """An entry UniProt says nothing about must read as an absence, not as blank text."""
    for row in proteins.values():
        for key in ("function", "disruption_phenotype", "subcellular_location"):
            assert row[key] is None or row[key].strip()


# --- ligand identity ---------------------------------------------------------


@pytest.fixture(scope="session")
def ligands() -> dict[str, dict]:
    comps = json.loads((FIXTURES / "rcsb_chem_comps.json").read_text())
    return {r["comp_id"]: r for r in pdb.normalize_chem_comps(comps)}


def test_a_ligand_carries_the_keys_that_find_it_elsewhere(ligands: dict) -> None:
    tca1 = ligands["1W6"]
    assert tca1["inchikey"] == "ISNBJLXHBBZKSL-UHFFFAOYSA-N"
    assert tca1["chembl_id"] == "CHEMBL3262462"
    assert tca1["smiles"]


def test_a_ligand_rcsb_cannot_place_says_so(ligands: dict) -> None:
    """Most PDB components have no ChEMBL cross-reference, and that is not a failure."""
    assert ligands["ZID"]["chembl_id"] is None
    assert ligands["ZID"]["inchikey"]  # it still has a structure key


def test_roles_come_from_the_same_rule_as_the_structures(ligands: dict) -> None:
    assert ligands["1W6"]["role"] == "ligand"
    assert ligands["FAD"]["role"] == "cofactor"
