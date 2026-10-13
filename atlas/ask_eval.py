"""Does the model the deployer chose answer the atlas's questions? Run before trusting it.

`atlas eval-ask` puts a few fixed questions about the validation genes to whichever
backend ATLAS_LLM names, and checks each answer. The expected answers are read from
the store when the eval runs, never written down here, so a rebuild that moves a
number moves the expectation with it.

The danger with /ask is not a weak model in general but a plausible wrong join that
returns a confident number; a model that does that fails here rather than in front
of a visitor. Five questions are a smoke test, not a benchmark: a pass says the
model can use the two tools and read the schema notes, not that every answer is right.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from dataclasses import dataclass

from . import agent, store


def has_token(answer: str, expected: str) -> bool:
    """`expected` as a whole identifier: Rv3790, not Rv37901 or Rv3790c."""
    return re.search(rf"(?<![\w-]){re.escape(expected)}(?![\w-])", answer) is not None


def has_number(answer: str, expected: str) -> bool:
    """`expected` as a whole number, with or without thousands separators."""
    n = int(expected)
    for form in {f"{n}", f"{n:,}"}:
        if re.search(rf"(?<![\w.,]){re.escape(form)}(?![\w]|[.,]\d)", answer):
            return True
    return False


def says(answer: str, expected: str) -> bool:
    """A yes/no question is answered by the first word, so "not ... yes" cannot pass."""
    first = re.match(r"\W*(\w+)", answer)
    return first is not None and first.group(1).lower() == expected


@dataclass(frozen=True)
class Case:
    name: str
    question: str
    expected: str
    check: Callable[[str, str], bool]


def _gene(name: str) -> dict | None:
    relation = store.read("target_summary").filter(f"gene_name = '{name}'")
    row = relation.fetchone()
    return dict(zip(relation.columns, row, strict=True)) if row else None


def cases() -> list[Case]:
    """The questions this store can grade; a gene the store lacks is not asked."""
    found: list[Case] = []
    if dpre1 := _gene("dprE1"):
        found.append(
            Case(
                "dprE1 locus tag",
                "What is the Rv locus tag of the gene dprE1? Reply with the tag.",
                dpre1["rv_id"],
                has_token,
            )
        )
    if inha := _gene("inhA"):
        found.append(
            Case(
                "inhA structures",
                "How many experimental PDB structures of its own does inhA have in the "
                "atlas? Reply with the number.",
                str(inha["n_pdb"]),
                has_number,
            )
        )
    if mmpl3 := _gene("mmpL3"):
        found.append(
            Case(
                "mmpL3 in the WHO catalogue",
                "Is mmpL3 in the WHO mutation catalogue? Start your reply with yes or no.",
                "yes" if mmpl3["in_who_catalogue"] else "no",
                says,
            )
        )
    if (groel2 := _gene("groEL2")) and groel2.get("human_homolog_gene"):
        found.append(
            Case(
                "groEL2 human homologue",
                "Which human gene is groEL2 most similar to, according to the atlas? "
                "Reply with the gene symbol.",
                groel2["human_homolog_gene"],
                has_token,
            )
        )
    essential = store.read("target_summary").filter("essentiality IN ('ES', 'ESD') AND n_pdb > 0")
    found.append(
        Case(
            "essential genes with a structure",
            "How many genes are essential (ES or ESD) and have at least one experimental "
            "PDB structure of their own? Reply with the number.",
            str(essential.aggregate("count(*)").fetchone()[0]),
            has_number,
        )
    )
    return found


def run(ask: Callable[..., agent.Answer] = agent.ask, out: Callable[[str], None] = print) -> int:
    """Ask every question, print a line each, and return how many failed."""
    described = agent.describe_backend()
    if described:
        out(f"# {described['provider']} · {described['model']} ({described['label']})")
    failures = 0
    for case in cases():
        try:
            answer = ask(case.question).text
        except RuntimeError as error:
            failures += 1
            out(f"FAIL  {case.name}: {error}")
            continue
        if case.check(answer, case.expected):
            out(f"PASS  {case.name} ({case.expected})")
        else:
            failures += 1
            excerpt = " ".join(answer.split())[:160]
            out(f"FAIL  {case.name}: expected {case.expected}, got: {excerpt}")
    out(f"# {failures} of {len(cases())} failed")
    return failures


def main() -> int:
    try:
        agent.backend()
    except RuntimeError as error:
        print(f"Not configured: {error}", file=sys.stderr)
        return 2
    return 1 if run() else 0
