"""PubChem campaigns and the UniChem bridge that reaches ChEMBL compounds."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atlas.sources import pubchem, unichem

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
        "From src:'1'\tTo src:'9'\nCHEMBL6329\t12846578\n",
    ],
    ids=["no header", "swapped header", "wrong second column"],
)
def test_unichem_refuses_a_file_without_its_header(tmp_path, text):
    """The first line is skipped as a header. A file that lacks one would lose its
    first real pair silently, and a swapped column order would surface only by
    accident, as a collision. The second column is checked as well as the first:
    a file mapping src 1 to some other source would otherwise read as a CID map.
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


# --- campaign discovery -------------------------------------------------------
#
# The fixture is four real summaries from PUG-REST (fetched 2026-10-11) with
# their Protocol and Comment text dropped; tests/fixtures/README.md says why each
# one is there.


def _summaries() -> list[dict]:
    data = json.loads((FIXTURES / "pubchem_aid_summary.json").read_text())
    return data["AssaySummaries"]["AssaySummary"]


def _rows() -> dict[str, dict]:
    return {row["aid"]: row for row in pubchem.normalize_screens(_summaries())}


def test_zero_active_means_no_call_was_stated_not_that_nothing_was_active():
    """PubChem's summary reports SIDCountActive: 0 for a deposit with no cutoff.

    Read literally it says a 65,366-compound screen found nothing. Every one of
    its rows is `Unspecified`: the depositor never stated a threshold, so
    `n_active` is NULL and `outcome_stated` is false.
    """
    row = _rows()["1671170"]
    assert row["outcome_stated"] is False
    assert row["n_active"] is None
    assert row["n_inactive"] is None
    assert row["n_inconclusive"] is None
    assert row["n_tested"] == 65366


def test_a_few_actives_beside_an_all_unspecified_set_is_still_no_call():
    """Six of the eight ChEMBL deposits among the 28 are not zero-active at all.

    AID 1671178 (Pks13) reports 25 actives, and `SIDCountUnspecified` equal to
    `SIDCountAll`: the 25 are the IC50 rows, and every one of those compounds
    also has a single-point row that carries no call. Deciding `outcome_stated`
    from "is any call count above zero" would publish 25 actives and 0 inactives
    for a screen that called nothing inactive, which is the false zero again.
    """
    row = _rows()["1671178"]
    assert row["n_tested"] == 66592
    assert row["outcome_stated"] is False
    assert row["n_active"] is None
    assert row["n_inactive"] is None


def test_a_summary_with_no_unspecified_field_falls_back_to_the_call_counts():
    """The field is the better signal, but a response without it must not read as stated."""
    bare = {"AID": 1, "Name": "x", "SIDCountAll": 100}
    row = pubchem.normalize_screens([bare])[0]
    assert row["outcome_stated"] is False
    assert row["n_active"] is None
    called = {**bare, "SIDCountActive": 3, "SIDCountInactive": 97}
    assert pubchem.normalize_screens([called])[0]["outcome_stated"] is True


def test_a_real_screen_keeps_every_call_it_stated():
    row = _rows()["1626"]
    assert row["outcome_stated"] is True
    assert row["n_active"] == 2044
    assert row["n_inactive"] == 209843
    assert row["n_inconclusive"] == 3510
    assert row["screen_id"] == "pubchem:1626"
    assert row["depositor"] == "SRMLSC"


def test_the_library_the_prose_names_is_not_what_was_deposited():
    """AID 1626's prose says 216,163 compounds were screened; 215,397 SIDs are deposited."""
    rows = _rows()
    assert rows["1626"]["library_size_stated"] == 216163
    assert rows["1626"]["n_tested"] == 215397
    assert rows["2060911"]["library_size_stated"] == 100639
    assert rows["2060911"]["n_tested"] == 93270
    # "Biochemical assay for Mt-TrpRS" states no figure, and none is invented.
    assert rows["1671170"]["library_size_stated"] is None


