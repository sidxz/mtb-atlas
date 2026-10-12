"""The read API over the fixture store: drugs and trials both ways round.

The API reads only the normalized store, so pointing it at the fixture store
exercises every route without a network or a full build.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

from atlas import api, store, summary
from atlas.sources import chembl


@pytest.fixture
def client(evidence_store: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    for module in (api, store, summary):
        monkeypatch.setattr(module, "STORE", evidence_store)
    return TestClient(api.app)


# The shared fixture store stops at campaigns and stages. Result rows are added to a
# copy, through the ingesters' own functions, so nothing here changes what every other
# test reads.
MACOZINONE = "CHEMBL3330226"
CHEMREPS_SMILES = "O=c1nc(N2CCN(CC3CCCCC3)CC2)sc2c([N+](=O)[O-])cc(C(F)(F)F)cc12 chemreps"


def _pubchem_row(stage: str, tag: int, outcome: str | None, cid: str) -> dict[str, object]:
    """A row in the shape `pubchem.normalize_results` yields."""
    return {
        "stage_id": stage,
        "screen_id": stage,
        "pubchem_cid": cid,
        "pubchem_sid": f"9{tag}",
        "molecule_chembl_id": None,
        "outcome": outcome,
        "activity_score": 80 if outcome == "active" else 0,
        "result_tag": tag,
        "activity_id": None,
        "activity_comment": None,
        "endpoint": None,
        "standard_value": None,
        "standard_units": None,
        "standard_relation": None,
    }


@pytest.fixture(scope="module")
def screen_store(evidence_store: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    copy = tmp_path_factory.mktemp("screens") / "store"
    shutil.copytree(evidence_store, copy)
    # A paper whose stages measure the compound, not a protein: whole-cell potency,
    # the three tiers beyond it, and a pathogen that is not Mtb. None reaches a gene,
    # so target_summary (built without them) stays true.
    assays = [
        {
            "assay_chembl_id": assay_id,
            "document_chembl_id": "CHEMBL_DOC3",
            "target_chembl_id": target,
            "description": description,
            "assay_strain": None,
        }
        for assay_id, target, description in (
            ("CHEMBL9300001", "CHEMBL360", "Antimycobacterial activity against M. tuberculosis"),
            ("CHEMBL9300002", None, "Cytotoxicity against African green monkey Vero cells"),
            ("CHEMBL9300003", None, "Metabolic stability in mouse liver microsomes"),
            ("CHEMBL9300004", "CHEMBL352", "Antibacterial activity against S. aureus"),
            # A selectivity index that is not a TB number. ChEMBL files these on the
            # derived stages of the same papers, and the endpoint string cannot tell
            # them apart -- only the description names the organism.
            (
                "CHEMBL9300005",
                None,
                "Selectivity index, ratio of CC50 for human MT4 cells to IC50 for HIV1 3B",
            ),
        )
    ]
    organisms = {
        "CHEMBL360": {"target_type": "ORGANISM", "organism": "Mycobacterium tuberculosis"},
        "CHEMBL352": {"target_type": "ORGANISM", "organism": "Staphylococcus aureus"},
    }
    acts = [
        {"assay_chembl_id": assay, "molecule_chembl_id": molecule, "activity_id": i}
        for i, (assay, molecule) in enumerate(
            (
                ("CHEMBL9300001", MACOZINONE),  # potency, and a tier beyond it
                ("CHEMBL9300002", MACOZINONE),
                ("CHEMBL9300001", "CHEMBL_POTENCY_ONLY"),
                ("CHEMBL9300004", "CHEMBL_ELSEWHERE"),  # neither Mtb potency nor a tier
                ("CHEMBL9300003", "CHEMBL_ADME_ONLY"),
                # Whole-cell too, so its only reported ratio being a bound is visible
                # here: a compound on derived stages alone has no profiling row at all.
                ("CHEMBL9300001", "CHEMBL_BOUND_ONLY"),
                ("CHEMBL9100001", "CHEMBL_PROTEIN"),  # dprE1's own protein: potency
                ("CHEMBL9100004", "CHEMBL_DERIVED_ONLY"),  # a computed ratio: not tested
            ),
            start=1,
        )
    ]
    # The authors' own selectivity index, on the derived stage conftest builds for it:
    # one measured, one a bound. A bound must not become the number.
    acts += [
        {
            "assay_chembl_id": "CHEMBL9100004",
            "molecule_chembl_id": molecule,
            "activity_id": 900 + i,
            "standard_type": "Selectivity Index",
            "standard_value": value,
            "standard_relation": relation,
            "standard_units": None,
        }
        for i, (molecule, value, relation) in enumerate(
            ((MACOZINONE, "40", "="), (MACOZINONE, "1000", ">"), ("CHEMBL_BOUND_ONLY", "500", ">"))
        )
    ]
    acts.append(
        {
            "assay_chembl_id": "CHEMBL9300005",
            "molecule_chembl_id": MACOZINONE,
            "activity_id": 950,
            "standard_type": "Selectivity Index",
            "standard_value": "9999",
            "standard_relation": "=",
            "standard_units": None,
        }
    )
    new_stages = chembl.stamp_stage_counts(
        chembl.normalize_campaign_assays(assays, organisms), acts
    )
    new_screens = chembl.campaign_screens(
        new_stages,
        acts,
        {"CHEMBL_DOC3": {"doc_type": "PUBLICATION", "title": "A third paper", "year": 2023}},
    )
    label = {"source_version": "ChEMBL_37 (2026-05-01)", "retrieved_at": "2026-10-09"}
    for name, extra in (("screens", new_screens), ("screen_stages", new_stages)):
        rows = [*store.records(name, store=copy), *store.stamp(extra, source="chembl", **label)]
        store.write_stamped(name, rows, store=copy)
    stages = store.records("screen_stages", store=copy)
    results = [
        *store.stamp(chembl.campaign_results(stages, acts), source="chembl", **label),
        *store.stamp(
            [
                # Calls stated: one active, one inactive.
                _pubchem_row("pubchem:9000008", 1, "active", "101"),
                _pubchem_row("pubchem:9000008", 2, "inactive", "102"),
                # The same molecule the literature profiled, called in a deposit: the
                # call pair's numerator and denominator both come from here.
                {
                    **_pubchem_row("pubchem:9000008", 3, "active", "104"),
                    "molecule_chembl_id": MACOZINONE,
                },
                {
                    **_pubchem_row("pubchem:9000007", 1, "inactive", "104"),
                    "molecule_chembl_id": MACOZINONE,
                },
                # No cutoff deposited: no call, which is not inactive.
                _pubchem_row("pubchem:9000001", 1, None, "103"),
            ],
            source="pubchem",
            source_version="E-utilities fixture",
            retrieved_at="2026-10-09",
        ),
    ]
    store.write_stamped("screen_results", results, store=copy)
    # Structures, in all three states: macozinone's differs from its `compounds` SMILES so a
    # test can tell which table a page drew from, the ADME-only compound was looked up and
    # not found, and every other compound was never looked up.
    store.write_parquet(
        "compound_structures",
        [
            {
                "molecule_chembl_id": MACOZINONE,
                "has_structure": True,
                "canonical_smiles": CHEMREPS_SMILES,
                "standard_inchi_key": "BJDZBXGJNBMCAV-UHFFFAOYSA-N",
            },
            {
                "molecule_chembl_id": "CHEMBL_POTENCY_ONLY",
                "has_structure": True,
                "canonical_smiles": "CCO",
                "standard_inchi_key": "LFQSCWFLJHTTHZ-UHFFFAOYSA-N",
            },
            {
                "molecule_chembl_id": "CHEMBL_ADME_ONLY",
                "has_structure": False,
                "canonical_smiles": None,
                "standard_inchi_key": None,
            },
        ],
        source="chembl",
        source_version="chembl_37",
        retrieved_at="2026-10-11",
        store=copy,
    )
    return copy


@pytest.fixture
def screens(screen_store: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    for module in (api, store, summary):
        monkeypatch.setattr(module, "STORE", screen_store)
    return TestClient(api.app)


def test_target_page_carries_drugs_and_trials(client: TestClient) -> None:
    page = client.get("/targets/Rv3790").json()
    assert {(d["molecule_chembl_id"], d["link"]) for d in page["drugs"]} >= {
        ("CHEMBL3330226", "mechanism"),
        ("CHEMBL3330226", "bosch_2021"),
    }
    assert {t["nct_id"] for t in page["trials"]} == {"NCT03036163", "NCT03423030"}


def test_a_gene_without_drugs_says_so(client: TestClient) -> None:
    page = client.get("/targets/Rv0667").json()  # rpoB: resistance, but no target claim
    assert not [d for d in page["drugs"] if d["link"] in ("mechanism", "bosch_2021")]
    assert any("No drug" in text for text in page["absences"])


def test_drug_page_goes_back_to_genes_and_trials(client: TestClient) -> None:
    drug = client.get("/drugs/CHEMBL3330226").json()
    assert drug["pref_name"] == "MACOZINONE"
    assert ("Rv3790", "mechanism") in {(g["rv_id"], g["link"]) for g in drug["genes"]}
    assert {t["nct_id"] for t in drug["trials"]} == {"NCT03036163", "NCT03423030"}
    assert drug["mechanisms"][0]["target_chembl_id"] == "CHEMBL3804751"


def test_drug_list_filters_by_phase(client: TestClient) -> None:
    items = client.get("/drugs", params={"min_phase": 4}).json()["items"]
    assert items and all(d["max_phase_tb"] >= 4 for d in items)
    assert "TMC207" in next(d for d in items if d["pref_name"] == "BEDAQUILINE")["synonyms"]
    assert "CHEMBL3330226" not in {d["molecule_chembl_id"] for d in items}


def test_trials_filter_by_drug(client: TestClient) -> None:
    page = client.get("/trials", params={"molecule": "CHEMBL376488"}).json()
    assert "NCT02333799" in {t["nct_id"] for t in page["items"]}
    assert all(
        "CHEMBL376488" in {d["molecule_chembl_id"] for d in t["drugs"]} for t in page["items"]
    )


def test_trial_page_names_how_each_drug_was_linked(client: TestClient) -> None:
    trial = client.get("/trials/NCT03423030").json()
    (link,) = trial["drugs"]
    assert link["molecule_chembl_id"] == "CHEMBL3330226"
    assert link["via_chembl_ref"] is True
    assert link["via_intervention_name"] is False


def test_unknown_ids_are_404(client: TestClient) -> None:
    assert client.get("/drugs/CHEMBL0").status_code == 404
    assert client.get("/trials/NCT00000000").status_code == 404


def test_targets_filter_on_clinical_drugs(client: TestClient) -> None:
    hits = client.get("/targets", params={"has_clinical_drug": True}).json()["items"]
    assert {"Rv3790", "Rv0206c", "Rv1484", "Rv1305"} <= {g["rv_id"] for g in hits}
    assert "Rv0667" not in {g["rv_id"] for g in hits}


def test_meta_lists_the_clinical_sources(client: TestClient) -> None:
    meta = client.get("/meta").json()
    assert "ClinicalTrials.gov" in {s["name"] for s in meta["sources"]}
    assert meta["counts"]["trials"] > 0


def test_target_page_leads_with_the_protein(client: TestClient) -> None:
    page = client.get("/targets/Rv3790").json()
    assert page["function"].startswith("Component of the DprE1-DprE2 complex")
    assert page["reviewed"] is True
    assert page["locations"] == ["Periplasm"]
    assert "essential" in page["disruption_phenotype"]
    assert page["n_references"] == len(page["pubmed_ids"])


def test_targets_carry_membrane_topology(client: TestClient) -> None:
    hits = client.get("/targets", params={"q": "mmpL3"}).json()["items"]
    assert hits[0]["n_transmembrane"] == 12


def test_structures_separate_a_neighbours_ligand(client: TestClient) -> None:
    """rpoB's rifampicin structure must not read as a ligand of rpoC."""
    rpoc = client.get("/targets/Rv0668").json()
    entry = next(s for s in rpoc["structures"] if s["pdb_id"] == "5UHB")
    assert entry["ligand_ids"] == []
    assert entry["ligand_ids_elsewhere"] == ["RFP"]
    rpob = client.get("/targets/Rv0667").json()
    assert next(s for s in rpob["structures"] if s["pdb_id"] == "5UHB")["ligand_ids"] == ["RFP"]


