#!/usr/bin/env python3
"""把 MULLER2022 命名陆地区域编译为 Unity 可随机读取的分层逐 Ma 数据。"""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
import struct
import time
from collections import Counter, defaultdict
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

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
FILE_MAGIC = b"TER2"
FILE_VERSION = 2
HEADER_FORMAT = "<4siifffi"
FRAME_ENTRY_FORMAT = "<fqiiii"
NODE_HEADER_FORMAT = "<QQiiiiiifIi"
POLYGON_HEADER_FORMAT = "<ffffi"
RING_HEADER_FORMAT = "<Bi"
SNORM_SCALE = 32767.0
NODE_KIND_TOPOLOGY = 1
NODE_KIND_LAND_UNIT = 2
NODE_FLAG_INTERACTABLE = 1
TOPOLOGY_PATHS = (
    Path("Topologies/250-0_plate_bounds.gpml"),
    Path("Topologies/410-250_plate_bounds.gpml"),
    Path("Topologies/1000-410-Topologies.gpml"),
    Path("Topologies/1000-410-Convergence.gpml"),
    Path("Topologies/1000-410-Divergence.gpml"),
    Path("Topologies/1000-410-Transforms.gpml"),
    Path("Topologies/TopologyBuildingBlocks.gpml"),
)

_WORKER_FEATURES: pygplates.FeatureCollection | None = None
_WORKER_ROTATIONS: pygplates.RotationModel | None = None
_WORKER_TOPOLOGIES: list[pygplates.FeatureCollection] | None = None
_WORKER_STRING_IDS: dict[str, int] | None = None
_WORKER_COASTLINE_KM = 0.0
_WORKER_MINIMUM_AREA_KM2 = 0.0


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
class EncodedNode:
    instance_id: int
    stable_id: int
    parent_index: int
    kind: int
    level: int
    plate_id: int
    feature_id_string_id: int
    name_string_id: int
    name: str
    area_km2: float
    interactable: bool
    polygons: tuple[EncodedPolygon, ...]


@dataclass(frozen=True)
class TopologyInstance:
    feature_id: str
    name: str
    plate_id: int
    geometry: object
    area_steradians: float


@dataclass
class LandUnitBuilder:
    feature_id: str
    name: str
    plate_id: int
    parent_feature_id: str
    area_km2: float
    polygons: list[EncodedPolygon]


def point_xyz(point: object) -> tuple[float, float, float]:
    x, y, z = point.to_xyz()  # type: ignore[attr-defined]
    return float(x), float(y), float(z)


def clean_ring(points: Sequence[object]) -> list[object]:
    """去掉连续重复点和闭环末尾重复点。"""
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


def quantize_directions(vertices: np.ndarray) -> np.ndarray:
    """把单位球方向量化为三分量有符号 16 位整数。"""
    return np.rint(np.clip(vertices, -1.0, 1.0) * SNORM_SCALE).astype("<i2")


def clean_quantized_ring(vertices: np.ndarray) -> np.ndarray:
    kept: list[np.ndarray] = []
    for vertex in vertices:
        if not kept or not np.array_equal(vertex, kept[-1]):
            kept.append(vertex)
    if len(kept) > 1 and np.array_equal(kept[0], kept[-1]):
        kept.pop()
    if len({tuple(int(value) for value in vertex) for vertex in kept}) < 3:
        return np.empty((0, 3), dtype="<i2")
    return np.asarray(kept, dtype="<i2")


