"""
Model bundle CLI (portable .pkl, see ml_engine/artifacts.py).

    python -m app.artifacts save --train-file examples/judge/train.csv [--out models/x.pkl] [--no-latest] [--no-pretrained]
    python -m app.artifacts load models/latest.pkl [--install]

`save` trains a judge-mode model on the file and writes a bundle (and models/latest.pkl unless --no-latest).
`load` verifies a bundle (checksum, format version, restricted unpickling, self-test prediction) and prints its
summary; --install copies it into models/ as the active model (latest.pkl).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


def _models_dir() -> Path:
    from backend.app.api.v1.judge import models_dir

    return models_dir()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.artifacts", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("save", help="train on a file and save a bundle")
    s.add_argument("--train-file", required=True)
    s.add_argument("--out", default=None)
    s.add_argument("--no-latest", action="store_true")
    s.add_argument("--no-pretrained", action="store_true", help="train only on the file (no production-model fallback)")
    ld = sub.add_parser("load", help="verify a bundle and print its summary")
    ld.add_argument("path")
    ld.add_argument("--install", action="store_true", help="make it the active model (models/latest.pkl)")
    a = ap.parse_args(argv)

    from ml_engine import judge
    from ml_engine.artifacts import BundleError, describe, load_bundle, save_bundle

    if a.cmd == "save":
        from backend.app.api.v1.judge import pretrained_for
        from backend.app.core.config import settings
        from data_engine.tabular import read_table
        from evaluation.cost import CostConfig

        src = Path(a.train_file)
        table = read_table(src.read_bytes().decode("utf-8"))
        jm, _, _ = judge.train(table, src.name, CostConfig.from_settings(), pretrained=None if a.no_pretrained else pretrained_for(table.params),
                               max_flag_rate=settings.JUDGE_MAX_FLAG_RATE)
        if a.out:
            res = save_bundle(jm.model, jm.info, Path(a.out))
            if not a.no_latest:
                judge.install_latest(Path(a.out), Path(a.out).parent)
        else:
            path = jm.save(_models_dir()) if not a.no_latest else None
            res = {"path": str(path)}
        print(json.dumps({**res, "path_chosen": jm.info["path"], "n_parts": jm.info["n_parts"], "n_lots": jm.info["n_lots"]}, indent=2))
        return 0

    try:
        _, meta, notes = load_bundle(Path(a.path))
    except BundleError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    info = describe(meta, Path(a.path))
    print(json.dumps({**info, "metrics_held_out": (meta.get("metrics") or {}).get("held_out", {}).get("detection")}, indent=2, default=str))
    if a.install:
        d = _models_dir()
        d.mkdir(parents=True, exist_ok=True)
        dest = judge.existing_copy(Path(a.path).read_bytes(), d)
        if dest is None:
            dest = d / f"imported_{meta['bundle_id']}.pkl"
            shutil.copyfile(a.path, dest)
        judge.install_latest(dest, d)
        print(f"installed as {dest} and {d / 'latest.pkl'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
