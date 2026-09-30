#!/usr/bin/env python3
"""
End-to-end smoke test against a RUNNING stack (default http://localhost:8000). Standard library only.

    python scripts/smoke_test.py [--api http://localhost:8000] [--restart]

Checks, exiting non-zero on the first failure:
  1. /health and /api/v1/lots
  2. CSV ingest of a synthetic ~10 uA lot (built here, seeded) -> every part has a prediction,
     an explanation can be generated, and a decision can be recorded and appears in the audit log
  3. injection: a part at 30 uA (0h) / 36 uA (24h) in the ~10 uA lot, below the 50 uA limit at every
     interval, is flagged by BOTH Module A and Module B
  4. perturbation: re-ingesting the same lot with one part's 24h value changed changes that part's
     forecast and its explanation text
  5. --restart: `docker compose restart`, wait for health, and confirm the lot, predictions and the
     recorded decision are still there
"""

from __future__ import annotations

import argparse
import json
import math
import random
import subprocess
import sys
import time
import urllib.error
import urllib.request

PARAMS = ("leakage_current_ua", "iddq_ma", "propagation_delay_ns")
HOURS = (0, 24, 96, 168)


class SmokeFailure(Exception):
    pass


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise SmokeFailure(msg)
    print(f"  ok  {msg}")


