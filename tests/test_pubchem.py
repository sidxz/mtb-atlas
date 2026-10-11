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
# The fixture is five real summaries from PUG-REST (fetched 2026-10-11) with
# their Protocol and Comment text dropped; tests/fixtures/README.md says why each
# one is there.
#
# `SIDCountAll` counts SIDs (substances), not compounds: AID 1626 has 215,397 SIDs
# over 215,098 CIDs, and its prose says 216,163 compounds were screened.


def _summary(**counts) -> dict:
    """A well-formed summary with every count PubChem always sends."""
    base = {
        "AID": 1,
        "SourceName": "Some Depositor",
        "Name": "x",
        "SIDCountAll": 100,
        "SIDCountActive": 0,
        "SIDCountInactive": 0,
        "SIDCountInconclusive": 0,
        "SIDCountUnspecified": 100,
    }
    return {**base, **counts}


def _summaries() -> list[dict]:
    data = json.loads((FIXTURES / "pubchem_aid_summary.json").read_text())
    return data["AssaySummaries"]["AssaySummary"]


def _rows() -> dict[str, dict]:
    return {row["aid"]: row for row in pubchem.normalize_screens(_summaries())}


def test_zero_active_means_no_call_was_stated_not_that_nothing_was_active():
    """PubChem's summary reports SIDCountActive: 0 for a deposit with no cutoff.

    Read literally it says a screen of 65,366 SIDs found nothing. Every one of
    its rows is `Unspecified`: the depositor never stated a threshold, so
    `n_active` is NULL and `outcome_stated` is false. The number of SIDs left
    without a call is PubChem's own and is kept: it is not a zero that means
    "no call", it is the count of them.
    """
    row = _rows()["1671170"]
    assert row["outcome_stated"] is False
    assert row["n_active"] is None
    assert row["n_inactive"] is None
    assert row["n_inconclusive"] is None
    assert row["n_tested"] == 65366
    assert row["n_unspecified"] == 65366


def test_a_few_actives_beside_an_all_unspecified_set_is_still_no_call():
    """Six of the eight ChEMBL deposits among the 28 are not zero-active at all.

    AID 1671178 (Pks13) reports 25 actives, and `SIDCountUnspecified` equal to
    `SIDCountAll`: the 25 are the IC50 rows, and every one of those SIDs
    also has a single-point row that carries no call. Deciding `outcome_stated`
    from "is any call count above zero" would publish 25 actives and 0 inactives
    for a screen that called nothing inactive, which is the false zero again.
    """
    row = _rows()["1671178"]
    assert row["n_tested"] == 66592
    assert row["outcome_stated"] is False
    assert row["n_active"] is None
    assert row["n_inactive"] is None
    assert row["n_unspecified"] == 66592


def test_a_partial_deposit_keeps_its_calls_and_says_how_many_sids_have_none():
    """AID 2253871 (a small ChEMBL deposit, below the floor) calls 13 of its 15 SIDs.

    1,912 of the 8,391 small AIDs fetched look like this and none of the 28 large
    ones do. The calls are real, so they are kept; without `n_unspecified` the
    13 + 0 + 0 against 15 tested would have a gap and nothing to explain it.
    """
    row = _rows()["2253871"]
    assert row["outcome_stated"] is True
    assert (row["n_active"], row["n_inactive"], row["n_inconclusive"]) == (13, 0, 0)
    assert row["n_unspecified"] == 2
    assert row["n_tested"] == 15
    assert 13 + 0 + 0 + row["n_unspecified"] == row["n_tested"]


def test_a_summary_whose_calls_are_all_zero_is_not_a_stated_outcome():
    """No SID is Unspecified here, yet nothing was called either (every SID is a
    probe, say). Reading it as stated would publish 0 actives for a screen that
    called nothing."""
    row = pubchem.normalize_screens([_summary(SIDCountUnspecified=0)])[0]
    assert row["outcome_stated"] is False
    assert row["n_active"] is None
    assert row["n_unspecified"] == 0
    called = pubchem.normalize_screens(
        [_summary(SIDCountActive=3, SIDCountInactive=97, SIDCountUnspecified=0)]
    )[0]
    assert called["outcome_stated"] is True


