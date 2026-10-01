"""Portable model bundle: round trip, checksum, restricted unpickling."""

from __future__ import annotations

import hashlib
import os
import pickle

import pandas as pd
import pytest

from data_engine.physics_generator import PhysicsBurnInGenerator
from data_engine.tabular import read_table
from evaluation.cost import CostConfig
from ml_engine import judge
from ml_engine.artifacts import PROTOCOL, BundleError, load_bundle, save_bundle
from ml_engine.features import PARAMETERS


def _wide(df, hours):
    w = df.pivot_table(index=["component_id", "lot_id"], columns="interval_hours", values=list(PARAMETERS))
    w.columns = [f"{p}_{h}h" for p, h in w.columns]
    return w[[c for c in w.columns if int(c.rsplit("_", 1)[1][:-1]) in hours]].reset_index().rename(columns={"component_id": "part_id"}).to_csv(index=False)


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    df = PhysicsBurnInGenerator(num_lots=6, components_per_lot=40, random_seed=21).generate_dataset()
    lots = sorted(df["lot_id"].unique())
    d = tmp_path_factory.mktemp("bundle")
    train_file = d / "train.csv"
    train_file.write_bytes(_wide(df[df["lot_id"].isin(lots[:4])], (0, 24, 96, 168)).encode("utf-8"))
    jm, _, _ = judge.train(read_table(train_file.read_bytes().decode("utf-8")), "train.csv", CostConfig())
    path = jm.save(d / "models")
    return jm, path, train_file, _wide(df[df["lot_id"].isin(lots[4:])], (0, 24))


def test_round_trip_gives_identical_predictions_and_records_the_training_file_hash(trained):
    jm, path, train_file, test_csv = trained
    loaded = judge.JudgeModel.load_active(path.parent)  # latest.pkl
    a, _ = judge.predict(jm, read_table(test_csv))
    b, _ = judge.predict(loaded, read_table(test_csv))
    pd.testing.assert_frame_equal(a, b)
    assert loaded.info["bundle"]["data_sha256"] == hashlib.sha256(train_file.read_bytes()).hexdigest()
    assert loaded.info["oof_metrics"] == jm.info["oof_metrics"] and "train_optimistic" in loaded.info  # stored metrics unchanged
    with open(path, "rb") as fh:  # no labels / training rows in the bundle
        model = pickle.loads(pickle.load(fh)["payload_bytes"])["model"]
    assert model.validation_ is None and not model.training_component_ids_


def test_a_flipped_byte_fails_the_checksum(trained, tmp_path):
    _, path, _, _ = trained
    outer = pickle.loads(path.read_bytes())
    payload = bytearray(outer["payload_bytes"])
    payload[len(payload) // 2] ^= 0x01
    outer["payload_bytes"] = bytes(payload)
    bad = tmp_path / "flipped.pkl"
    bad.write_bytes(pickle.dumps(outer, protocol=PROTOCOL))
    with pytest.raises(BundleError, match="checksum"):
        load_bundle(bad)


class _Evil:
    def __init__(self, marker):
        self.marker = marker

    def __reduce__(self):
        return (os.system, (f"echo pwned > {self.marker}",))


def test_a_pickle_referencing_os_system_is_rejected(tmp_path):
    marker = tmp_path / "pwned.txt"
    payload_bytes = pickle.dumps({"format_version": 1, "model": _Evil(marker)}, protocol=PROTOCOL)
    outer = {"format": "parikshak-model-bundle", "bundle_checksum": hashlib.sha256(payload_bytes).hexdigest(),
             "payload_bytes": payload_bytes}  # a valid checksum: only the restricted unpickler stands in the way
    evil = tmp_path / "evil.pkl"
    evil.write_bytes(pickle.dumps(outer, protocol=PROTOCOL))
    with pytest.raises(BundleError, match="refused to load .*system"):
        load_bundle(evil)
    assert not marker.exists()
    with pytest.raises(BundleError):
        save_bundle.__globals__["restricted_loads"](pickle.dumps(_Evil(marker)))  # also at the outer level
    assert not marker.exists()
