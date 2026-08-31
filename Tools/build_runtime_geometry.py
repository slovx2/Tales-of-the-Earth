#!/usr/bin/env python3
"""把 MULLER2022 海岸线编译为 Unity 可按帧读取的球面三角网格。"""

from __future__ import annotations

import argparse
import json
import math
import struct
import time
from pathlib import Path
from typing import Sequence

import mapbox_earcut
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
FILE_MAGIC = b"TEG1"
FILE_VERSION = 1
HEADER_FORMAT = "<4siiff"
FRAME_ENTRY_FORMAT = "<fqiii"


def point_xyz(point: object) -> tuple[float, float, float]:
    x, y, z = point.to_xyz()  # type: ignore[attr-defined]
    return float(x), float(y), float(z)


def clean_ring(points: Sequence[object]) -> list[object]:
    """移除连续重复点，避免三角化产生零面积边。"""
    cleaned: list[object] = []
    previous: tuple[float, float, float] | None = None
    for point in points:
        xyz = point_xyz(point)
        if previous is None or sum((xyz[i] - previous[i]) ** 2 for i in range(3)) > 1e-18:
            cleaned.append(point)
            previous = xyz
    if len(cleaned) > 1:
        first = point_xyz(cleaned[0])
        last = point_xyz(cleaned[-1])
        if sum((first[i] - last[i]) ** 2 for i in range(3)) <= 1e-18:
            cleaned.pop()
    return cleaned


def tangent_projection(vertices: np.ndarray, center: np.ndarray) -> np.ndarray:
    """投影到多边形中心的方位等距平面，兼顾跨日期变更线和极区。"""
    center = center / np.linalg.norm(center)
    reference = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    if abs(float(np.dot(center, reference))) > 0.98:
        reference = np.array([1.0, 0.0, 0.0], dtype=np.float64)
    east = np.cross(reference, center)
    east /= np.linalg.norm(east)
    north = np.cross(center, east)

    cos_angles = np.clip(vertices @ center, -1.0, 1.0)
    angles = np.arccos(cos_angles)
    tangent = vertices - cos_angles[:, None] * center
    tangent_lengths = np.linalg.norm(tangent, axis=1)
    directions = np.zeros_like(tangent)
    nonzero = tangent_lengths > 1e-12
    directions[nonzero] = tangent[nonzero] / tangent_lengths[nonzero, None]
    return np.column_stack((angles * (directions @ east), angles * (directions @ north)))


def triangulate_polygon(geometry: object, tessellation_radians: float) -> tuple[np.ndarray, np.ndarray] | None:
    dense = geometry.to_tessellated(tessellation_radians)  # type: ignore[attr-defined]
    rings = [clean_ring(dense.get_exterior_ring_points())]
    for ring_index in range(dense.get_number_of_interior_rings()):
        rings.append(clean_ring(dense.get_interior_ring_points(ring_index)))
    rings = [ring for ring in rings if len(ring) >= 3]
    if not rings:
        return None

    vertices = np.asarray([point_xyz(point) for ring in rings for point in ring], dtype=np.float64)
    ring_ends = np.cumsum([len(ring) for ring in rings], dtype=np.uint32)
    center = np.asarray(point_xyz(dense.get_interior_centroid()), dtype=np.float64)
    projected = tangent_projection(vertices, center)
    local_indices = mapbox_earcut.triangulate_float64(projected, ring_ends).astype(np.uint32)
    if len(local_indices) == 0:
        return None

    triangles = local_indices.reshape(-1, 3)
    a = vertices[triangles[:, 0]]
    b = vertices[triangles[:, 1]]
    c = vertices[triangles[:, 2]]
    outward = np.einsum("ij,ij->i", np.cross(b - a, c - a), a + b + c)
    reversed_triangles = outward < 0.0
    triangles[reversed_triangles, 1], triangles[reversed_triangles, 2] = (
        triangles[reversed_triangles, 2].copy(),
        triangles[reversed_triangles, 1].copy(),
    )
    return vertices.astype(np.float32), triangles.reshape(-1).astype(np.uint32)


