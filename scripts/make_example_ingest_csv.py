#!/usr/bin/env python3
"""
Writes frontend/public/example_ingest.csv: one nominal lot from the SEEDED generator in the ingest
format, plus rows that exercise the ingest rules (a latent-defect part that stays under the 50 uA
static limit, a part with a missing 24h cell, a non-numeric cell and a duplicate part ID).

    python scripts/make_example_ingest_csv.py [--seed 2002] [--parts 60]
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from data_engine.generator import BurnInSyntheticGenerator  # noqa: E402

PARAMS = ("leakage_current_ua", "iddq_ma", "propagation_delay_ns")
OUT = os.path.join(os.path.dirname(__file__), "..", "frontend", "public", "example_ingest.csv")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=2002)  # nominal lot with a ~10 uA leakage median
    ap.add_argument("--parts", type=int, default=60)
    args = ap.parse_args()

    df = BurnInSyntheticGenerator(num_lots=5, components_per_lot=args.parts, random_seed=args.seed).generate_dataset()
    lot = df.loc[~df["is_benign_high_lot"], "lot_id"].iloc[0]
    df = df[df["lot_id"] == lot]
    wide = df.pivot_table(index="serial_number", columns="interval_hours", values=list(PARAMS))

    header = ["part_id"] + [f"{p}_{h}h" for h in (0, 24, 96, 168) for p in PARAMS]
    rows = [",".join(header)]
    for sn, r in wide.iterrows():
        rows.append(",".join([sn.replace("LOT-2026-", "EX-")] + [f"{r[(p, h)]:.4f}" for h in (0, 24, 96, 168) for p in PARAMS]))

    # Latent defect (the PS scenario): ~30 uA in a ~10 uA lot, drifting, never above the 50 uA datasheet limit.
    med0 = float(wide[("leakage_current_ua", 0)].median())
    iddq, delay = float(wide[("iddq_ma", 0)].median()), float(wide[("propagation_delay_ns", 0)].median())
    latent = [30.0, iddq, delay, 36.0, iddq * 1.02, delay, 42.0, iddq * 1.04, delay, 48.5, iddq * 1.06, delay]
    rows.append(",".join(["EX-LATENT-001"] + [f"{v:.4f}" for v in latent]))
    gap = [f"{v:.4f}" for v in latent]
    gap[3] = ""  # missing leakage 24h -> imputed with lot median, part marked insufficient data
    rows.append(",".join(["EX-MISSING-24H"] + gap))
    bad = [f"{v:.4f}" for v in latent]
    bad[1] = "n/a"  # non-numeric -> treated as missing
    rows.append(",".join(["EX-NONNUMERIC"] + bad))
    rows.append(rows[1])  # duplicate part ID -> row rejected

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(rows) + "\n")
    print(f"wrote {OUT}: {len(rows) - 1} data rows (lot median 0h leakage {med0:.2f} uA)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