@pytest.mark.parametrize(
    "key",
    [
        "SIDCountAll",
        "SIDCountActive",
        "SIDCountInactive",
        "SIDCountInconclusive",
        "SIDCountUnspecified",
        "SourceName",
    ],
)
def test_a_summary_missing_a_field_the_row_depends_on_raises(key):
    """A missing count read as 0 would be a stated zero, which is the false zero
    this module exists to avoid; a missing depositor would be a campaign whose
    licence cannot be traced. Real summaries always carry all of these."""
    summary = _summary()
    del summary[key]
    with pytest.raises(ValueError, match=key):
        pubchem.normalize_screens([summary])
    with pytest.raises(ValueError, match=key):
        pubchem.normalize_screens([{**summary, key: None}])


def test_a_real_screen_keeps_every_call_it_stated():
    row = _rows()["1626"]
    assert row["outcome_stated"] is True
    assert row["n_active"] == 2044
    assert row["n_inactive"] == 209843
    assert row["n_inconclusive"] == 3510
    assert row["n_unspecified"] == 0
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
    assert set(_rows()) == {"1626", "1671170", "1671178", "2060911", "2253871"}


def test_the_method_is_how_the_outcome_was_called_not_where_the_assay_sits():
    """PubChem calls AID 1626 `confirmatory`; it is the 215,397-SID primary screen.

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


def test_a_campaign_row_has_exactly_the_agreed_keys():
    """DuckDB types a column from a sample of the rows, so a key present in some
    rows only becomes NULL for all of them without an error. The ChEMBL campaign
    rows must carry this same set, and a drift here is what that sample hides."""
    expected = {
        "screen_id",
        "aid",
        "title",
        "depositor",
        "deposit_kind",
        "library_name",
        "library_size_stated",
        "year",
        "n_stages",
        "n_tested",
        "n_active",
        "n_inactive",
        "n_inconclusive",
        "n_unspecified",
        "outcome_stated",
        "outcome_method",
        "stages_source",
        "project_declared",
        "modalities",
        "document_chembl_id",
        "pubmed_id",
        "targets",
        "licence",
    }
    for row in _rows().values():
        assert set(row) == expected
    # No blanket licence is claimed; the depositor column is where it lives.
    assert "per depositor" in _rows()["1626"]["licence"]


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


def test_a_summary_pubchem_does_not_return_raises_instead_of_dropping_the_campaign(monkeypatch):
    """PUG-REST skips an AID it cannot find and still answers 200 for the rest
    (checked with AID 999999999 beside two real ones), so a lost summary is
    silent. An absent campaign would read as an answer.

    `fetch` has already cached the incomplete batch by the time this raises, so
    every later run raises too; the message says how to get out."""

    def fake_fetch(url, dest, **kwargs):
        aids = url.split("/aid/")[1].split("/")[0].split(",")
        kept = [a for a in aids if a not in {"1010", "1055"}]
        body = {"AssaySummaries": {"AssaySummary": [{"AID": int(a)} for a in kept]}}
        return _Page(json.dumps(body))

    monkeypatch.setattr(pubchem, "fetch", fake_fetch)
    with pytest.raises(ValueError, match=r"1010.*1055.*atlas refresh pubchem.*force=True"):
        pubchem.fetch_summaries([str(n) for n in range(1000, 1060)])


def test_a_truncated_aid_list_raises_instead_of_dropping_campaigns(monkeypatch):
    """esearch returns `retmax` ids and says how many matched; a list shorter than
    the count would silently lose campaigns. The response is cached before the
    check runs, so the message names the way out."""

    def fake_fetch(url, dest, **kwargs):
        body = {"esearchresult": {"count": "12519", "idlist": ["1626", "375"]}}
        return _Page(json.dumps(body))

    monkeypatch.setattr(pubchem, "fetch", fake_fetch)
    with pytest.raises(ValueError, match=r"12519.*atlas refresh pubchem.*force=True"):
        pubchem.fetch_aids()


def test_aids_come_back_as_strings_in_the_order_pubchem_gave_them(monkeypatch):
    seen = {}

    def fake_fetch(url, dest, **kwargs):
        seen["url"] = url
        body = {"esearchresult": {"count": "3", "idlist": ["2060911", "375", "1626"]}}
        return _Page(json.dumps(body))

    monkeypatch.setattr(pubchem, "fetch", fake_fetch)
    # Neither ascending nor descending, as numbers or as strings, and not the
    # reverse of itself: any sort or reversal changes it.
    assert pubchem.fetch_aids() == ["2060911", "375", "1626"]
    assert "txid1773[ORGN]" in seen["url"]


def test_the_search_carries_the_size_floor_so_only_large_summaries_are_fetched(monkeypatch):
    """12,519 AIDs carry the Mtb tag and 28 reach 10,000 tested SIDs. Fetching every
    summary is 501 requests, and PubChem answered 429 from the 337th and kept
    answering it through fetch's backoff, so the floor goes in the search term."""
    seen = {}

    def fake_fetch(url, dest, **kwargs):
        seen["url"] = url
        return _Page(json.dumps({"esearchresult": {"count": "0", "idlist": []}}))

    monkeypatch.setattr(pubchem, "fetch", fake_fetch)
    pubchem.fetch_aids()
    assert f"{pubchem.MIN_TESTED}:" in seen["url"]
    assert "[TSC]" in seen["url"]
    assert pubchem.MIN_TESTED == 10_000


