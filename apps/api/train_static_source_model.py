"""Train the static-source model (successor to train_thermal_classifier.py).

Target: NASA FIRMS type 2 ("other static land source") vs type 0
("presumed vegetation fire"). Volcano (27 archive rows) and offshore
(decided by location) are not modelled; the API reads NASA's own labels
at the location for those.

Features: the detection's own measurements plus its location history
(3x3 cells of ~400 m). Coordinates are deliberately excluded: with them
the previous model memorised where static sources are and its static
recall fell from 0.86 to 0.44 on unseen regions.

Evaluation: whole 0.5-degree blocks are held out (train 60%, calibration
20%, test 20%), so test locations are never seen during training.

    python train_static_source_model.py
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.frozen import FrozenEstimator
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    precision_recall_fscore_support,
)

from app.services.grid import CELL_SIZE_DEGREES
from app.services.static_model import FEATURES

ROOT = Path(__file__).resolve().parents[2]
CSV_PATH = (
    ROOT / "data" / "firms" / "archive" / "827421"
    / "fire_archive_J2V-C2_827421.csv"
)
MODEL_DIR = ROOT / "apps" / "api" / "models"
MODEL_PATH = MODEL_DIR / "static_source_model.joblib"
REPORT_PATH = MODEL_DIR / "static_source_metrics.json"

SEED = 42
BLOCK_DEGREES = 0.5
KEY_STRIDE = 100_000


def load_archive() -> pd.DataFrame:
    df = pd.read_csv(
        CSV_PATH,
        usecols=["latitude", "longitude", "brightness", "scan", "track",
                 "acq_date", "acq_time", "confidence", "bright_t31",
                 "frp", "daynight", "type"],
        dtype={"acq_time": str, "confidence": str, "daynight": str},
    )
    df["acq_date"] = pd.to_datetime(df["acq_date"])
    return df


def add_history_features(df: pd.DataFrame) -> pd.DataFrame:
    """Same definitions as static_model.history_features() at inference."""
    cx = np.floor(df.longitude / CELL_SIZE_DEGREES).astype(np.int64)
    cy = np.floor(df.latitude / CELL_SIZE_DEGREES).astype(np.int64)
    df["cell"] = cx * KEY_STRIDE + cy
    df["is_night"] = (df.daynight == "N").astype(int)
    df["ym"] = df.acq_date.dt.year * 12 + df.acq_date.dt.month
    df["moy"] = df.acq_date.dt.month
    df["day"] = (df.acq_date - pd.Timestamp("2000-01-01")).dt.days

    offsets = [dx * KEY_STRIDE + dy for dx in (-1, 0, 1) for dy in (-1, 0, 1)]

    def neighborhood_distinct(column: str) -> pd.Series:
        pairs = df[["cell", column]].drop_duplicates()
        shifted = pd.concat(
            [pairs.assign(cell=pairs.cell + o) for o in offsets],
            ignore_index=True,
        ).drop_duplicates()
        return shifted.groupby("cell")[column].size()

    sums = df.groupby("cell").agg(
        n=("is_night", "size"),
        night=("is_night", "sum"),
        frp_sum=("frp", "sum"),
        frp_n=("frp", "count"),
    )
    shifted = pd.concat(
        [sums.set_axis(sums.index + o) for o in offsets]
    ).groupby(level=0).sum()

    hist = pd.DataFrame({
        "hist_active_months": neighborhood_distinct("ym"),
        "hist_calendar_months": neighborhood_distinct("moy"),
        "hist_active_days": neighborhood_distinct("day"),
    }).join(shifted, how="left")
    hist["hist_night_share"] = hist.night / hist.n
    hist["hist_log_detections"] = np.log1p(hist.n)
    hist["hist_mean_frp"] = hist.frp_sum / hist.frp_n.replace(0, np.nan)

    return df.join(hist[[
        "hist_active_months", "hist_calendar_months", "hist_active_days",
        "hist_night_share", "hist_log_detections", "hist_mean_frp",
    ]], on="cell")


def add_observation_features(df: pd.DataFrame) -> pd.DataFrame:
    t = df.acq_time.str.zfill(4)
    df["acq_month"] = df.acq_date.dt.month
    df["acq_minute_utc"] = t.str[:2].astype(int) * 60 + t.str[2:].astype(int)
    df["brightness_ti4"] = df.brightness
    df["brightness_ti5"] = df.bright_t31
    df["confidence_code"] = df.confidence.str.lower().map({"l": 0, "n": 1, "h": 2})
    return df


def metrics(y: np.ndarray, prob: np.ndarray, threshold: float = 0.5) -> dict:
    pred = prob >= threshold
    p, r, f, _ = precision_recall_fscore_support(
        y, pred, average="binary", zero_division=0
    )
    return {
        "precision": round(float(p), 4),
        "recall": round(float(r), 4),
        "f1": round(float(f), 4),
        "average_precision": round(float(average_precision_score(y, prob)), 4),
        "brier": round(float(brier_score_loss(y, prob)), 5),
        "positives": int(y.sum()),
        "rows": int(len(y)),
    }


def reliability(y: np.ndarray, prob: np.ndarray) -> list[dict]:
    bins = np.array([0, 0.1, 0.3, 0.5, 0.7, 0.9, 1.0001])
    out = []
    for lo, hi in zip(bins[:-1], bins[1:]):
        sel = (prob >= lo) & (prob < hi)
        if sel.sum():
            out.append({
                "bin": f"{lo:.1f}-{min(hi, 1):.1f}",
                "rows": int(sel.sum()),
                "mean_predicted": round(float(prob[sel].mean()), 3),
                "observed_static_rate": round(float(y[sel].mean()), 3),
            })
    return out


def main() -> None:
    print("Loading archive...")
    df = load_archive()
    print(f"Rows: {len(df):,}")

    # History uses every labelled row (as the API's cell registry does),
    # then the modelling set keeps the two classes the model separates.
    df = add_history_features(df)
    df = add_observation_features(df)
    df = df[df["type"].isin([0, 2])].copy()
    df["y"] = (df["type"] == 2).astype(int)

    block = (
        np.floor(df.latitude / BLOCK_DEGREES).astype(int) * 1000
        + np.floor(df.longitude / BLOCK_DEGREES).astype(int)
    )
    rng = np.random.default_rng(SEED)
    blocks = np.array(sorted(block.unique()))
    rng.shuffle(blocks)
    n = len(blocks)
    role = pd.Series("train", index=blocks)
    role.iloc[int(n * 0.6):int(n * 0.8)] = "calibration"
    role.iloc[int(n * 0.8):] = "test"
    df["role"] = block.map(role).values

    train = df[df.role == "train"]
    calib = df[df.role == "calibration"]
    test = df[df.role == "test"]
    print(f"Train {len(train):,} / calibration {len(calib):,} / test {len(test):,} rows")

    base = HistGradientBoostingClassifier(
        max_iter=300, learning_rate=0.08, max_leaf_nodes=31,
        min_samples_leaf=200, l2_regularization=1.0, random_state=SEED,
    )
    base.fit(train[FEATURES], train.y)
    model = CalibratedClassifierCV(FrozenEstimator(base), method="isotonic")
    model.fit(calib[FEATURES], calib.y)

    prob = model.predict_proba(test[FEATURES])[:, 1]
    y = test.y.to_numpy()

    # Transparent baseline: the persistent-site rule applied per detection.
    rule = (
        (test.hist_calendar_months >= 8) & (test.hist_night_share >= 0.5)
    ).to_numpy().astype(float)

    report = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "target": "NASA FIRMS type 2 (static land source) vs type 0 (vegetation)",
        "archive": CSV_PATH.name,
        "features": FEATURES,
        "split": f"held-out {BLOCK_DEGREES} degree blocks: 60% train, "
                 "20% isotonic calibration, 20% test",
        "rows": {"train": len(train), "calibration": len(calib), "test": len(test)},
        "spatial_test": metrics(y, prob),
        "spatial_test_reliability": reliability(y, prob),
        "baseline_site_rule": {
            "rule": "neighbourhood active >= 8 calendar months and >= 50% night detections",
            **metrics(y, rule),
        },
        "limitations": [
            "Labels are NASA's static-source flag, not verified industrial activity; "
            "NASA's flag misses some persistent sources (see thermal_sites report).",
            "Volcano and offshore classes are not modelled.",
            "Location history is computed from the same archive period as the labels.",
            "Only NOAA-21 VIIRS detections are used.",
        ],
    }

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump({
        "model": model,
        "features": FEATURES,
        "name": "static_source_model_v2",
        "metrics": {
            "spatial_test": report["spatial_test"],
            "baseline_site_rule": report["baseline_site_rule"],
        },
    }, MODEL_PATH, compress=3)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(json.dumps({k: report[k] for k in (
        "spatial_test", "baseline_site_rule", "spatial_test_reliability"
    )}, indent=2))
    print(f"Saved {MODEL_PATH.name} ({MODEL_PATH.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