def test_a_bound_ligand_is_named_and_tied_to_its_drug(client: TestClient) -> None:
    """5UHB holds rifampicin on rpoB's chain, and rifampicin is an approved TB drug."""
    (ligand,) = client.get("/targets/Rv0667").json()["bound_ligands"]
    assert ligand["comp_id"] == "RFP"
    assert ligand["molecule_chembl_id"] == "CHEMBL374478"
    assert ligand["drug_name"] == "RIFAMPIN"
    assert ligand["max_phase_tb"] == 4


def test_a_bound_ligand_that_is_no_known_drug_is_still_named(client: TestClient) -> None:
    (ligand,) = client.get("/targets/Rv1484").json()["bound_ligands"]  # InhA, 1ZID
    assert ligand["comp_id"] == "ZID"
    assert "NICOTINAMIDE" in ligand["name"]
    assert ligand["drug_name"] is None


# --- one box over everything -------------------------------------------------


def hits(client: TestClient, q: str) -> dict[str, list[str]]:
    found = client.get("/search", params={"q": q}).json()
    return {kind: [item["id"] for item in items] for kind, items in found.items()}


def test_an_identifier_finds_its_own_object(client: TestClient) -> None:
    assert hits(client, "Rv3790")["genes"][0] == "Rv3790"
    assert hits(client, "CHEMBL376488")["drugs"][0] == "CHEMBL376488"
    assert hits(client, "NCT02333799")["trials"][0] == "NCT02333799"
    assert hits(client, "P9WJF1")["genes"][0] == "Rv3790"  # the accession, not the tag