# --- the per-compound results -------------------------------------------------
#
# `pubchem_aid_results.csv` is five real rows of AID 1626 (TAACF, the primary
# screen) and `pubchem_aid_unspecified.csv` five real rows of AID 1671170
# (Mt-TrpRS, a ChEMBL deposit with no activity call). Both keep the header and
# every metadata row after it, because only a numeric `PUBCHEM_RESULT_TAG` tells
# a result from one. tests/fixtures/README.md says what each row is for.

# The true UniChem pairs for three of the fixture's CIDs. 135458645 has no ChEMBL id.
BRIDGE = {
    "911287": "CHEMBL1461400",
    "3803930": "CHEMBL533602",
    "7314608": "CHEMBL1404086",
}

RESULT_KEYS = {
    "stage_id",
    "screen_id",
    "pubchem_cid",
    "pubchem_sid",
    "molecule_chembl_id",
    "outcome",
    "activity_score",
    "endpoint",
    "standard_value",
    "standard_units",
    "standard_relation",
}


def _results(name="pubchem_aid_results.csv", aid="1626", bridge=BRIDGE, **kwargs):
    return list(pubchem.normalize_results(FIXTURES / name, aid, bridge, **kwargs))


def _unspecified():
    return _results("pubchem_aid_unspecified.csv", "1671170", {})


def test_results_skip_the_metadata_rows_and_keep_every_outcome():
    rows = _results()
    # Ten lines follow the header; five of them are column metadata.
    assert [row["pubchem_sid"] for row in rows] == [
        "26660563",
        "49681785",
        "14730495",
        "22405324",
        "26719829",
    ]
    assert [row["outcome"] for row in rows] == [
        "active",
        "active",
        "inactive",
        "inactive",
        "inconclusive",
    ]
    assert [row["activity_score"] for row in rows] == [80, 80, 0, 0, 40]
    assert rows[0]["stage_id"] == "pubchem:1626"
    assert rows[0]["screen_id"] == "pubchem:1626"


def test_a_cid_with_no_unichem_mapping_is_still_a_result():
    rows = _results()
    assert rows[0]["molecule_chembl_id"] == "CHEMBL1461400"
    # CID 135458645 has no ChEMBL id, and the row survives: it was tested either way.
    assert rows[1]["pubchem_cid"] == "135458645"
    assert rows[1]["molecule_chembl_id"] is None
    # A row with no CID at all still has its SID.
    nocid = _unspecified()[-1]
    assert nocid["pubchem_cid"] is None
    assert nocid["pubchem_sid"] == "374364304"
    assert nocid["molecule_chembl_id"] is None


def test_two_sids_of_one_compound_can_disagree_and_both_rows_are_kept():
    """CID 135458645 is Active as SID 49681785 and Inconclusive as SID 26719829.

    11 CIDs in AID 1626 do this. A row per compound would have to pick one and
    the choice would be silent; a row per SID keeps both calls.
    """
    rows = [row for row in _results() if row["pubchem_cid"] == "135458645"]
    assert [(row["pubchem_sid"], row["outcome"]) for row in rows] == [
        ("49681785", "active"),
        ("26719829", "inconclusive"),
    ]


def test_an_unspecified_outcome_is_null_and_keeps_its_value():
    """No threshold was deposited, so there is no call and no score -- but the
    number is real, and a censored one keeps its qualifier."""
    rows = _unspecified()
    assert [row["outcome"] for row in rows] == [None] * 5
    assert [row["activity_score"] for row in rows] == [None] * 5
    effect, ic50 = rows[2], rows[3]
    assert (effect["endpoint"], effect["standard_relation"]) == ("Percent Effect", "=")
    assert (effect["standard_value"], effect["standard_units"]) == (54.24, "%")
    # `>` 194984 nM is a lower bound; stored as given, with its relation.
    assert (ic50["endpoint"], ic50["standard_relation"]) == ("IC50", ">")
    assert (ic50["standard_value"], ic50["standard_units"]) == (194984.0, "nM")


