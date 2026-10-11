"""Drug precedent for a fold: the Pfam bridge from ChEMBL mechanisms.

The question is "has anyone ever got a drug onto a protein shaped like this
one", and the whole risk is in the joins. A mechanism points at a target, a
target has components, a component carries Pfam domains, and any of those steps
can quietly multiply or lose a row. Synthetic payloads here, because what is
being tested is the shape of the join and not ChEMBL's contents; the real rows
live in `tests/fixtures/extra_evidence.json` and are asserted in
`test_summary.py`.
"""

from __future__ import annotations

from typing import Any

from atlas.sources.precedent import normalize, pfam_domains

MTB_DOMAINS = ("PF00001", "PF00002")


def _component(accession: str, *domains: tuple[str, str]) -> dict[str, Any]:
    return {
        "accession": accession,
        "target_component_xrefs": [
            # The real payload mixes PDB, GO, InterPro and PANTHER into the same
            # list, and only the Pfam entries are the key.
            {"xref_src_db": "PDB", "xref_id": "1ABC", "xref_name": None},
            {"xref_src_db": "InterPro", "xref_id": "IPR000001", "xref_name": "something"},
            *(
                {"xref_src_db": "Pfam", "xref_id": pfam_id, "xref_name": name}
                for pfam_id, name in domains
            ),
        ],
    }


def _target(target_id: str, *accessions: str, kind: str = "SINGLE PROTEIN") -> dict[str, Any]:
    return {
        "target_chembl_id": target_id,
        "pref_name": f"target {target_id}",
        "target_type": kind,
        "organism": "Staphylococcus aureus",
        "tax_id": 1280,
        "target_components": [{"accession": accession} for accession in accessions],
    }


def _mechanism(mec_id: int, molecule: str, target: str, **extra: Any) -> dict[str, Any]:
    return {
        "mec_id": mec_id,
        "molecule_chembl_id": molecule,
        "parent_molecule_chembl_id": molecule,
        "target_chembl_id": target,
        "max_phase": 4,
        "action_type": "INHIBITOR",
        "mechanism_of_action": "something inhibitor",
        **extra,
    }


def _payloads(mechanisms: list, targets: list, components: list) -> dict[str, list]:
    return {"mechanisms": mechanisms, "targets": targets, "components": components}


def test_a_drug_on_a_protein_sharing_a_domain_is_a_row() -> None:
    rows = normalize(
        _payloads(
            [_mechanism(1, "CHEMBL1", "CHEMBL_T1")],
            [_target("CHEMBL_T1", "Q00001")],
            [_component("Q00001", ("PF00001", "widget"))],
        ),
        MTB_DOMAINS,
    )
    assert len(rows) == 1
    row = rows[0]
    assert (row["pfam_id"], row["pfam_name"]) == ("PF00001", "widget")
    # The accession is the protein the drug was actually filed against, which is
    # what lets the roll-up exclude a gene from being its own precedent.
    assert row["accession"] == "Q00001"
    assert row["max_phase"] == 4.0
    assert row["organism"] == "Staphylococcus aureus"
    assert row["target_type"] == "SINGLE PROTEIN"


def test_a_domain_no_mtb_protein_carries_is_dropped() -> None:
    """37,178 rows become 6,953 this way, and nothing that could reach a gene
    is lost: a domain absent from the proteome can never join."""
    rows = normalize(
        _payloads(
            [_mechanism(1, "CHEMBL1", "CHEMBL_T1")],
            [_target("CHEMBL_T1", "Q00001")],
            [_component("Q00001", ("PF09999", "not in this genome"))],
        ),
        MTB_DOMAINS,
    )
    assert rows == []


def test_a_complex_target_is_kept_not_dropped() -> None:
    """Shown, never counted, is the rule -- so the row has to exist.

    ChEMBL files the ribosome's approved drugs against a complex naming every
    subunit. Dropping those rows here would hide the fact; the roll-up is what
    refuses to count them, and `target_type` is how it tells them apart.
    """
    rows = normalize(
        _payloads(
            [_mechanism(1, "CHEMBL1", "CHEMBL_T1")],
            [_target("CHEMBL_T1", "Q00001", "Q00002", kind="PROTEIN COMPLEX")],
            [
                _component("Q00001", ("PF00001", "widget")),
                _component("Q00002", ("PF00002", "sprocket")),
            ],
        ),
        MTB_DOMAINS,
    )
    assert {row["target_type"] for row in rows} == {"PROTEIN COMPLEX"}
    # One row per component, each naming its own accession: that is how a
    # subunit's claim stays attributable to the subunit.
    assert {row["accession"] for row in rows} == {"Q00001", "Q00002"}