def test_a_drug_name_finds_the_drug_and_its_trials(client: TestClient) -> None:
    found = hits(client, "bedaquiline")
    assert "CHEMBL376488" in found["drugs"]
    assert "NCT02333799" in found["trials"]


def test_a_synonym_finds_the_drug(client: TestClient) -> None:
    assert "CHEMBL376488" in hits(client, "TMC207")["drugs"]


def test_a_gene_name_beats_a_product_mention(client: TestClient) -> None:
    """Typing a gene name should not bury it under everything that mentions it."""
    assert hits(client, "dprE1")["genes"][0] == "Rv3790"


def test_every_hit_says_what_it_is(client: TestClient) -> None:
    for items in client.get("/search", params={"q": "rif"}).json().values():
        for item in items:
            assert item["id"] and item["label"]


def test_a_search_that_matches_nothing_is_empty_not_an_error(client: TestClient) -> None:
    found = client.get("/search", params={"q": "zzzznotathing"})
    assert found.status_code == 200
    assert all(items == [] for items in found.json().values())


# --- a compound, the other way round -----------------------------------------


def test_a_compound_names_the_genes_it_hits(client: TestClient) -> None:
    """Hit triage runs compound-first: what does this molecule touch, and how hard?"""
    page = client.get("/compounds/CHEMBL3330226").json()  # macozinone
    assert page["pref_name"] == "MACOZINONE"
    (gene,) = [g for g in page["genes"] if g["rv_id"] == "Rv3790"]
    assert gene["gene_name"] == "dprE1"
    assert gene["evidence"] == "direct"
    assert gene["best_pchembl"] is not None