def test_a_campaign_that_never_says_mtb_is_still_a_campaign():
    """The summary carries no taxonomy, and the title and target name often omit it.

    AID 1671170 is "Biochemical assay for Mt-TrpRS" on "Tryptophan--tRNA ligase".
    A name test for "tubercul" or "mycobacter" drops it, and 7 more of the 28
    large AIDs that the taxonomy search selects (RecA, MbtI, FadD28, RmlC/D,
    CoaBC, ClpP1P2 and the Cornell heat-shock screen), all of them Mtb campaigns.
    """
    assert set(_rows()) == {"1626", "1671170", "1671178", "2060911"}


def test_the_method_is_how_the_outcome_was_called_not_where_the_assay_sits():
    """PubChem calls AID 1626 `confirmatory`; it is the 215,397-compound primary screen.

    The field says an outcome came from a dose-response curve, and AID 1626 has
    IC50 columns. Read as a funnel stage it would label the largest primary
    screens in public TB chemistry as confirmatory, so it is stored under its own
    name and the stage is left to the project structure and the title.
    """
    row = _rows()["1626"]
    assert row["outcome_method"] == "confirmatory"
    assert "stage" not in row
    assert row["stages_source"] == "from_prose"
    assert [key for key, value in row.items() if value == "confirmatory"] == ["outcome_method"]


def test_the_target_is_kept_exactly_as_pubchem_states_it():
    """No normalising and no matching: the accession is a UniProt id, a RefSeq NP_,
    an EMBL id or a PDB chain depending on the depositor, and the name can be a
    gene symbol. Resolving either to a locus is the results task's job."""
    rows = _rows()
    assert rows["2060911"]["targets"] == [
        {"accession": "P9WHW5", "name": "Serine/threonine protein phosphatase PstP"}
    ]
    # A whole-cell campaign has no protein target; that is stated by an empty
    # list, not by a missing key.
    assert rows["1626"]["targets"] == []


def test_the_depositor_is_stored_as_given_even_when_it_is_not_a_name():
    """AID 2060911's `SourceName` is the bare string "11908". The licence is per
    depositor, so the field is recorded either way and never resolved."""
    assert _rows()["2060911"]["depositor"] == "11908"


class _Page:
    def __init__(self, text: str) -> None:
        self.text = text


def test_summaries_are_fetched_in_batches_that_cover_every_aid_once(monkeypatch):
    """A batch is a cache entry, so the cache name must differ per batch or the
    second batch is served the first batch's file."""
    calls = []

    def fake_fetch(url, dest, **kwargs):
        calls.append((url, dest, kwargs))
        aids = url.split("/aid/")[1].split("/")[0].split(",")
        body = {"AssaySummaries": {"AssaySummary": [{"AID": int(a)} for a in aids]}}
        return _Page(json.dumps(body))

    monkeypatch.setattr(pubchem, "fetch", fake_fetch)
    aids = [str(n) for n in range(1000, 1060)]
    got = pubchem.fetch_summaries(aids)
    assert [s["AID"] for s in got] == [int(a) for a in aids]
    assert len(calls) == 3
    assert len({dest for _, dest, _ in calls}) == 3
    # PubChem asks for at most 5 requests a second.
    assert all(kwargs["min_interval"] >= 0.2 for _, _, kwargs in calls)


def test_a_truncated_aid_list_raises_instead_of_dropping_campaigns(monkeypatch):
    """esearch returns `retmax` ids and says how many matched; a list shorter than
    the count would silently lose campaigns."""

    def fake_fetch(url, dest, **kwargs):
        body = {"esearchresult": {"count": "12519", "idlist": ["1626", "375"]}}
        return _Page(json.dumps(body))

    monkeypatch.setattr(pubchem, "fetch", fake_fetch)
    with pytest.raises(ValueError, match="12519"):
        pubchem.fetch_aids()


def test_aids_come_back_as_strings_in_the_order_pubchem_gave_them(monkeypatch):
    seen = {}

    def fake_fetch(url, dest, **kwargs):
        seen["url"] = url
        body = {"esearchresult": {"count": "2", "idlist": ["2060911", "375"]}}
        return _Page(json.dumps(body))

    monkeypatch.setattr(pubchem, "fetch", fake_fetch)
    assert pubchem.fetch_aids() == ["2060911", "375"]
    assert "txid1773[ORGN]" in seen["url"]
