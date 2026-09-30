#!/usr/bin/env python3
"""
Regenerates SIH26170_EVALUATION_REPORT.md and reports/evaluation_results.json.

Thin wrapper kept for `make report`; the single source of truth is `python -m evaluation.run`,
which evaluates on held-out lots (GroupKFold over lots, 96h/168h and labels hidden).
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from evaluation.run import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