def test_a_sid_on_two_rows_keeps_both():
    """AID 1671170 has 65,646 rows over 65,366 SIDs. Of the 280 SIDs on two rows,
    259 are a single-point `Percent Effect` beside an `IC50`, 15 are two IC50s and
    6 are two replicate `Percent Effect` rows. Keeping one row per SID would drop
    a real measurement in every case, and which one would be arbitrary."""
    rows = _unspecified()
    replicate = [row for row in rows if row["pubchem_sid"] == "312400166"]
    assert [row["standard_value"] for row in replicate] == [-1.988, 1.19]
    pair = [row for row in rows if row["pubchem_sid"] == "312401710"]
    assert [(row["endpoint"], row["standard_value"]) for row in pair] == [
        ("Percent Effect", 54.24),
        ("IC50", 194984.0),
    ]


def test_a_campaign_without_standard_columns_still_carries_the_potency_keys():
    """AID 1626 names its columns itself (`IC90`, `% Inhibition of H37Rv @ 100 uM`).
    The four potency keys are present and NULL anyway: ChEMBL rows fill them, and
    DuckDB types a column from the rows it sees, so a key that only some rows carry
    becomes NULL for all of them without an error."""
    for row in _results():
        assert set(row) == RESULT_KEYS
        assert row["endpoint"] is None
        assert row["standard_value"] is None
        assert row["standard_units"] is None
        assert row["standard_relation"] is None
    for row in _unspecified():
        assert set(row) == RESULT_KEYS


def test_a_project_members_results_point_at_the_campaign_not_the_assay():
    """The stage stays the assay; the screen is the campaign the project names."""
    rows = _results(aid="449762", screen_id="pubchem:project:435019")
    assert {row["stage_id"] for row in rows} == {"pubchem:449762"}
    assert {row["screen_id"] for row in rows} == {"pubchem:project:435019"}


def test_an_outcome_pubchem_has_not_told_us_about_raises(tmp_path):
    """`Unspecified` is the absence of a call. A label this module does not know
    (PubChem also counts `Probe`) must not be read the same way."""
    path = tmp_path / "probe.csv"
    path.write_text(
        "PUBCHEM_RESULT_TAG,PUBCHEM_SID,PUBCHEM_CID,PUBCHEM_ACTIVITY_OUTCOME,PUBCHEM_ACTIVITY_SCORE\n"
        "1,10,20,Probe,100\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Probe.*AID 7"):
        list(pubchem.normalize_results(path, "7", {}))


def test_a_download_that_is_not_a_result_table_raises_instead_of_reading_as_empty(tmp_path):
    """A 200 with an HTML error page parses as a CSV with no result rows, which
    would read as a campaign that tested nothing."""
    path = tmp_path / "busy.csv"
    path.write_text("<html><body>Server busy, try later</body></html>\n", encoding="utf-8")
    with pytest.raises(ValueError, match="AID 7.*PUBCHEM_RESULT_TAG"):
        list(pubchem.normalize_results(path, "7", {}))


def test_results_come_from_the_uncapped_route_at_pubchems_pace(monkeypatch):
    """PUG-REST refuses above 10,000 SIDs ("Too many SIDs"), and AID 1626 has
    215,397. `pcget.cgi` has no cap, and a 30 MB body needs more than the default
    two-minute timeout."""
    seen = {}

    def fake_fetch(url, dest, **kwargs):
        seen.update(url=url, dest=dest, **kwargs)
        return _Page("")

    monkeypatch.setattr(pubchem, "fetch", fake_fetch)
    pubchem.fetch_results("1626")
    assert "pcget.cgi" in seen["url"]
    assert seen["url"].endswith("&aid=1626")
    assert seen["dest"] == "results/1626.csv"
    assert seen["min_interval"] == pubchem.PACE
    assert seen["timeout"] >= 600


# --- the declared ladder ------------------------------------------------------


def _projects() -> dict:
    return json.loads((FIXTURES / "pubchem_projects.json").read_text())


