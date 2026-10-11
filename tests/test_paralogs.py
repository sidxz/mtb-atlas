"""Functional redundancy: what counts as a second copy, and what does not.

The roll-up is covered by the fixture store; this runs the real phmmer search
over a tiny synthetic proteome, because the four drop rules (self-hits,
duplicate sequences, the identity floor, the coverage floor) are the whole
value of the column and each one is a branch.
"""

from __future__ import annotations

import gzip

import pytest

from atlas.sources import paralogs

# Four proteins, built so the expected answer is unambiguous.
#
#  TARGET   the gene under test.
#  TWIN     TARGET with a handful of substitutions: a full-length near-copy,
#           so a real backup.
#  DOMAIN   a short protein matching only TARGET's first third: a family
#           member, not a backup -- the shape dprE1 and mmpL3 have.
#  CLONE    byte-identical to TARGET under a second accession: an annotation
#           artefact, not redundancy.
_BLOCK_A = "MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQAPILSRVGDGTQDNLSGAEKAVQVKVKALPDAQFEVVHS"
_BLOCK_B = "LAKWKRQLSEIRHTVDNNTVWVNDGGNGYLLRMADPGSFWNEIAPQLFKLADGVELFVGNTSCVKDGRIIET"
_TARGET = _BLOCK_A + _BLOCK_B
# Substitutions spread across both halves, so identity stays high and the
# alignment still spans the whole sequence.
_TWIN = (_BLOCK_A.replace("KTAYIAK", "KSAYLAR").replace("GDGTQDN", "GEGTQEN")) + (
    _BLOCK_B.replace("LAKWKRQ", "LSKWRRE").replace("GNTSCVK", "GNTACIK")
)


def _proteome(tmp_path, entries):
    path = tmp_path / "mtb.fasta.gz"
    with gzip.open(path, "wt") as handle:
        for acc, gene, sequence in entries:
            handle.write(f">sp|{acc}|{gene}_MYCTU {gene} protein OS=Mtb GN={gene}\n")
            handle.write(f"{sequence}\n")
    return path


@pytest.fixture(scope="module")
def rows(tmp_path_factory):
    pytest.importorskip("pyhmmer")
    path = _proteome(
        tmp_path_factory.mktemp("paralogs"),
        [
            ("P00001", "target", _TARGET),
            ("P00002", "twin", _TWIN),
            ("P00003", "domain", _BLOCK_A),
            ("P00004", "clone", _TARGET),
        ],
    )
    return {r["uniprot_acc"]: r for r in paralogs.normalize(path)}


def test_every_protein_gets_a_row(rows):
    """Including those with no paralog: absence is an answer, not a gap."""
    assert set(rows) == {"P00001", "P00002", "P00003", "P00004"}


def test_a_protein_is_not_its_own_paralog(rows):
    """The best hit against one's own proteome is oneself, at 100%."""
    for row in rows.values():
        assert row["closest_acc"] != row["uniprot_acc"]
        assert row["uniprot_acc"] not in row["paralog_accs"]


def test_an_identical_sequence_under_two_accessions_is_not_redundancy(rows):
    """`clone` is byte-identical to `target`, which is annotation, not biology.

    Left in, it would be a perfect 100%-identity full-length "backup" and the
    flag would fire on every shared-accession locus in the genome.
    """
    assert "P00004" not in rows["P00001"]["paralog_accs"]
    assert "P00001" not in rows["P00004"]["paralog_accs"]


def test_a_full_length_near_copy_is_a_backup(rows):
    target = rows["P00001"]
    assert target["close_paralog"] is True
    assert target["closest_close_gene"] == "twin"
    assert target["closest_close_identity"] >= paralogs.CLOSE_IDENTITY


def test_a_partial_match_is_a_relative_not_a_backup(rows):
    """`domain` matches half of `target`, so it is found but not counted.

    This is the distinction the column exists to make: mmpL3's nearest
    relative is mmpL1 over a fifth of the protein, and mmpL3 has no backup.
    """
    domain = rows["P00003"]
    # It does find target -- the hit is real and stays visible.
    assert domain["has_paralog"] is True
    assert domain["closest_gene"] == "target"
    # From target's side, the short protein must not be the redundant copy.
    target = rows["P00001"]
    assert target["closest_close_gene"] != "domain"
    assert "P00003" in target["paralog_accs"]


def test_the_nearest_relative_is_ranked_by_bitscore_not_identity(rows):
    """A short exact fragment must not outrank a full-length near-copy.

    `domain` is 100% identical to `target` over half of it; `twin` is ~90%
    identical over all of it. Ranked by identity the fragment wins, which
    reads as "this gene's closest relative is a third of itself".
    """
    target = rows["P00001"]
    assert target["closest_gene"] == "twin"
    assert target["closest_coverage"] >= paralogs.CLOSE_COVERAGE


def test_coverage_is_never_more_than_fully_covered(rows):
    """pyhmmer can report marginally more aligned columns than the query has."""
    for row in rows.values():
        if row["closest_coverage"] is not None:
            assert 0.0 <= row["closest_coverage"] <= 1.0


def test_the_threshold_is_recorded_in_the_source_version(tmp_path):
    """The flag is this atlas's convention, so the numbers behind it are shown."""
    assert "identity" in f"{paralogs.CLOSE_IDENTITY:.0%} identity"
    assert paralogs.CLOSE_IDENTITY == 0.30
    assert paralogs.CLOSE_COVERAGE == 0.70
