"""PubChem campaigns and the UniChem bridge that reaches ChEMBL compounds."""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas.sources import unichem

FIXTURES = Path(__file__).parent / "fixtures"


def test_unichem_maps_cid_to_chembl_id_and_skips_half_rows():
    mapping = unichem.chembl_by_cid(FIXTURES / "unichem_src1src22.txt")
    assert mapping == {
        "12846578": "CHEMBL6329",
        "22247451": "CHEMBL1098659",
        "962": "CHEMBL1098659",
        "3162": "CHEMBL1004",
        "16694118": "CHEMBL3833402",
        "24850": "CHEMBL3833402",
        "75366293": "CHEMBL3833402",
    }


def test_unichem_normalize_keeps_both_identifiers():
    rows = list(unichem.normalize(FIXTURES / "unichem_src1src22.txt"))
    assert rows[0] == {"molecule_chembl_id": "CHEMBL6329", "pubchem_cid": "12846578"}
    assert len(rows) == 7


def test_one_compound_can_have_several_pubchem_entries():
    """0.9% of ChEMBL ids map to more than one CID -- up to 32 of them.

    Every CID has to resolve, because a PubChem screening result arrives keyed
    on whichever CID the depositor used. Inverting the dict to {chembl_id: cid}
    would keep one CID per compound and silently drop the rest; the CID side is
    the unique one (no CID repeats in the full file's 2,832,793 pairs), which is
    why the bridge is keyed on it.
    """
    mapping = unichem.chembl_by_cid(FIXTURES / "unichem_src1src22.txt")
    for cid in ("16694118", "24850", "75366293"):
        assert mapping[cid] == "CHEMBL3833402"


def test_unichem_raises_when_a_cid_maps_to_two_chembl_ids(tmp_path):
    """The bridge is keyed on CID, which is unique in the live file. If that ever
    stops being true, the build must stop: keeping either pair would attribute one
    compound's screening history to another.
    """
    path = tmp_path / "collision.txt"
    path.write_text("From src:'1'\tTo src:'22'\nCHEMBL6329\t12846578\nCHEMBL1004\t12846578\n")
    with pytest.raises(ValueError, match="CID 12846578 maps to both CHEMBL6329 and CHEMBL1004"):
        unichem.chembl_by_cid(path)


@pytest.mark.parametrize(
    "text",
    [
        "CHEMBL6329\t12846578\n",
        "From src:'22'\tTo src:'1'\nCHEMBL6329\t12846578\n",
    ],
    ids=["no header", "swapped header"],
)
def test_unichem_refuses_a_file_without_its_header(tmp_path, text):
    """The first line is skipped as a header. A file that lacks one would lose its
    first real pair silently, and a swapped column order would surface only by
    accident, as a collision.
    """
    path = tmp_path / "no_header.txt"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="header"):
        unichem.chembl_by_cid(path)


def test_unichem_identical_repeat_is_not_a_collision(tmp_path):
    """The same pair twice changes no attribution, so it is kept rather than raised on."""
    path = tmp_path / "repeat.txt"
    lines = ["From src:'1'\tTo src:'22'", "CHEMBL6329\t12846578", "CHEMBL6329\t12846578"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert unichem.chembl_by_cid(path) == {"12846578": "CHEMBL6329"}