def test_a_declared_project_groups_its_members_and_an_undeclared_one_stands_alone():
    """AID 449775's real project lists 39 AIDs, among them the 327,669-SID primary
    (449762) and the confirmatory. Asked from either, they name one campaign."""
    links = _projects()
    grouped = pubchem.group_projects(
        {"449762": links["449775"], "449775": links["449775"], "1626": links["1626"]}
    )
    # The lowest member is 435019, which is neither AID that was asked.
    assert grouped["449762"] == grouped["449775"] == "pubchem:project:435019"
    # TAACF 1626 declares nothing. The campaign is the AID, and that is not the
    # same claim as "this screen had no follow-up".
    assert grouped["1626"] == "pubchem:1626"


def test_the_lowest_member_is_the_lowest_number_not_the_lowest_text():
    payload = {"linksets": [{"linksetdbs": [{"links": ["100000", "99999", "100001"]}]}]}
    assert pubchem.group_projects({"100000": payload}) == {"100000": "pubchem:project:99999"}


def test_a_project_that_lists_only_itself_is_not_a_project():
    payload = {"linksets": [{"linksetdbs": [{"links": ["1626"]}]}]}
    assert pubchem.group_projects({"1626": payload}) == {"1626": "pubchem:1626"}


def test_a_project_is_read_from_the_pcassay_project_link_at_pubchems_pace(monkeypatch):
    seen = {}

    def fake_fetch(url, dest, **kwargs):
        seen.update(url=url, dest=dest, **kwargs)
        return _Page(json.dumps(_projects()["449775"]))

    monkeypatch.setattr(pubchem, "fetch", fake_fetch)
    payload = pubchem.fetch_project("449775")
    assert "linkname=pcassay_pcassay_same_assay_project_list" in seen["url"]
    assert seen["url"].endswith("&id=449775")
    assert seen["dest"] == "projects/449775.json"
    assert seen["min_interval"] == pubchem.PACE
    assert seen["json_body"] is True
    assert len(payload["linksets"][0]["linksetdbs"][0]["links"]) == 39


# --- the gene a campaign aims at ----------------------------------------------
#
# 18 accessions over 16 AIDs: 7 UniProt, 8 RefSeq NP_, 2 EMBL, 1 PDB chain. The
# crosswalk joins on UniProt, so the RefSeq ones are bridged through UniProt's own
# cross-references; the EMBL form returns nothing there (`xref:embl-CCE37082`:
# 0 results) and the PDB chain is not a UniProt id at all. Those stay unmatched,
# and are recorded as such.

# True crosswalk pairs. A0A089QRB9 is the accession Rv1180 (pks3) and Rv1181 (pks4) share.
RV_BY_ACC = {
    "P9WHW5": ["Rv0018c"],
    "P9WQA3": ["Rv0363c"],
    "A0A089QRB9": ["Rv1180", "Rv1181"],
}
LINK_KEYS = {
    "accession",
    "name",
    "accession_kind",
    "uniprot_accessions",
    "rv_ids",
    "shared_accession",
}


def _uniprot_answers(monkeypatch):
    """Serve the two real UniProt answers in the fixture, and refuse anything else."""
    answers = json.loads((FIXTURES / "pubchem_refseq_uniprot.json").read_text())
    asked = []

    def fake_fetch(url, dest, **kwargs):
        asked.append(url)
        accession = url.split("xref:refseq-")[1].split("&")[0]
        return _Page(json.dumps(answers[accession]))

    monkeypatch.setattr(pubchem, "fetch", fake_fetch)
    return asked


@pytest.mark.parametrize(
    ("accession", "kind"),
    [
        ("P9WHW5", "uniprot"),
        ("I6X8D2", "uniprot"),
        ("P9WNZ1", "uniprot"),
        ("A0A089QRB9", "uniprot"),
        ("NP_214877", "refseq"),
        ("CCE37082", "other"),
        ("CAB06100", "other"),
        ("2A88_A", "other"),
    ],
)
def test_an_accession_is_classified_by_its_shape(accession, kind):
    assert pubchem.accession_kind(accession) == kind


def test_a_uniprot_accession_joins_the_crosswalk_directly(monkeypatch):
    asked = _uniprot_answers(monkeypatch)
    (linked,) = pubchem.link_targets(
        [{"accession": "P9WHW5", "name": "Serine/threonine protein phosphatase PstP"}], RV_BY_ACC
    )
    assert linked["rv_ids"] == ["Rv0018c"]
    assert linked["uniprot_accessions"] == ["P9WHW5"]
    assert linked["shared_accession"] is False
    assert asked == []


