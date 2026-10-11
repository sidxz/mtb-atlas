"""PubChem campaigns and the UniChem bridge that reaches ChEMBL compounds."""

from __future__ import annotations

from pathlib import Path

from atlas.sources import unichem

FIXTURES = Path(__file__).parent / "fixtures"


def test_unichem_maps_cid_to_chembl_id_and_skips_half_rows():
    mapping = unichem.chembl_by_cid(FIXTURES / "unichem_src1src22.txt")
    assert mapping == {
        "4": "CHEMBL6329",
        "5": "CHEMBL1098659",
        "6": "CHEMBL1004",
        "16694118": "CHEMBL3833402",
        "24850": "CHEMBL3833402",
        "75366293": "CHEMBL3833402",
    }


def test_unichem_normalize_keeps_both_identifiers():
    rows = list(unichem.normalize(FIXTURES / "unichem_src1src22.txt"))
    assert rows[0] == {"molecule_chembl_id": "CHEMBL6329", "pubchem_cid": "4"}
    assert len(rows) == 6


def test_one_compound_can_have_several_pubchem_entries():
    """7.5% of ChEMBL ids map to more than one CID -- up to 14 of them.

    Every CID has to resolve, because a PubChem screening result arrives keyed
    on whichever CID the depositor used. Inverting the dict to {chembl_id: cid}
    would keep one CID per compound and silently drop the rest; the CID side is
    the unique one (0 collisions in a 26,867-pair sample), which is why the
    bridge is keyed on it.
    """
    mapping = unichem.chembl_by_cid(FIXTURES / "unichem_src1src22.txt")
    for cid in ("16694118", "24850", "75366293"):
        assert mapping[cid] == "CHEMBL3833402"