def build_frame(feature_collection: object, rotation_model: object, time_ma: float,
                coastline_km: float) -> tuple[np.ndarray, np.ndarray, dict[str, object]]:
    started = time.perf_counter()
    reconstructed: list[object] = []
    pygplates.reconstruct(feature_collection, rotation_model, reconstructed, time_ma)
    vertex_parts: list[np.ndarray] = []
    index_parts: list[np.ndarray] = []
    vertex_offset = 0
    polygon_count = 0
    skipped_count = 0
    tessellation_radians = coastline_km / EARTH_RADIUS_KM
    for reconstructed_feature in reconstructed:
        geometry = reconstructed_feature.get_reconstructed_geometry()  # type: ignore[attr-defined]
        if not hasattr(geometry, "get_exterior_ring_points"):
            continue
        polygon_count += 1
        result = triangulate_polygon(geometry, tessellation_radians)
        if result is None:
            skipped_count += 1
            continue
        vertices, indices = result
        vertex_parts.append(vertices)
        index_parts.append(indices + vertex_offset)
        vertex_offset += len(vertices)

    vertices = np.concatenate(vertex_parts) if vertex_parts else np.empty((0, 3), dtype=np.float32)
    indices = np.concatenate(index_parts) if index_parts else np.empty(0, dtype=np.uint32)
    statistics: dict[str, object] = {
        "time_ma": time_ma,
        "polygon_count": polygon_count,
        "skipped_polygon_count": skipped_count,
        "vertex_count": len(vertices),
        "triangle_count": len(indices) // 3,
        "build_seconds": time.perf_counter() - started,
    }
    return vertices, indices, statistics


def write_dataset(args: argparse.Namespace) -> None:
    model_dir = ensure_model(args.zip, args.model_dir)
    geometry_file = model_dir / LAND_GEOMETRY_PATH
    rotation_file = model_dir / ROTATION_PATH
    features = pygplates.FeatureCollection(str(geometry_file))
    rotations = pygplates.RotationModel(str(rotation_file))
    times = [float(value) for value in range(0, args.max_time_ma + 1, args.time_step_ma)]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    table_offset = struct.calcsize(HEADER_FORMAT)
    entry_size = struct.calcsize(FRAME_ENTRY_FORMAT)
    entries: list[tuple[float, int, int, int, int]] = []
    frame_statistics: list[dict[str, object]] = []

    with args.out.open("wb") as output:
        output.write(struct.pack(HEADER_FORMAT, FILE_MAGIC, FILE_VERSION, len(times),
                                 float(args.time_step_ma), float(args.coastline_km)))
        output.write(b"\0" * (entry_size * len(times)))
        for time_ma in times:
            vertices, indices, statistics = build_frame(features, rotations, time_ma, args.coastline_km)
            offset = output.tell()
            output.write(vertices.astype("<f4", copy=False).tobytes())
            output.write(indices.astype("<u4", copy=False).tobytes())
            byte_length = output.tell() - offset
            entries.append((time_ma, offset, byte_length, len(vertices), len(indices)))
            statistics["byte_length"] = byte_length
            frame_statistics.append(statistics)
            print(f"{time_ma:6.1f} Ma  顶点 {len(vertices):7d}  三角形 {len(indices) // 3:7d}  "
                  f"{statistics['build_seconds']:.2f}s")
        output.seek(table_offset)
        for entry in entries:
            output.write(struct.pack(FRAME_ENTRY_FORMAT, *entry))

    metadata = {
        "format": "Tales Earth Geometry",
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
        "coastline_resolution_km": args.coastline_km,
        "frame_count": len(times),
        "storage": "每帧球面顶点 float32x3 + uint32 三角形索引，运行时仅加载当前帧",
        "file": str(args.out),
        "file_size_bytes": args.out.stat().st_size,
        "file_sha256": sha256(args.out),
        "frames": frame_statistics,
    }
    args.out.with_suffix(".json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    print(f"已生成 {args.out}，{args.out.stat().st_size / 1024 / 1024:.1f} MiB")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", type=Path, default=Path("Data/raw/gplates/Muller_etal_2022_SE_v1.2.4.zip"))
    parser.add_argument("--model-dir", type=Path, default=Path("Data/processed/gplates/muller2022"))
    parser.add_argument("--out", type=Path,
                        default=Path("Assets/StreamingAssets/EarthGeometry/land_frames.bin"))
    parser.add_argument("--time-step-ma", type=int, default=1)
    parser.add_argument("--max-time-ma", type=int, default=1000)
    parser.add_argument("--coastline-km", type=float, default=25.0)
    args = parser.parse_args()
    if args.time_step_ma <= 0 or args.max_time_ma < 0 or args.coastline_km <= 0:
        parser.error("时间步长、最大年代和海岸线精度必须为正值")
    write_dataset(args)


if __name__ == "__main__":
    main()
