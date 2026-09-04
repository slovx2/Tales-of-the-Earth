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
    NODE_FLAG_INTERACTABLE,
    NODE_HEADER_FORMAT,
    NODE_KIND_LAND_UNIT,
    NODE_KIND_TOPOLOGY,
    SNORM_SCALE,
    build_frame,
    clean_quantized_ring,
    collect_names,
    collect_strings,
    load_topology_sources,
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
        self.assertLessEqual(
            float(np.max(np.abs(decoded - vertices))), 0.5 / SNORM_SCALE + 1e-12)

    def test_quantization_preserves_date_line_sides(self) -> None:
        longitude = np.deg2rad(np.asarray((179.9, -179.9)))
        vertices = np.column_stack((np.cos(longitude), np.sin(longitude), np.zeros(2)))
        decoded = quantize_directions(vertices).astype(np.float64) / SNORM_SCALE
        self.assertGreater(decoded[0, 1], 0.0)
        self.assertLess(decoded[1, 1], 0.0)

    def test_quantization_removes_degenerate_tiny_ring(self) -> None:
        vertices = np.asarray(((10, 20, 30), (10, 20, 30), (11, 21, 31)), dtype="<i2")
        self.assertEqual(len(clean_quantized_ring(vertices)), 0)


class RegionDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.zip_path = ROOT_DIR / "Data/raw/gplates/Muller_etal_2022_SE_v1.2.4.zip"
        cls.model_dir = ROOT_DIR / "Data/processed/gplates/muller2022"
        ensure_model(cls.zip_path, cls.model_dir)
        cls.features = pygplates.FeatureCollection(str(cls.model_dir / LAND_GEOMETRY_PATH))
        cls.rotations = pygplates.RotationModel(str(cls.model_dir / ROTATION_PATH))
        cls.topology_sources = load_topology_sources(cls.model_dir)
        cls.strings = collect_strings(cls.features, cls.topology_sources)
        cls.string_ids = {value: index for index, value in enumerate(cls.strings)}

    def build(self, time_ma: float = 0.0):
        return build_frame(
            self.features, self.rotations, self.topology_sources, time_ma,
            self.string_ids, 25.0, 250_000.0)

    def test_zero_ma_keeps_hierarchy_and_all_land_units(self) -> None:
        nodes, statistics = self.build()
        topology_count = int(statistics["topology_count"])
        parents = nodes[:topology_count]
        children = nodes[topology_count:]
        self.assertEqual(len(parents), 36)
        self.assertGreater(len(children), 800)
        self.assertTrue(all(node.kind == NODE_KIND_TOPOLOGY and node.parent_index == -1
                            and node.level == 1 and node.interactable for node in parents))
        self.assertTrue(all(node.kind == NODE_KIND_LAND_UNIT and node.level == 2
                            and 0 <= node.parent_index < topology_count for node in children))
        self.assertTrue(any(not node.interactable for node in children))
        self.assertTrue(all(node.interactable == (node.area_km2 >= 250_000.0)
                            for node in children))
        self.assertEqual(len(nodes), len({node.instance_id for node in nodes}))
        self.assertGreater(int(statistics["parent_boundary_edge_count"]), 1_000)

    def test_same_source_feature_can_split_across_parent_topologies(self) -> None:
        nodes, statistics = self.build()
        children = nodes[int(statistics["topology_count"]):]
        parents_by_stable: dict[int, set[int]] = {}
        for node in children:
            parents_by_stable.setdefault(node.stable_id, set()).add(node.parent_index)
        self.assertTrue(any(len(parents) > 1 for parents in parents_by_stable.values()))

    def test_land_area_is_not_removed_by_interaction_threshold(self) -> None:
        nodes, statistics = self.build(250.0)
        children = [node for node in nodes if node.kind == NODE_KIND_LAND_UNIT]
        self.assertEqual(len(children), int(statistics["land_unit_count"]))
        self.assertAlmostEqual(
            sum(node.area_km2 for node in children),
            float(statistics["all_land_area_km2"]),
            delta=5.0,
        )
        self.assertGreater(sum(not node.interactable for node in children), 300)

    def test_duplicate_and_sub_quantization_geometry_does_not_break_parent_outline(self) -> None:
        _, statistics = self.build(80.0)
        self.assertGreater(int(statistics["dissolve_duplicate_polygon_count"]), 0)
        self.assertGreater(int(statistics["parent_boundary_edge_count"]), 1_000)

    def test_small_topology_gap_uses_bounded_nearest_parent_fallback(self) -> None:
        _, statistics = self.build(151.0)
        self.assertEqual(int(statistics["topology_gap_fallback_assignment_count"]), 1)
        self.assertLess(float(statistics["maximum_topology_assignment_gap_km"]), 25.0)

    def test_chinese_catalog_covers_all_source_names(self) -> None:
        catalog_path = ROOT_DIR / "Assets/Resources/EarthRegionNamesZhCn.json"
        document = json.loads(catalog_path.read_text(encoding="utf-8"))
        entries = document["regions"]
        sources = [entry["source"] for entry in entries]
        displays = [entry["display"] for entry in entries]
        land_names = set(collect_names(self.features))
        topology_names = {
            feature.get_name()
            for collection in self.topology_sources
            for feature in collection
            if feature.get_feature_type() ==
               pygplates.FeatureType.gpml_topological_closed_plate_boundary and feature.get_name()
        }
        self.assertEqual(document["languageCode"], "zh-CN")
        self.assertEqual(sources, sorted(sources))
        self.assertEqual(len(sources), len(set(sources)))
        self.assertEqual(set(sources), land_names | topology_names)
        self.assertTrue(all(display.strip() for display in displays))
        self.assertTrue(all(entry["basis"].strip() and entry["reference"].strip()
                            for entry in entries))
        self.assertEqual(next(entry for entry in entries if entry["source"] == "Eurasia")[
            "topologyDisplay"], "欧亚板块")
        self.assertEqual(next(entry for entry in entries if entry["source"] == "Eurasia")[
            "display"], "欧亚大陆")

    def test_binary_random_access_table_and_deterministic_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            outputs = [Path(temporary) / name for name in ("first.bin", "second.bin")]
            for index, output in enumerate(outputs):
                write_dataset(argparse.Namespace(
                    zip=self.zip_path, model_dir=self.model_dir, out=output,
                    time_step_ma=1, max_time_ma=2, coastline_km=25.0,
                    minimum_area_km2=250_000.0, jobs=index + 1))
            self.assertEqual(
                hashlib.sha256(outputs[0].read_bytes()).digest(),
                hashlib.sha256(outputs[1].read_bytes()).digest())

            with outputs[0].open("rb") as source:
                header = struct.unpack(HEADER_FORMAT, source.read(struct.calcsize(HEADER_FORMAT)))
                self.assertEqual(header[0], b"TER2")
                self.assertEqual(header[1], 2)
                self.assertEqual(header[2], 3)
                strings = []
                for _ in range(header[6]):
                    length = struct.unpack("<H", source.read(2))[0]
                    strings.append(source.read(length).decode("utf-8"))
                entries = [
                    struct.unpack(FRAME_ENTRY_FORMAT, source.read(struct.calcsize(FRAME_ENTRY_FORMAT)))
                    for _ in range(header[2])
                ]
                self.assertEqual([entry[0] for entry in entries], [0.0, 1.0, 2.0])
                source.seek(entries[0][1])
                node = struct.unpack(NODE_HEADER_FORMAT,
                                     source.read(struct.calcsize(NODE_HEADER_FORMAT)))
                self.assertEqual(node[2], -1)
                self.assertEqual(node[3:5], (NODE_KIND_TOPOLOGY, 1))
                self.assertEqual(node[9] & NODE_FLAG_INTERACTABLE, NODE_FLAG_INTERACTABLE)


if __name__ == "__main__":
    unittest.main()
