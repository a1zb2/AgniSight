"""Shared spatial grid used by the cell registry and history lookups.

The cell size (~440 m N-S) is close to one VIIRS I-band pixel (375 m at
nadir). PostgreSQL computes the same value with agni_cell() (migration
0002), so both sides must keep using plain floor(value / CELL_SIZE).
"""

from math import floor

CELL_SIZE_DEGREES = 0.004

# A location's history is read from its own cell and the 8 cells around it,
# which tolerates VIIRS geolocation scatter and sources on a cell boundary.
NEIGHBOR_OFFSETS = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)]


def cell_index(value: float) -> int:
    return floor(value / CELL_SIZE_DEGREES)


def cell_of(longitude: float, latitude: float) -> tuple[int, int]:
    return cell_index(longitude), cell_index(latitude)


def neighborhood(cell: tuple[int, int]) -> list[tuple[int, int]]:
    x, y = cell
    return [(x + dx, y + dy) for dx, dy in NEIGHBOR_OFFSETS]


def cell_center(cell: tuple[int, int]) -> tuple[float, float]:
    x, y = cell
    return (
        (x + 0.5) * CELL_SIZE_DEGREES,
        (y + 0.5) * CELL_SIZE_DEGREES,
    )
