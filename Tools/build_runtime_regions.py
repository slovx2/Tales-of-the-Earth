#!/usr/bin/env python3
"""把 MULLER2022 命名陆地区域编译为 Unity 可随机读取的逐 Ma 数据。"""

from __future__ import annotations

import argparse
import json
import math
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
import pygplates

from generate_paleogeography import (
    LAND_DEFINITION,
    LAND_GEOMETRY_PATH,
    MODEL_SHA256,
    MODEL_URL,
    ROTATION_PATH,
    ensure_model,
)
from rasterize_natural_earth import sha256


EARTH_RADIUS_KM = 6371.0
FILE_MAGIC = b"TER1"
FILE_VERSION = 1
HEADER_FORMAT = "<4siifffi"
FRAME_ENTRY_FORMAT = "<fqiiii"
REGION_HEADER_FORMAT = "<ifi"
POLYGON_HEADER_FORMAT = "<ffffi"
RING_HEADER_FORMAT = "<Bi"
SNORM_SCALE = 32767.0


@dataclass(frozen=True)
class EncodedRing:
    is_hole: bool
    vertices: np.ndarray


@dataclass(frozen=True)
class EncodedPolygon:
    cone_center: tuple[float, float, float]
    cone_minimum_dot: float
    rings: tuple[EncodedRing, ...]


@dataclass(frozen=True)
class EncodedRegion:
    name_id: int
    name: str
    area_km2: float
    polygons: tuple[EncodedPolygon, ...]


def point_xyz(point: object) -> tuple[float, float, float]:
    x, y, z = point.to_xyz()  # type: ignore[attr-defined]
    return float(x), float(y), float(z)


def clean_ring(points: Sequence[object]) -> list[object]:
    """去掉连续重复点和闭环末尾重复点。"""
    cleaned: list[object] = []
    previous: tuple[float, float, float] | None = None
    for point in points:
        xyz = point_xyz(point)
        if previous is None or sum((xyz[index] - previous[index]) ** 2 for index in range(3)) > 1e-18:
            cleaned.append(point)
            previous = xyz
    if len(cleaned) > 1:
        first = point_xyz(cleaned[0])
        last = point_xyz(cleaned[-1])
        if sum((first[index] - last[index]) ** 2 for index in range(3)) <= 1e-18:
            cleaned.pop()
    return cleaned


def quantize_directions(vertices: np.ndarray) -> np.ndarray:
    """把单位球方向量化为三分量有符号 16 位整数。"""
    clipped = np.clip(vertices, -1.0, 1.0)
    return np.rint(clipped * SNORM_SCALE).astype("<i2")


def encode_polygon(geometry: object, coastline_radians: float) -> EncodedPolygon | None:
    dense = geometry.to_tessellated(coastline_radians)  # type: ignore[attr-defined]
    source_rings = [clean_ring(dense.get_exterior_ring_points())]
    hole_flags = [False]
    for ring_index in range(dense.get_number_of_interior_rings()):
        source_rings.append(clean_ring(dense.get_interior_ring_points(ring_index)))
        hole_flags.append(True)
    valid = [(ring, is_hole) for ring, is_hole in zip(source_rings, hole_flags) if len(ring) >= 3]
    if not valid or valid[0][1]:
        return None

    all_vertices = np.asarray(
        [point_xyz(point) for ring, _ in valid for point in ring], dtype=np.float64)
    center = np.asarray(point_xyz(dense.get_interior_centroid()), dtype=np.float64)
    center_length = float(np.linalg.norm(center))
    if center_length <= 1e-12:
        center = np.mean(all_vertices, axis=0)
        center_length = float(np.linalg.norm(center))
    if center_length <= 1e-12:
        return None
    center /= center_length
    minimum_dot = float(np.min(all_vertices @ center)) - 1e-5
    encoded_rings = tuple(
        EncodedRing(
            is_hole=is_hole,
            vertices=quantize_directions(
                np.asarray([point_xyz(point) for point in ring], dtype=np.float64)),
        )
        for ring, is_hole in valid
    )
    return EncodedPolygon(
        cone_center=(float(center[0]), float(center[1]), float(center[2])),
        cone_minimum_dot=max(-1.0, minimum_dot),
        rings=encoded_rings,
    )