def test_a_compound_that_is_a_tb_drug_says_so(client: TestClient) -> None:
    page = client.get("/compounds/CHEMBL3330226").json()
    assert page["drug"]["max_phase_tb"] == 2


def test_a_compound_that_is_not_a_drug_says_nothing_about_phase(client: TestClient) -> None:
    page = client.get("/compounds/CHEMBL1076347").json()
    assert page["drug"] is None


def test_whole_cell_stays_separate_from_protein_activity(client: TestClient) -> None:
    """The rule the atlas is built on: a MIC is not evidence against a protein."""
    page = client.get("/compounds/CHEMBL3330226").json()
    assert all(a["evidence"] != "whole_cell" for a in page["activities"])
    assert all(a["evidence"] == "whole_cell" for a in page["whole_cell"])


def test_a_wildcard_in_the_term_is_a_character_not_a_pattern(client: TestClient) -> None:
    """`%` and `_` are LIKE wildcards; typing one should mean itself."""
    for term in ("%", "_", "   "):
        found = client.get("/search", params={"q": term}).json()
        # A fixture campaign id (`chembl:CHEMBL_DOC1`) holds a real underscore, so a hit
        # is allowed only where the character itself is there to be found.
        for items in found.values():
            for hit in items:
                assert term in f"{hit['id']}{hit['label']}{hit['detail'] or ''}", (term, hit)
    assert client.get("/targets", params={"q": "%"}).json()["total"] == 0


def test_an_unmeasurable_gene_gets_an_absence_not_a_zero(client: TestClient) -> None:
    """inhA takes no insertions in Griffin's library, so that screen measured nothing.

    The gene page has to say that, because `log2fc 0.00, q 1.0` is exactly what
    a gene with no effect also reads.
    """
    page = client.get("/targets/Rv1484").json()
    assert page["conditions"] == []
    assert page["tnseq_coverage"]["unmeasured"] >= 1
    assert any("no transposon insertions" in a for a in page["absences"])


def test_a_knockout_background_is_not_served_as_a_condition(client: TestClient) -> None:
    """A hit in a knockout screen is an interaction with the deleted gene."""
    page = client.get("/targets/Rv3790").json()
    screens = {hit["screen_id"] for hit in page["conditions"]}
    assert all("_KO_" not in screen for screen in screens)


def test_only_annotated_screens_reach_the_gene_page(client: TestClient) -> None:
    """A screen whose condition the authors do not record describes nothing.

    `CC001.Unc_vs_mbio_H37Rv` is in the store and deliberately unannotated, so
    it must not appear as though it were a condition.
    """
    page = client.get("/targets/Rv3790").json()
    served = {hit["screen_id"] for hit in page["conditions"] + page["interactions"]}
    assert "CC001.Unc_vs_mbio_H37Rv" not in served


# --- screens: campaigns, stages, result rows ---------------------------------


def test_the_campaign_list_says_what_it_does_not_hold(screens: TestClient) -> None:
    """A set that was never ingested must read as absent, not as screened-and-empty."""
    page = screens.get("/screens").json()
    assert page["total"] == len(store.records("screens", store=store.STORE))
    assert any("Pathogen Box" in name for name in page["not_ingested"])
    # Shares over measured stages: a derived ratio has no funnel position to default.
    measured = [s for s in store.records("screen_stages", store=store.STORE) if not s["derived"]]
    assert page["stage_labels"]["n_stages"] == len(measured)


