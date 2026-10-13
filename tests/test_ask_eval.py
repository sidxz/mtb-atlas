"""`atlas eval-ask`: does the model the deployer chose answer the atlas's questions?

The model is faked here; the point is that the questions read their expected
answers from the store, and that the checks pass a right answer and catch a
plausible wrong one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atlas import agent, ask_eval, store


@pytest.fixture(autouse=True)
def _store(evidence_store: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store, "STORE", evidence_store)


@pytest.mark.parametrize(
    ("answer", "expected", "ok"),
    [
        ("dprE1 is Rv3790.", "Rv3790", True),
        ("It is **Rv3790**", "Rv3790", True),
        ("Rv37901 is a different locus", "Rv3790", False),
        ("Rv3790c", "Rv3790", False),
    ],
)
def test_a_token_must_stand_alone(answer: str, expected: str, ok: bool) -> None:
    assert ask_eval.has_token(answer, expected) is ok


@pytest.mark.parametrize(
    ("answer", "expected", "ok"),
    [
        ("inhA has 135 structures.", "135", True),
        ("There are 1,234 genes", "1234", True),
        ("There are 1234 genes", "1234", True),
        ("There are 12345 genes", "1234", False),
        ("about 135.5 on average", "135", False),
        ("Rv0135 is unrelated", "135", False),
    ],
)
def test_a_number_must_be_that_number(answer: str, expected: str, ok: bool) -> None:
    assert ask_eval.has_number(answer, expected) is ok


@pytest.mark.parametrize(
    ("answer", "expected", "ok"),
    [
        ("No. mmpL3 is not in the catalogue.", "no", True),
        ("**No** — it is absent.", "no", True),
        ("Yes, it is.", "no", False),
        ("Not in the catalogue, yes.", "no", False),
    ],
)
def test_yes_or_no_is_read_from_the_first_word(answer: str, expected: str, ok: bool) -> None:
    assert ask_eval.says(answer, expected) is ok


def test_expectations_come_from_the_store_and_absent_genes_are_skipped() -> None:
    by_name = {case.name: case for case in ask_eval.cases()}
    assert by_name["dprE1 locus tag"].expected == "Rv3790"
    assert by_name["mmpL3 in the WHO catalogue"].expected == "no"
    inha = store.read("target_summary").filter("gene_name = 'inhA'").fetchone()
    assert by_name["inhA structures"].expected == str(inha[inha_index()])
    # The fixture store has no groEL2, so its question is not asked rather than failed.
    assert "groEL2 human homologue" not in by_name
    assert "essential genes with a structure" in by_name


def inha_index() -> int:
    return store.read("target_summary").columns.index("n_pdb")


def _answers(right: bool):
    def ask(question: str, **_: object) -> agent.Answer:
        case = next(c for c in ask_eval.cases() if c.question == question)
        if not right:
            return agent.Answer(text="I believe the answer is 42, and yes.")
        if case.check is ask_eval.says:
            return agent.Answer(text=f"{case.expected.capitalize()}.")
        return agent.Answer(text=f"The answer is {case.expected}.")

    return ask


def test_right_answers_pass_and_wrong_ones_fail() -> None:
    lines: list[str] = []
    assert ask_eval.run(ask=_answers(True), out=lines.append) == 0
    assert all(line.startswith(("PASS", "#")) for line in lines if line)

    lines.clear()
    failures = ask_eval.run(ask=_answers(False), out=lines.append)
    assert failures == len(ask_eval.cases())
    assert any(line.startswith("FAIL") for line in lines)


def test_a_backend_error_is_a_failure_not_a_crash() -> None:
    def broken(question: str, **_: object) -> agent.Answer:
        raise RuntimeError("The model call failed: connection refused")

    lines: list[str] = []
    assert ask_eval.run(ask=broken, out=lines.append) == len(ask_eval.cases())
    assert any("connection refused" in line for line in lines)
