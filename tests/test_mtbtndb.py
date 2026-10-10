"""Conditional TnSeq across published screens, read from TRANSIT's raw output.

Two things are being proved here, and they are the reason this source is read
raw instead of from the authors' processed table.

The first is that a gene with no transposon insertions has nothing to compare,
and TRANSIT still prints `log2FC 0.00, q 1.00000` for it. Only `Sum Ctrl` and
`Sum Exp` tell that apart from a real "no effect", and the processed table drops
both. Note that this is a property of the *screen*, not of the gene: `katG`
takes no insertions in Griffin's library and is one of the strongest hits in
Smith's.

The second is the trap the data cannot fix. TRANSIT counts TA sites over the
whole ORF; Griffin counted 5-80% of it. So `dprE1` and `mmpL3`, which Griffin's
own table reports as `n/a`, carry fold changes here, built on insertions at the
ORF ends where they are least likely to disrupt anything. The value is kept --
it is what the source says -- and must never be shown without `measured` and
the gene's essentiality call beside it.
"""

from __future__ import annotations

import pytest

from atlas.sources import mtbtndb

from .conftest import FIXTURES

ARCHIVE = FIXTURES / "mtbtndb_transit_outputs.tar.gz"
GRIFFIN = "griffin_cholesterol_vs_griffin_glycerol"
REFERENCE = "CC001.Unc_vs_mbio_H37Rv"
STRAIN_VS_STRAIN = "CC002.Unc_vs_C57BL.6J"
DRUG = "bellerose_MB_HRZE_wk1_vs_bellerose_MB_d21_untreated"
RVBD = "xu_inh_02_vs_xu_inh_0"


@pytest.fixture(scope="session")
def rows() -> list[dict]:
    return list(mtbtndb.normalize(ARCHIVE))


@pytest.fixture(scope="session")
def screens() -> dict[str, dict]:
    described = mtbtndb.annotation(FIXTURES / "mtbtndb_col_desc.tsv")
    return {s["screen_id"]: s for s in mtbtndb.screens(ARCHIVE, described)}


@pytest.fixture(scope="session")
def by_screen(rows: list[dict]) -> dict[str, dict[str, dict]]:
    out: dict[str, dict[str, dict]] = {}
    for row in rows:
        out.setdefault(row["screen_id"], {})[row["rv_id"]] = row
    return out


def test_a_measured_gene_carries_every_number_transit_reported(by_screen: dict) -> None:
    cyp125 = by_screen[GRIFFIN]["Rv3545c"]
    assert cyp125["measured"] is True
    assert cyp125["sum_control"] == pytest.approx(5944.6)
    assert cyp125["sum_experimental"] == pytest.approx(1303.54)
    assert cyp125["log2fc"] == pytest.approx(-2.77)
    assert cyp125["q_value"] == pytest.approx(0.0)
    assert cyp125["n_ta_sites"] == 24


def test_zero_insertions_is_unmeasured_not_unaffected(by_screen: dict) -> None:
    """The 534-gene class. The number is there; `measured` is what denies it."""
    for rv_id in ("Rv0001", "Rv0440", "Rv1484", "Rv1908c"):  # dnaA, groEL2, inhA, katG
        row = by_screen[GRIFFIN][rv_id]
        assert row["measured"] is False
        assert row["sum_control"] == 0
        assert row["sum_experimental"] == 0
        # Exactly what a gene with no effect would also read, which is the point.
        assert row["log2fc"] == 0.0
        assert row["q_value"] == pytest.approx(1.0)
        # The sites exist; it is the insertions that do not.
        assert row["n_ta_sites"] > 0


def test_unmeasurable_is_a_property_of_the_screen_not_the_gene(by_screen: dict) -> None:
    """katG: no insertions in Griffin's library, a top hit in Smith's."""
    assert by_screen[GRIFFIN]["Rv1908c"]["measured"] is False
    smith = by_screen[REFERENCE]["Rv1908c"]
    assert smith["measured"] is True
    assert smith["sum_control"] == pytest.approx(78938.2)
    assert smith["log2fc"] == pytest.approx(-6.78)
    assert smith["q_value"] == pytest.approx(0.0)


def test_the_window_limited_genes_still_get_a_value_here(by_screen: dict) -> None:
    """dprE1 and mmpL3 read `n/a` in Griffin's own table and a fold change here.

    Griffin counts TA sites in 5-80% of the ORF and finds nothing; TRANSIT
    counts the whole ORF and finds reads at the ends. Both numbers are faithful
    to their method, so the row is kept and the disagreement is reported.
    """
    dpre1 = by_screen[GRIFFIN]["Rv3790"]
    assert dpre1["measured"] is True
    assert dpre1["log2fc"] == pytest.approx(0.37)
    assert dpre1["n_ta_sites"] == 27  # Griffin's own table says 20, over 5-80%

    mmpl3 = by_screen[GRIFFIN]["Rv0206c"]
    assert mmpl3["measured"] is True
    assert mmpl3["log2fc"] == pytest.approx(-1.67)
    assert mmpl3["n_ta_sites"] == 34  # Griffin: 26