def encoded_polygon_from_rings(
    rings: Sequence[EncodedRing], center_xyz: Sequence[float] | None = None
) -> EncodedPolygon | None:
    if not rings or rings[0].is_hole or len(rings[0].vertices) < 3:
        return None
    all_vertices = np.concatenate([ring.vertices for ring in rings]).astype(np.float64)
    all_vertices /= SNORM_SCALE
    exterior = rings[0].vertices.astype(np.float64) / SNORM_SCALE
    center = (np.asarray(center_xyz, dtype=np.float64)
              if center_xyz is not None else np.mean(exterior, axis=0))
    center_length = float(np.linalg.norm(center))
    if center_length <= 1e-12:
        center = np.mean(all_vertices, axis=0)
        center_length = float(np.linalg.norm(center))
    if center_length <= 1e-12:
        center = np.asarray((1.0, 0.0, 0.0))
        center_length = 1.0
    center /= center_length
    minimum_dot = float(np.min(all_vertices @ center)) - 1e-5
    return EncodedPolygon(
        cone_center=(float(center[0]), float(center[1]), float(center[2])),
        cone_minimum_dot=max(-1.0, minimum_dot),
        rings=tuple(rings),
    )


def encode_polygon(geometry: object, coastline_radians: float) -> EncodedPolygon | None:
    dense = geometry.to_tessellated(coastline_radians)  # type: ignore[attr-defined]
    source_rings = [clean_ring(dense.get_exterior_ring_points())]
    hole_flags = [False]
    for ring_index in range(dense.get_number_of_interior_rings()):
        source_rings.append(clean_ring(dense.get_interior_ring_points(ring_index)))
        hole_flags.append(True)
    rings_list: list[EncodedRing] = []
    for ring, is_hole in zip(source_rings, hole_flags):
        if len(ring) < 3:
            continue
        vertices = clean_quantized_ring(quantize_directions(
            np.asarray([point_xyz(point) for point in ring], dtype=np.float64)))
        if len(vertices) >= 3:
            rings_list.append(EncodedRing(is_hole=is_hole, vertices=vertices))
        elif not is_hole:
            return None
    rings = tuple(rings_list)
    return encoded_polygon_from_rings(rings, point_xyz(dense.get_interior_centroid()))


def stable_u64(value: str) -> int:
    """稳定的 64 位语义/实例键；禁止使用随进程变化的 Python hash。"""
    return int.from_bytes(hashlib.sha256(value.encode("utf-8")).digest()[:8], "little")


def feature_id(feature: object) -> str:
    return str(feature.get_feature_id())  # type: ignore[attr-defined]


def collect_names(features: Iterable[object]) -> list[str]:
    """兼容原工具接口：返回非空原始名称全集。"""
    return sorted({feature.get_name() for feature in features if feature.get_name()})


def load_topology_sources(model_dir: Path) -> list[pygplates.FeatureCollection]:
    return [pygplates.FeatureCollection(str(model_dir / path)) for path in TOPOLOGY_PATHS]


def collect_strings(
    land_features: Iterable[object], topology_sources: Iterable[Iterable[object]]
) -> list[str]:
    values: set[str] = set()
    for feature in land_features:
        values.add(feature_id(feature))
        if feature.get_name():
            values.add(feature.get_name())
    for collection in topology_sources:
        for feature in collection:
            if feature.get_feature_type() != pygplates.FeatureType.gpml_topological_closed_plate_boundary:
                continue
            values.add(feature_id(feature))
            if feature.get_name():
                values.add(feature.get_name())
    return sorted(values)


def resolve_topology_instances(
    topology_sources: Sequence[pygplates.FeatureCollection],
    rotations: pygplates.RotationModel,
    time_ma: float,
) -> list[TopologyInstance]:
    resolved: list[object] = []
    pygplates.resolve_topologies(topology_sources, rotations, resolved, time_ma)
    instances: list[TopologyInstance] = []
    for item in resolved:
        if not isinstance(item, pygplates.ResolvedTopologicalBoundary):
            continue
        feature = item.get_feature()
        geometry = item.get_resolved_boundary()
        instances.append(TopologyInstance(
            feature_id=feature_id(feature),
            name=feature.get_name() or "",
            plate_id=int(feature.get_reconstruction_plate_id()),
            geometry=geometry,
            area_steradians=float(geometry.get_area()),
        ))
    return sorted(instances, key=lambda item: item.feature_id)