def test_a_refseq_accession_is_bridged_through_uniprot(monkeypatch):
    asked = _uniprot_answers(monkeypatch)
    (linked,) = pubchem.link_targets([{"accession": "NP_214877", "name": "fba"}], RV_BY_ACC)
    assert linked["accession"] == "NP_214877"
    assert linked["accession_kind"] == "refseq"
    assert linked["uniprot_accessions"] == ["P9WQA3"]
    assert linked["rv_ids"] == ["Rv0363c"]
    assert len(asked) == 1
    assert "rest.uniprot.org" in asked[0]


def test_a_refseq_protein_of_another_organism_reaches_no_locus(monkeypatch):
    """RefSeq is not an Mtb namespace: NP_999999 is a rat protein, UniProt answers
    with it, and the crosswalk (H37Rv only) has no such accession."""
    _uniprot_answers(monkeypatch)
    (linked,) = pubchem.link_targets([{"accession": "NP_999999", "name": "x"}], RV_BY_ACC)
    assert linked["uniprot_accessions"] == ["D3ZNH9"]
    assert linked["rv_ids"] == []


def test_a_refseq_accession_uniprot_does_not_know_is_recorded_unmatched(monkeypatch):
    monkeypatch.setattr(pubchem, "fetch", lambda *a, **k: _Page('{"results": []}'))
    (linked,) = pubchem.link_targets([{"accession": "NP_214877", "name": "x"}], RV_BY_ACC)
    assert linked["uniprot_accessions"] == []
    assert linked["rv_ids"] == []


def test_an_embl_id_and_a_pdb_chain_stay_unmatched_and_are_not_looked_up(monkeypatch):
    """No request, no guess. The name is kept verbatim and is never matched to a
    gene: "bioA" is also a gene symbol, and an EMBL-id target named "bioA" is how
    a screen would land on the wrong locus. The decoy key stands for any map that
    a name could be looked up in."""
    asked = _uniprot_answers(monkeypatch)
    linked = pubchem.link_targets(
        [
            {"accession": "CCE37082", "name": "bioA"},
            {"accession": "2A88_A", "name": "Ribonucleoside-diphosphate reductase"},
        ],
        {**RV_BY_ACC, "bioA": ["Rv1568"]},
    )
    assert [(t["accession"], t["name"]) for t in linked] == [
        ("CCE37082", "bioA"),
        ("2A88_A", "Ribonucleoside-diphosphate reductase"),
    ]
    assert [t["accession_kind"] for t in linked] == ["other", "other"]
    assert [t["rv_ids"] for t in linked] == [[], []]
    assert [t["uniprot_accessions"] for t in linked] == [[], []]
    assert asked == []


def test_an_accession_two_loci_share_reaches_both_and_says_so(monkeypatch):
    _uniprot_answers(monkeypatch)
    (linked,) = pubchem.link_targets([{"accession": "A0A089QRB9", "name": "x"}], RV_BY_ACC)
    assert linked["rv_ids"] == ["Rv1180", "Rv1181"]
    assert linked["shared_accession"] is True


def test_every_linked_target_carries_the_same_keys(monkeypatch):
    """Targets are stored as a list of structs, so a key on some of them only is
    the same silent-NULL trap as on the rows."""
    _uniprot_answers(monkeypatch)
    linked = pubchem.link_targets(
        [
            {"accession": "P9WHW5", "name": "a"},
            {"accession": "NP_214877", "name": "b"},
            {"accession": "CCE37082", "name": "c"},
        ],
        RV_BY_ACC,
    )
    assert [set(t) for t in linked] == [LINK_KEYS] * 3
    assert pubchem.link_targets([], RV_BY_ACC) == []


def test_a_refseq_lookup_is_cached_under_uniprot_and_refuses_a_non_refseq_string(monkeypatch):
    """The accession becomes part of a URL and a cache filename, and it came from
    a depositor."""
    seen = {}

    def fake_fetch(url, dest, **kwargs):
        seen.update(url=url, dest=dest, **kwargs)
        return _Page('{"results": []}')

    monkeypatch.setattr(pubchem, "fetch", fake_fetch)
    pubchem.fetch_refseq("NP_214877")
    assert "xref:refseq-NP_214877" in seen["url"]
    assert "fields=accession" in seen["url"]
    assert seen["dest"] == "refseq/NP_214877.json"
    assert seen["source"] == "uniprot"
    assert seen["json_body"] is True
    with pytest.raises(ValueError, match="RefSeq"):
        pubchem.fetch_refseq("../../etc/passwd")