def build_frame(feature_collection: object, rotation_model: object, time_ma: float,
                names_to_ids: dict[str, int], coastline_km: float,
                minimum_area_km2: float) -> tuple[list[EncodedRegion], dict[str, object]]:
    started = time.perf_counter()
    reconstructed: list[object] = []
    pygplates.reconstruct(feature_collection, rotation_model, reconstructed, time_ma)
    geometries_by_name: dict[str, list[object]] = {}
    area_by_name: dict[str, float] = {}
    total_named_area_km2 = 0.0
    skipped_unnamed = 0

    for reconstructed_feature in reconstructed:
        geometry = reconstructed_feature.get_reconstructed_geometry()  # type: ignore[attr-defined]
        if not hasattr(geometry, "get_exterior_ring_points"):
            continue
        name = reconstructed_feature.get_feature().get_name()  # type: ignore[attr-defined]
        if not name:
            skipped_unnamed += 1
            continue
        area_km2 = float(geometry.get_area()) * EARTH_RADIUS_KM * EARTH_RADIUS_KM
        geometries_by_name.setdefault(name, []).append(geometry)
        area_by_name[name] = area_by_name.get(name, 0.0) + area_km2
        total_named_area_km2 += area_km2

    coastline_radians = coastline_km / EARTH_RADIUS_KM
    regions: list[EncodedRegion] = []
    polygon_count = 0
    ring_count = 0
    vertex_count = 0
    retained_area_km2 = 0.0
    for name in sorted(geometries_by_name, key=lambda value: names_to_ids[value]):
        area_km2 = area_by_name[name]
        if area_km2 < minimum_area_km2:
            continue
        polygons = tuple(
            polygon
            for geometry in geometries_by_name[name]
            if (polygon := encode_polygon(geometry, coastline_radians)) is not None
        )
        if not polygons:
            continue
        regions.append(EncodedRegion(names_to_ids[name], name, area_km2, polygons))
        retained_area_km2 += area_km2
        polygon_count += len(polygons)
        ring_count += sum(len(polygon.rings) for polygon in polygons)
        vertex_count += sum(len(ring.vertices) for polygon in polygons for ring in polygon.rings)

    statistics: dict[str, object] = {
        "time_ma": time_ma,
        "region_count": len(regions),
        "polygon_count": polygon_count,
        "ring_count": ring_count,
        "vertex_count": vertex_count,
        "skipped_unnamed_polygon_count": skipped_unnamed,
        "named_land_area_km2": total_named_area_km2,
        "retained_area_km2": retained_area_km2,
        "retained_land_fraction": (
            retained_area_km2 / total_named_area_km2 if total_named_area_km2 > 0.0 else 0.0
        ),
        "build_seconds": time.perf_counter() - started,
    }
    return regions, statistics


def write_names(output: object, names: list[str]) -> None:
    for name in names:
        encoded = name.encode("utf-8")
        if len(encoded) > 65535:
            raise ValueError(f"区域名称过长：{name[:80]}")
        output.write(struct.pack("<H", len(encoded)))  # type: ignore[attr-defined]
        output.write(encoded)  # type: ignore[attr-defined]


def write_frame(output: object, regions: list[EncodedRegion]) -> None:
    for region in regions:
        output.write(struct.pack(  # type: ignore[attr-defined]
            REGION_HEADER_FORMAT, region.name_id, region.area_km2, len(region.polygons)))
        for polygon in region.polygons:
            output.write(struct.pack(  # type: ignore[attr-defined]
                POLYGON_HEADER_FORMAT,
                *polygon.cone_center,
                polygon.cone_minimum_dot,
                len(polygon.rings),
            ))
            for ring in polygon.rings:
                output.write(struct.pack(  # type: ignore[attr-defined]
                    RING_HEADER_FORMAT, 1 if ring.is_hole else 0, len(ring.vertices)))
                output.write(ring.vertices.tobytes())  # type: ignore[attr-defined]


def collect_names(features: object) -> list[str]:
    return sorted({feature.get_name() for feature in features if feature.get_name()})


