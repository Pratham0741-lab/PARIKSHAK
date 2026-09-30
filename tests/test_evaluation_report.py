"""The committed evaluation report must be exactly what a fresh run produces."""

from __future__ import annotations

import json

from evaluation.run import REPORT_JSON, REPORT_MD, evaluate, render_markdown


def test_evaluation_report_matches_fresh_run():
    fresh = evaluate()
    committed = json.loads(REPORT_JSON.read_text(encoding="utf-8"))
    assert json.loads(json.dumps(fresh, sort_keys=True)) == committed
    assert REPORT_MD.read_text(encoding="utf-8") == render_markdown(committed)
    # The report quotes held-out numbers and labels in-sample numbers as optimistic.
    md = REPORT_MD.read_text(encoding="utf-8")
    assert "held-out" in md.lower() and "TRAIN (optimistic)" in md