def test_one_row_per_domain_on_a_component() -> None:
    """A protein with two of the gene's domains is two rows, not one.

    Both are true statements and the roll-up counts DISTINCT molecules, so the
    duplication cannot inflate a count.
    """
    rows = normalize(
        _payloads(
            [_mechanism(1, "CHEMBL1", "CHEMBL_T1")],
            [_target("CHEMBL_T1", "Q00001")],
            [_component("Q00001", ("PF00001", "widget"), ("PF00002", "sprocket"))],
        ),
        MTB_DOMAINS,
    )
    assert sorted(row["pfam_id"] for row in rows) == ["PF00001", "PF00002"]
    assert {row["molecule_chembl_id"] for row in rows} == {"CHEMBL1"}


def test_two_mechanisms_on_the_same_pair_stay_two_rows() -> None:
    """Keyed on ChEMBL's own `mec_id`, so a second mechanism is not swallowed."""
    rows = normalize(
        _payloads(
            [
                _mechanism(1, "CHEMBL1", "CHEMBL_T1", mechanism_of_action="inhibitor"),
                _mechanism(2, "CHEMBL1", "CHEMBL_T1", mechanism_of_action="allosteric modulator"),
            ],
            [_target("CHEMBL_T1", "Q00001")],
            [_component("Q00001", ("PF00001", "widget"))],
        ),
        MTB_DOMAINS,
    )
    assert len(rows) == 2
    assert {row["mechanism_of_action"] for row in rows} == {"inhibitor", "allosteric modulator"}


def test_a_salt_is_folded_into_its_parent() -> None:
    """The same rule `normalize_drugs` follows, so a drug is not counted twice
    because ChEMBL files its hydrochloride separately."""
    rows = normalize(
        _payloads(
            [_mechanism(1, "CHEMBL1_HCL", "CHEMBL_T1", parent_molecule_chembl_id="CHEMBL1")],
            [_target("CHEMBL_T1", "Q00001")],
            [_component("Q00001", ("PF00001", "widget"))],
        ),
        MTB_DOMAINS,
    )
    assert [row["molecule_chembl_id"] for row in rows] == ["CHEMBL1"]


def test_a_mechanism_whose_target_is_missing_is_skipped() -> None:
    """A target the fetch did not return is an absence, not a row with holes.

    `fetch_json_many` skips a handful of failures by design, and a row carrying
    a domain with no idea what protein it came from would be unattributable.
    """
    rows = normalize(
        _payloads(
            [_mechanism(1, "CHEMBL1", "CHEMBL_MISSING")],
            [_target("CHEMBL_T1", "Q00001")],
            [_component("Q00001", ("PF00001", "widget"))],
        ),
        MTB_DOMAINS,
    )
    assert rows == []


def test_an_unknown_phase_is_neither_approved_nor_clinical() -> None:
    """ChEMBL writes -1 for a molecule whose phase it does not know.

    Kept as -1 rather than coerced: the roll-up counts `>= 4` and `1..3`, so it
    falls into neither, which is the honest answer for 131 of the rows.
    """
    rows = normalize(
        _payloads(
            [_mechanism(1, "CHEMBL1", "CHEMBL_T1", max_phase=-1)],
            [_target("CHEMBL_T1", "Q00001")],
            [_component("Q00001", ("PF00001", "widget"))],
        ),
        MTB_DOMAINS,
    )
    assert rows[0]["max_phase"] == -1.0


def test_only_pfam_cross_references_are_read() -> None:
    domains = pfam_domains([_component("Q00001", ("PF00001", "widget"))])
    assert domains == {"Q00001": [("PF00001", "widget")]}


def test_a_salt_s_separate_mechanism_is_not_a_second_row() -> None:
    """ChEMBL files one mechanism per salt, and salts fold into their parent.

    Daunorubicin, its hydrochloride and its citrate all make the same claim
    about human topoisomerase II; keying on `mec_id` printed it three times.
    The row keeps the earliest record id, so the key stays ChEMBL's.
    """
    rows = normalize(
        _payloads(
            [
                _mechanism(70, "CHEMBL1_CITRATE", "CHEMBL_T1", parent_molecule_chembl_id="CHEMBL1"),
                _mechanism(12, "CHEMBL1", "CHEMBL_T1"),
                _mechanism(41, "CHEMBL1_HCL", "CHEMBL_T1", parent_molecule_chembl_id="CHEMBL1"),
            ],
            [_target("CHEMBL_T1", "Q00001")],
            [_component("Q00001", ("PF00001", "widget"))],
        ),
        MTB_DOMAINS,
    )
    assert len(rows) == 1
    assert rows[0]["mec_id"] == 12
