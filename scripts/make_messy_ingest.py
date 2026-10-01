"""
Write examples/ingest_messy.csv from frontend/public/example_ingest.csv: the same lot as an operator might
export it, i.e. semicolon-delimited, non-canonical headers (Serial Number, I_0 (nA), Iddq_0h, tpd_0h_ps, ...),
leakage in nA and delay in ps, no 96h columns, one blank cell, one non-numeric cell and one duplicate part ID.
Ingest must detect all of it (see tests/test_robust_ingest.py).

    python scripts/make_messy_ingest.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    src = pd.read_csv(ROOT / "frontend" / "public" / "example_ingest.csv")
    out = pd.DataFrame({"Serial Number": src["part_id"]})
    for h in (0, 24, 168):
        out[f"I_{h} (nA)"] = (src[f"leakage_current_ua_{h}h"] * 1000).round(1)
        out[f"Iddq_{h}h"] = src[f"iddq_ma_{h}h"]
        out[f"tpd_{h}h_ps"] = (src[f"propagation_delay_ns_{h}h"] * 1000).round(1)
    out = out.astype(object)
    out.loc[3, "Iddq_24h"] = ""          # blank -> imputed with the lot median, flagged, never 0
    out.loc[5, "tpd_0h_ps"] = "n.a.?"    # non-numeric -> missing
    out = pd.concat([out, out.iloc[[1]]], ignore_index=True)  # duplicate part ID
    path = ROOT / "examples" / "ingest_messy.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, sep=";", index=False)
    print(f"wrote {path} ({len(out)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
