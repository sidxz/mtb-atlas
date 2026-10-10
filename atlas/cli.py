"""`atlas build` -- run the pipeline. Ingesters are idempotent, so re-running is cheap."""

from __future__ import annotations

import argparse

from . import crosswalk
from .store import read


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="atlas", description=__doc__)
    parser.add_argument(
        "command", choices=("build", "summary"), help="build the store, or summarise it"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-download raw files instead of using the on-disk cache",
    )
    args = parser.parse_args(argv)

    if args.command == "build":
        for path in crosswalk.build_all(force=args.force):
            print(f"wrote {path.relative_to(path.parent.parent.parent)}")
        return 0

    print(
        read("crosswalk").aggregate("""
            count(*) AS genes,
            count(uniprot_acc) AS with_accession,
            sum(conflict::int) AS conflicts,
            sum(shared_accession::int) AS shared_accession,
            sum((n_pdb > 0)::int) AS with_structure,
            sum((n_chembl_targets > 0)::int) AS with_chembl_target,
            sum((chembl_evidence = 'orthologue')::int) AS via_orthologue
        """)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
