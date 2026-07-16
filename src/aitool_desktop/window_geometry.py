"""Pure window geometry persistence and placement helpers.

The module deliberately contains no GUI dependencies.  A saved geometry is a
small, strict v1 JSON document, while display selection and clamping are kept
as pure functions so they can be tested without a desktop session.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


SCHEMA_VERSION = 1
DEFAULT_WINDOW_WIDTH = 320
DEFAULT_WINDOW_HEIGHT = 640
MIN_WINDOW_WIDTH = 320
MIN_WINDOW_HEIGHT = 420
MAX_WINDOW_DIMENSION = 10_000


@dataclass(frozen=True)
class WindowGeometry:
    """A window rectangle represented by its top-left corner and size."""

    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        for name in ("x", "y", "width", "height"):
            if type(getattr(self, name)) is not int:
                raise TypeError(f"{name} must be an int")


@dataclass(frozen=True)
class WorkArea:
    """A display's usable rectangle.

    ``right`` and ``bottom`` are the far edges, so the usable size is
    ``right - left`` by ``bottom - top``.  This representation naturally
    supports monitors positioned at negative coordinates.
    """

    left: int
    top: int
    right: int
    bottom: int

    def __post_init__(self) -> None:
        for name in ("left", "top", "right", "bottom"):
            if type(getattr(self, name)) is not int:
                raise TypeError(f"{name} must be an int")
        if self.right <= self.left or self.bottom <= self.top:
            raise ValueError("work area must have positive width and height")

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @classmethod
    def from_xywh(cls, left: int, top: int, width: int, height: int) -> WorkArea:
        """Build a work area from a top-left point and a size."""

        return cls(left, top, left + width, top + height)


# A descriptive alias is useful to callers that get monitor rectangles from
# an operating-system API.
DisplayWorkArea = WorkArea


DEFAULT_GEOMETRY = WindowGeometry(0, 0, DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)

_GEOMETRY_KEYS = frozenset(("schema_version", "x", "y", "width", "height"))


class InvalidGeometry(ValueError):
    """Raised when a geometry document does not satisfy the v1 contract."""


def default_geometry(work_area: WorkArea | None = None) -> WindowGeometry:
    """Return the default 320x640 geometry at an area's top-left corner.

    With no work area this retains the historical origin-based value for the
    persistence/parser APIs.  Placement code passes the selected primary area
    explicitly so that a missing or invalid saved value uses that area's
    top-left corner.
    """

    if work_area is None:
        left = DEFAULT_GEOMETRY.x
        top = DEFAULT_GEOMETRY.y
    else:
        if not isinstance(work_area, WorkArea):
            raise TypeError("work_area must be a WorkArea")
        left = work_area.left
        top = work_area.top
    return WindowGeometry(left, top, DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)


def _valid_dimension(value: object) -> bool:
    return type(value) is int and 0 < value <= MAX_WINDOW_DIMENSION


def _parse_geometry_payload(payload: object) -> WindowGeometry:
    if not isinstance(payload, dict):
        raise InvalidGeometry("geometry JSON must be an object")
    if set(payload) != _GEOMETRY_KEYS:
        raise InvalidGeometry("geometry has missing or unknown fields")
    if payload["schema_version"] != SCHEMA_VERSION or type(payload["schema_version"]) is not int:
        raise InvalidGeometry("unsupported geometry schema version")

    values = {name: payload[name] for name in ("x", "y", "width", "height")}
    if any(type(value) is not int for value in values.values()):
        raise InvalidGeometry("geometry coordinates and dimensions must be ints")
    if not _valid_dimension(values["width"]) or not _valid_dimension(values["height"]):
        raise InvalidGeometry("geometry dimensions are outside the v1 bounds")
    return WindowGeometry(**values)


def parse_window_geometry_strict(
    data: str | bytes | bytearray | Mapping[str, object],
) -> WindowGeometry:
    """Parse and strictly validate a v1 geometry document.

    ``InvalidGeometry`` (a ``ValueError`` subclass) is raised for malformed
    JSON, wrong types, missing fields, extra fields, unsupported versions, or
    out-of-range dimensions.
    """

    if isinstance(data, (str, bytes, bytearray)):
        try:
            payload = json.loads(data)
        except (TypeError, ValueError) as exc:
            raise InvalidGeometry("invalid geometry JSON") from exc
    elif isinstance(data, Mapping):
        payload = dict(data)
    else:
        raise InvalidGeometry("geometry input must be JSON or a mapping")
    return _parse_geometry_payload(payload)


def parse_window_geometry(
    data: str | bytes | bytearray | Mapping[str, object],
    *,
    fallback: WindowGeometry | None = None,
) -> WindowGeometry:
    """Parse geometry and return the default (or ``fallback``) on rejection."""

    safe_fallback = default_geometry() if fallback is None else fallback
    if not isinstance(safe_fallback, WindowGeometry):
        raise TypeError("fallback must be a WindowGeometry")
    try:
        return parse_window_geometry_strict(data)
    except (InvalidGeometry, TypeError, ValueError):
        return safe_fallback


# Short names make the JSON boundary convenient without hiding the strict API.
parse_geometry = parse_window_geometry
parse_geometry_strict = parse_window_geometry_strict


def geometry_to_payload(geometry: WindowGeometry) -> dict[str, int]:
    """Return the exact v1 payload for a valid geometry."""

    if not isinstance(geometry, WindowGeometry):
        raise TypeError("geometry must be a WindowGeometry")
    if not all(type(getattr(geometry, name)) is int for name in ("x", "y", "width", "height")):
        raise InvalidGeometry("geometry fields must be ints")
    if not _valid_dimension(geometry.width) or not _valid_dimension(geometry.height):
        raise InvalidGeometry("geometry dimensions are outside the v1 bounds")
    return {
        "schema_version": SCHEMA_VERSION,
        "x": geometry.x,
        "y": geometry.y,
        "width": geometry.width,
        "height": geometry.height,
    }


def serialize_window_geometry(geometry: WindowGeometry) -> str:
    """Serialize a valid geometry as compact, UTF-8-compatible JSON."""

    return json.dumps(geometry_to_payload(geometry), ensure_ascii=False, separators=(",", ":"))


serialize_geometry = serialize_window_geometry


def load_window_geometry(
    path: str | os.PathLike[str],
    *,
    fallback: WindowGeometry | None = None,
) -> WindowGeometry:
    """Load a geometry file, falling back when it is absent or invalid."""

    safe_fallback = default_geometry() if fallback is None else fallback
    if not isinstance(safe_fallback, WindowGeometry):
        raise TypeError("fallback must be a WindowGeometry")
    loaded = _read_window_geometry(path)
    return safe_fallback if loaded is None else loaded


def _read_window_geometry(path: str | os.PathLike[str]) -> WindowGeometry | None:
    """Read a geometry file without turning an invalid value into a position."""

    try:
        return parse_window_geometry_strict(Path(path).read_bytes())
    except (OSError, InvalidGeometry, TypeError, ValueError):
        return None


load_geometry = load_window_geometry


def save_window_geometry(path: str | os.PathLike[str], geometry: WindowGeometry) -> None:
    """Atomically save geometry using a same-directory temp file.

    The temporary file is flushed and fsynced before ``os.replace``.  Any
    failure before replacement leaves an existing destination untouched; the
    temporary file is removed in all failure paths.
    """

    serialized = serialize_window_geometry(geometry)
    destination = Path(path)
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = temporary.name
            temporary.write(serialized)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, destination)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass


save_geometry = save_window_geometry


def _coerce_saved_geometry(
    saved: WindowGeometry | Mapping[str, object] | None,
) -> WindowGeometry | None:
    if isinstance(saved, WindowGeometry):
        candidate = saved
    elif isinstance(saved, Mapping):
        try:
            candidate = parse_window_geometry_strict(saved)
        except (InvalidGeometry, TypeError, ValueError):
            return None
    else:
        return None

    if not all(type(getattr(candidate, name)) is int for name in ("x", "y", "width", "height")):
        return None
    if not _valid_dimension(candidate.width) or not _valid_dimension(candidate.height):
        return None
    return candidate


def _intersection_area(geometry: WindowGeometry, area: WorkArea) -> int:
    overlap_width = max(0, min(geometry.x + geometry.width, area.right) - max(geometry.x, area.left))
    overlap_height = max(0, min(geometry.y + geometry.height, area.bottom) - max(geometry.y, area.top))
    return overlap_width * overlap_height


def select_work_area(
    saved_geometry: WindowGeometry | Mapping[str, object] | None,
    work_areas: Sequence[WorkArea],
    *,
    primary_index: int = 0,
) -> WorkArea:
    """Select a display by center, then by maximum positive intersection.

    Center hits and intersection ties retain the supplied work-area order.
    A zero-area intersection is intentionally not a match.
    """

    if not work_areas:
        raise ValueError("at least one work area is required")
    if not 0 <= primary_index < len(work_areas):
        raise IndexError("primary_index is outside work_areas")
    if not all(isinstance(area, WorkArea) for area in work_areas):
        raise TypeError("work_areas must contain WorkArea values")

    candidate = _coerce_saved_geometry(saved_geometry)
    if candidate is None:
        return work_areas[primary_index]
    doubled_center_x = 2 * candidate.x + candidate.width
    doubled_center_y = 2 * candidate.y + candidate.height
    for area in work_areas:
        if (
            2 * area.left <= doubled_center_x < 2 * area.right
            and 2 * area.top <= doubled_center_y < 2 * area.bottom
        ):
            return area

    best_area: WorkArea | None = None
    best_intersection = 0
    for area in work_areas:
        intersection = _intersection_area(candidate, area)
        if intersection > best_intersection:
            best_intersection = intersection
            best_area = area
    return work_areas[primary_index] if best_area is None else best_area


def place_window_geometry(
    saved_geometry: WindowGeometry | Mapping[str, object] | None,
    work_areas: Sequence[WorkArea],
    *,
    primary_index: int = 0,
) -> WindowGeometry:
    """Choose a display, clamp size, then clamp the top-left position."""

    area = select_work_area(saved_geometry, work_areas, primary_index=primary_index)
    candidate = _coerce_saved_geometry(saved_geometry)
    if candidate is None:
        candidate = default_geometry(area)

    width = min(max(candidate.width, MIN_WINDOW_WIDTH), MAX_WINDOW_DIMENSION)
    height = min(max(candidate.height, MIN_WINDOW_HEIGHT), MAX_WINDOW_DIMENSION)
    # A work area smaller than the normal minimum is allowed to determine the
    # actual size.  This is done after the normal minimum/max bound.
    width = min(width, area.width)
    height = min(height, area.height)

    x = min(max(candidate.x, area.left), area.right - width)
    y = min(max(candidate.y, area.top), area.bottom - height)
    return WindowGeometry(x, y, width, height)


def load_and_place_window_geometry(
    path: str | os.PathLike[str],
    work_areas: Sequence[WorkArea],
    *,
    primary_index: int = 0,
) -> WindowGeometry:
    """Load and place geometry, using the primary area's top-left for defaults.

    Unlike :func:`load_window_geometry`, this composition keeps an invalid or
    missing file distinguishable from a valid origin-based geometry.  Such a
    file therefore cannot select a display based on the fallback's center.
    """

    saved_geometry = _read_window_geometry(path)
    return place_window_geometry(saved_geometry, work_areas, primary_index=primary_index)


resolve_window_geometry = place_window_geometry
restore_window_geometry = place_window_geometry
clamp_geometry = place_window_geometry


__all__ = [
    "SCHEMA_VERSION",
    "DEFAULT_WINDOW_WIDTH",
    "DEFAULT_WINDOW_HEIGHT",
    "MIN_WINDOW_WIDTH",
    "MIN_WINDOW_HEIGHT",
    "MAX_WINDOW_DIMENSION",
    "WindowGeometry",
    "WorkArea",
    "DisplayWorkArea",
    "DEFAULT_GEOMETRY",
    "InvalidGeometry",
    "default_geometry",
    "parse_window_geometry_strict",
    "parse_window_geometry",
    "parse_geometry_strict",
    "parse_geometry",
    "geometry_to_payload",
    "serialize_window_geometry",
    "serialize_geometry",
    "load_window_geometry",
    "load_geometry",
    "save_window_geometry",
    "save_geometry",
    "select_work_area",
    "place_window_geometry",
    "load_and_place_window_geometry",
    "resolve_window_geometry",
    "restore_window_geometry",
    "clamp_geometry",
]