VertexKey = tuple[int, int, int]
EdgeKey = tuple[VertexKey, VertexKey]


def vertex_key(vertex: np.ndarray) -> VertexKey:
    return int(vertex[0]), int(vertex[1]), int(vertex[2])


def canonical_ring(vertices: Sequence[VertexKey]) -> tuple[VertexKey, ...]:
    """忽略起点和方向，为几何完全相同的环生成确定键。"""
    minimum = min(vertices)
    candidates: list[tuple[VertexKey, ...]] = []
    for sequence in (list(vertices), list(reversed(vertices))):
        for index, vertex in enumerate(sequence):
            if vertex == minimum:
                candidates.append(tuple(sequence[index:] + sequence[:index]))
    return min(candidates)


def canonical_polygon(polygon: EncodedPolygon) -> tuple[tuple[bool, tuple[VertexKey, ...]], ...]:
    rings = [
        (ring.is_hole, canonical_ring([vertex_key(vertex) for vertex in ring.vertices]))
        for ring in polygon.rings
    ]
    return tuple(sorted(rings))


def choose_continuation(previous: VertexKey, current: VertexKey,
                        candidates: Sequence[VertexKey]) -> VertexKey:
    """在四岔接触点沿最平滑方向续接，避免把相切的两个闭环串在一起。"""
    current_vector = np.asarray(current, dtype=np.float64) / SNORM_SCALE
    current_vector /= np.linalg.norm(current_vector)

    def tangent_towards(target: VertexKey) -> np.ndarray:
        vector = np.asarray(target, dtype=np.float64) / SNORM_SCALE
        tangent = vector - current_vector * float(vector @ current_vector)
        length = float(np.linalg.norm(tangent))
        if length <= 1e-12:
            return np.zeros(3, dtype=np.float64)
        return tangent / length

    incoming_backwards = tangent_towards(previous)
    return min(candidates, key=lambda value: (
        float(incoming_backwards @ tangent_towards(value)), value))


def trace_boundary_loops(
    edges: dict[EdgeKey, tuple[VertexKey, VertexKey, bool]],
) -> tuple[list[tuple[bool, list[VertexKey]]], int]:
    adjacency: dict[VertexKey, set[EdgeKey]] = defaultdict(set)
    for edge in edges:
        adjacency[edge[0]].add(edge)
        adjacency[edge[1]].add(edge)
    junction_count = sum(len(items) != 2 for items in adjacency.values())
    if any(len(items) < 2 or len(items) % 2 for items in adjacency.values()):
        raise ValueError("父级 dissolve 产生开放链或奇数度边界顶点")

    remaining = set(edges)
    loops: list[tuple[bool, list[VertexKey]]] = []
    while remaining:
        first_edge = min(remaining)
        source_start, source_end, source_is_hole = edges[first_edge]
        start, current = source_start, source_end
        previous = start
        vertices = [start]
        hole_votes = Counter((source_is_hole,))
        remaining.remove(first_edge)
        while current != start:
            vertices.append(current)
            available = [edge for edge in adjacency[current] if edge in remaining]
            if not available:
                raise ValueError("父级 dissolve 边界未闭合")
            preferred = [
                edge for edge in available
                if edges[edge][2] == (hole_votes[True] > hole_votes[False])
            ]
            candidates = preferred or available
            neighbours = [edge[1] if edge[0] == current else edge[0] for edge in candidates]
            next_vertex = (neighbours[0] if len(neighbours) == 1 else
                           choose_continuation(previous, current, neighbours))
            next_edge = (current, next_vertex) if current < next_vertex else (next_vertex, current)
            remaining.remove(next_edge)
            hole_votes[edges[next_edge][2]] += 1
            previous, current = current, next_vertex
            if len(vertices) > len(edges) + 1:
                raise ValueError("父级 dissolve 边界追踪异常")
        if len(vertices) < 3:
            raise ValueError("父级 dissolve 产生退化闭环")
        loops.append((hole_votes[True] > hole_votes[False], vertices))
    return loops, junction_count