def call(api: str, path: str, body=None, method=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(api + path, data=data, method=method or ("POST" if body is not None else "GET"),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def build_lot_csv(seed: int, perturb_24h: float | None = None) -> str:
    """~10 uA nominal lot, the latent part, and a PERTURB-001 part whose 24h leakage can be overridden."""
    rng = random.Random(seed)
    rows = [",".join(["part_id"] + [f"{p}_{h}h" for h in HOURS for p in PARAMS])]
    for i in range(60):
        v0 = math.exp(rng.gauss(math.log(10.0), 0.10))
        slope = abs(rng.gauss(0.004, 0.002))
        iddq, delay = rng.gauss(1.5, 0.05), rng.gauss(4.2, 0.1)
        vals = []
        for h in HOURS:
            vals += [v0 + slope * h + rng.gauss(0, 0.15), iddq + rng.gauss(0, 0.02), delay + rng.gauss(0, 0.03)]
        rows.append(",".join([f"SMK-{i:03d}"] + [f"{v:.4f}" for v in vals]))
    latent = [30.0, 1.5, 4.2, 36.0, 1.53, 4.2, 42.0, 1.56, 4.2, 48.5, 1.59, 4.2]
    rows.append(",".join(["LATENT-001"] + [f"{v:.4f}" for v in latent]))
    pert = [10.0, 1.5, 4.2, 10.1 if perturb_24h is None else perturb_24h, 1.5, 4.2, 10.3, 1.5, 4.2, 10.5, 1.5, 4.2]
    rows.append(",".join(["PERTURB-001"] + [f"{v:.4f}" for v in pert]))
    return "\n".join(rows) + "\n"


def ingest(api: str, csv: str, name: str):
    status, res = call(api, "/api/v1/ingest", {"csv": csv, "lot_number": name, "actor": "smoke-test"})
    check(status == 201, f"ingest {name} -> HTTP {status}")
    return res


def parts_by_serial(api: str, lot_id: str):
    status, parts = call(api, f"/api/v1/lots/{lot_id}/parts")
    check(status == 200, f"GET /lots/{lot_id[:8]}.../parts -> HTTP {status}")
    return {p["serial_number"]: p for p in parts}


def wait_healthy(api: str, timeout_s: int = 240) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            if call(api, "/health")[0] == 200:
                return
        except Exception:
            pass
        time.sleep(3)
    raise SmokeFailure(f"API not healthy after {timeout_s}s")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--restart", action="store_true", help="also test persistence across `docker compose restart`")
    args = ap.parse_args()
    api = args.api.rstrip("/")
    tag = time.strftime("%Y%m%d-%H%M%S")
    try:
        print("[1] health and lots")
        wait_healthy(api, 60)
        status, lots = call(api, "/api/v1/lots")
        check(status == 200 and len(lots) > 0, f"lots list ({len(lots)} lots)")

        print("[2] ingest")
        res = ingest(api, build_lot_csv(7), f"SMOKE-{tag}-A")
        lot_id = res["lot_id"]
        check(res["validation"]["parts_accepted"] == 62, "62 parts accepted")
        parts = parts_by_serial(api, lot_id)
        check(all(p["prediction"] is not None for p in parts.values()), "every ingested part has a prediction")
        latent = parts["LATENT-001"]
        status, exp = call(api, f"/api/v1/components/{latent['id']}/explain")
        check(status == 200 and "LATENT-001" in exp["summary"], "explanation generated for LATENT-001")
        status, _ = call(api, f"/api/v1/reviews/{latent['id']}/action",
                         {"inspector_id": "SMOKE-QA", "disposition": "QUARANTINED", "inspector_notes": "smoke test decision"})
        check(status == 201, "decision recorded")
        status, audit = call(api, f"/api/v1/audit?lot_id={lot_id}")
        check(any(e["action"] == "Decision recorded" and e["component_id"] == latent["id"] for e in audit),
              "decision appears in the audit log")

        print("[3] injection scenario (30 uA part in a ~10 uA lot, limit 50 uA)")
        leak = sorted(p["readings"][0]["leakage_current_ua"] for s, p in parts.items() if s.startswith("SMK-"))
        median0 = leak[len(leak) // 2]
        check(9.0 < median0 < 11.0, f"lot median 0h leakage {median0:.2f} uA")
        check(all(r["leakage_current_ua"] < 50 for r in latent["readings"]), "latent part below 50 uA at every interval")
        pr = latent["prediction"]
        check(pr["module_a_flag"] is True, f"Module A flags it (score {pr['module_a_score']:.2f} >= {pr['threshold_a']:.2f})")
        check(pr["module_b_flag"] is True, f"Module B flags it (drift z {pr['module_b_score']:.2f} >= k {pr['threshold_b']:.2f})")
        check(pr["verdict"] in ("REVIEW", "REJECT"), f"verdict {pr['verdict']}")

        print("[4] perturbation scenario (one 24h value changed)")
        base = parts["PERTURB-001"]
        res_b = ingest(api, build_lot_csv(7, perturb_24h=13.0), f"SMOKE-{tag}-B")
        pert = parts_by_serial(api, res_b["lot_id"])["PERTURB-001"]
        f0, f1 = base["prediction"]["pred_leakage_168h"], pert["prediction"]["pred_leakage_168h"]
        check(abs(f1 - f0) > 1e-3, f"PERTURB-001 forecast changed: {f0:.3f} -> {f1:.3f} uA")
        e0 = call(api, f"/api/v1/components/{base['id']}/explain")[1]["summary"]
        e1 = call(api, f"/api/v1/components/{pert['id']}/explain")[1]["summary"]
        check(e0 != e1, "PERTURB-001 explanation changed")
        other0 = parts["SMK-000"]["prediction"]["pred_leakage_168h"]
        print(f"      (unperturbed SMK-000 forecast in lot A: {other0:.3f} uA)")

        if args.restart:
            print("[5] persistence across `docker compose restart`")
            subprocess.run(["docker", "compose", "restart"], check=True)
            wait_healthy(api)
            again = parts_by_serial(api, lot_id)
            check(len(again) == len(parts), "ingested lot still present after restart")
            check(again["LATENT-001"]["prediction"]["verdict"] == pr["verdict"], "prediction persisted")
            check((again["LATENT-001"]["latest_decision"] or {}).get("disposition") == "QUARANTINED", "decision persisted")
            status, _ = call(api, f"/api/v1/components/{latent['id']}/explain")
            check(status == 200, "explanations still served (model artifact persisted)")
    except SmokeFailure as e:
        print(f"FAIL: {e}")
        return 1
    except Exception as e:  # connection errors etc.
        print(f"FAIL: {type(e).__name__}: {e}")
        return 1
    print("SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