def test_the_gene_page_and_the_gene_table_count_screens_alike(screens: TestClient) -> None:
    """`SCREEN_REACH` restates summary's rule per campaign; the two must not drift apart."""
    disagree = (
        api._db()
        .sql(
            f"WITH reach AS ({api.SCREEN_REACH}), g AS (SELECT rv_id,"
            " count(*) FILTER (WHERE own) AS own, count(*) FILTER (WHERE via_complex) AS cx"
            " FROM reach GROUP BY 1)"
            " SELECT s.rv_id FROM target_summary s LEFT JOIN g USING (rv_id)"
            " WHERE coalesce(g.own, 0) <> s.n_target_screens"
            "    OR coalesce(g.cx, 0) <> s.n_complex_screens"
        )
        .fetchall()
    )
    assert disagree == []
    assert any(s["own"] for s in screens.get("/targets/Rv3790").json()["screens"])


def test_a_complex_screen_is_shown_on_the_subunit_and_not_counted(screens: TestClient) -> None:
    page = screens.get("/targets/Rv2461c").json()  # clpP1: the ClpP1P2 complex only
    assert page["screens"] and not any(s["own"] for s in page["screens"])
    assert any("part of a complex" in a for a in page["absences"])
    own = screens.get("/screens", params={"rv_id": "Rv2461c", "own": True}).json()
    assert own["total"] == 0
    assert screens.get("/screens", params={"rv_id": "Rv2461c", "own": False}).json()["total"]


def test_filters_and_paging_run_over_the_population(screens: TestClient) -> None:
    """A filter applied to the loaded page would narrow the page, not the answer."""
    whole = screens.get("/screens").json()
    own = screens.get("/screens", params={"has_own_gene": True}).json()
    complex_only = screens.get("/screens", params={"has_own_gene": False}).json()
    assert own["total"] + complex_only["total"] == whole["total"]
    assert all(any(g["own"] for g in s["genes"]) for s in own["items"])
    assert not any(g["own"] for s in complex_only["items"] for g in s["genes"])
    # The total is the population's, and a later page is a window into the same one.
    page = screens.get("/screens", params={"limit": 2, "offset": 2}).json()
    assert page["total"] == whole["total"]
    assert [s["screen_id"] for s in page["items"]] == [s["screen_id"] for s in whole["items"][2:4]]


def test_no_call_is_not_inactive(screens: TestClient) -> None:
    """A deposit with no cutoff stated no call, and a filter for non-hits must not find it."""
    url = "/screens/pubchem:9000001/results"
    assert screens.get(url, params={"outcome": "inactive"}).json()["total"] == 0
    (row,) = screens.get(url, params={"outcome": "no_call"}).json()["items"]
    assert row["outcome"] is None


def test_stage_counts_come_from_the_rows_per_stage(screens: TestClient) -> None:
    (stage,) = screens.get("/screens/pubchem:9000008").json()["stages"]
    assert (stage["n_active_rows"], stage["n_inactive_rows"], stage["n_no_call_rows"]) == (2, 1, 0)


def test_result_rows_are_paged_and_never_dumped(screens: TestClient) -> None:
    url = "/screens/pubchem:9000008/results"
    assert screens.get(url, params={"limit": 5000}).status_code == 422
    assert screens.get("/screens/pubchem:0/results").status_code == 404
    assert screens.get("/screens/pubchem:0").status_code == 404


def test_a_target_that_reaches_no_locus_stays_on_the_campaign(screens: TestClient) -> None:
    """The MbtI shape: a deposit names a protein the crosswalk cannot key, so the gene
    reads zero and the campaign is the only place the screen shows."""
    found = screens.get("/screens", params={"unplaced": True}).json()
    assert found["total"] == found["n_unplaced"] >= 1
    assert all(item["unplaced_targets"] for item in found["items"])


def test_hit_profiling_counts_coverage_in_three_buckets(screens: TestClient) -> None:
    page = screens.get("/hits").json()
    # The derived-only compound is not "tested": a computed ratio is not a measurement.
    assert "CHEMBL_DERIVED_ONLY" not in {i["molecule_chembl_id"] for i in page["items"]}
    population = page["population"]
    assert (
        population["compounds"],
        population["beyond_potency"],  # macozinone (cytotox), the ADME-only compound
        population["potency_only"],  # two whole-cell only, and dprE1's own protein
        population["elsewhere_only"],  # S. aureus and nothing else
    ) == (6, 2, 3, 1)