def polygon_from_vertex_keys(vertices: Sequence[VertexKey]) -> pygplates.PolygonOnSphere:
    points = []
    for vertex in vertices:
        direction = np.asarray(vertex, dtype=np.float64) / SNORM_SCALE
        direction /= np.linalg.norm(direction)
        points.append(pygplates.PointOnSphere(tuple(float(value) for value in direction)))
    return pygplates.PolygonOnSphere(points)


def dissolve_parent_polygons(
    child_polygons: Sequence[EncodedPolygon],
) -> tuple[tuple[EncodedPolygon, ...], int, int, int, int]:
    """以量化共享边抵消内部边，并把剩余边缝合为父级陆地外轮廓。"""
    occurrences: dict[EdgeKey, list[tuple[VertexKey, VertexKey, bool]]] = defaultdict(list)
    seen_polygons: set[tuple[tuple[bool, tuple[VertexKey, ...]], ...]] = set()
    for polygon in child_polygons:
        geometry_key = canonical_polygon(polygon)
        if geometry_key in seen_polygons:
            continue
        seen_polygons.add(geometry_key)
        for ring in polygon.rings:
            vertices = [vertex_key(vertex) for vertex in ring.vertices]
            for first, second in zip(vertices, vertices[1:] + vertices[:1]):
                if first == second:
                    continue
                key = (first, second) if first < second else (second, first)
                occurrences[key].append((first, second, ring.is_hole))

    remaining: dict[EdgeKey, tuple[VertexKey, VertexKey, bool]] = {}
    duplicate_edge_count = 0
    for edge, values in occurrences.items():
        # 静态陆地区域构成面分区：偶数次共享边属于内部，奇数次只留一份外边界。
        # 三片区域在同一线段相接时会出现三次，仍是可确定的奇偶规则。
        if len(values) % 2:
            remaining[edge] = values[0]
            duplicate_edge_count += max(0, len(values) - 1)
    if not remaining:
        raise ValueError("父级 dissolve 没有剩余外边界")

    loops, junction_count = trace_boundary_loops(remaining)
    exterior_loops = [vertices for is_hole, vertices in loops if not is_hole]
    hole_loops = [vertices for is_hole, vertices in loops if is_hole]
    if not exterior_loops:
        raise ValueError("父级 dissolve 没有外环")

    exterior_polygons = [(vertices, polygon_from_vertex_keys(vertices))
                         for vertices in exterior_loops]
    holes_by_exterior: list[list[list[VertexKey]]] = [[] for _ in exterior_polygons]
    for hole in hole_loops:
        centroid = polygon_from_vertex_keys(hole).get_interior_centroid()
        candidates = [
            (float(polygon.get_area()), index)
            for index, (_, polygon) in enumerate(exterior_polygons)
            if polygon.is_point_in_polygon(centroid)
        ]
        if not candidates:
            raise ValueError("父级 dissolve 的洞不属于任何外环")
        holes_by_exterior[min(candidates)[1]].append(hole)

    encoded: list[EncodedPolygon] = []
    for index, (exterior, _) in enumerate(exterior_polygons):
        rings = [EncodedRing(False, np.asarray(exterior, dtype="<i2"))]
        rings.extend(
            EncodedRing(True, np.asarray(hole, dtype="<i2"))
            for hole in sorted(holes_by_exterior[index])
        )
        polygon = encoded_polygon_from_rings(rings)
        if polygon is not None:
            encoded.append(polygon)
    encoded.sort(key=lambda polygon: tuple(polygon.rings[0].vertices[0]))
    return (tuple(encoded), junction_count, len(remaining), duplicate_edge_count,
            len(child_polygons) - len(seen_polygons))


