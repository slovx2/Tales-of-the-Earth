from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pygplates


TOOLS_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = TOOLS_DIR.parent
sys.path.insert(0, str(TOOLS_DIR))

from build_runtime_regions import (  # noqa: E402
    FRAME_ENTRY_FORMAT,
    HEADER_FORMAT,
    SNORM_SCALE,
    build_frame,
    collect_names,
    quantize_directions,
    write_dataset,
)
from generate_paleogeography import (  # noqa: E402
    LAND_GEOMETRY_PATH,
    ROTATION_PATH,
    ensure_model,
)


class RegionEncodingTests(unittest.TestCase):
    def test_snorm_direction_quantization_error_is_bounded(self) -> None:
        vertices = np.asarray((
            (1.0, 0.0, 0.0),
            (-0.3, 0.4, np.sqrt(0.75)),
            (0.001, -0.999, 0.044699),
        ), dtype=np.float64)
        vertices /= np.linalg.norm(vertices, axis=1)[:, None]
        encoded = quantize_directions(vertices)
        decoded = encoded.astype(np.float64) / SNORM_SCALE
        self.assertLessEqual(float(np.max(np.abs(decoded - vertices))), 0.5 / SNORM_SCALE + 1e-12)

    def test_quantization_preserves_date_line_sides(self) -> None:
        longitude = np.deg2rad(np.asarray((179.9, -179.9)))
        vertices = np.column_stack((np.cos(longitude), np.sin(longitude), np.zeros(2)))
        decoded = quantize_directions(vertices).astype(np.float64) / SNORM_SCALE
        self.assertGreater(decoded[0, 1], 0.0)
        self.assertLess(decoded[1, 1], 0.0)


class RegionDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.zip_path = ROOT_DIR / "Data/raw/gplates/Muller_etal_2022_SE_v1.2.4.zip"
        cls.model_dir = ROOT_DIR / "Data/processed/gplates/muller2022"
        ensure_model(cls.zip_path, cls.model_dir)
        cls.features = pygplates.FeatureCollection(str(cls.model_dir / LAND_GEOMETRY_PATH))
        cls.rotations = pygplates.RotationModel(str(cls.model_dir / ROTATION_PATH))
        cls.names = collect_names(cls.features)
        cls.name_ids = {name: index for index, name in enumerate(cls.names)}

    def test_zero_ma_groups_names_and_applies_area_threshold(self) -> None:
        regions, statistics = build_frame(
            self.features, self.rotations, 0.0, self.name_ids, 25.0, 250_000.0)
        self.assertEqual(len(regions), 149)
        self.assertEqual(len({region.name for region in regions}), len(regions))
        self.assertTrue(all(region.area_km2 >= 250_000.0 for region in regions))
        self.assertAlmostEqual(float(statistics["retained_land_fraction"]), 0.756, delta=0.002)
        self.assertGreater(int(statistics["vertex_count"]), 80_000)

    def test_chinese_catalog_covers_all_source_names(self) -> None:
        regions, _ = build_frame(
            self.features, self.rotations, 0.0, self.name_ids, 25.0, 250_000.0)
        catalog_path = ROOT_DIR / "Assets/Resources/EarthRegionNamesZhCn.json"
        document = json.loads(catalog_path.read_text(encoding="utf-8"))
        self.assertEqual(document["languageCode"], "zh-CN")
        entries = document["regions"]
        sources = [entry["source"] for entry in entries]
        displays = [entry["display"] for entry in entries]
        allowed_bases = {"惯用译名", "组合翻译", "审慎音译", "原始名称疑误"}
        self.assertEqual(sources, sorted(sources))
        self.assertEqual(len(sources), len(set(sources)))
        self.assertEqual(len(sources), 642)
        self.assertEqual(set(sources), set(self.names))
        self.assertTrue({region.name for region in regions}.issubset(set(sources)))
        self.assertTrue(all(display.strip() for display in displays))
        self.assertTrue(all(any("\u4e00" <= character <= "\u9fff" for character in display)
                            for display in displays))
        self.assertTrue(all(entry["basis"] in allowed_bases for entry in entries))
        self.assertTrue(all(entry["reference"].strip() for entry in entries))

    def test_binary_contains_one_ma_random_access_table_and_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "first.bin"
            second = Path(temporary) / "second.bin"
            for output in (first, second):
                write_dataset(argparse.Namespace(
                    zip=self.zip_path,
                    model_dir=self.model_dir,
                    out=output,
                    time_step_ma=1,
                    max_time_ma=2,
                    coastline_km=25.0,
                    minimum_area_km2=250_000.0,
                ))
            self.assertEqual(
                hashlib.sha256(first.read_bytes()).digest(),
                hashlib.sha256(second.read_bytes()).digest())

            with first.open("rb") as source:
                header = struct.unpack(HEADER_FORMAT, source.read(struct.calcsize(HEADER_FORMAT)))
                self.assertEqual(header[0], b"TER1")
                self.assertEqual(header[2], 3)
                self.assertEqual(header[3], 1.0)
                self.assertEqual(header[5], 250_000.0)
                for _ in range(header[6]):
                    name_length = struct.unpack("<H", source.read(2))[0]
                    self.assertTrue(source.read(name_length).decode("utf-8"))
                entries = [
                    struct.unpack(FRAME_ENTRY_FORMAT, source.read(struct.calcsize(FRAME_ENTRY_FORMAT)))
                    for _ in range(header[2])
                ]
                self.assertEqual([entry[0] for entry in entries], [0.0, 1.0, 2.0])
                self.assertTrue(all(entry[2] > 0 and entry[3] > 0 for entry in entries))
                self.assertTrue(all(entries[index][1] < entries[index + 1][1] for index in range(2)))


if __name__ == "__main__":
    unittest.main()
