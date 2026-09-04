from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from pohl_climate import (  # noqa: E402
    KOPPEN_AF,
    KOPPEN_BW,
    KOPPEN_EF,
    KOPPEN_ET,
    MappedClimateFields,
    classify_koppen,
    compute_transition,
    interpolate_mapped_fields,
    map_slice_to_target,
    precipitation_mm_day_to_monthly,
    target_cell_centres,
    PohlClimateSlice,
)


class PohlClimateTests(unittest.TestCase):
    def test_grid_centres_and_longitude_wrap(self) -> None:
        lon, lat = target_cell_centres(360, 180)
        self.assertAlmostEqual(float(lon[0]), -179.5)
        self.assertAlmostEqual(float(lon[-1]), 179.5)
        self.assertAlmostEqual(float(lat[0]), 89.5)
        self.assertAlmostEqual(float(lat[-1]), -89.5)

    def test_mapping_uses_nearest_land_and_fallback(self) -> None:
        lon = np.asarray([0.0, 180.0], dtype=np.float32)
        lat = np.asarray([-45.0, 45.0], dtype=np.float32)
        values = np.zeros((12, 2, 2), dtype=np.float32)
        values[:, 0, 0] = 1.0
        values[:, 1, 1] = 9.0
        slice_ = PohlClimateSlice(0.0, lon, lat, values, values, values,
                                  np.ones((2, 2), dtype=bool), np.ones((2, 2), dtype=np.uint8))
        mapped = map_slice_to_target(slice_, width=4, height=2, maximum_distance_degrees=30.0)
        self.assertEqual(mapped.temperature_monthly.shape, (12, 2, 4))
        self.assertTrue(np.isfinite(mapped.confidence).all())

    def test_interpolation_is_exact_at_endpoints(self) -> None:
        a = MappedClimateFields(np.zeros((12, 1, 1), np.float32), np.zeros((12, 1, 1), np.float32),
                                np.zeros((12, 1, 1), np.float32), np.ones((1, 1), np.float32))
        b = MappedClimateFields(np.full((12, 1, 1), 10, np.float32), np.full((12, 1, 1), 20, np.float32),
                                np.full((12, 1, 1), 30, np.float32), np.zeros((1, 1), np.float32))
        np.testing.assert_array_equal(interpolate_mapped_fields(a, b, 0).temperature_monthly, a.temperature_monthly)
        np.testing.assert_array_equal(interpolate_mapped_fields(a, b, 1).temperature_monthly, b.temperature_monthly)
        self.assertEqual(float(interpolate_mapped_fields(a, b, .5).precipitation_monthly[0, 0, 0]), 10.0)

    def test_synthetic_koppen_classes(self) -> None:
        lat = np.asarray([[10.0]])
        tropical_wet = np.full((12, 1, 1), 26.0, np.float32)
        wet = precipitation_mm_day_to_monthly(np.full((12, 1, 1), 8.0, np.float32))
        self.assertEqual(int(classify_koppen(tropical_wet, wet, lat)[0, 0]), KOPPEN_AF)
        dry = precipitation_mm_day_to_monthly(np.full((12, 1, 1), 0.05, np.float32))
        self.assertEqual(int(classify_koppen(tropical_wet, dry, lat)[0, 0]), KOPPEN_BW)
        polar = np.full((12, 1, 1), -12.0, np.float32)
        self.assertEqual(int(classify_koppen(polar, wet, lat)[0, 0]), KOPPEN_EF)
        tundra = np.full((12, 1, 1), 3.0, np.float32)
        self.assertEqual(int(classify_koppen(tundra, wet, lat)[0, 0]), KOPPEN_ET)

    def test_transition_does_not_cross_ocean_and_wraps_longitude(self) -> None:
        classes = np.asarray([[9, 9, 10, 0], [9, 9, 10, 0]], dtype=np.uint8)
        land = classes > 0
        primary, secondary, blend = compute_transition(classes, land)
        self.assertGreater(float(blend[0, 1]), 0.0)
        self.assertEqual(int(secondary[0, 1]), 10)
        self.assertEqual(int(blend[0, 3]), 0)


if __name__ == "__main__":
    unittest.main()
