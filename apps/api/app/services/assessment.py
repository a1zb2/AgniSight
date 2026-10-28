"""Evidence-based interpretation of a thermal event.

Four separate outputs, deliberately not merged into one number:

* category  - the most defensible source interpretation, or "unresolved".
* evidence  - each supporting, conflicting or contextual observation, with
              its data source and weight.
* strength  - how many independent lines of evidence agree (strong /
              moderate / limited). Not a probability.
* priority  - a transparent triage score for investigators, with the
              factors that produced it. Not a fire-risk probability.

Inputs come from the event's detections, the precomputed location history
(thermal_cells / thermal_sites), mapped OSM context and, only where NASA's
own label is unavailable, the static-source model.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

HISTORY_START_LABEL = "January 2024"
REVISIT_NOTE = "NOAA-21 passes over India roughly every 12 hours (day and night)"

CATEGORY_TITLES = {
    "volcanic": "Volcanic thermal activity",
    "offshore_source": "Persistent offshore heat source",
    "offshore_anomaly": "Offshore thermal anomaly",
    "kiln_activity": "Heat at a mapped brick kiln",
    "extraction_source": "Persistent heat at a mapped mine or quarry",
    "waste_source": "Persistent heat at a mapped landfill",
    "industrial_source": "Persistent heat source at a mapped industrial site",
    "unmapped_source": "Persistent heat source with no mapped facility",
    "industrial_episodic": "Heat at a mapped industrial site",
    "extraction_activity": "Thermal activity at a mapped mine or quarry",
    "waste_activity": "Thermal activity at a mapped landfill",
    "vegetation_candidate": "Likely vegetation or agricultural burning",
    "unresolved": "Unresolved thermal anomaly",
}

# Industrial sites are expected to produce heat; what matters is whether
# this location is a known continuous source. Episodic categories are
# therefore titled by the location's history rather than called unusual.
EPISODIC_PREFIX = {
    "new": "First heat detected",
    "occasional": "Occasional heat",
    "seasonal": "Seasonal heat",
    "recurrent": "Recurring heat",
    "persistent": "Heat",
}
EPISODIC_SITES = {
    "industrial_episodic": ("at a mapped industrial site", "at industrial site"),
    "extraction_activity": ("at a mapped mine or quarry", "at mine or quarry"),
    "waste_activity": ("at a mapped landfill", "at landfill"),
}

SHORT_TITLES = {
    "volcanic": "Volcanic activity",
    "offshore_source": "Persistent offshore heat",
    "offshore_anomaly": "Offshore detection",
    "kiln_activity": "Brick kiln heat",
    "extraction_source": "Persistent heat at mine",
    "waste_source": "Persistent landfill heat",
    "industrial_source": "Persistent industrial heat",
    "unmapped_source": "Persistent heat, no mapped facility",
    "vegetation_candidate": "Vegetation or crop burning",
    "unresolved": "Unresolved detection",
}


def titles(category: str, pattern: str) -> tuple[str, str]:
    """Full and short title for a category, given the location pattern."""
    if category in EPISODIC_SITES:
        long_place, short_place = EPISODIC_SITES[category]
        prefix = EPISODIC_PREFIX[pattern]
        return f"{prefix} {long_place}", f"{prefix} {short_place}"
    return CATEGORY_TITLES[category], SHORT_TITLES[category]


PATTERN_LABELS = {
    "persistent": "Year-round persistent location",
    "recurrent": "Recurring location",
    "seasonal": "Seasonally recurring location",
    "occasional": "Occasional prior activity",
    "new": "No prior detections at this location",
}

WEIGHT_POINTS = {"strong": 2.0, "moderate": 1.0, "weak": 0.5}
INDUSTRIAL_GROUPS = {"thermal_power", "heavy_industry", "industrial_area", "storage"}


@dataclass
class Evidence:
    stance: str  # supports | conflicts | context
    source: str
    text: str
    weight: str = "moderate"

    def as_dict(self) -> dict[str, str]:
        return self.__dict__.copy()


def _pct(value: float) -> str:
    return f"{round(value * 100)}%"


def _fmt_date(value: datetime | None) -> str:
    return value.strftime("%d %b %Y") if value else "unknown"


def location_pattern(history: dict, prior: dict, site: dict | None) -> str:
    if site and site.get("site_class") == "persistent":
        return "persistent"
    if (
        history["calendar_months"] >= 8
        and (history["night_share"] or 0) >= 0.5
    ):
        return "persistent"
    if prior["active_days"] == 0:
        return "new"
    if prior["active_months"] >= 2 and prior["calendar_months"] <= 5:
        return "seasonal"
    if prior["active_months"] >= 2:
        return "recurrent"
    return "occasional"


def _nasa_label(history: dict) -> tuple[str | None, float]:
    """Dominant NASA source type at the location, if labels exist."""
    if history["nasa_typed_count"] < 5:
        return None, 0.0
    shares = {
        "static": history["nasa_static_share"] or 0,
        "vegetation": history["nasa_vegetation_share"] or 0,
        "offshore": history["nasa_offshore_share"] or 0,
        "volcano": history["nasa_volcano_share"] or 0,
    }
    label, share = max(shares.items(), key=lambda kv: kv[1])
    return (label, share) if share >= 0.5 else ("mixed", share)


def assess_event(
    event: dict[str, Any],
    history: dict[str, Any],
    prior: dict[str, Any],
    site: dict[str, Any] | None,
    context: dict[str, Any],
    model: dict[str, Any] | None,
) -> dict[str, Any]:
    ev: list[Evidence] = []
    pattern = location_pattern(history, prior, site)
    nasa_label, nasa_share = _nasa_label(history)
    primary = context.get("primary")
    relation = context.get("relation", "none")
    group = primary["group"] if primary else None
    close = relation in ("inside", "adjacent")
    near = relation == "nearby"
    model_p = model.get("static_probability") if model else None
    model_used = model_p is not None and nasa_label is None

    # --- Location history -------------------------------------------------
    if pattern == "persistent":
        ev.append(Evidence(
            "supports", "Location history",
            f"Active in {history['calendar_months']} of 12 calendar months "
            f"({history['active_months']} distinct months since "
            f"{HISTORY_START_LABEL}), {_pct(history['night_share'] or 0)} "
            "of detections at night: a year-round, non-seasonal pattern.",
            "strong",
        ))
    elif pattern == "new":
        ev.append(Evidence(
            "context", "Location history",
            f"No detections within ~600 m before this event since "
            f"{HISTORY_START_LABEL}.",
            "moderate",
        ))
    else:
        ev.append(Evidence(
            "context", "Location history",
            f"{PATTERN_LABELS[pattern]}: {prior['active_days']} earlier active "
            f"days across {prior['active_months']} months "
            f"({prior['calendar_months']} calendar months), "
            f"last on {_fmt_date(prior['last_date'])}.",
            "moderate",
        ))

    # --- NASA source-type labels -----------------------------------------
    if nasa_label and nasa_label != "mixed":
        names = {
            "static": "a static land source",
            "vegetation": "presumed vegetation fire",
            "offshore": "offshore",
            "volcano": "an active volcano",
        }
        ev.append(Evidence(
            "supports", "NASA FIRMS archive",
            f"NASA labelled {_pct(nasa_share)} of "
            f"{history['nasa_typed_count']} archived detections here as "
            f"{names[nasa_label]}.",
            "strong",
        ))
    elif nasa_label == "mixed":
        ev.append(Evidence(
            "context", "NASA FIRMS archive",
            "NASA's archived labels here are mixed; no single source type "
            "accounts for half of them.", "weak",
        ))

    # --- Model (only where NASA has not labelled the location) -----------
    if model_used:
        ev.append(Evidence(
            "supports" if model_p >= 0.7 else "context",
            "Static-source model",
            f"Estimated {_pct(model_p)} chance that NASA would flag this "
            "detection as a static source. NASA has not labelled this "
            "location yet.",
            "moderate" if model_p >= 0.7 or model_p <= 0.1 else "weak",
        ))

    # --- This event --------------------------------------------------------
    day_night = event.get("day_night")
    if day_night == "N":
        ev.append(Evidence(
            "context", "This event",
            "Detected at night, when sunlit surfaces cannot contribute; "
            "typical of combustion or industrial heat.", "weak",
        ))

    static_like = (
        nasa_label == "static"
        or pattern == "persistent"
        or (model_used and model_p >= 0.7)
    )

    # --- Mapped context ----------------------------------------------------
    if primary and relation != "vicinity":
        where = {
            "inside": "inside",
            "adjacent": f"{round(primary['distance_m'])} m from",
            "nearby": f"{primary['distance_m'] / 1000:.1f} km from",
        }[relation]
        name = f": {primary['name']}" if primary["name"] else " (unnamed)"
        ev.append(Evidence(
            "supports" if close and primary["thermal_relevance"] != "low" else "context",
            "OpenStreetMap",
            f"Event centroid is {where} a mapped feature, "
            f"{primary['category']}{name}.",
            "strong" if relation == "inside" else "moderate" if close else "weak",
        ))
        if "solar" in primary["category"].lower() and close:
            ev.append(Evidence(
                "conflicts", "OpenStreetMap",
                "A mapped solar plant is not a combustion source; hot or "
                "reflective panels may explain daytime detections. Verify "
                "with imagery.", "moderate",
            ))
    else:
        ev.append(Evidence(
            "context", "OpenStreetMap",
            "No relevant industrial, mining or waste feature is mapped "
            "within 1.5 km.", "weak",
        ))

    # --- Category ---------------------------------------------------------
    if nasa_label == "volcano":
        category = "volcanic"
    elif nasa_label == "offshore":
        category = "offshore_source" if pattern == "persistent" else "offshore_anomaly"
    elif group == "brick_kiln" and (close or near):
        category = "kiln_activity"
    elif static_like:
        if close and group == "extraction":
            category = "extraction_source"
        elif close and group == "waste":
            category = "waste_source"
        elif (close and group in INDUSTRIAL_GROUPS) or (
            near and primary and primary["thermal_relevance"] == "high"
        ):
            category = "industrial_source"
        else:
            category = "unmapped_source"
    elif close and group in INDUSTRIAL_GROUPS:
        category = "industrial_episodic"
    elif close and group == "extraction":
        category = "extraction_activity"
    elif close and group == "waste":
        category = "waste_activity"
    elif (
        nasa_label == "vegetation"
        or (pattern in ("new", "seasonal", "occasional") and day_night != "N")
    ):
        category = "vegetation_candidate"
    else:
        category = "unresolved"

    # Conflicts worth surfacing explicitly.
    if category == "vegetation_candidate" and nasa_label == "static":
        category = "unresolved"
    if category in ("industrial_episodic", "vegetation_candidate") and model_used and model_p >= 0.7:
        ev.append(Evidence(
            "conflicts", "Static-source model",
            "The model leans towards a static source although the location "
            "has no established persistent pattern.", "weak",
        ))
    if category == "vegetation_candidate" and day_night == "N":
        ev.append(Evidence(
            "conflicts", "This event",
            "Night-only detection is less typical of agricultural burning.",
            "weak",
        ))
    if category.endswith("_source") and nasa_label == "vegetation":
        ev.append(Evidence(
            "conflicts", "NASA FIRMS archive",
            "NASA's archived labels here mostly indicate vegetation fire; "
            "the persistent pattern may be repeated burning.", "moderate",
        ))

    strength = _strength(ev)
    priority = _priority(category, event, history, prior, pattern)

    return {
        "category": category,
        "title": titles(category, pattern)[0],
        "short_title": titles(category, pattern)[1],
        "location_pattern": pattern,
        "location_pattern_label": PATTERN_LABELS[pattern],
        "strength": strength,
        "evidence": [e.as_dict() for e in ev],
        "unknowns": _unknowns(category, nasa_label, relation, model_used),
        "next_steps": _next_steps(category, event, primary),
        "priority": priority,
    }


def _strength(evidence: list[Evidence]) -> dict[str, Any]:
    support = sum(WEIGHT_POINTS[e.weight] for e in evidence if e.stance == "supports")
    conflict = sum(WEIGHT_POINTS[e.weight] for e in evidence if e.stance == "conflicts")
    score = support - conflict
    level = "strong" if score >= 3.5 else "moderate" if score >= 1.5 else "limited"
    if level == "strong" and conflict >= 1:
        level = "moderate"
    sources = sorted({e.source for e in evidence if e.stance == "supports"})
    return {
        "level": level,
        "supporting_sources": sources,
        "conflicts": sum(1 for e in evidence if e.stance == "conflicts"),
        "definition": "How many independent data sources support the "
                      "category (strong: several agree; limited: little "
                      "direct support). Not a probability.",
    }


def _priority(category: str, event: dict, history: dict, prior: dict,
              pattern: str) -> dict[str, Any]:
    factors: list[dict[str, Any]] = []

    def add(points: int, label: str) -> None:
        factors.append({"points": points, "label": label})

    if category == "industrial_episodic":
        add(35, "Heat at a mapped industrial site that is not a known continuous source")
    elif category == "waste_activity":
        add(25, "Activity at a mapped landfill")
    elif category == "extraction_activity":
        add(15, "Activity at a mapped mine or quarry")
    elif category == "unmapped_source":
        add(10, "Persistent heat source not present in the facility map")

    peak = event.get("max_frp_mw")
    baseline = prior.get("mean_frp")
    anomalous = False
    # A baseline only means something for an established source; a field
    # burned a few times before has no meaningful "normal" intensity.
    has_baseline = (
        pattern in ("persistent", "recurrent")
        and category != "vegetation_candidate"
        and prior["frp_count"] >= 10
    )
    if peak is not None and baseline and has_baseline:
        ratio = peak / baseline
        if ratio >= 5:
            add(25, f"Peak FRP {ratio:.1f}x this location's prior mean ({baseline:.1f} MW)")
            anomalous = True
        elif ratio >= 3:
            add(15, f"Peak FRP {ratio:.1f}x this location's prior mean ({baseline:.1f} MW)")
            anomalous = True
    if peak is not None:
        if peak >= 100:
            add(20, f"Very high peak FRP ({peak:.0f} MW)")
        elif peak >= 30:
            add(10, f"High peak FRP ({peak:.0f} MW)")

    count = event.get("observation_count", 1)
    if count >= 10:
        add(10, f"{count} detections in this event")
    elif count >= 4:
        add(5, f"{count} detections in this event")
    if event.get("high_confidence_count", 0) > 0:
        add(5, "At least one high-confidence detection")
    # Novelty matters where heat is unexpected, not for crop burning.
    if pattern == "new" and category != "vegetation_candidate":
        add(10, f"First detection at this location since {HISTORY_START_LABEL}")

    # Isolated faint or low-confidence detections include sensor noise and
    # sub-pixel hot spots; keep them below substantial events.
    confidence = event.get("confidence_counts") or {}
    if count == 1 and (peak is None or peak < 3):
        add(-15, f"Single low-intensity detection ({peak or 0:.1f} MW)")
    if confidence and set(confidence) <= {"l", "low"}:
        add(-10, "Only low-confidence detections")

    routine = category in (
        "industrial_source", "kiln_activity", "extraction_source",
        "waste_source", "offshore_source",
    ) and pattern in ("persistent", "recurrent", "seasonal")
    if routine and not anomalous:
        add(-20, "Consistent with this location's established activity")

    score = max(0, min(100, sum(f["points"] for f in factors)))
    level = "investigate" if score >= 50 else "review" if score >= 25 else "monitor"
    return {
        "score": score,
        "level": level,
        "factors": factors,
        "definition": "Triage rule for ordering investigation; additive "
                      "points shown above. Not a probability of fire or harm.",
    }


def _unknowns(category: str, nasa_label: str | None, relation: str,
              model_used: bool) -> list[str]:
    items = [
        "No ground or high-resolution imagery verification is included.",
        "Only NOAA-21 VIIRS detections are ingested; S-NPP, NOAA-20 and "
        "MODIS would add overpasses and history.",
    ]
    if relation in ("none", "vicinity"):
        items.append(
            "OpenStreetMap coverage of Indian industry is incomplete; an "
            "unmapped facility cannot be ruled out."
        )
    if nasa_label is None:
        items.append(
            "NASA has not labelled this location: source-type labels exist "
            "only in the standard-processing archive (to June 2026)."
        )
    if category == "unresolved":
        items.append("The available evidence does not single out a source type.")
    if model_used:
        items.append(
            "The model reproduces NASA's static-source flag; it was not "
            "trained on verified industrial activity."
        )
    return items


def _next_steps(category: str, event: dict, primary: dict | None) -> list[str]:
    date = event.get("start_date_label", "the event date")
    name = (primary or {}).get("name") or "the mapped facility"
    imagery = (
        f"Compare Sentinel-2 (10 m) or Landsat imagery before and after "
        f"{date} for smoke, burn scars or damage."
    )
    watch = f"Check whether detections recur on the next overpasses ({REVISIT_NOTE})."
    steps = {
        "industrial_episodic": [
            imagery,
            f"Confirm with {name}, the fire service or the State Pollution "
            "Control Board whether an incident or new process occurred.",
            watch,
        ],
        "industrial_source": [
            "Treat as an operating source; investigate only if FRP or extent "
            "departs from its baseline.",
            f"Confirm the process at {name} (furnace, flare, kiln, boiler).",
        ],
        "unmapped_source": [
            "Identify the facility from high-resolution imagery; consider "
            "adding it to OpenStreetMap.",
            imagery,
        ],
        "kiln_activity": [
            "Brick kilns normally fire through the dry season; compare with "
            "the location's earlier seasons.",
            imagery,
        ],
        "extraction_source": [
            "Persistent heat at mines can indicate coal-seam or dump fires; "
            "compare FRP with the baseline over time.",
        ],
        "extraction_activity": [imagery, watch],
        "waste_source": [
            "Recurring landfill heat suggests smouldering waste; check with the "
            "municipal body.",
        ],
        "waste_activity": [
            imagery,
            "Landfill fires can smoulder for weeks; inform the municipal body "
            "if detections continue.",
            watch,
        ],
        "vegetation_candidate": [
            "Check land cover (cropland, forest, scrub) in imagery.",
            "Compare with the regional crop-residue burning season.",
        ],
        "offshore_source": [
            "Offshore persistent heat often corresponds to oil and gas "
            "platforms, which are not in the local OSM extract.",
        ],
        "offshore_anomaly": [imagery, watch],
        "volcanic": ["Cross-check with volcanological bulletins."],
        "unresolved": [imagery, watch],
    }
    return steps[category]
