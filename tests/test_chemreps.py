"""ChEMBL's structure file, read for the ids the store references and no others."""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas.sources import chemreps

FIXTURES = Path(__file__).parent / "fixtures"
CHEMREPS = FIXTURES / "chembl_chemreps.txt"
MACOZINONE = "CHEMBL3330226"


def _rows(wanted: set[str], path: Path = CHEMREPS) -> dict[str, dict]:
    return {row["molecule_chembl_id"]: row for row in chemreps.normalize(path, wanted)}


def test_a_wanted_id_in_the_file_has_its_structure() -> None:
    row = _rows({MACOZINONE})[MACOZINONE]
    assert row["has_structure"] is True
    assert row["canonical_smiles"].startswith("O=c1nc(N2CCN(CC3CCCCC3)CC2)")
    assert row["standard_inchi_key"] == "BJDZBXGJNBMCAV-UHFFFAOYSA-N"


def test_an_id_nobody_asked_for_is_not_kept() -> None:
    """CHEMBL1 is in the file; the store does not reference it, so it gets no row."""
    assert set(_rows({MACOZINONE})) == {MACOZINONE}


def test_a_wanted_id_the_file_lacks_is_false_not_absent() -> None:
    """Looked up and not found is a row, so it cannot read as never looked up."""
    row = _rows({MACOZINONE, "CHEMBL999999999"})["CHEMBL999999999"]
    assert row == {
        "molecule_chembl_id": "CHEMBL999999999",
        "has_structure": False,
        "canonical_smiles": None,
        "standard_inchi_key": None,
    }


def test_a_blank_smiles_is_not_a_structure() -> None:
    """True with a NULL SMILES would promise a drawing the page cannot make."""
    row = _rows({"CHEMBL_BLANK"})["CHEMBL_BLANK"]
    assert (row["has_structure"], row["canonical_smiles"]) == (False, None)


def test_a_line_that_is_not_four_fields_is_skipped() -> None:
    row = _rows({"CHEMBL_SHORT"})["CHEMBL_SHORT"]
    assert row["has_structure"] is False


def test_every_wanted_id_gets_exactly_one_row() -> None:
    wanted = {MACOZINONE, "CHEMBL64", "CHEMBL_BLANK", "CHEMBL_SHORT", "CHEMBL999999999"}
    rows = list(chemreps.normalize(CHEMREPS, wanted))
    assert sorted(row["molecule_chembl_id"] for row in rows) == sorted(wanted)
    assert sum(row["has_structure"] for row in rows) == 2


def test_a_file_without_its_header_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "headless.txt"
    path.write_text("".join(CHEMREPS.read_text().splitlines(keepends=True)[1:]))
    with pytest.raises(ValueError, match="header"):
        list(chemreps.normalize(path, {MACOZINONE}))


def test_an_id_listed_twice_is_refused(tmp_path: Path) -> None:
    lines = CHEMREPS.read_text().splitlines(keepends=True)
    path = tmp_path / "twice.txt"
    path.write_text("".join([*lines, lines[1]]))
    with pytest.raises(ValueError, match=MACOZINONE):
        list(chemreps.normalize(path, {MACOZINONE}))


def test_the_release_comes_from_the_mapping_file() -> None:
    assert chemreps.release_name(FIXTURES / "chembl_uniprot_mapping.txt") == "chembl_37"


def test_a_mapping_file_that_names_no_release_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "mapping.txt"
    path.write_text("P9WGR1\tCHEMBL1849\tInhA\tSINGLE PROTEIN\n")
    with pytest.raises(ValueError, match="release"):
        chemreps.release_name(path)


def test_the_url_names_the_release_twice() -> None:
    assert chemreps.url("chembl_37") == (
        "https://ftp.ebi.ac.uk/pub/databases/chembl/ChEMBLdb/releases/chembl_37/"
        "chembl_37_chemreps.txt.gz"
    )