def select_parent_topology(
    geometry: object, topologies: Sequence[TopologyInstance], maximum_gap_radians: float
) -> tuple[TopologyInstance, int, float]:
    centroid = geometry.get_interior_centroid()  # type: ignore[attr-defined]
    candidates = [item for item in topologies if item.geometry.is_point_in_polygon(centroid)]
    if candidates:
        return (min(candidates, key=lambda item: (item.area_steradians, item.feature_id)),
                len(candidates), 0.0)
    distances = [
        (float(pygplates.GeometryOnSphere.distance(centroid, item.geometry)), item.feature_id, item)
        for item in topologies
    ]
    distance, _, nearest = min(distances)
    if distance > maximum_gap_radians:
        raise ValueError(
            f"重建陆地几何中心距最近动态拓扑 {distance * EARTH_RADIUS_KM:.1f} km")
    return nearest, 0, distance * EARTH_RADIUS_KM


def build_frame(
    feature_collection: pygplates.FeatureCollection,
    rotation_model: pygplates.RotationModel,
    topology_sources: Sequence[pygplates.FeatureCollection],
    time_ma: float,
    strings_to_ids: dict[str, int],
    coastline_km: float,
    minimum_area_km2: float,
) -> tuple[list[EncodedNode], dict[str, object]]:
    started = time.perf_counter()
    topologies = resolve_topology_instances(topology_sources, rotation_model, time_ma)
    reconstructed: list[object] = []
    pygplates.reconstruct(feature_collection, rotation_model, reconstructed, time_ma)
    coastline_radians = coastline_km / EARTH_RADIUS_KM
    # 源文件确有少量 Feature ID 被多个不同名称复用，名称必须参与语义区分。
    units: dict[tuple[str, str, str], LandUnitBuilder] = {}
    overlap_assignments = 0
    gap_fallback_assignments = 0
    maximum_assignment_gap_km = 0.0

    for reconstructed_feature in reconstructed:
        geometry = reconstructed_feature.get_reconstructed_geometry()  # type: ignore[attr-defined]
        if not hasattr(geometry, "get_exterior_ring_points"):
            continue
        source = reconstructed_feature.get_feature()  # type: ignore[attr-defined]
        parent, candidate_count, assignment_gap_km = select_parent_topology(
            geometry, topologies, max(50.0, coastline_km * 2.0) / EARTH_RADIUS_KM)
        overlap_assignments += int(candidate_count > 1)
        gap_fallback_assignments += int(candidate_count == 0)
        maximum_assignment_gap_km = max(maximum_assignment_gap_km, assignment_gap_km)
        source_id = feature_id(source)
        name = source.get_name() or ""
        key = source_id, name, parent.feature_id
        encoded = encode_polygon(geometry, coastline_radians)
        if encoded is None:
            continue
        area_km2 = float(geometry.get_area()) * EARTH_RADIUS_KM * EARTH_RADIUS_KM
        if key not in units:
            units[key] = LandUnitBuilder(
                source_id, name, int(source.get_reconstruction_plate_id()),
                parent.feature_id, 0.0, [])
        unit = units[key]
        unit.area_km2 += area_km2
        unit.polygons.append(encoded)

    topologies_by_id = {item.feature_id: item for item in topologies}
    parent_ids = sorted({unit.parent_feature_id for unit in units.values()})
    parent_indexes = {source_id: index for index, source_id in enumerate(parent_ids)}
    nodes: list[EncodedNode] = []
    junction_count = 0
    parent_boundary_edges = 0
    duplicate_edge_count = 0
    duplicate_polygon_count = 0
    for source_id in parent_ids:
        topology = topologies_by_id[source_id]
        children = [unit for unit in units.values() if unit.parent_feature_id == source_id]
        child_polygons = [polygon for unit in children for polygon in unit.polygons]
        try:
            polygons, junctions, edge_count, duplicates, duplicate_polygons = \
                dissolve_parent_polygons(child_polygons)
        except ValueError as error:
            raise ValueError(
                f"{time_ma:g} Ma 拓扑 {topology.name or source_id} 的陆地边界合并失败：{error}"
            ) from error
        junction_count += junctions
        parent_boundary_edges += edge_count
        duplicate_edge_count += duplicates
        duplicate_polygon_count += duplicate_polygons
        nodes.append(EncodedNode(
            stable_u64(f"topology-instance:{source_id}"),
            stable_u64(f"topology-plate:{topology.plate_id}"),
            -1,
            NODE_KIND_TOPOLOGY,
            1,
            topology.plate_id,
            strings_to_ids[source_id],
            strings_to_ids[topology.name] if topology.name else -1,
            topology.name,
            sum(child.area_km2 for child in children),
            True,
            polygons,
        ))

    for key in sorted(units, key=lambda value: (parent_indexes[value[2]], value[0], value[1])):
        unit = units[key]
        nodes.append(EncodedNode(
            stable_u64(f"land-instance:{unit.feature_id}:{unit.name}:{unit.parent_feature_id}"),
            stable_u64(f"land-feature:{unit.feature_id}:{unit.name}"),
            parent_indexes[unit.parent_feature_id],
            NODE_KIND_LAND_UNIT,
            2,
            unit.plate_id,
            strings_to_ids[unit.feature_id],
            strings_to_ids[unit.name] if unit.name else -1,
            unit.name,
            unit.area_km2,
            unit.area_km2 >= minimum_area_km2,
            tuple(unit.polygons),
        ))

    instance_ids = [node.instance_id for node in nodes]
    if len(instance_ids) != len(set(instance_ids)):
        raise ValueError("区域实例 ID 哈希冲突")
    polygon_count = sum(len(node.polygons) for node in nodes)
    ring_count = sum(len(polygon.rings) for node in nodes for polygon in node.polygons)
    vertex_count = sum(
        len(ring.vertices) for node in nodes for polygon in node.polygons for ring in polygon.rings)
    statistics: dict[str, object] = {
        "time_ma": time_ma,
        "node_count": len(nodes),
        "level_node_counts": {
            "1": len(parent_ids),
            "2": len(units),
        },
        "topology_count": len(parent_ids),
        "land_unit_count": len(units),
        "children_with_parent_count": len(units),
        "parent_assignment_coverage": 1.0 if units else 0.0,
        "interactable_land_unit_count": sum(node.kind == NODE_KIND_LAND_UNIT and node.interactable for node in nodes),
        "non_interactable_land_unit_count": sum(node.kind == NODE_KIND_LAND_UNIT and not node.interactable for node in nodes),
        "polygon_count": polygon_count,
        "ring_count": ring_count,
        "vertex_count": vertex_count,
        "topology_overlap_assignment_count": overlap_assignments,
        "topology_gap_fallback_assignment_count": gap_fallback_assignments,
        "maximum_topology_assignment_gap_km": maximum_assignment_gap_km,
        "dissolve_junction_count": junction_count,
        "parent_boundary_edge_count": parent_boundary_edges,
        "dissolve_duplicate_edge_count": duplicate_edge_count,
        "dissolve_duplicate_polygon_count": duplicate_polygon_count,
        "parent_boundary_validation_passed": True,
        "named_land_area_km2": sum(node.area_km2 for node in nodes if node.kind == NODE_KIND_LAND_UNIT and node.name),
        "all_land_area_km2": sum(node.area_km2 for node in nodes if node.kind == NODE_KIND_LAND_UNIT),
        "build_seconds": time.perf_counter() - started,
    }
    return nodes, statistics


