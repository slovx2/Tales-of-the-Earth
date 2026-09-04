from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np


TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

from build_runtime_terrain import resample_bilinear  # noqa: E402


class TerrainResamplingTests(unittest.TestCase):
    def test_resample_returns_requested_shape(self) -> None:
        source = np.arange(8 * 6, dtype=np.float32).reshape(8, 6)
        result = resample_bilinear(source, 3, 4)
        self.assertEqual(result.shape, (4, 3))
        self.assertTrue(np.isfinite(result).all())

    def test_constant_field_is_preserved(self) -> None:
        source = np.full((8, 6), 123.5, dtype=np.float32)
        result = resample_bilinear(source, 3, 4)
        np.testing.assert_allclose(result, 123.5, rtol=0.0, atol=1e-5)

    def test_longitude_wrap_is_continuous(self) -> None:
        source = np.tile(np.asarray([0.0, 10.0, 20.0, 30.0], dtype=np.float32), (4, 1))
        result = resample_bilinear(source, 8, 4)
        self.assertAlmostEqual(float(result[0, -1]), 15.0, places=5)
        self.assertAlmostEqual(float(result[0, 0]), 0.0, places=5)


if __name__ == "__main__":
    unittest.main()
