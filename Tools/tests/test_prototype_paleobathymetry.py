from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
import pygplates


TOOLS_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = TOOLS_DIR.parent
sys.path.insert(0, str(TOOLS_DIR))

from prototype_paleobathymetry import (  # noqa: E402
    CONTINENTAL_MARGIN_PATH,
    MAX_SEAFLOOR_AGE_MA,
    RIDGE_RESET_DISTANCE_KM,
    SHALLOW_CONTINENTAL_SEA_DEPTH_M,
    TOPOLOGY_PATHS,
    build_bathymetry,
    gdh1_depth_m,
    initialise_missing_ocean,
    resolve_plate_grid,
    stage_rotation_matrix,
    xyz_to_nearest_grid_indices,
)
from prototype_paleotopography import ROTATION_PATH  # noqa: E402


class BathymetryFormulaTests(unittest.TestCase):
    def test_gdh1_is_continuous_and_deepens_with_age(self) -> None:
        age = np.asarray((0.0, 10.0, 20.0, 20.0001, 80.0, 220.0))
        depth = gdh1_depth_m(age)
        self.assertAlmostEqual(float(depth[0]), -2600.0)
        self.assertTrue(np.all(np.diff(depth) < 0.0))
        self.assertLess(abs(float(depth[3] - depth[2])), 2.0)

    def test_continental_margin_is_directly_shallow(self) -> None:
        age = np.asarray(((0.0, np.nan, np.nan),))
        land = np.asarray(((False, False, True),))
        margin = np.asarray(((False, True, False),))
        depth = build_bathymetry(age, land, margin)
        self.assertAlmostEqual(float(depth[0, 0]), -2600.0)
        self.assertAlmostEqual(float(depth[0, 1]), -SHALLOW_CONTINENTAL_SEA_DEPTH_M)
        self.assertTrue(np.isnan(depth[0, 2]))

    def test_missing_ocean_initialisation_preserves_non_oceanic_nan(self) -> None:
        age = np.full((1, 4), np.nan)
        oceanic = np.asarray(((True, True, False, False),))
        ridge_distance = np.asarray(((0.0, 6000.0, 0.0, 0.0),))
        result, count = initialise_missing_ocean(
            age, oceanic, ridge_distance, MAX_SEAFLOOR_AGE_MA, 30.0
        )
        self.assertEqual(count, 2)
        self.assertEqual(float(result[0, 0]), 0.0)
        self.assertAlmostEqual(float(result[0, 1]), 200.0)
        self.assertTrue(np.isnan(result[0, 2:]).all())

    def test_date_line_grid_sampling_wraps(self) -> None:
        longitude = np.deg2rad(np.asarray((179.9, -179.9)))
        xyz = np.column_stack((np.cos(longitude), np.sin(longitude), np.zeros(2)))
        y, x = xyz_to_nearest_grid_indices(xyz, width=360, height=180)
        self.assertEqual(int(y[0]), int(y[1]))
        self.assertTrue(np.array_equal(x, np.asarray((359, 0))))


class BathymetryTopologyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.model_dir = ROOT_DIR / "Data/processed/gplates/muller2022"
        cls.rotations = pygplates.RotationModel(str(cls.model_dir / ROTATION_PATH))

    def test_stage_rotation_maps_young_position_to_older_position(self) -> None:
        present = np.asarray((0.3, -0.4, 0.5), dtype=np.float64)
        present /= np.linalg.norm(present)
        plate_id = 701
        older_time = 100.0
        younger_time = 99.0
        older_rotation = self.rotations.get_rotation(older_time, plate_id)
        younger_rotation = self.rotations.get_rotation(younger_time, plate_id)
        expected = np.asarray(
            (older_rotation * pygplates.PointOnSphere(tuple(present))).to_xyz()
        )
        younger = np.asarray(
            (younger_rotation * pygplates.PointOnSphere(tuple(present))).to_xyz()
        )
        actual = stage_rotation_matrix(
            self.rotations, plate_id, older_time, younger_time
        ) @ younger
        self.assertLess(float(np.linalg.norm(expected - actual)), 1e-12)

    def test_dynamic_topologies_cover_smoke_grid(self) -> None:
        sources = [
            pygplates.FeatureCollection(str(self.model_dir / path))
            for path in TOPOLOGY_PATHS
        ]
        for time_ma in (0.0, 540.0, 970.0):
            plate_ids, polygon_count, gap_count = resolve_plate_grid(
                sources, self.rotations, time_ma, width=36, height=18
            )
            self.assertGreater(polygon_count, 10)
            self.assertEqual(gap_count, 0)
            self.assertTrue((plate_ids >= 0).all())
            self.assertGreater(len(np.unique(plate_ids)), 5)

    def test_continental_margin_source_exists(self) -> None:
        self.assertTrue((self.model_dir / CONTINENTAL_MARGIN_PATH).exists())


if __name__ == "__main__":
    unittest.main()
