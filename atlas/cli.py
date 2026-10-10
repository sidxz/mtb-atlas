"""`atlas build` -- run the pipeline. Ingesters are idempotent, so re-running is cheap.

Keeping it current is three more: `check` asks every source whether it has
released, `refresh <source>` rebuilds only what that source feeds, and `diff`
says what the rebuild did to the numbers.
"""

from __future__ import annotations

import argparse

from . import freshness, pipeline, storediff
from .store import read
from .summary import counts

STATE_MARK = {
    "stale": "STALE",
    "current": "ok",
    "frozen": "frozen",
    "unknown": "?",
    "unbuilt": "unbuilt",
}


def _check(expensive: bool, only: str | None) -> int:
    reports = freshness.check(expensive=expensive, only=only)
    width = max(len(r.source) for r in reports)
    for report in sorted(reports, key=lambda r: (r.state != "stale", r.source)):
        mark = STATE_MARK[report.state]
        print(f"  {mark:<7} {report.source:<{width}}  {report.stored or '—'}")
        if report.detail:
            print(f"  {'':<7} {'':<{width}}  {report.detail}")
        if report.rebuilds:
            print(f"  {'':<7} {'':<{width}}  rebuild: {' -> '.join(report.rebuilds)}")
    stale = [r for r in reports if r.state == "stale"]
    print()
    if stale:
        print(f"{len(stale)} source(s) have moved. Refresh with:")
        for report in stale:
            print(f"  uv run atlas refresh {report.source}")
    else:
        print("Everything in the store is the current release.")
    return 0


def _diff() -> int:
    diffs = storediff.compare()
    changed = [d for d in diffs if d.changed]
    if not changed:
        print(f"{len(diffs)} tables, none changed.")
        return 0
    width = max(len(d.table) for d in changed)
    for d in changed:
        before = "absent" if d.before is None else f"{d.before:,}"
        after = "absent" if d.after is None else f"{d.after:,}"
        delta = "" if d.before is None or d.after is None else f"  ({d.after - d.before:+,})"
        print(f"  {d.table:<{width}}  {before:>9} -> {after:>9}{delta}")
        if d.added or d.removed:
            print(f"  {'':<{width}}  +{d.added:,} / -{d.removed:,} by key")
            for label, examples in (("+", d.examples_added), ("-", d.examples_removed)):
                if examples:
                    print(f"  {'':<{width}}    {label} {', '.join(examples)}")
        elif not d.keyed:
            print(f"  {'':<{width}}  no key declared; compared on row count only")
        if d.version_before != d.version_after:
            print(f"  {'':<{width}}  version {d.version_before} -> {d.version_after}")
    print(f"\n{len(changed)} of {len(diffs)} tables changed.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="atlas", description=__doc__)
    parser.add_argument(
        "command",
        choices=(
            "build",
            "identity",
            "evidence",
            "clinical",
            "summary",
            "check",
            "refresh",
            "diff",
        ),
        help="build everything or one stage; check for upstream releases; "
        "refresh one source; diff the store against the one before the last refresh",
    )
    parser.add_argument(
        "source",
        nargs="?",
        help=f"for refresh and check: one of {', '.join(sorted(freshness.BY_NAME))}",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-download raw files instead of using the on-disk cache",
    )
    parser.add_argument(
        "--expensive",
        action="store_true",
        help="for check: also replay the RCSB structure search, which is the only "
        "way to count its entries and the only probe that is not a single request",
    )
    args = parser.parse_args(argv)

    if args.command == "check":
        return _check(args.expensive, args.source)

    if args.command == "diff":
        return _diff()

    if args.command == "refresh":
        if not args.source:
            parser.error("refresh needs a source: " + ", ".join(sorted(freshness.BY_NAME)))
        source = freshness.BY_NAME.get(args.source)
        if source is None:
            parser.error(
                f"{args.source} is not a source. One of: " + ", ".join(sorted(freshness.BY_NAME))
            )
        if source.frozen:
            # Allowed -- a corrupt cache is a reason -- but it cannot bring
            # anything new, and saying so is cheaper than letting someone
            # wonder why the diff is empty.
            print(f"note: {source.name} is {source.frozen}, so this cannot bring new data.")
        for path in pipeline.refresh(args.source):
            print(f"wrote {path.relative_to(path.parent.parent.parent)}")
        print("\nNow run `uv run atlas diff` to see what moved.")
        return 0

    if args.command in ("build", "identity", "evidence", "clinical"):
        # A single stage assumes the earlier ones are already in the store, and
        # the evidence and clinical stages refresh the per-gene roll-up after.
        runner = {
            "build": pipeline.build_all,
            "identity": pipeline.build_identity,
            # The roll-up reads the clinical tables where they exist, so the
            # evidence stage refreshes their links first -- no network, they
            # are joins over the store. Where they do not exist, the roll-up
            # leaves the clinical columns NULL and says so.
            "evidence": lambda force: [
                *pipeline.build_evidence(force=force),
                *pipeline.relink_clinical(),
                pipeline.build_summary(),
            ],
            "clinical": lambda force: [
                *pipeline.build_clinical(force=force),
                pipeline.build_summary(),
            ],
        }[args.command]
        for path in runner(force=args.force):
            print(f"wrote {path.relative_to(path.parent.parent.parent)}")
        return 0

    if args.command == "summary":
        for key, value in counts().items():
            print(f"{value:>8,}  {key.replace('_', ' ')}")
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