def initialize_frame_worker(
    model_dir: str, strings: Sequence[str], coastline_km: float, minimum_area_km2: float
) -> None:
    global _WORKER_FEATURES, _WORKER_ROTATIONS, _WORKER_TOPOLOGIES
    global _WORKER_STRING_IDS, _WORKER_COASTLINE_KM, _WORKER_MINIMUM_AREA_KM2
    root = Path(model_dir)
    _WORKER_FEATURES = pygplates.FeatureCollection(str(root / LAND_GEOMETRY_PATH))
    _WORKER_ROTATIONS = pygplates.RotationModel(str(root / ROTATION_PATH))
    _WORKER_TOPOLOGIES = load_topology_sources(root)
    _WORKER_STRING_IDS = {value: index for index, value in enumerate(strings)}
    _WORKER_COASTLINE_KM = coastline_km
    _WORKER_MINIMUM_AREA_KM2 = minimum_area_km2


def build_frame_worker(time_ma: float) -> tuple[list[EncodedNode], dict[str, object]]:
    if (_WORKER_FEATURES is None or _WORKER_ROTATIONS is None or
            _WORKER_TOPOLOGIES is None or _WORKER_STRING_IDS is None):
        raise RuntimeError("区域帧工作进程没有初始化")
    return build_frame(
        _WORKER_FEATURES, _WORKER_ROTATIONS, _WORKER_TOPOLOGIES, time_ma,
        _WORKER_STRING_IDS, _WORKER_COASTLINE_KM, _WORKER_MINIMUM_AREA_KM2)


