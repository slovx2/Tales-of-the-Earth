from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

import numpy as np
import pygplates


TOOLS_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = TOOLS_DIR.parent
sys.path.insert(0, str(TOOLS_DIR))

from prototype_paleotopography import (  # noqa: E402
    HypsometricCalibration,
    ROTATION_PATH,
    erosion_from_relief,
    finite_rotation_matrix,
    growth_increment,
)


class FormulaTests(unittest.TestCase):
    def test_erosion_increases_with_relief(self) -> None:
        relief = np.asarray((0.0, 1000.0, 2000.0, 3000.0, 7000.0))
        erosion = erosion_from_relief(relief)
        self.assertTrue(np.all(np.diff(erosion) > 0.0))
        self.assertAlmostEqual(float(erosion[0]), 1.0, delta=1.0)
        self.assertAlmostEqual(float(erosion[2]), 301.0, delta=1e-9)
        self.assertAlmostEqual(float(erosion[-1]), 601.0, delta=1.0)

    def test_growth_approaches_zero_at_high_elevation(self) -> None:
        elevation = np.asarray((0.0, 1000.0, 3000.0, 6000.0))
        growth = growth_increment(elevation, scale=300.0, decay=0.001)
        self.assertTrue(np.all(np.diff(growth) < 0.0))
        self.assertAlmostEqual(float(growth[0]), 300.0)

    def test_hypsometric_mapping_is_monotonic(self) -> None:
        calibration = HypsometricCalibration(
            np.asarray((-500.0, 0.0, 1000.0, 7000.0)),
            np.asarray((0.0, 200.0, 800.0, 6000.0)),
        )
        mapped = calibration.apply(np.linspace(-500.0, 7000.0, 100))
        self.assertTrue(np.all(np.diff(mapped) >= 0.0))


class RotationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        model_dir = ROOT_DIR / "Data/processed/gplates/muller2022"
        cls.rotations = pygplates.RotationModel(str(model_dir / ROTATION_PATH))

    def test_numpy_rotation_matches_pygplates(self) -> None:
        source = np.asarray((0.3, -0.4, 0.5), dtype=np.float64)
        source /= np.linalg.norm(source)
        for plate_id, time_ma in ((701, 100.0), (101, 400.0), (401, 750.0)):
            rotation = self.rotations.get_rotation(time_ma, plate_id)
            expected = np.asarray((rotation * pygplates.PointOnSphere(tuple(source))).to_xyz())
            actual = finite_rotation_matrix(rotation) @ source
            self.assertLess(float(np.linalg.norm(expected - actual)), 1e-12)
            self.assertAlmostEqual(float(np.linalg.norm(actual)), 1.0, delta=1e-12)


if __name__ == "__main__":
    unittest.main()
