"""Inference for the static-source model (train_static_source_model.py).

The model estimates how likely NASA would label a detection a "static
land source" given its measurements and its location history. It is used
as evidence only where NASA's own label for the location is unavailable,
and it is not a probability that a fire is occurring.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MODEL_DIR = Path(__file__).resolve().parents[2] / "models"
MODEL_PATH = MODEL_DIR / "static_source_model.joblib"
REPORT_PATH = MODEL_DIR / "static_source_metrics.json"

FEATURES = [
    "brightness_ti4", "brightness_ti5", "frp", "scan", "track",
    "acq_month", "acq_minute_utc", "confidence_code", "is_night",
    "hist_active_months", "hist_calendar_months", "hist_active_days",
    "hist_night_share", "hist_log_detections", "hist_mean_frp",
]

CONFIDENCE_CODES = {"l": 0, "low": 0, "n": 1, "nominal": 1, "h": 2, "high": 2}


@lru_cache(maxsize=1)
def load_bundle() -> dict[str, Any] | None:
    if not MODEL_PATH.is_file():
        logger.warning("Static-source model not found at %s", MODEL_PATH)
        return None
    return joblib_load(MODEL_PATH)


def joblib_load(path: Path):
    import joblib  # deferred: keeps API start-up fast when unused

    return joblib.load(path)


def history_features(summary: dict[str, Any]) -> dict[str, float]:
    """Map a thermal_registry.summarize_cells() result to model inputs."""
    detections = summary["detection_count"]
    return {
        "hist_active_months": summary["active_months"],
        "hist_calendar_months": summary["calendar_months"],
        "hist_active_days": summary["active_days"],
        "hist_night_share": (
            summary["night_share"] if summary["night_share"] is not None else math.nan
        ),
        "hist_log_detections": math.log1p(detections),
        "hist_mean_frp": (
            summary["mean_frp"] if summary["mean_frp"] is not None else math.nan
        ),
    }


def observation_features(observation: Any) -> dict[str, float]:
    timestamp = observation.observed_at.astimezone(timezone.utc)

    def value(v):
        return math.nan if v is None else float(v)

    return {
        "brightness_ti4": value(observation.brightness_ti4),
        "brightness_ti5": value(observation.brightness_ti5),
        "frp": value(observation.frp),
        "scan": value(observation.scan),
        "track": value(observation.track),
        "acq_month": timestamp.month,
        "acq_minute_utc": timestamp.hour * 60 + timestamp.minute,
        "confidence_code": CONFIDENCE_CODES.get(
            (observation.confidence or "").strip().lower(), math.nan
        ),
        "is_night": 1 if observation.day_night == "N" else 0,
    }


def predict_static_probability(rows: list[dict[str, float]]) -> list[float] | None:
    """Calibrated P(NASA static label) per feature row; None if no model."""
    bundle = load_bundle()
    if bundle is None or not rows:
        return None
    import pandas as pd  # deferred with the model: the API may never need it

    try:
        frame = pd.DataFrame(rows, columns=bundle["features"])
        return bundle["model"].predict_proba(frame)[:, 1].tolist()
    except Exception:
        logger.exception("Static-source model inference failed")
        return None


@lru_cache(maxsize=1)
def model_card() -> dict[str, Any] | None:
    """Held-out metrics, read from the training report so that showing them
    does not load scikit-learn."""
    if not REPORT_PATH.is_file():
        return None
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    return {key: report[key] for key in ("name", "spatial_test", "baseline_site_rule")}