def write_dataset(args: argparse.Namespace) -> None:
    model_dir = ensure_model(args.zip, args.model_dir)
    geometry_file = model_dir / LAND_GEOMETRY_PATH
    rotation_file = model_dir / ROTATION_PATH
    features = pygplates.FeatureCollection(str(geometry_file))
    rotations = pygplates.RotationModel(str(rotation_file))
    names = collect_names(features)
    names_to_ids = {name: index for index, name in enumerate(names)}
    times = [float(value) for value in range(0, args.max_time_ma + 1, args.time_step_ma)]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    header_size = struct.calcsize(HEADER_FORMAT)
    names_size = sum(2 + len(name.encode("utf-8")) for name in names)
    table_offset = header_size + names_size
    entry_size = struct.calcsize(FRAME_ENTRY_FORMAT)
    entries: list[tuple[float, int, int, int, int, int]] = []
    frame_statistics: list[dict[str, object]] = []

    with args.out.open("wb") as output:
        output.write(struct.pack(
            HEADER_FORMAT,
            FILE_MAGIC,
            FILE_VERSION,
            len(times),
            float(args.time_step_ma),
            float(args.coastline_km),
            float(args.minimum_area_km2),
            len(names),
        ))
        write_names(output, names)
        if output.tell() != table_offset:
            raise AssertionError("区域名称表长度计算错误")
        output.write(b"\0" * (entry_size * len(times)))

        for time_ma in times:
            regions, statistics = build_frame(
                features,
                rotations,
                time_ma,
                names_to_ids,
                args.coastline_km,
                args.minimum_area_km2,
            )
            offset = output.tell()
            write_frame(output, regions)
            byte_length = output.tell() - offset
            entries.append((
                time_ma,
                offset,
                byte_length,
                len(regions),
                int(statistics["polygon_count"]),
                int(statistics["vertex_count"]),
            ))
            statistics["byte_length"] = byte_length
            frame_statistics.append(statistics)
            print(
                f"{time_ma:6.1f} Ma  区域 {len(regions):4d}  "
                f"多边形 {statistics['polygon_count']:5d}  "
                f"顶点 {statistics['vertex_count']:7d}  "
                f"覆盖 {float(statistics['retained_land_fraction']) * 100.0:5.1f}%  "
                f"{statistics['build_seconds']:.2f}s",
                flush=True,
            )

        output.seek(table_offset)
        for entry in entries:
            output.write(struct.pack(FRAME_ENTRY_FORMAT, *entry))

    metadata = {
        "format": "Tales Earth Regions",
        "format_version": FILE_VERSION,
        "model": "MULLER2022",
        "model_url": MODEL_URL,
        "model_sha256": MODEL_SHA256,
        "land_definition": LAND_DEFINITION,
        "geometry_source": str(LAND_GEOMETRY_PATH),
        "geometry_sha256": sha256(geometry_file),
        "rotation_source": str(ROTATION_PATH),
        "rotation_sha256": sha256(rotation_file),
        "time_resolution_ma": args.time_step_ma,
        "maximum_time_ma": args.max_time_ma,
        "coastline_resolution_km": args.coastline_km,
        "minimum_region_area_km2": args.minimum_area_km2,
        "frame_count": len(times),
        "name_count": len(names),
        "coordinate_storage": "数学球面 XYZ 的 SNORM int16x3；Unity 读取时反射 Y 轴",
        "maximum_component_quantization_error": 1.0 / SNORM_SCALE,
        "file": str(args.out),
        "file_size_bytes": args.out.stat().st_size,
        "file_sha256": sha256(args.out),
        "frames": frame_statistics,
    }
    args.out.with_suffix(".json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    print(f"已生成 {args.out}，{args.out.stat().st_size / 1024 / 1024:.1f} MiB")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--zip", type=Path,
        default=Path("Data/raw/gplates/Muller_etal_2022_SE_v1.2.4.zip"))
    parser.add_argument(
        "--model-dir", type=Path,
        default=Path("Data/processed/gplates/muller2022"))
    parser.add_argument(
        "--out", type=Path,
        default=Path("Assets/StreamingAssets/EarthRegions/region_frames.bin"))
    parser.add_argument("--time-step-ma", type=int, default=1)
    parser.add_argument("--max-time-ma", type=int, default=1000)
    parser.add_argument("--coastline-km", type=float, default=25.0)
    parser.add_argument("--minimum-area-km2", type=float, default=250_000.0)
    args = parser.parse_args()
    if (args.time_step_ma <= 0 or args.max_time_ma < 0 or
            args.coastline_km <= 0.0 or args.minimum_area_km2 <= 0.0):
        parser.error("时间步长、最大年代、海岸线精度和最小面积必须为正值")
    write_dataset(args)


if __name__ == "__main__":
    main()