def write_strings(output: object, strings: Sequence[str]) -> None:
    for value in strings:
        encoded = value.encode("utf-8")
        if len(encoded) > 65535:
            raise ValueError(f"区域字符串过长：{value[:80]}")
        output.write(struct.pack("<H", len(encoded)))  # type: ignore[attr-defined]
        output.write(encoded)  # type: ignore[attr-defined]


def write_frame(output: object, nodes: Sequence[EncodedNode]) -> None:
    for node in nodes:
        output.write(struct.pack(  # type: ignore[attr-defined]
            NODE_HEADER_FORMAT,
            node.instance_id,
            node.stable_id,
            node.parent_index,
            node.kind,
            node.level,
            node.plate_id,
            node.feature_id_string_id,
            node.name_string_id,
            node.area_km2,
            NODE_FLAG_INTERACTABLE if node.interactable else 0,
            len(node.polygons),
        ))
        for polygon in node.polygons:
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


def write_dataset(args: argparse.Namespace) -> None:
    model_dir = ensure_model(args.zip, args.model_dir)
    geometry_file = model_dir / LAND_GEOMETRY_PATH
    rotation_file = model_dir / ROTATION_PATH
    features = pygplates.FeatureCollection(str(geometry_file))
    topology_sources = load_topology_sources(model_dir)
    rotations = pygplates.RotationModel(str(rotation_file))
    strings = collect_strings(features, topology_sources)
    strings_to_ids = {value: index for index, value in enumerate(strings)}
    times = [float(value) for value in range(0, args.max_time_ma + 1, args.time_step_ma)]
    jobs = int(getattr(args, "jobs", 1))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    header_size = struct.calcsize(HEADER_FORMAT)
    strings_size = sum(2 + len(value.encode("utf-8")) for value in strings)
    table_offset = header_size + strings_size
    entry_size = struct.calcsize(FRAME_ENTRY_FORMAT)
    entries: list[tuple[float, int, int, int, int, int]] = []
    frame_statistics: list[dict[str, object]] = []

    with ExitStack() as stack:
        output = stack.enter_context(args.out.open("wb"))
        if jobs > 1:
            process_pool = stack.enter_context(multiprocessing.get_context("spawn").Pool(
                processes=jobs,
                initializer=initialize_frame_worker,
                initargs=(str(model_dir), strings, args.coastline_km, args.minimum_area_km2),
            ))
            frame_results = process_pool.imap(build_frame_worker, times, chunksize=1)
        else:
            frame_results = (
                build_frame(
                    features, rotations, topology_sources, time_ma, strings_to_ids,
                    args.coastline_km, args.minimum_area_km2)
                for time_ma in times
            )
        output.write(struct.pack(
            HEADER_FORMAT,
            FILE_MAGIC,
            FILE_VERSION,
            len(times),
            float(args.time_step_ma),
            float(args.coastline_km),
            float(args.minimum_area_km2),
            len(strings),
        ))
        write_strings(output, strings)
        if output.tell() != table_offset:
            raise AssertionError("区域字符串表长度计算错误")
        output.write(b"\0" * (entry_size * len(times)))

        for time_ma, (nodes, statistics) in zip(times, frame_results):
            offset = output.tell()
            write_frame(output, nodes)
            byte_length = output.tell() - offset
            entries.append((
                time_ma,
                offset,
                byte_length,
                len(nodes),
                int(statistics["polygon_count"]),
                int(statistics["vertex_count"]),
            ))
            statistics["byte_length"] = byte_length
            frame_statistics.append(statistics)
            print(
                f"{time_ma:6.1f} Ma  拓扑 {statistics['topology_count']:3d}  "
                f"陆地区域 {statistics['land_unit_count']:4d}  "
                f"可拾取 {statistics['interactable_land_unit_count']:4d}  "
                f"顶点 {statistics['vertex_count']:7d}  {statistics['build_seconds']:.2f}s",
                flush=True,
            )

        output.seek(table_offset)
        for entry in entries:
            output.write(struct.pack(FRAME_ENTRY_FORMAT, *entry))

    topology_metadata = [
        {
            "path": str(path),
            "sha256": sha256(model_dir / path),
        }
        for path in TOPOLOGY_PATHS
    ]
    metadata = {
        "format": "Tales Earth Regions",
        "format_version": FILE_VERSION,
        "model": "MULLER2022",
        "model_url": MODEL_URL,
        "model_sha256": MODEL_SHA256,
        "land_definition": LAND_DEFINITION,
        "hierarchy": [
            "逐帧解析且拥有陆地后代的 TopologicalClosedPlateBoundary",
            "按父拓扑实例拆分的 Coastline/Static 陆地构造单元",
        ],
        "geometry_source": str(LAND_GEOMETRY_PATH),
        "geometry_sha256": sha256(geometry_file),
        "topology_sources": topology_metadata,
        "rotation_source": str(ROTATION_PATH),
        "rotation_sha256": sha256(rotation_file),
        "time_resolution_ma": args.time_step_ma,
        "maximum_time_ma": args.max_time_ma,
        "coastline_resolution_km": args.coastline_km,
        "minimum_interactable_land_unit_area_km2": args.minimum_area_km2,
        "frame_count": len(times),
        "string_count": len(strings),
        "coordinate_storage": "数学球面 XYZ 的 SNORM int16x3；Unity 读取时反射 Y 轴",
        "maximum_component_quantization_error": 1.0 / SNORM_SCALE,
        "parent_boundary_method": "25 km 细分并量化后抵消共享边，再缝合闭环",
        "parent_boundary_validation": "全部帧已通过闭环、顶点度数和洞归属校验",
        "parent_assignment_method": "球面包含；无包含候选时仅在 50 km/两倍细分精度内取最近拓扑",
        "file": str(args.out),
        "file_size_bytes": args.out.stat().st_size,
        "file_sha256": sha256(args.out),
        "frames": frame_statistics,
    }
    args.out.with_suffix(".json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()
    if (args.time_step_ma <= 0 or args.max_time_ma < 0 or
            args.coastline_km <= 0.0 or args.minimum_area_km2 <= 0.0 or args.jobs <= 0):
        parser.error("时间步长、最大年代、海岸线精度和最小面积必须为正值")
    write_dataset(args)


if __name__ == "__main__":
    main()
