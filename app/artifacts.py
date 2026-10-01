"""Alias for `python -m backend.app.artifacts` (model bundle save/load CLI)."""

import sys

from backend.app.artifacts import main

if __name__ == "__main__":
    sys.exit(main())
