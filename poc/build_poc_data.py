"""Build the POC display dataset. NOT part of the pipeline.

This script stands in for the M1 ingesters so the POC views have real numbers to
show. It reads the M0 crosswalk, then adds essentiality, ligand potency and
resistance from sources that M1 will ingest properly, with the same provenance
discipline but none of the caching, rate limiting or tests.

Delete this once M1 lands.

    uv run python poc/build_poc_data.py --dejesus <table-s3.xlsx> --who <master.txt>
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atlas.fetch import fetch_json  # noqa: E402
from atlas.store import provenance, read  # noqa: E402

OUT = Path(__file__).parent / "data" / "atlas-poc.json"

# Genes whose full variant list the target-page POC shows.
FOCUS_GENES = {"inhA", "katG", "rpoB", "dprE1", "mmpL3"}

# WHO gradings that mean "associated with resistance"; 3-5 are uncertain or not
# associated and would overstate the evidence if counted.
ASSOCIATED = ("1) Assoc w R", "2) Assoc w R - Interim")

AA3 = {
    "Ala": "A",
    "Arg": "R",
    "Asn": "N",
    "Asp": "D",
    "Cys": "C",
    "Gln": "Q",
    "Glu": "E",
    "Gly": "G",
    "His": "H",
    "Ile": "I",
    "Leu": "L",
    "Lys": "K",
    "Met": "M",
    "Phe": "F",
    "Pro": "P",
    "Ser": "S",
    "Thr": "T",
    "Trp": "W",
    "Tyr": "Y",
    "Val": "V",
    "Ter": "*",
}
MISSENSE = re.compile(r"^p\.([A-Z][a-z]{2})(\d+)([A-Z][a-z]{2})$")


def residue(mutation: str) -> dict | None:
    """`p.Ser94Ala` -> the pieces a structure viewer needs to highlight it."""
    match = MISSENSE.match(mutation)
    if not match:
        return None
    wild, position, mutant = match.groups()
    return {
        "pos": int(position),
        "from": AA3.get(wild, wild),
        "to": AA3.get(mutant, mutant),
        "label": f"{AA3.get(wild, wild)}{position}{AA3.get(mutant, mutant)}",
    }


def essentiality(xlsx: Path) -> dict[str, dict]:
    """DeJesus 2017 Table S3. Row 1 is a caption; the header is row 2."""
    from openpyxl import load_workbook

    worksheet = load_workbook(xlsx, read_only=True)["ORF Essentiality Calls"]
    rows = worksheet.iter_rows(values_only=True)
    next(rows)
    header = [str(h) for h in next(rows)]
    call = header.index("Final Call")
    sites = header.index("Number of TA Sites")
    insert = header.index("Fraction of Sites with Insertions")
    out = {}
    for row in rows:
        if not row[0]:
            continue
        out[str(row[0])] = {
            "call": row[call],
            "ta_sites": row[sites],
            "insertion_fraction": round(float(row[insert] or 0), 4),
        }
    return out


def who_catalogue(master: Path) -> dict[str, dict]:
    """WHO 2nd edition master file, aggregated per gene symbol."""
    csv.field_size_limit(10**9)
    with master.open(encoding="utf-8", errors="replace") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        per_gene: dict[str, dict] = collections.defaultdict(
            lambda: {
                "associated": 0,
                "total": 0,
                "drugs": set(),
                "variants": {},
                "effects": collections.Counter(),
            }
        )
        for row in reader:
            gene = row["gene"]
            entry = per_gene[gene]
            entry["total"] += 1
            if row["FINAL CONFIDENCE GRADING"] not in ASSOCIATED:
                continue
            entry["associated"] += 1
            entry["drugs"].add(row["drug"])
            entry["effects"][row["effect"]] += 1
            # One row per variant per drug upstream; collapse to the variant and
            # collect the drugs it confers resistance to.
            variant = entry["variants"].setdefault(
                row["mutation"],
                {
                    "mutation": row["mutation"],
                    "grading": row["FINAL CONFIDENCE GRADING"],
                    "tier": row["tier"],
                    "effect": row["effect"],
                    "position": row["genomic position"],
                    "residue": residue(row["mutation"]),
                    "drugs": [],
                },
            )
            if row["drug"] not in variant["drugs"]:
                variant["drugs"].append(row["drug"])
            # Grade 1 outranks grade 2 if the same variant appears as both.
            variant["grading"] = min(variant["grading"], row["FINAL CONFIDENCE GRADING"])

    for entry in per_gene.values():
        entry["drugs"] = sorted(entry["drugs"])
        entry["effects"] = dict(entry["effects"])
        variants = sorted(entry["variants"].values(), key=lambda v: (v["grading"], v["mutation"]))
        entry["variants"] = variants
        entry["mappable"] = [v for v in variants if v["residue"]]
    return dict(per_gene)


def chembl_potency(target_ids: list[str]) -> dict[str, dict]:
    """Activity count and best potency per ChEMBL target."""
    out = {}
    for n, target_id in enumerate(target_ids, 1):
        print(f"  chembl {n}/{len(target_ids)} {target_id}", end="\r", file=sys.stderr)
        base = (
            "https://www.ebi.ac.uk/chembl/api/data/activity.json"
            f"?target_chembl_id={target_id}&pchembl_value__isnull=false"
        )
        best = fetch_json(f"{base}&order_by=-pchembl_value&limit=1")
        activities = best.get("activities") or []
        out[target_id] = {
            "n_activities": best["page_meta"]["total_count"],
            "best_pchembl": float(activities[0]["pchembl_value"]) if activities else None,
            "best_compound": activities[0]["molecule_chembl_id"] if activities else None,
            "best_type": activities[0]["standard_type"] if activities else None,
        }
    print(file=sys.stderr)
    return out


def alphafold(accessions: list[str]) -> dict[str, dict]:
    """Mean pLDDT per accession, for the handful of genes a target page shows."""
    out = {}
    for accession in accessions:
        try:
            (model,) = fetch_json(f"https://alphafold.ebi.ac.uk/api/prediction/{accession}")
        except Exception as error:  # noqa: BLE001 - POC: a missing model is not fatal
            print(f"  alphafold {accession}: {error}", file=sys.stderr)
            continue
        out[accession] = {
            "entry_id": model["entryId"],
            "plddt": model["globalMetricValue"],
            "very_high": model["fractionPlddtVeryHigh"],
            "confident": model["fractionPlddtConfident"],
            "low": model["fractionPlddtLow"],
            "very_low": model["fractionPlddtVeryLow"],
            "version": model["latestVersion"],
            "created": model["modelCreatedDate"][:10],
            "cif": model["cifUrl"],
        }
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dejesus", type=Path, required=True, help="mBio Table S3 .xlsx")
    parser.add_argument("--who", type=Path, required=True, help="WHO catalogue master .txt")
    parser.add_argument("--focus", nargs="*", default=["Rv3790", "Rv1484", "Rv0206c"])
    parser.add_argument("--skip-chembl", action="store_true")
    args = parser.parse_args()

    relation = read("crosswalk")
    columns = relation.columns
    genes = [dict(zip(columns, row, strict=True)) for row in relation.fetchall()]
    print(f"crosswalk: {len(genes)} genes", file=sys.stderr)

    ess = essentiality(args.dejesus)
    who = who_catalogue(args.who)
    print(f"essentiality: {len(ess)} ORFs | WHO: {len(who)} genes", file=sys.stderr)

    target_ids = sorted({t["target_id"] for g in genes for t in g["chembl_targets"]})
    potency = {} if args.skip_chembl else chembl_potency(target_ids)

    focus_accs = [g["uniprot_acc"] for g in genes if g["rv_id"] in args.focus and g["uniprot_acc"]]
    models = alphafold(focus_accs)

    out = []
    for gene in genes:
        # WHO keys on gene symbol, and for the unnamed genes the symbol *is* the
        # Rv tag, so try both.
        resistance = who.get(gene["gene_name"] or "") or who.get(gene["rv_id"])
        targets = [
            {**target, **potency.get(target["target_id"], {})} for target in gene["chembl_targets"]
        ]
        out.append(
            {
                "rv_id": gene["rv_id"],
                "gene_name": gene["gene_name"],
                "product": gene["product"],
                "category": gene["functional_category"],
                "start": gene["start"],
                "stop": gene["stop"],
                "strand": gene["strand"],
                "uniprot": gene["uniprot_acc"],
                "acc_status": gene["acc_status"],
                "conflict": gene["conflict"],
                "shared_with": gene["shares_accession_with"],
                "length": gene["length"],
                "n_pdb": gene["n_pdb"],
                "pdb_ids": gene["pdb_ids"][:12],
                "alphafold": gene["alphafold_id"],
                "targets": targets,
                "evidence": gene["chembl_evidence"],
                "n_activities": sum(t.get("n_activities") or 0 for t in targets),
                "best_pchembl": max(
                    (t.get("best_pchembl") for t in targets if t.get("best_pchembl")),
                    default=None,
                ),
                "essentiality": ess.get(gene["rv_id"], {}).get("call"),
                "ta_sites": ess.get(gene["rv_id"], {}).get("ta_sites"),
                "resistance_drugs": gene["resistance_drugs"],
                "who": resistance
                and {
                    "associated": resistance["associated"],
                    "total": resistance["total"],
                    "drugs": resistance["drugs"],
                    "effects": resistance["effects"],
                    "n_mappable": len(resistance["mappable"]),
                    # Only the focus genes carry the full variant list; 65 genes'
                    # worth would triple the payload for no POC benefit.
                    "variants": resistance["variants"][:40]
                    if gene["rv_id"] in args.focus or gene["gene_name"] in FOCUS_GENES
                    else [],
                },
            }
        )

    versions = {name: provenance(name) for name in ("genes", "proteins", "chembl_targets")}
    payload = {
        "generated": max(str(retrieved) for _, retrieved in versions.values()),
        "provenance": {
            "mycobrowser": {
                "version": versions["genes"][0],
                "licence": "none stated (citation requested)",
            },
            "uniprot": {"version": versions["proteins"][0], "licence": "CC BY 4.0"},
            "chembl": {"version": versions["chembl_targets"][0], "licence": "CC BY-SA 3.0"},
            "dejesus": {
                "version": "mBio 2017 Table S3 (PMC5241402)",
                "licence": "CC BY 4.0",
            },
            "who": {
                "version": "WHO catalogue 2nd ed. (2023)",
                "licence": "ODC-By 1.0",
            },
            "alphafold": {"version": "v6", "licence": "CC BY 4.0"},
            "pdb": {"version": "live", "licence": "CC0 1.0"},
        },
        "models": models,
        "genes": out,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, separators=(",", ":")))
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.1f} MB)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
