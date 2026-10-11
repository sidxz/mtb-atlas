"""A structure to work from that is not of this protein: what qualifies.

The roll-up is covered by the fixture store. This runs the real phmmer search
over a tiny synthetic pair of proteomes, because the three decisions the column
rests on are each a branch: the two floors, and the `same_sequence` rule that
separates "this is the protein, under another accession" from "this is a
relative". That last one has a false positive worth a test of its own -- a
perfect match over the whole query, inside a protein twice its length.
"""

from __future__ import annotations

import gzip

import pytest

from atlas.sources import orthologue_structures as ortho

# Two blocks, so a half-length match is unambiguous.
_BLOCK_A = "MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQAPILSRVGDGTQDNLSGAEKAVQVKVKALPDAQFEVVHS"
_BLOCK_B = "LAKWKRQLSEIRHTVDNNTVWVNDGGNGYLLRMADPGSFWNEIAPQLFKLADGVELFVGNTSCVKDGRIIET"
_TARGET = _BLOCK_A + _BLOCK_B
# Substitutions across both halves: a full-length relative, not a copy.
_COUSIN = (_BLOCK_A.replace("KTAYIAK", "KSAYLAR").replace("GDGTQDN", "GEGTQEN")) + (
    _BLOCK_B.replace("LAKWKRQ", "LSKWRRE").replace("GNTSCVK", "GNTACIK")
)
# Something else entirely: the Mtb protein with no mycobacterial relative at all.
_UNRELATED = "MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG" * 2
# Padding for the fusion case. Deliberately not `_UNRELATED`: sharing it would
# make `lonely` match the fusion protein, and the test for an unmatched gene
# would be testing the fixture rather than the rule.
_FILLER = (
    "MSEQNNTEMTFQIQRIYTKDISFEAPNAPHVFQKDWQPEVKLDLDTASSQLADDVYEVVLRVTVTASLGEET"
    "AFLCEVQQGGIFSIAGIEGTQMAHCLGAYCPNILFPYARECITSMVSRGTFPQLNLAPVNFDALFMNYLQQQ"
    "AGEGTEEHQDA"
)


def _fasta(path, entries, *, organism="Mycolicibacterium smegmatis", taxon="246196"):
    with gzip.open(path, "wt") as handle:
        for acc, gene, sequence in entries:
            handle.write(
                f">sp|{acc}|{gene}_MYCXX {gene} protein"
                f" OS={organism} OX={taxon} GN={gene} PE=1 SV=1\n"
            )
            handle.write(f"{sequence}\n")
    return path


@pytest.fixture(scope="module")
def pairs(tmp_path_factory):
    pytest.importorskip("pyhmmer")
    directory = tmp_path_factory.mktemp("orthologue")
    mtb = _fasta(
        directory / "mtb.fasta.gz",
        [("P00001", "target", _TARGET), ("P00009", "lonely", _UNRELATED)],
        organism="Mycobacterium tuberculosis H37Rv",
        taxon="83332",
    )
    hosts = _fasta(
        directory / "hosts.fasta.gz",
        [
            # The protein itself, filed under another accession: same_sequence.
            ("A00001", "twinAcc", _TARGET),
            # A full-length relative: an orthologue, with its numbers.
            ("A00002", "cousin", _COUSIN),
            # A perfect match over the whole query, inside something twice as
            # long. Identity and coverage both say 1.0 and it is still not
            # this protein -- the `O07717`/`Q8VJU4` case.
            ("A00003", "fusion", _TARGET + _FILLER),
            # Half the query: below the coverage floor, so not listed at all.
            ("A00004", "fragment", _BLOCK_A),
        ],
    )
    rows = ortho.bridge(mtb, hosts)
    return {(row["uniprot_acc"], row["via_acc"]): row for row in rows}


def test_an_identical_sequence_under_another_accession_is_the_protein(pairs):
    row = pairs[("P00001", "A00001")]
    assert row["relation"] == "same_sequence"
    assert row["identity"] == 1.0
    assert row["coverage"] == 1.0
    assert row["via_gene"] == "twinAcc"


def test_a_full_length_relative_is_an_orthologue_with_its_numbers(pairs):
    row = pairs[("P00001", "A00002")]
    assert row["relation"] == "orthologue"
    assert ortho.MIN_IDENTITY <= row["identity"] < 1.0
    assert row["coverage"] >= ortho.MIN_COVERAGE


def test_a_perfect_match_inside_a_longer_protein_is_not_the_protein(pairs):
    """Identity 1.0 and coverage 1.0, and still a different protein.

    `fusion` contains the whole query exactly, so both numbers max out. The
    query/target length ratio is what tells them apart, and it is the same
    measurement as coverage taken from the target's end.
    """
    row = pairs[("P00001", "A00003")]
    assert row["identity"] == 1.0
    assert row["coverage"] == 1.0
    assert row["relation"] == "orthologue"


def test_a_partial_match_is_below_the_coverage_floor(pairs):
    """A shared domain is not a structure of this protein."""
    assert ("P00001", "A00004") not in pairs


def test_a_protein_with_no_mycobacterial_relative_gets_no_row(pairs):
    """Absence is the answer, and it has to be able to mean absence."""
    assert not [key for key in pairs if key[0] == "P00009"]


def test_the_headers_carry_organism_taxon_and_gene(pairs):
    """One download: the FASTA header holds what a second TSV stream would."""
    row = pairs[("P00001", "A00002")]
    assert row["via_organism"] == "Mycolicibacterium smegmatis"
    assert row["via_taxon"] == "246196"
    assert row["via_gene"] == "cousin"


def test_an_organism_with_spaces_and_brackets_survives_the_header(tmp_path):
    """Strain names hold spaces, slashes and brackets, so ` OX=` is the delimiter."""
    name = "Mycolicibacterium smegmatis (strain ATCC 700084 / mc(2)155)"
    path = _fasta(tmp_path / "h.fasta.gz", [("A00001", "x", _TARGET)], organism=name)
    assert ortho._hosts(path)["A00001"]["via_organism"] == name


def test_structures_are_joined_per_entry_not_per_pair():
    """One row per (Mtb protein, neighbour's entry), so entries are countable."""
    pair = {"uniprot_acc": "P00001", "via_acc": "A00001", "relation": "orthologue"}
    structures = [
        {
            "uniprot_acc": "A00001",
            "pdb_id": pdb_id,
            "title": None,
            "method": "X-RAY DIFFRACTION",
            "resolution": 2.0,
            "released": "2020-01-01",
            "entity_description": None,
            "n_ligands": 1,
            "ligand_ids": ["LIG"],
        }
        for pdb_id in ("1ABC", "2ABC")
    ]
    # A structure belonging to a neighbour nobody bridged to must not be joined.
    structures.append({**structures[0], "uniprot_acc": "A09999", "pdb_id": "9ZZZ"})
    rows = list(ortho.normalize([pair], structures))
    assert [row["pdb_id"] for row in rows] == ["1ABC", "2ABC"]
    assert all(row["uniprot_acc"] == "P00001" for row in rows)


def test_the_floors_are_recorded_in_the_version_the_probe_compares():
    """`atlas check` compares against the same statement the table was stamped from."""
    label = ortho.version_label(1340)
    assert "30% identity" in label
    assert "70% of the query" in label
    assert "1340 entries" in label
    assert ortho.MIN_IDENTITY == 0.30
    assert ortho.MIN_COVERAGE == 0.70