def test_a_single_read_counts_as_measured_and_shows_why(by_screen: dict) -> None:
    """inhA on 1.3 reads over 9 sites. Measured, and weak -- the counts say so.

    The line is structural (any insertion at all), not a power calculation this
    atlas invented. Anyone wanting a stricter threshold has the numbers.
    """
    inha = by_screen[REFERENCE]["Rv1484"]
    assert inha["measured"] is True
    assert inha["sum_control"] == pytest.approx(1.3)
    assert inha["sum_experimental"] == 0
    assert inha["n_ta_sites"] == 9


def test_the_host_genetics_panel_is_skipped(by_screen: dict, screens: dict) -> None:
    """Strain against strain is a host-genetics question, 1833 of 1969 files."""
    assert STRAIN_VS_STRAIN not in by_screen
    assert STRAIN_VS_STRAIN not in screens


def test_a_strain_against_the_reference_library_is_kept(screens: dict) -> None:
    """The same panel measured against the shared library is in-vivo evidence."""
    row = screens[REFERENCE]
    assert row["study"] == "2020_Smith"
    assert row["control_study"] == "2017A_DeJesus"
    assert row["cross_study"] is True
    assert row["experimental"] == "CC001.Unc"
    assert row["control"] == "mbio_H37Rv"


def test_a_within_study_screen_is_not_flagged_cross_study(screens: dict) -> None:
    for screen, study in ((GRIFFIN, "2011_Griffin"), (DRUG, "2019_Bellerose")):
        row = screens[screen]
        assert row["study"] == study
        assert row["control_study"] == study
        assert row["cross_study"] is False


def test_replicate_counts_come_from_the_wig_list(screens: dict) -> None:
    row = screens[GRIFFIN]
    assert row["n_replicates_control"] == 2
    assert row["n_replicates"] == 3


def test_a_screen_carries_the_authors_own_description(screens: dict) -> None:
    """The condition annotation, joined on the authors' own screen id."""
    griffin = screens[GRIFFIN]
    assert griffin["annotated"] is True
    assert griffin["condition_class"] == "in_vitro"
    assert griffin["carbon_source"] == "cholesterol"
    assert "cholesterol" in griffin["description"]

    inh = screens[RVBD]
    assert inh["stress"] == "Isoniazid"
    assert inh["condition_class"] == "in_vitro"
    assert inh["carbon_source"] == "glycerol"

    mice = screens[DRUG]
    assert mice["condition_class"] == "in_vivo"
    assert mice["mouse_strain"] == "BALB/cJ"


def test_an_unannotated_screen_is_null_not_in_vitro(screens: dict) -> None:
    """The authors call the host panel `<strain>_vs_in_vitro`; the archive does
    not, and no file uses that name. Rather than match them by guesswork, the
    screen is left undescribed -- and `annotated` says so, so "no condition
    recorded" can never be read as "in vitro".
    """
    row = screens[REFERENCE]
    assert row["annotated"] is False
    assert row["condition_class"] is None
    assert row["medium"] is None
    assert row["mouse_strain"] is None
    # It is still fully identified: the slug and both studies are known.
    assert row["study"] == "2020_Smith"


def test_a_missing_cell_is_none_not_a_dash(screens: dict) -> None:
    """`-` is how the table writes "not applicable"."""
    assert screens[DRUG]["carbon_source"] is None
    assert screens[GRIFFIN]["stress"] is None


def test_the_second_annotation_is_keyed_back_onto_rv_tags(by_screen: dict) -> None:
    """Eight screens were resampled against H37RvBD and say `RVBD_3790`.

    They dropped silently until the screen count came back 128 instead of 136,
    and they are the drug-exposure series -- isoniazid, rifampicin, ethambutol,
    vancomycin, meropenem -- so losing them would have cost the most useful
    conditions in the source.
    """
    rows = by_screen[RVBD]
    assert "RVBD_3790" not in rows
    dpre1 = rows["Rv3790"]
    assert dpre1["log2fc"] == pytest.approx(1.34)
    assert dpre1["measured"] is True
    assert rows["Rv1484"]["measured"] is False  # inhA, no insertions, under INH


def test_a_screen_that_parses_to_nothing_is_an_error_not_an_absence(tmp_path) -> None:
    """The guard that would have caught the RVBD annotation immediately."""
    import io
    import tarfile

    broken = tmp_path / "broken.tar.gz"
    body = b"#Control Data: b'2011_Griffin/a.wig'\n#Orf\tName\n" + b"XYZ_0001\t-\n"
    with tarfile.open(broken, "w:gz") as tar:
        info = tarfile.TarInfo("Results/result_resampling_made_up_vs_nothing.txt")
        info.size = len(body)
        tar.addfile(info, io.BytesIO(body))
    with pytest.raises(ValueError, match="parsed no genes"):
        list(mtbtndb.normalize(broken))


def test_non_resampling_members_are_ignored(by_screen: dict) -> None:
    """The archive also ships a loess dump and a batch log."""
    assert set(by_screen) == {GRIFFIN, REFERENCE, DRUG, RVBD}


def test_every_row_is_attributable(rows: list[dict], screens: dict) -> None:
    for row in rows:
        assert "Jinich" in row["citation"]
    for screen in screens.values():
        assert screen["study"]
    assert mtbtndb.DATA_DOI in mtbtndb.SOURCE_VERSION
    # The annotation is a different file with a different provenance, pinned to
    # the commit the paper cites rather than to a moving branch.
    assert mtbtndb.PAPER_COMMIT in mtbtndb.ANNOTATION_URL
    assert "master" not in mtbtndb.ANNOTATION_URL
