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

    1,912 small AIDs (Task 6's census) look like this and none of the 28 large
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
    def __init__(self, text: str, headers: dict | None = None) -> None:
        self.text = text
        self.headers = headers or {}


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
    assert all(kwargs["min_interval"] == pubchem.PACE for _, _, kwargs in calls)


def test_the_pace_is_inside_what_eutils_allows_without_an_api_key():
    """PUG-REST asks for at most 5 requests a second; E-utilities allows 3 without a
    key, and the AID search and the project links go to E-utilities. PACE was 0.25,
    which is 4 a second, and this machine has already been edge-blocked once."""
    assert 1 / pubchem.PACE <= 3


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


def test_a_search_the_server_could_not_run_is_an_error_and_not_an_empty_list(monkeypatch):
    """E-utilities answers HTTP 200, `count: "0"` and an `errorlist` for a search it could not
    run, which parses like a campaign list with no campaigns: the build would write empty
    tables stamped "0 AIDs". The response is cached before the check runs."""
    body = {
        "esearchresult": {
            "count": "0",
            "idlist": [],
            "errorlist": {"phrasesnotfound": ["txid1773[ORGN]"], "fieldsnotfound": []},
        }
    }
    monkeypatch.setattr(pubchem, "fetch", lambda url, dest, **kw: _Page(json.dumps(body)))
    with pytest.raises(ValueError, match=r"no count.*txid1773.*atlas refresh pubchem.*force=True"):
        pubchem.fetch_aids()


def test_an_error_reply_with_no_idlist_still_gets_the_reason_and_the_way_out(monkeypatch):
    """The reply that names an error need not carry the list the build reads next, and a bare
    `KeyError: 'idlist'` would hide both the reason and the remedy the guard exists to give."""
    body = {"esearchresult": {"ERROR": "Invalid db name specified"}}
    monkeypatch.setattr(pubchem, "fetch", lambda url, dest, **kw: _Page(json.dumps(body)))
    with pytest.raises(ValueError, match=r"Invalid db name.*atlas refresh pubchem.*force=True"):
        pubchem.fetch_aids()


@pytest.mark.parametrize(
    ("reply", "says"),
    [
        ({"count": "0", "errorlist": {"phrasesnotfound": ["x"], "fieldsnotfound": []}}, "'x'"),
        ({"count": "0", "errorlist": {"phrasesnotfound": [], "fieldsnotfound": ["TSC"]}}, "TSC"),
        # An error text beside a count is still an error, and its reason is what gets shown.
        ({"count": "5", "ERROR": "Invalid db name specified"}, "Invalid db name"),
        ({"idlist": []}, "no count in the reply"),
        ({"count": "many"}, "no count in the reply"),
    ],
)
def test_a_reply_that_is_not_a_count_raises(reply, says):
    with pytest.raises(ValueError, match=f"no count.*{says}"):
        pubchem.esearch_count(reply)


def test_a_genuine_zero_is_a_count():
    """The elink guard's rule, here too: an empty answer has no error beside it. NCBI sends
    the `errorlist` keys with empty lists when nothing is wrong."""
    clean = {"count": "0", "errorlist": {"phrasesnotfound": [], "fieldsnotfound": []}}
    assert pubchem.esearch_count(clean) == 0
    assert pubchem.esearch_count({"count": "28"}) == 28


def test_aids_come_back_as_strings_in_the_order_pubchem_gave_them(monkeypatch):
    seen = {}

    def fake_fetch(url, dest, **kwargs):
        seen.update(url=url, **kwargs)
        body = {"esearchresult": {"count": "3", "idlist": ["2060911", "375", "1626"]}}
        return _Page(json.dumps(body))

    monkeypatch.setattr(pubchem, "fetch", fake_fetch)
    # Neither ascending nor descending, as numbers or as strings, and not the
    # reverse of itself: any sort or reversal changes it.
    assert pubchem.fetch_aids() == ["2060911", "375", "1626"]
    assert "txid1773[ORGN]" in seen["url"]
    assert seen["min_interval"] == pubchem.PACE


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
    # How a row is told from its neighbours: PubChem's row in its own datatable, or
    # ChEMBL's activity. Each source fills one and leaves the other NULL.
    "result_tag",
    "activity_id",
    # ChEMBL's own comment on an activity ("Not Determined"). PubChem has no equivalent.
    "activity_comment",
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


@pytest.mark.parametrize("cell", ["1,200", ">5", "nan", "inf", "1e999", "5 uM"])
def test_a_standard_value_that_is_not_a_finite_number_raises(tmp_path, cell):
    """The column is FLOAT in the file's own `RESULT_TYPE` row. A cell that will not
    parse swallowed into NULL leaves `endpoint`, `standard_relation` and
    `standard_units` populated: "IC50 in nM, no value", with no trace of why. NaN
    and infinity parse, and are no more a measurement."""
    path = tmp_path / "bad.csv"
    path.write_text(
        "PUBCHEM_RESULT_TAG,PUBCHEM_SID,PUBCHEM_CID,PUBCHEM_ACTIVITY_OUTCOME,Standard Value\n"
        f'1,10,20,Unspecified,"{cell}"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=rf"AID 7.*{cell!r}"):
        list(pubchem.normalize_results(path, "7", {}))


def test_a_blank_standard_value_is_no_value_and_a_plain_one_is_a_float(tmp_path):
    path = tmp_path / "blank.csv"
    path.write_text(
        "PUBCHEM_RESULT_TAG,PUBCHEM_SID,PUBCHEM_CID,PUBCHEM_ACTIVITY_OUTCOME,Standard Value\n"
        "1,10,20,Unspecified,\n2,11,21,Unspecified,-1.5e2\n",
        encoding="utf-8",
    )
    rows = list(pubchem.normalize_results(path, "7", {}))
    assert [row["standard_value"] for row in rows] == [None, -150.0]


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
    # `actvty=all` is what returns the inactives; `actvty=active` would cut AID
    # 1626 from 215,397 rows to about 2,000 and nothing else would notice.
    assert "actvty=all" in seen["url"]
    assert seen["url"].endswith("&aid=1626")
    assert seen["dest"] == "results/1626.csv"
    assert seen["min_interval"] == pubchem.PACE
    assert seen["timeout"] >= 600


# --- the declared ladder ------------------------------------------------------


def _projects() -> dict:
    return json.loads((FIXTURES / "pubchem_projects.json").read_text())


def _asked(aid: str, payload: dict) -> dict:
    """What eLink answers when the same project is asked for from another member."""
    return {**payload, "linksets": [{**payload["linksets"][0], "ids": [aid]}]}


def test_a_declared_project_groups_its_members_and_an_undeclared_one_stands_alone():
    """AID 449775's real project lists 39 AIDs, among them the 327,669-SID primary
    (449762) and the confirmatory. Asked from either, they name one campaign."""
    links = _projects()
    grouped = pubchem.group_projects(
        {
            "449762": _asked("449762", links["449775"]),
            "449775": links["449775"],
            "1626": links["1626"],
        }
    )
    # The lowest member is 435019, which is neither AID that was asked.
    assert grouped["449762"] == grouped["449775"] == "pubchem:project:435019"
    # TAACF 1626 declares nothing. The campaign is the AID, and that is not the
    # same claim as "this screen had no follow-up".
    assert grouped["1626"] == "pubchem:1626"


def test_the_lowest_member_is_the_lowest_number_not_the_lowest_text():
    payload = {
        "linksets": [{"ids": ["100000"], "linksetdbs": [{"links": ["100000", "99999", "100001"]}]}]
    }
    assert pubchem.group_projects({"100000": payload}) == {"100000": "pubchem:project:99999"}


def test_a_project_that_lists_only_itself_is_not_a_project():
    payload = {"linksets": [{"ids": ["1626"], "linksetdbs": [{"links": ["1626"]}]}]}
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


ERRORS = [
    pytest.param(_projects()["error"], id="eutils error"),
    pytest.param({"linksets": []}, id="no linkset"),
    pytest.param({"linksets": [{"dbfrom": "pcassay", "ids": ["7"]}]}, id="linkset for another id"),
    pytest.param(
        {"linksets": [{"dbfrom": "pcassay", "ids": ["1"]}], "ERROR": "Invalid linkname"},
        id="error beside a linkset",
    ),
]


@pytest.mark.parametrize("payload", ERRORS)
def test_an_eutils_error_is_not_a_project_that_declares_none(payload):
    """E-utilities answers HTTP 200 with JSON for a bad db, id or linkname, and
    `{"linksets": [], "ERROR": "Invalid db name specified"}` has no project in it
    either. Read as one, it would say AID 1 "declares no project", which is not
    the same statement as the lookup having failed. The genuine answer is a
    linkset whose `ids` is the AID that was asked, and the 1626 fixture is one."""
    with pytest.raises(ValueError, match=r"AID 1\b.*atlas refresh pubchem"):
        pubchem.group_projects({"1": payload})


def test_a_project_lookup_that_eutils_failed_is_not_returned_to_be_cached(monkeypatch):
    """`fetch` has cached the body by the time it is parsed, so the error is raised
    here, with the way out, rather than left for `group_projects` to find."""
    monkeypatch.setattr(pubchem, "fetch", lambda *a, **k: _Page(json.dumps(_projects()["error"])))
    with pytest.raises(ValueError, match=r"AID 1\b.*Invalid db name.*atlas refresh pubchem"):
        pubchem.fetch_project("1")


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


def test_a_uniprot_accession_the_crosswalk_does_not_hold_is_recorded_unmatched(monkeypatch):
    """AID 493033 (MbtI, 104,781 SIDs) names `P9WFX0`, UniProt's CDC 1551 entry. The crosswalk,
    which is H37Rv, holds the sibling `P9WFX1` for Rv2386c, so a well-formed UniProt accession
    reached no locus: 1 of the 7 UniProt targets among the 28 AIDs. It keeps its accession and
    resolves to nothing, and the H37Rv sibling is not guessed from it."""
    asked = _uniprot_answers(monkeypatch)
    (linked,) = pubchem.link_targets(
        [{"accession": "P9WFX0", "name": "Salicylate synthase"}],
        {**RV_BY_ACC, "P9WFX1": ["Rv2386c"]},
    )
    assert linked["accession"] == "P9WFX0"
    assert linked["accession_kind"] == "uniprot"
    assert linked["uniprot_accessions"] == ["P9WFX0"]
    assert linked["rv_ids"] == []
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


def test_a_refseq_that_reaches_two_loci_through_two_accessions_shares_nothing(monkeypatch):
    """`shared_accession` is the crosswalk column's meaning: an accession that
    belongs to more than one locus. UniProt mapping one RefSeq protein to two
    accessions (here Swiss-Prot and TrEMBL entries of two different genes, a
    synthetic answer) reaches two loci without any accession being shared, and
    flagging it would send Task 9 looking for siblings that do not exist."""
    body = {"results": [{"primaryAccession": "P9WHW5"}, {"primaryAccession": "P9WQA3"}]}
    monkeypatch.setattr(pubchem, "fetch", lambda *a, **k: _Page(json.dumps(body)))
    (linked,) = pubchem.link_targets([{"accession": "NP_214877", "name": "x"}], RV_BY_ACC)
    assert linked["uniprot_accessions"] == ["P9WHW5", "P9WQA3"]
    assert linked["rv_ids"] == ["Rv0018c", "Rv0363c"]
    assert linked["shared_accession"] is False


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


def test_a_refseq_answer_that_runs_to_a_second_page_raises_instead_of_truncating(monkeypatch):
    """UniProt's search returns 25 hits and a `Link: ...; rel="next"` header when
    there are more (checked live: a query for 4,059 hits sends one). The guard
    mirrors the one on the AID list: a silent cut is a locus that goes unmatched
    with nothing to say the answer was incomplete."""
    link = (
        "<https://rest.uniprot.org/uniprotkb/search?format=json&fields=accession"
        "&query=xref%3Arefseq-NP_214877&cursor=88d67348niembui5ewaai9up6mimhem4c9&size=25>; "
        'rel="next"'
    )
    body = {"results": [{"primaryAccession": "P9WQA3"}]}
    monkeypatch.setattr(
        pubchem, "fetch", lambda *a, **k: _Page(json.dumps(body), headers={"link": link})
    )
    with pytest.raises(ValueError, match=r"NP_214877.*more than one page") as raised:
        pubchem.fetch_refseq("NP_214877")
    # Fetching it again returns the same first page, so the usual "re-run with
    # force" remedy cannot help here. The message has to say what would.
    message = str(raised.value)
    assert "force" not in message and "refresh" not in message
    assert "size" in message and "cursor" in message


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


# --- telling one result row from another --------------------------------------
#
# The key a row is known by has been wrong twice. `(stage_id, pubchem_cid,
# molecule_chembl_id)` repeats because one CID sits under several SIDs. The next
# candidate, `(stage_id, pubchem_sid, activity_id, endpoint)`, repeats 21 times in
# AID 1671170 alone, because a SID can be measured twice for the same endpoint
# (6 replicate `Percent Effect` rows, 15 SIDs with two `IC50` rows). Adding the value
# does not help: 15 of those pairs repeat the value as well. What does not repeat is
# `PUBCHEM_RESULT_TAG`, the row's number in PubChem's own table.


def test_a_result_row_carries_its_number_in_the_pubchem_table():
    assert [row["result_tag"] for row in _results()] == [1, 13, 2045, 2046, 2275]
    assert [row["result_tag"] for row in _unspecified()] == [2227, 2228, 3777, 3778, 65639]
    assert all(row["activity_id"] is None for row in _results() + _unspecified())
    # A PubChem row has no ChEMBL comment, and the column is there for the ChEMBL rows.
    assert all(row["activity_comment"] is None for row in _results() + _unspecified())


def test_the_sid_and_endpoint_do_not_tell_two_rows_apart_but_the_row_number_does():
    """312400166 is on two `Percent Effect` rows, -1.988 and 1.19: two measurements."""
    rows = _unspecified()
    by_sid_and_endpoint = [(row["pubchem_sid"], row["endpoint"]) for row in rows]
    assert len(set(by_sid_and_endpoint)) < len(rows)
    pubchem.check_result_key(rows)


def test_a_result_key_that_repeats_is_refused_with_the_rows_that_repeat_it():
    rows = _unspecified()
    with pytest.raises(ValueError, match=r"repeats 1 time.*pubchem:1671170.*2227") as raised:
        pubchem.check_result_key([*rows, rows[0]])
    assert "result_tag" in str(raised.value)


def test_a_row_with_neither_a_row_number_nor_an_activity_has_no_identity():
    row = {**_results()[0], "result_tag": None, "activity_id": None}
    with pytest.raises(ValueError, match="neither"):
        pubchem.check_result_key([row])


def test_the_same_row_number_in_two_stages_is_two_rows():
    """Row 1 of AID 1626 and row 1 of AID 1671170 are different rows."""
    a, b = _results()[0], {**_results()[0], "stage_id": "pubchem:1671170"}
    pubchem.check_result_key([a, b])


def test_a_chembl_row_is_told_by_its_activity():
    chembl_row = {**_results()[0], "stage_id": "chembl:CHEMBL100", "result_tag": None}
    pubchem.check_result_key([{**chembl_row, "activity_id": 1}, {**chembl_row, "activity_id": 2}])
    with pytest.raises(ValueError, match="repeats 1 time"):
        pubchem.check_result_key([{**chembl_row, "activity_id": 1}] * 2)


def test_a_download_is_complete_when_its_distinct_sids_are_the_summarys_count():
    """65,646 rows cover 65,366 SIDs: the count is of SIDs, so the extra rows are
    not extra compounds. Five trimmed rows cover three."""
    rows = _unspecified()
    assert len(rows) == 5
    pubchem.check_complete("1671170", rows, 3)


@pytest.mark.parametrize("expected", [4, 2])
def test_a_download_with_fewer_or_more_sids_than_the_summary_counts_raises(expected):
    """A truncated download is a successful one: it parses, it has the right header,
    and a screen short of its compounds reads as compounds nobody tested."""
    with pytest.raises(ValueError, match=rf"AID 1671170.*3.*{expected}.*force=True"):
        pubchem.check_complete("1671170", _unspecified(), expected)


def test_a_row_with_no_sid_is_not_counted_as_a_compound():
    """Three SIDs are expected; one row has lost its SID, so two are there. Counting the
    missing one as a SID of its own would make three."""
    rows = _unspecified()
    rows[-1] = {**rows[-1], "pubchem_sid": None}
    with pytest.raises(ValueError, match="AID 1671170.*2.*3"):
        pubchem.check_complete("1671170", rows, 3)


# --- one campaign, several AIDs ------------------------------------------------


def test_a_campaign_of_one_assay_is_that_assays_row_under_the_campaigns_id():
    row = _rows()["1626"]
    campaign = pubchem.campaign_row("pubchem:1626", [row], declared=False)
    assert campaign == row | {"project_declared": False}
    declared = pubchem.campaign_row("pubchem:project:435019", [row], declared=True)
    assert declared["screen_id"] == "pubchem:project:435019"
    assert declared["project_declared"] is True
    # The one ingested assay is still the campaign's assay, and findable by its AID.
    assert declared["aid"] == "1626"
    assert declared["n_stages"] == 1


def test_two_assays_of_one_project_are_one_campaign_row():
    """AIDs 588335 and 588726 both reach 10,000 SIDs and share a declared project: two
    `screens` rows under one `screen_id` would break the table's key.

    `n_tested` is the number of distinct SIDs across the stages, counted by the caller
    from the result rows: a project that screens one library in two assays tested it
    once, and the sum (here 280,763) would flatter the screen by the overlap. Whether a
    SID called active in one stage and inactive in the next is "active" is a choice this
    pipeline has no business making, and per-stage counts of calls overlap, so none of the
    call counts is given for a campaign of several stages: they are NULL and the figures
    are on each stage."""
    rows = _rows()
    called, uncalled = rows["1626"], rows["1671170"]
    campaign = pubchem.campaign_row(
        "pubchem:project:1626", [uncalled, called], declared=True, n_tested=270000
    )
    assert campaign["screen_id"] == "pubchem:project:1626"
    assert campaign["n_stages"] == 2
    assert campaign["aid"] is None
    assert campaign["n_tested"] == 270000
    assert campaign["n_tested"] < called["n_tested"] + uncalled["n_tested"]
    # A stage stated its calls, so the campaign did; the counts are not summed.
    assert campaign["outcome_stated"] is True
    for part in ("n_active", "n_inactive", "n_inconclusive", "n_unspecified"):
        assert campaign[part] is None, part
    # The biggest stage names the campaign and states its library size.
    assert campaign["title"] == called["title"]
    assert campaign["library_size_stated"] == 216163
    assert campaign["depositor"] == "ChEMBL; SRMLSC"
    assert campaign["outcome_method"] == "confirmatory"
    assert campaign["targets"] == uncalled["targets"]


def test_a_campaign_none_of_whose_assays_stated_a_call_states_none():
    rows = _rows()
    campaign = pubchem.campaign_row(
        "pubchem:project:1671170",
        [rows["1671170"], rows["1671178"]],
        declared=True,
        n_tested=100000,
    )
    assert campaign["outcome_stated"] is False
    assert campaign["n_tested"] == 100000
    for part in ("n_active", "n_inactive", "n_inconclusive"):
        assert campaign[part] is None, part
    # No stage called anything and every SID in each is `Unspecified`, so every substance
    # in the campaign is, with no rule needed to say which call wins. The same knowledge as
    # a single assay's or a ChEMBL campaign's `n_unspecified == n_tested`.
    assert campaign["n_unspecified"] == campaign["n_tested"]


def test_unspecified_is_not_assumed_for_a_stage_that_did_not_say_so_itself():
    """No call was stated here either, but 65,366 SIDs were tested and PubChem counts none
    of them `Unspecified` (they might all be probes, say). Equating the two for this stage
    would turn a count PubChem did not make into one it did."""
    rows = _rows()
    odd = {**rows["1671170"], "n_unspecified": 0}
    campaign = pubchem.campaign_row(
        "pubchem:project:1671170", [odd, rows["1671178"]], declared=True, n_tested=100000
    )
    assert campaign["outcome_stated"] is False
    assert campaign["n_unspecified"] is None


def test_the_mixed_campaign_has_no_unspecified_count_either():
    """One stage called its SIDs and the other did not: a substance can be in the first's
    calls and the second's unspecified, so how many are unspecified depends on a rule."""
    rows = _rows()
    campaign = pubchem.campaign_row(
        "pubchem:project:1626", [rows["1626"], rows["1671170"]], declared=True, n_tested=270000
    )
    assert campaign["outcome_stated"] is True
    assert campaign["n_unspecified"] is None


def test_a_campaign_of_several_assays_is_refused_without_its_distinct_count():
    """Falling back to the sum would put the flattering number back in silently."""
    rows = _rows()
    with pytest.raises(ValueError, match="distinct"):
        pubchem.campaign_row("pubchem:project:1626", [rows["1626"], rows["1671170"]], declared=True)


def test_a_campaign_of_one_assay_keeps_its_own_call_counts_and_ignores_a_stray_count():
    row = _rows()["1626"]
    campaign = pubchem.campaign_row("pubchem:1626", [row], declared=False, n_tested=1)
    assert (campaign["n_tested"], campaign["n_active"]) == (215397, 2044)


def test_a_campaign_lists_a_target_once_however_many_of_its_assays_name_it():
    rows = _rows()
    twin = {**rows["2060911"], "aid": "2060912"}
    campaign = pubchem.campaign_row(
        "pubchem:project:2060911", [rows["2060911"], twin], declared=True, n_tested=93270
    )
    assert len(campaign["targets"]) == 1


def test_a_stage_is_the_assay_and_carries_the_campaign_it_belongs_to():
    stage = pubchem.stage_row(_rows()["1671170"], "pubchem:project:435019")
    assert stage["stage_id"] == "pubchem:1671170"
    assert stage["screen_id"] == "pubchem:project:435019"
    assert (stage["n_tested"], stage["n_active"]) == (65366, None)
    # The title names no measurement, so no modality is invented from it.
    assert stage["modality"] is None
    assert stage["stage"] == "primary"
    assert stage["derived"] is False
    assert stage["description"] == _rows()["1671170"]["title"]


def test_a_counter_screen_title_is_a_counter_screen_stage():
    row = {**_rows()["1626"], "title": "Counterscreen for inhibitors in Vero cells"}
    assert pubchem.stage_row(row, "pubchem:1626")["stage"] == "counter_screen"


def test_the_unichem_dict_can_be_cut_to_the_cids_that_are_wanted():
    """The full file is 2,832,793 pairs, a few hundred MB as a dict, for a screens
    table that touches a fraction of them."""
    path = FIXTURES / "unichem_src1src22.txt"
    assert unichem.chembl_by_cid(path, only={"962", "24850", "not-in-the-file"}) == {
        "962": "CHEMBL1098659",
        "24850": "CHEMBL3833402",
    }
    assert unichem.chembl_by_cid(path, only=set()) == {}


def test_a_collision_on_a_cid_nobody_asked_about_is_not_this_builds_problem(tmp_path):
    path = tmp_path / "collision.txt"
    path.write_text("From src:'1'\tTo src:'22'\nCHEMBL1\t5\nCHEMBL2\t5\nCHEMBL3\t6\n")
    assert unichem.chembl_by_cid(path, only={"6"}) == {"6": "CHEMBL3"}
    with pytest.raises(ValueError, match="CID 5"):
        unichem.chembl_by_cid(path, only={"5"})
