from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from aitool_desktop.window_geometry import (  # noqa: E402
    DEFAULT_GEOMETRY,
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
    MAX_WINDOW_DIMENSION,
    MIN_WINDOW_HEIGHT,
    MIN_WINDOW_WIDTH,
    InvalidGeometry,
    WindowGeometry,
    WorkArea,
    default_geometry,
    load_and_place_window_geometry,
    load_window_geometry,
    parse_window_geometry,
    parse_window_geometry_strict,
    place_window_geometry,
    save_window_geometry,
    select_work_area,
    serialize_window_geometry,
)


class WindowGeometryTests(unittest.TestCase):
    def test_first_run_default_uses_fixed_width_and_balanced_height(self) -> None:
        self.assertEqual((DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT), (320, 640))
        self.assertEqual(DEFAULT_GEOMETRY, WindowGeometry(0, 0, 320, 640))

    def test_v1_round_trip_and_exact_schema(self) -> None:
        geometry = WindowGeometry(-120, 50, 800, 600)
        payload = json.loads(serialize_window_geometry(geometry))
        self.assertEqual(set(payload), {"schema_version", "x", "y", "width", "height"})
        self.assertEqual(parse_window_geometry_strict(serialize_window_geometry(geometry)), geometry)

    def test_invalid_json_types_fields_versions_and_dimensions_fall_back(self) -> None:
        base = {"schema_version": 1, "x": 1, "y": 2, "width": 800, "height": 600}
        invalid = [
            "{bad",
            {**base, "extra": 1},
            {**base, "x": True},
            {**base, "width": 800.0},
            {**base, "height": "600"},
            {key: value for key, value in base.items() if key != "height"},
            {**base, "schema_version": 2},
            {**base, "width": 0},
            {**base, "height": -1},
            {**base, "width": MAX_WINDOW_DIMENSION + 1},
        ]
        for document in invalid:
            with self.subTest(document=document):
                self.assertEqual(parse_window_geometry(document), DEFAULT_GEOMETRY)
                with self.assertRaises(InvalidGeometry):
                    parse_window_geometry_strict(document)

    def test_negative_coordinates_and_center_then_intersection_selection(self) -> None:
        left = WorkArea(-1920, 0, 0, 1080)
        right = WorkArea(0, 0, 1920, 1080)
        saved = WindowGeometry(-1500, 100, 700, 600)
        self.assertIs(select_work_area(saved, [left, right]), left)
        self.assertEqual(place_window_geometry(saved, [left, right]), saved)

    def test_saved_geometry_from_wider_version_is_restored_unchanged(self) -> None:
        area = WorkArea(0, 0, 1920, 1080)
        saved = WindowGeometry(40, 60, 760, 760)
        self.assertEqual(place_window_geometry(saved, [area]), saved)

    def test_default_geometry_starts_at_a_work_area_top_left(self) -> None:
        primary = WorkArea(-1920, 80, 0, 1160)
        self.assertEqual(
            default_geometry(primary),
            WindowGeometry(-1920, 80, 320, 640),
        )

    def test_missing_or_invalid_geometry_uses_primary_top_left_default(self) -> None:
        primary = WorkArea(0, 0, 1920, 1080)
        left = WorkArea(-1920, 0, 0, 1080)
        expected = WindowGeometry(0, 0, 320, 640)
        self.assertEqual(place_window_geometry(None, [left, primary], primary_index=1), expected)
        self.assertEqual(
            place_window_geometry({"x": "bad"}, [left, primary], primary_index=1),
            expected,
        )

        self.assertEqual(
            place_window_geometry(None, [left, primary], primary_index=0),
            WindowGeometry(-1920, 0, 320, 640),
        )

    def test_mapping_placement_requires_strict_v1_payload(self) -> None:
        primary = WorkArea(0, 0, 1920, 1080)
        invalid_mappings = [
            {"x": 1, "y": 2, "width": 800, "height": 600},
            {"schema_version": 2, "x": 1, "y": 2, "width": 800, "height": 600},
            {"schema_version": 1, "x": 1, "y": 2, "width": 800, "height": 600, "extra": 1},
        ]
        expected = default_geometry(primary)
        for saved in invalid_mappings:
            with self.subTest(saved=saved):
                self.assertEqual(place_window_geometry(saved, [primary]), expected)

    def test_load_and_place_invalid_files_use_primary_top_left_default(self) -> None:
        first = WorkArea(0, 0, 1920, 1080)
        negative_primary = WorkArea(-1920, -100, 0, 980)
        expected = WindowGeometry(-1920, -100, 320, 640)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "geometry.json"
            self.assertEqual(
                load_and_place_window_geometry(path, [first, negative_primary], primary_index=1),
                expected,
            )

            path.write_text("{bad", encoding="utf-8")
            self.assertEqual(
                load_and_place_window_geometry(path, [first, negative_primary], primary_index=1),
                expected,
            )

            path.write_text(
                json.dumps({"schema_version": 2, "x": 1, "y": 2, "width": 800, "height": 600}),
                encoding="utf-8",
            )
            self.assertEqual(
                load_and_place_window_geometry(path, [first, negative_primary], primary_index=1),
                expected,
            )

            saved = WindowGeometry(-1500, 100, 700, 600)
            path.write_text(serialize_window_geometry(saved), encoding="utf-8")
            self.assertEqual(
                load_and_place_window_geometry(path, [first, negative_primary], primary_index=1),
                saved,
            )

    def test_maximum_intersection_zero_intersection_and_tie_order(self) -> None:
        first = WorkArea(0, 0, 1000, 1000)
        second = WorkArea(1000, 0, 2000, 1000)
        # No intersection falls back to the requested primary display.
        saved = WindowGeometry(900, 1200, 200, 200)
        self.assertIs(select_work_area(saved, [first, second]), first)

        # A positive maximum intersection wins when the center is in a gap.
        first = WorkArea(0, 0, 100, 100)
        second = WorkArea(200, 0, 300, 100)
        maximum = WindowGeometry(40, 40, 300, 20)
        self.assertIs(select_work_area(maximum, [first, second]), second)

        tie = WindowGeometry(50, 40, 200, 20)
        self.assertIs(select_work_area(tie, [first, second]), first)

        no_intersection = WindowGeometry(5000, 5000, 200, 200)
        self.assertIs(select_work_area(no_intersection, [second, first]), second)

    def test_size_is_limited_before_position_and_small_work_area_is_allowed(self) -> None:
        area = WorkArea(-500, -300, 0, 0)
        placed = place_window_geometry(WindowGeometry(-999, -999, MAX_WINDOW_DIMENSION, MAX_WINDOW_DIMENSION), [area])
        self.assertEqual(placed, WindowGeometry(-500, -300, area.width, area.height))

        normal = WorkArea(0, 0, 1600, 900)
        placed = place_window_geometry(WindowGeometry(1500, 800, 100, 100), [normal])
        self.assertEqual(placed.width, MIN_WINDOW_WIDTH)
        self.assertEqual(placed.height, MIN_WINDOW_HEIGHT)
        self.assertEqual((placed.x, placed.y), (normal.right - placed.width, normal.bottom - placed.height))

    def test_position_clamp_includes_negative_work_area_bounds(self) -> None:
        area = WorkArea(-1920, -200, -320, 700)
        placed = place_window_geometry(WindowGeometry(-9999, -9999, 700, 600), [area])
        self.assertEqual(placed, WindowGeometry(-1920, -200, 700, 600))
        placed = place_window_geometry(WindowGeometry(9999, 9999, 700, 600), [area])
        self.assertEqual(placed, WindowGeometry(-1020, 100, 700, 600))

    def test_atomic_save_failure_keeps_old_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "geometry.json"
            old = WindowGeometry(1, 2, 700, 500)
            new = WindowGeometry(30, 40, 900, 700)
            save_window_geometry(path, old)
            old_contents = path.read_bytes()
            with patch("aitool_desktop.window_geometry.os.replace", side_effect=OSError("replace failed")):
                with self.assertRaises(OSError):
                    save_window_geometry(path, new)
            self.assertEqual(path.read_bytes(), old_contents)
            self.assertEqual(load_window_geometry(path), old)
            self.assertEqual(list(Path(directory).glob(".geometry.json.*.tmp")), [])

    def test_load_missing_or_invalid_file_uses_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.json"
            self.assertEqual(load_window_geometry(path), DEFAULT_GEOMETRY)
            path.write_text("null", encoding="utf-8")
            self.assertEqual(load_window_geometry(path), DEFAULT_GEOMETRY)


if __name__ == "__main__":
    unittest.main()