def test_a_published_selectivity_index_is_served_and_a_bound_is_not(screens: TestClient) -> None:
    """The ratio is the paper's own number. `> 1000` says the experiment never reached
    it, so it is counted apart and never becomes the value -- the `pmic` rule again."""
    (row,) = screens.get("/hits", params={"q": MACOZINONE}).json()["items"]
    assert (row["n_selectivity"], row["selectivity_min"], row["selectivity_max"]) == (1, 40, 40)
    assert row["n_selectivity_censored"] == 1
    # The HIV selectivity index on the same paper is not this compound's TB selectivity,
    # and only the stage's description says so.
    assert row["selectivity_max"] != 9999
    # A compound whose only reported ratio is a bound has no measured one at all.
    (bound,) = screens.get("/hits", params={"q": "CHEMBL_BOUND_ONLY"}).json()["items"]
    assert bound["n_selectivity"] is None and bound["n_selectivity_censored"] == 1
    assert "CHEMBL_BOUND_ONLY" not in {
        i["molecule_chembl_id"]
        for i in screens.get("/hits", params={"has": "n_selectivity"}).json()["items"]
    }


def test_a_stated_call_is_counted_against_its_own_denominator(screens: TestClient) -> None:
    """Only 25 of 999 campaigns state calls, so an actives count alone would read as
    'never a hit' for a compound nobody called either way."""
    (row,) = screens.get("/hits", params={"q": MACOZINONE}).json()["items"]
    assert (row["n_active_campaigns"], row["n_call_campaigns"]) == (1, 2)
    (quiet,) = screens.get("/hits", params={"q": "CHEMBL_POTENCY_ONLY"}).json()["items"]
    assert quiet["n_call_campaigns"] is None and quiet["n_active_campaigns"] is None


def test_a_mic_and_nothing_else_is_the_strict_count(screens: TestClient) -> None:
    """The loose reading counts compounds carrying other-pathogen or unclassified
    assays, which is not nothing else."""
    population = screens.get("/hits").json()["population"]
    # The third `potency_only` compound was measured on a protein, not a cell.
    assert population["whole_cell_and_nothing_else"] == 2
    assert population["potency_only"] == 3


def test_a_campaign_filters_the_profile_without_redefining_it(screens: TestClient) -> None:
    """Membership in the campaign, not a profile recomputed over it: the columns count
    a compound's whole literature, and the headers must keep meaning that."""
    whole = {h["molecule_chembl_id"]: h for h in screens.get("/hits").json()["items"]}
    page = screens.get("/hits", params={"screen": "chembl:CHEMBL_DOC3"}).json()
    assert 0 < page["total"] < len(whole)
    for hit in page["items"]:
        assert hit == whole[hit["molecule_chembl_id"]]
    # A gene's own protein assay is in another campaign, so that compound is excluded.
    assert "CHEMBL_PROTEIN" not in {h["molecule_chembl_id"] for h in page["items"]}


def test_an_unmeasured_tier_is_null_not_zero(screens: TestClient) -> None:
    (row,) = screens.get("/hits", params={"q": "CHEMBL_POTENCY_ONLY"}).json()["items"]
    assert row["n_mtb_whole_cell"] == 1
    assert row["n_cytotox"] is None and row["n_adme"] is None and row["n_in_vivo"] is None


def test_hit_profiling_filters_on_which_tiers_exist(screens: TestClient) -> None:
    found = screens.get("/hits", params={"has": "n_cytotox"}).json()["items"]
    assert [(i["molecule_chembl_id"], i["pref_name"]) for i in found] == [
        (MACOZINONE, "MACOZINONE")
    ]
    assert screens.get("/hits", params={"sort": "score"}).status_code == 400


def test_a_compound_known_only_from_a_screen_has_a_page(screens: TestClient) -> None:
    page = screens.get("/compounds/CHEMBL_POTENCY_ONLY").json()
    assert page["genes"] == []
    assert page["tested_in"][0]["screen_id"] == "chembl:CHEMBL_DOC3"
    assert screens.get("/compounds/CHEMBL_NOWHERE").status_code == 404


def test_the_gene_table_carries_screen_columns_with_their_nulls(screens: TestClient) -> None:
    """No call is read from ChEMBL, so a gene screened only there has NULL actives, not 0."""
    (dpre1,) = screens.get("/targets", params={"q": "Rv3790"}).json()["items"]
    assert dpre1["n_target_screens"] >= 1
    assert dpre1["n_screen_actives"] is None
    flagged = screens.get("/targets", params={"has_target_screen": True}).json()["items"]
    assert "Rv3790" in {g["rv_id"] for g in flagged}


def test_search_and_meta_know_the_campaigns(screens: TestClient) -> None:
    found = screens.get("/search", params={"q": "9000008"}).json()["screens"]
    assert "pubchem:9000008" in [hit["id"] for hit in found]
    counts = screens.get("/meta").json()["counts"]
    assert counts["screens"] == screens.get("/screens").json()["total"]
    assert counts["profiled_compounds"] == 2


