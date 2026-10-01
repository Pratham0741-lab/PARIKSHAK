"""
Portable model bundles (ml_engine/artifacts.py): export the active judge-mode model, import a bundle from another
machine (verified before it is used), and list the bundles in MODELS_DIR for the Model registry panel.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from backend.app.api.v1.judge import _ACTIVE, _LOCK, clean, models_dir
from ml_engine import judge
from ml_engine.artifacts import LATEST, BundleError, describe, load_bundle

router = APIRouter(prefix="/model", tags=["Model bundles"])
MAX_BYTES = 200 * 1024 * 1024


@router.post("/export", summary="Download the active model as a portable .pkl bundle")
async def export_bundle() -> Response:
    path = models_dir() / LATEST
    if not path.exists():
        raise HTTPException(status_code=404, detail="no active model bundle (train one in judge mode first)")
    meta = (await run_in_threadpool(load_bundle, path))[1]
    return Response(path.read_bytes(), media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="parikshak_model_{meta["bundle_id"]}.pkl"'})


def _import(data: bytes) -> Dict[str, Any]:
    d = models_dir()
    d.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp_import_", suffix=".pkl")
    with open(fd, "wb") as fh:
        fh.write(data)
    try:
        _, meta, _ = load_bundle(Path(tmp))  # checksum, format, restricted unpickle, self-test
    except BundleError as exc:
        Path(tmp).unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=f"bundle refused: {exc}") from exc
    dest = judge.existing_copy(data, d)
    if dest is None:
        dest = d / f"imported_{meta['bundle_id']}.pkl"
        shutil.move(tmp, dest)
    else:
        Path(tmp).unlink(missing_ok=True)
    with _LOCK:
        judge.install_latest(dest, d)
        _ACTIVE.update(model=None, loaded_from=None)
    return describe(meta, dest)


@router.post("/import", summary="Upload a .pkl bundle (raw body); verified, then made the active model")
async def import_bundle(request: Request) -> Dict[str, Any]:
    data = await request.body()
    if not data or len(data) > MAX_BYTES:
        raise HTTPException(status_code=422, detail="empty or too large bundle")
    return clean(await run_in_threadpool(_import, data))


def _list() -> List[Dict[str, Any]]:
    d = models_dir()
    if not d.exists():
        return []
    current_sum = None
    out = []
    for p in sorted(d.glob("*.pkl"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            _, meta, _ = load_bundle(p)
            row = {**describe(meta, p), "status": "ok", "metrics_held_out": ((meta.get("metrics") or {}).get("held_out") or {}).get("detection")}
        except BundleError as exc:
            row = {"file": p.name, "status": f"invalid: {exc}"}
        if p.name == LATEST:
            current_sum = row.get("bundle_checksum")
            continue
        out.append(row)
    for r in out:
        r["current"] = current_sum is not None and r.get("bundle_checksum") == current_sum
    return out


@router.get("/artifacts", summary="Model bundles in MODELS_DIR (newest first); 'current' = the one latest.pkl points to")
async def list_bundles() -> List[Dict[str, Any]]:
    return clean(await run_in_threadpool(_list))
