"""
Judge rehearsal against a running stack (scripts/judge_rehearsal.sh brings up a clean one first).
Standard library only. Exit code 1 on the first failed check.

  1. ingest a single-parameter (leakage-only) CSV -> 201, parameters_used == [leakage], every part screened
  2. train judge mode on examples/judge/train.csv (background job) -> done, "trained on" info
  3. predict on examples/judge/test.csv (0h/24h only) -> download preds.csv
  4. score: POST /judge/score (what the UI shows) vs `python -m evaluation.score --predictions preds.csv
     --truth truth.csv` run inside the backend container -> identical numbers
  5. messy file (examples/ingest_messy.csv: renamed headers, nA units, blanks, duplicate IDs, text in numeric
     cells) -> clear validation issues and a clear 409 (unit confirmation) on ingest, no crash (API healthy after)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EX = ROOT / "examples"
FAILED = []


def check(ok: bool, what: str) -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {what}", flush=True)
    if not ok:
        FAILED.append(what)


def call(api: str, path: str, body=None, raw: bool = False):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(api + path, data=data, headers={"Content-Type": "application/json"},
                                 method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            txt = r.read().decode()
            return r.status, (txt if raw else json.loads(txt))
    except urllib.error.HTTPError as e:
        txt = e.read().decode()
        try:
            return e.code, json.loads(txt)
        except ValueError:
            return e.code, txt


def single_parameter_csv() -> str:
    """Leakage-only file derived from the shipped example (columns of the other two parameters removed)."""
    lines = (ROOT / "frontend" / "public" / "example_ingest.csv").read_text().splitlines()
    head = lines[0].split(",")
    keep = [i for i, h in enumerate(head) if h == "part_id" or h.startswith("leakage_current_ua_")]
    return "\n".join(",".join(r.split(",")[i] for i in keep) for r in lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    a = ap.parse_args()
    api = a.api + "/api/v1"
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")

    print("[1] single-parameter ingest (leakage only)")
    s, r = call(api, "/ingest", {"csv": single_parameter_csv(), "lot_number": f"REHEARSAL-SP-{stamp}",
                                 "filename": "leakage_only.csv"})
    check(s == 201, f"ingest -> HTTP {s}")
    if s == 201:
        check(r["validation"]["parameters_used"] == ["leakage_current_ua"],
              f"parameters used: {r['validation']['parameters_used']}")
        check(r["screening"]["n_screened"] == r["validation"]["parts_accepted"],
              f"{r['screening']['n_screened']} parts screened, verdicts {r['screening']['verdicts']}")

    print("[2] judge train on examples/judge/train.csv")
    s, j = call(api, "/judge/train", {"csv": (EX / "judge" / "train.csv").read_text(), "filename": "train.csv"})
    check(s == 202, f"train accepted -> HTTP {s}")
    for _ in range(400):
        s, j = call(api, f"/judge/jobs/{j['id']}")
        if j["state"] != "running":
            break
        time.sleep(3)
    check(j["state"] == "done", f"training job {j['state']}: {j['message']}")
    m = call(api, "/judge/model")[1]["model"] or {}
    print(f"      trained on {m.get('file')}, {m.get('n_parts')} parts, {m.get('n_lots')} lots; path: {m.get('path')}")
    for b in m.get("banner", []):
        print(f"      banner: {b}")

    print("[3] predict on examples/judge/test.csv (0h/24h only)")
    s, p = call(api, "/judge/predict", {"csv": (EX / "judge" / "test.csv").read_text(), "filename": "test.csv"})
    check(s == 200, f"predict -> HTTP {s}")
    s, preds = call(api, "/judge/predictions.csv", raw=True)
    check(s == 200 and preds.splitlines()[0] == "Part_ID,Predicted_168h,PI_low,PI_high,Anomaly_score,Flag,Reason",
          "preds.csv downloaded with the export columns")

    print("[4] score: UI (POST /judge/score) vs CLI (python -m evaluation.score)")
    s, ui = call(api, "/judge/score", {"truth_csv": (EX / "judge" / "truth.csv").read_text(), "truth_filename": "truth.csv"})
    check(s == 200, f"score -> HTTP {s}")
    tmp = ROOT / "reports" / "rehearsal"
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "preds.csv").write_text(preds, encoding="utf-8")
    cid = subprocess.run(["docker", "compose", "ps", "-q", "burnin_backend"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    for f in ("preds.csv",):
        subprocess.run(["docker", "cp", str(tmp / f), f"{cid}:/tmp/{f}"], check=True, capture_output=True)
    subprocess.run(["docker", "cp", str(EX / "judge" / "truth.csv"), f"{cid}:/tmp/truth.csv"], check=True, capture_output=True)
    argv = ui["reproduce_with"].split()[3:]
    argv = ["/tmp/" + x if x in ("preds.csv", "truth.csv") else x for x in argv]
    cmd = ["docker", "exec", cid, "python", "-m", "evaluation.score", *argv, "--json", "/tmp/cli.json"]
    out = subprocess.run(cmd, capture_output=True, text=True)
    print("      $ python -m evaluation.score " + " ".join(argv))
    print("\n".join("      " + ln for ln in out.stdout.strip().splitlines()))
    check(out.returncode == 0, "CLI exit code 0")
    cli = json.loads(subprocess.run(["docker", "exec", cid, "cat", "/tmp/cli.json"], capture_output=True, text=True).stdout)
    for key in ("detection", "confusion_matrix", "regression", "interval", "trivial_policies"):
        check(cli[key] == ui[key], f"UI == CLI: {key}")
    d = ui["detection"]
    print(f"      recall {d['recall']:.4f}, precision {d['precision']:.4f}, cost {d['weighted_cost']:.0f} "
          f"(flag-all {ui['trivial_policies']['flag_all_parts']['weighted_cost']:.0f}), MAE {ui['regression']['mae']:.4f}")

    print("[5] messy file (renamed headers, nA, blanks, duplicate IDs, text in numeric cells)")
    messy = (EX / "ingest_messy.csv").read_text()
    s, v = call(api, "/ingest/validate", {"csv": messy})
    check(s == 200, f"validate -> HTTP {s}")
    msgs = " | ".join(i["message"] for i in v.get("issues", []))
    check(v.get("duplicate_part_ids", 0) >= 1 and "duplicate part ID" in msgs, "duplicate IDs reported with line numbers")
    check(v.get("non_numeric_cells", 0) >= 1 and "non-numeric" in msgs, "text in numeric cells reported")
    check(v.get("imputed_cells", 0) >= 1, "blank cells imputed and flagged (never 0)")
    check(v.get("needs_unit_confirmation") is True, "nA units detected and need confirmation")
    s, e = call(api, "/ingest", {"csv": messy, "lot_number": f"REHEARSAL-MESSY-{stamp}"})
    check(s == 409 and "confirm the detected units" in json.dumps(e), f"ingest without unit confirmation -> clear HTTP {s}")
    print(f"      error: {e.get('detail', {}).get('message') if isinstance(e, dict) else e}")
    check(call(a.api, "/health")[0] == 200, "API healthy after the messy file (no crash)")

    print("\nJUDGE REHEARSAL " + ("PASSED" if not FAILED else f"FAILED ({len(FAILED)}): " + "; ".join(FAILED)))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