def test_screen_rows_are_drawn_from_compound_structures(screens: TestClient) -> None:
    """`compounds` is the potency set; the screened set's structures are in their own table."""
    page = screens.get("/screens/pubchem:9000008/results").json()
    drawn = {row["molecule_chembl_id"]: row["smiles"] for row in page["items"]}
    assert drawn[MACOZINONE] == CHEMREPS_SMILES
    # Three rows; two are PubChem-only CIDs, never looked up, so one can be drawn.
    assert (page["total"], page["n_with_structure"]) == (3, 1)
    # Looked up and not found is a row in compound_structures, and is not drawable either.
    paper = screens.get("/screens/chembl:CHEMBL_DOC3/results", params={"limit": 500}).json()
    molecules = [row["molecule_chembl_id"] for row in paper["items"]]
    assert "CHEMBL_ADME_ONLY" in molecules and paper["total"] == len(molecules)
    drawable = {MACOZINONE, "CHEMBL_POTENCY_ONLY"}
    assert paper["n_with_structure"] == sum(m in drawable for m in molecules)


def test_hit_profiling_counts_structures_from_compound_structures(screens: TestClient) -> None:
    """Looked up and absent (ADME-only) is not drawable, and neither is never looked up."""
    page = screens.get("/hits").json()
    assert page["population"]["with_structure"] == 2
    smiles = {row["molecule_chembl_id"]: row["smiles"] for row in page["items"]}
    assert smiles["CHEMBL_POTENCY_ONLY"] == "CCO"
    assert smiles["CHEMBL_ADME_ONLY"] is None


def test_a_compound_known_only_from_a_screen_carries_its_structure(screens: TestClient) -> None:
    assert screens.get("/compounds/CHEMBL_POTENCY_ONLY").json()["smiles"] == "CCO"
    assert screens.get("/compounds/CHEMBL_ELSEWHERE").json()["smiles"] is None


