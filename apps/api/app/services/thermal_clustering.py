from collections import defaultdict
from datetime import timezone
from math import asin, cos, floor, radians, sin, sqrt


MAX_DISTANCE_KM = 3.0
MAX_TIME_GAP_HOURS = 6.0

GRID_SIZE_DEGREES = 0.025
GRID_NEIGHBOR_RANGE = 2


def _utc(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


def _distance_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(
        radians, (lat1, lon1, lat2, lon2)
    )

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = (
        sin(dlat / 2) ** 2
        + cos(lat1) * cos(lat2)
        * sin(dlon / 2) ** 2
    )

    a = min(1.0, max(0.0, a))

    return 6371.0 * 2.0 * asin(sqrt(a))


def cluster_observations(observations: list) -> list[list]:
    """Group detections within MAX_DISTANCE_KM and MAX_TIME_GAP_HOURS.

    Each group is bounded around its seed (newest first), so nearby groups
    are not merged into unlimited chains across a region.
    """
    if not observations:
        return []

    count = len(observations)

    grid = defaultdict(list)
    cells = []

    for index, observation in enumerate(observations):
        cell = (
            floor(observation.latitude / GRID_SIZE_DEGREES),
            floor(observation.longitude / GRID_SIZE_DEGREES),
        )
        cells.append(cell)
        grid[cell].append(index)

    times = [_utc(obs.observed_at) for obs in observations]
    max_gap_seconds = MAX_TIME_GAP_HOURS * 3600

    unassigned = set(range(count))
    groups = []

    for seed_index in range(count):
        if seed_index not in unassigned:
            continue

        seed = observations[seed_index]
        seed_time = times[seed_index]
        cell_lat, cell_lon = cells[seed_index]

        group_indices = [seed_index]
        unassigned.remove(seed_index)

        candidates = []

        for dlat in range(
            -GRID_NEIGHBOR_RANGE,
            GRID_NEIGHBOR_RANGE + 1,
        ):
            for dlon in range(
                -GRID_NEIGHBOR_RANGE,
                GRID_NEIGHBOR_RANGE + 1,
            ):
                cell = (cell_lat + dlat, cell_lon + dlon)
                candidates.extend(grid.get(cell, []))

        for candidate_index in candidates:
            if candidate_index not in unassigned:
                continue

            candidate = observations[candidate_index]

            time_gap = abs(
                (times[candidate_index] - seed_time).total_seconds()
            )

            if time_gap > max_gap_seconds:
                continue

            distance = _distance_km(
                seed.latitude,
                seed.longitude,
                candidate.latitude,
                candidate.longitude,
            )

            if distance > MAX_DISTANCE_KM:
                continue

            group_indices.append(candidate_index)
            unassigned.remove(candidate_index)

        groups.append(
            [observations[i] for i in group_indices]
        )

    return groups