def test_a_store_built_before_compound_structures_still_answers(
    screen_store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    copy = tmp_path / "store"
    shutil.copytree(screen_store, copy)
    (copy / "compound_structures.parquet").unlink()
    for module in (api, store, summary):
        monkeypatch.setattr(module, "STORE", copy)
    client = TestClient(api.app)
    # Not built is not "none can be drawn": NULL, the rule `counts()` keeps for a layer.
    assert client.get("/hits").json()["population"]["with_structure"] is None
    results = client.get("/screens/pubchem:9000008/results").json()
    assert results["n_with_structure"] is None
    assert {row["smiles"] for row in results["items"]} == {None}
    assert client.get("/compounds/CHEMBL_POTENCY_ONLY").json()["smiles"] is None


def test_every_request_shares_one_memory_ceiling(screens: TestClient) -> None:
    """A connection per request was an instance per request, each with 80% of RAM."""
    first, second = api._db(), api._db()
    assert first.execute("SELECT current_setting('memory_limit')").fetchone()[0] == "488.2 MiB"
    disk = first.execute("SELECT current_setting('max_temp_directory_size')").fetchone()[0]
    assert disk == "7.4 GiB"  # 8GB, not 90% of the free disk
    # Working memory is per thread: on 18, /hits needed 448-512 MB; on 4, under 256.
    assert first.execute("SELECT current_setting('threads')").fetchone()[0] == 4
    first.execute("CREATE TABLE shared_probe AS SELECT 1 AS x")
    assert second.execute("SELECT x FROM shared_probe").fetchone() == (1,)
    first.execute("DROP TABLE shared_probe")


def test_the_profile_is_built_once_and_rebuilt_with_the_store(
    screen_store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Shared across requests, so it must notice a rebuild rather than serve the old one."""
    copy = tmp_path / "store"
    shutil.copytree(screen_store, copy)
    for module in (api, store, summary):
        monkeypatch.setattr(module, "STORE", copy)
    client = TestClient(api.app)
    assert client.get("/hits").json()["population"]["with_structure"] == 2
    built = api._profiles[copy]
    client.get("/hits", params={"coverage": "potency_only"})
    assert api._profiles[copy] == built  # the same table, not a second one
    # A rebuild in which the potency-only compound was not found.
    rows = [
        {**row, "has_structure": False, "canonical_smiles": None, "standard_inchi_key": None}
        if row["molecule_chembl_id"] == "CHEMBL_POTENCY_ONLY"
        else row
        for row in store.records("compound_structures", store=copy)
    ]
    for row in rows:
        for column in ("source", "source_version", "retrieved_at"):
            row.pop(column)
    store.write_parquet(
        "compound_structures",
        rows,
        source="chembl",
        source_version="chembl_37",
        retrieved_at="2026-10-12",
        store=copy,
    )
    assert client.get("/hits").json()["population"]["with_structure"] == 1
    old = built[1]
    with pytest.raises(duckdb.CatalogException):
        api._db().execute(f"SELECT 1 FROM {old}")  # dropped, not left to accumulate


def test_a_rebuild_mid_request_does_not_pull_the_profile_from_under_it(
    screen_store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`/hits` runs three queries; a rebuild another request notices between them drops the
    shared table, so each request reads its own copy rather than the shared name."""
    copy = tmp_path / "store"
    shutil.copytree(screen_store, copy)
    for module in (api, store, summary):
        monkeypatch.setattr(module, "STORE", copy)
    reader = api._db()
    table = api._profile(reader)
    before = reader.execute(f"SELECT count(*) FROM {table}").fetchone()
    shutil.copy2(copy / "compound_structures.parquet", tmp_path / "cs.parquet")
    (copy / "compound_structures.parquet").unlink()
    shutil.copy(tmp_path / "cs.parquet", copy / "compound_structures.parquet")  # a new mtime
    assert TestClient(api.app).get("/hits").status_code == 200  # rebuilds, drops the old one
    assert reader.execute(f"SELECT count(*) FROM {table}").fetchone() == before


def test_a_store_without_screen_results_says_so(client: TestClient) -> None:
    assert client.get("/screens").status_code == 503
    assert "screens" not in client.get("/meta").json()["counts"]


@pytest.mark.parametrize(
    ("coverage", "expected"),
    [
        ("beyond_potency", {MACOZINONE, "CHEMBL_ADME_ONLY"}),
        ("potency_only", {"CHEMBL_POTENCY_ONLY", "CHEMBL_BOUND_ONLY", "CHEMBL_PROTEIN"}),
        ("elsewhere_only", {"CHEMBL_ELSEWHERE"}),
    ],
)
def test_profile_coverage_filters_partition_population(
    screens: TestClient, coverage: str, expected: set[str]
) -> None:
    page = screens.get("/hits", params={"coverage": coverage}).json()
    assert {row["molecule_chembl_id"] for row in page["items"]} == expected
    assert page["total"] == page["population"][coverage]


def test_profile_filters_combine_with_campaign_and_measurements(screens: TestClient) -> None:
    page = screens.get(
        "/hits",
        params={
            "coverage": "beyond_potency",
            "has": ["n_mtb_whole_cell", "n_cytotox"],
            "screen": "chembl:CHEMBL_DOC3",
        },
    ).json()
    assert [row["molecule_chembl_id"] for row in page["items"]] == [MACOZINONE]
    assert screens.get("/hits", params={"coverage": "unknown"}).status_code == 422


def test_campaign_gene_search_accepts_name_or_locus(screens: TestClient) -> None:
    locus = screens.get("/screens", params={"rv_id": "rv3790"}).json()
    name = screens.get("/screens", params={"rv_id": "DPRE1"}).json()
    assert locus["total"] > 0
    assert locus["items"] == name["items"]
    assert 0 < locus["n_own_genes"] <= locus["n_genes"]


def test_compound_evidence_matches_profile_and_preserves_provenance(screens: TestClient) -> None:
    evidence = screens.get(
        f"/compounds/{MACOZINONE}/screen-evidence", params={"category": "mammalian_cytotox"}
    ).json()
    profile = screens.get("/hits", params={"q": MACOZINONE}).json()["items"][0]
    assert len({row["stage_id"] for row in evidence["items"]}) == profile["n_cytotox"]
    assert all(row["molecule_chembl_id"] == MACOZINONE for row in evidence["items"])
    assert all(row["source"] == "chembl" and not row["derived"] for row in evidence["items"])
    assert all(row["source_version"] and row["retrieved_at"] for row in evidence["items"])
    assert evidence["items"][0]["description"]
    assert evidence["items"][0]["screen_title"]


def test_compound_evidence_paginates_and_selectivity_keeps_bounds(screens: TestClient) -> None:
    url = f"/compounds/{MACOZINONE}/screen-evidence"
    full = screens.get(url).json()
    first = screens.get(url, params={"limit": 1}).json()
    second = screens.get(url, params={"limit": 1, "offset": 1}).json()
    assert first["total"] == second["total"] == full["total"] > 1
    assert first["items"] + second["items"] == full["items"][:2]
    ratios = screens.get(url, params={"category": "selectivity"}).json()
    assert ratios["total"] == 2
    assert {row["standard_value"] for row in ratios["items"]} == {40, 1000}
    assert any(row["standard_relation"] == ">" for row in ratios["items"])
    assert screens.get(url, params={"limit": 1001}).status_code == 422
    assert screens.get(url, params={"category": "unknown"}).status_code == 422
