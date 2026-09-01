#!/usr/bin/env python3
"""按公开论文方法近似推演 MULLER2022 大陆的大尺度古高程。"""

from __future__ import annotations

import argparse
import json
import math
import zipfile
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

import numpy as np
import pygplates
from netCDF4 import Dataset
from PIL import Image
from scipy.spatial import cKDTree
from scipy.stats import spearmanr

from generate_paleogeography import (
    LAND_GEOMETRY_PATH,
    ROTATION_PATH,
    draw_reconstruction,
    ensure_model,
)


EARTH_RADIUS_KM = 6371.009
STATIC_POLYGONS_PATH = Path("StaticPolygons/shapes_static_polygons_Merdith_etal.gpml")
BOUNDARY_PATHS = (
    Path("Topologies/250-0_plate_bounds.gpml"),
    Path("Topologies/410-250_plate_bounds.gpml"),
    Path("Topologies/1000-410-Convergence.gpml"),
    Path("Topologies/1000-410-Divergence.gpml"),
)
SUBDUCTION_TYPE = "gpml:SubductionZone"
MID_OCEAN_RIDGE_TYPE = "gpml:MidOceanRidge"
CONTINENTAL_RIFT_TYPE = "gpml:ContinentalRift"
DIVERGENCE_TYPES = frozenset((MID_OCEAN_RIDGE_TYPE, CONTINENTAL_RIFT_TYPE))


@dataclass
class NodeState:
    present_xyz: np.ndarray
    plate_ids: np.ndarray
    elevation_m: np.ndarray
    arc_memory_ma: np.ndarray
    collision_timer_ma: np.ndarray
    rift_timer_ma: np.ndarray
    previous_other_plate_km: np.ndarray
    previous_divergence_km: np.ndarray


@dataclass(frozen=True)
class Snapshot:
    time_ma: int
    xyz: np.ndarray
    elevation_m: np.ndarray
    arc_mask: np.ndarray
    collision_mask: np.ndarray
    rift_mask: np.ndarray


@dataclass(frozen=True)
class HypsometricCalibration:
    source_elevation_m: np.ndarray
    target_elevation_m: np.ndarray

    def apply(self, elevation_m: np.ndarray) -> np.ndarray:
        return np.interp(
            elevation_m,
            self.source_elevation_m,
            self.target_elevation_m,
            left=self.target_elevation_m[0],
            right=self.target_elevation_m[-1],
        )

    def to_json(self) -> dict[str, object]:
        return {
            "method": "0 Ma land-elevation quantile mapping applied identically to every epoch",
            "source_elevation_m": self.source_elevation_m.tolist(),
            "target_elevation_m": self.target_elevation_m.tolist(),
        }


def fibonacci_sphere(count: int) -> np.ndarray:
    """生成近似等面积的单位球节点。"""
    indices = np.arange(count, dtype=np.float64)
    z = 1.0 - 2.0 * (indices + 0.5) / count
    radius = np.sqrt(np.maximum(0.0, 1.0 - z * z))
    longitude = indices * (math.pi * (3.0 - math.sqrt(5.0)))
    return np.column_stack((radius * np.cos(longitude), radius * np.sin(longitude), z))


def xyz_to_lat_lon(xyz: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    latitude = np.rad2deg(np.arcsin(np.clip(xyz[:, 2], -1.0, 1.0)))
    longitude = np.rad2deg(np.arctan2(xyz[:, 1], xyz[:, 0]))
    return latitude, longitude


def xyz_to_point(xyz: np.ndarray) -> pygplates.PointOnSphere:
    return pygplates.PointOnSphere((float(xyz[0]), float(xyz[1]), float(xyz[2])))


def sample_mask(mask: Image.Image, xyz: np.ndarray) -> np.ndarray:
    latitude, longitude = xyz_to_lat_lon(xyz)
    width, height = mask.size
    x = np.floor((longitude + 180.0) / 360.0 * width).astype(np.int64) % width
    y = np.floor((90.0 - latitude) / 180.0 * height).astype(np.int64)
    y = np.clip(y, 0, height - 1)
    pixels = np.asarray(mask.convert("L"), dtype=np.uint8)
    return pixels[y, x] >= 128


def build_nodes(
    coastlines: pygplates.FeatureCollection,
    rotations: pygplates.RotationModel,
    static_polygons_path: Path,
    global_node_count: int,
) -> tuple[NodeState, dict[str, int]]:
    candidates = fibonacci_sphere(global_node_count)
    modern_mask = draw_reconstruction(coastlines, rotations, 0.0, 1440, 720)
    land_candidates = candidates[sample_mask(modern_mask, candidates)]
    partitioner = pygplates.PlatePartitioner(str(static_polygons_path), rotations)
    kept: list[np.ndarray] = []
    plate_ids: list[int] = []
    for point_xyz in land_candidates:
        partition = partitioner.partition_point(xyz_to_point(point_xyz))
        if partition is None:
            continue
        kept.append(point_xyz)
        plate_ids.append(partition.get_feature().get_reconstruction_plate_id())
    present_xyz = np.asarray(kept, dtype=np.float64)
    ids = np.asarray(plate_ids, dtype=np.int32)
    node_count = len(ids)
    state = NodeState(
        present_xyz=present_xyz,
        plate_ids=ids,
        elevation_m=np.full(node_count, 150.0, dtype=np.float64),
        arc_memory_ma=np.zeros(node_count, dtype=np.int16),
        collision_timer_ma=np.zeros(node_count, dtype=np.int16),
        rift_timer_ma=np.zeros(node_count, dtype=np.int16),
        previous_other_plate_km=np.full(node_count, np.inf, dtype=np.float64),
        previous_divergence_km=np.full(node_count, np.inf, dtype=np.float64),
    )
    stats = {
        "global_candidates": global_node_count,
        "modern_land_candidates": len(land_candidates),
        "partitioned_nodes": node_count,
        "unpartitioned_nodes": len(land_candidates) - node_count,
        "plate_count": len(np.unique(ids)),
    }
    return state, stats


def finite_rotation_matrix(rotation: pygplates.FiniteRotation) -> np.ndarray:
    pole, angle = rotation.get_euler_pole_and_angle()
    axis = np.asarray(pole.to_xyz(), dtype=np.float64)
    axis /= np.linalg.norm(axis)
    x, y, z = axis
    skew = np.array(((0.0, -z, y), (z, 0.0, -x), (-y, x, 0.0)))
    identity = np.eye(3)
    return identity * math.cos(angle) + (1.0 - math.cos(angle)) * np.outer(axis, axis) + math.sin(angle) * skew


def reconstruct_nodes(state: NodeState, rotations: pygplates.RotationModel, time_ma: float) -> np.ndarray:
    result = np.empty_like(state.present_xyz)
    for plate_id in np.unique(state.plate_ids):
        indices = state.plate_ids == plate_id
        rotation = rotations.get_rotation(time_ma, int(plate_id))
        matrix = finite_rotation_matrix(rotation)
        result[indices] = state.present_xyz[indices] @ matrix.T
    result /= np.linalg.norm(result, axis=1, keepdims=True)
    return result


def load_boundary_features(model_dir: Path) -> list[pygplates.Feature]:
    result: list[pygplates.Feature] = []
    accepted = DIVERGENCE_TYPES | frozenset((SUBDUCTION_TYPE,))
    for relative_path in BOUNDARY_PATHS:
        for feature in pygplates.FeatureCollection(str(model_dir / relative_path)):
            if str(feature.get_feature_type()) in accepted and feature.get_geometry() is not None:
                result.append(feature)
    return result


def boundary_points(
    features: list[pygplates.Feature],
    rotations: pygplates.RotationModel,
    time_ma: float,
    accepted_types: frozenset[str],
    tessellation_degrees: float = 1.5,
) -> np.ndarray:
    reconstructed: list[pygplates.ReconstructedFeatureGeometry] = []
    pygplates.reconstruct(features, rotations, reconstructed, time_ma)
    points: list[tuple[float, float, float]] = []
    for reconstructed_feature in reconstructed:
        feature_type = str(reconstructed_feature.get_feature().get_feature_type())
        if feature_type not in accepted_types:
            continue
        geometry = reconstructed_feature.get_reconstructed_geometry()
        if not hasattr(geometry, "to_tessellated"):
            continue
        tessellated = geometry.to_tessellated(math.radians(tessellation_degrees))
        points.extend(tuple(point.to_xyz()) for point in tessellated.get_points())
    if not points:
        return np.empty((0, 3), dtype=np.float64)
    return np.asarray(points, dtype=np.float64)


def chord_to_km(chord: np.ndarray | float) -> np.ndarray | float:
    return 2.0 * EARTH_RADIUS_KM * np.arcsin(np.clip(np.asarray(chord) * 0.5, 0.0, 1.0))


def distance_to_points(node_xyz: np.ndarray, target_xyz: np.ndarray) -> np.ndarray:
    if len(target_xyz) == 0:
        return np.full(len(node_xyz), np.inf, dtype=np.float64)
    chord, _ = cKDTree(target_xyz).query(node_xyz, k=1)
    return np.asarray(chord_to_km(chord), dtype=np.float64)


def nearest_other_plate_distance(
    xyz: np.ndarray,
    plate_ids: np.ndarray,
    query_mask: np.ndarray,
    radius_km: float,
) -> np.ndarray:
    result = np.full(len(xyz), np.inf, dtype=np.float64)
    query_indices = np.flatnonzero(query_mask)
    if len(query_indices) == 0:
        return result
    chord_radius = 2.0 * math.sin((radius_km / EARTH_RADIUS_KM) * 0.5)
    tree = cKDTree(xyz)
    neighbours = tree.query_ball_point(xyz[query_indices], chord_radius)
    for node_index, candidates in zip(query_indices, neighbours):
        other = [candidate for candidate in candidates if plate_ids[candidate] != plate_ids[node_index]]
        if not other:
            continue
        chord = np.linalg.norm(xyz[other] - xyz[node_index], axis=1).min()
        result[node_index] = float(chord_to_km(chord))
    return result


def growth_increment(elevation_m: np.ndarray, scale: float, decay: float) -> np.ndarray:
    return scale / np.exp(np.clip(elevation_m * decay, -20.0, 20.0))


def erosion_from_relief(local_relief_m: np.ndarray) -> np.ndarray:
    """论文图 13 的公式；PDF 方程表漏排的负号由图中曲线确认。"""
    erosion = 301.0 - 200.0 * np.arctan((2000.0 - local_relief_m) * 0.007)
    return np.clip(erosion, 1.0, 601.0)


def local_relief(xyz: np.ndarray, elevation_m: np.ndarray) -> np.ndarray:
    neighbour_count = min(21, len(xyz))
    _, indices = cKDTree(xyz).query(xyz, k=neighbour_count)
    median = np.median(elevation_m[indices], axis=1)
    return np.abs(elevation_m - median)


def make_snapshot(
    time_ma: int,
    xyz: np.ndarray,
    state: NodeState,
    arc_mask: np.ndarray,
) -> Snapshot:
    return Snapshot(
        time_ma=time_ma,
        xyz=xyz.copy(),
        elevation_m=state.elevation_m.copy(),
        arc_mask=arc_mask.copy(),
        collision_mask=(state.collision_timer_ma > 0).copy(),
        rift_mask=(state.rift_timer_ma > 0).copy(),
    )


def initialise_oldest_time(
    state: NodeState,
    xyz: np.ndarray,
    subduction_xyz: np.ndarray,
) -> np.ndarray:
    arc_mask = distance_to_points(xyz, subduction_xyz) < 450.0
    state.elevation_m[arc_mask] = 700.0
    state.arc_memory_ma[arc_mask] = 10
    return arc_mask


def simulate(
    state: NodeState,
    rotations: pygplates.RotationModel,
    boundary_features: list[pygplates.Feature],
    oldest_time_ma: int,
    output_times: set[int],
) -> tuple[dict[int, Snapshot], list[dict[str, float | int]]]:
    snapshots: dict[int, Snapshot] = {}
    trace: list[dict[str, float | int]] = []
    xyz = reconstruct_nodes(state, rotations, float(oldest_time_ma))
    subduction_xyz = boundary_points(
        boundary_features, rotations, float(oldest_time_ma), frozenset((SUBDUCTION_TYPE,))
    )
    continental_rift_xyz = boundary_points(
        boundary_features, rotations, float(oldest_time_ma), frozenset((CONTINENTAL_RIFT_TYPE,))
    )
    ridge_xyz = boundary_points(
        boundary_features, rotations, float(oldest_time_ma), frozenset((MID_OCEAN_RIDGE_TYPE,))
    )
    arc_mask = initialise_oldest_time(state, xyz, subduction_xyz)
    continental_rift_km = distance_to_points(xyz, continental_rift_xyz)
    ridge_km = distance_to_points(xyz, ridge_xyz)
    state.previous_divergence_km = np.minimum(continental_rift_km, ridge_km * (400.0 / 150.0))
    state.previous_other_plate_km = nearest_other_plate_distance(
        xyz, state.plate_ids, np.ones(len(xyz), dtype=bool), 600.0
    )
    if oldest_time_ma in output_times:
        snapshots[oldest_time_ma] = make_snapshot(oldest_time_ma, xyz, state, arc_mask)

    for time_ma in range(oldest_time_ma - 1, -1, -1):
        xyz = reconstruct_nodes(state, rotations, float(time_ma))
        subduction_xyz = boundary_points(
            boundary_features, rotations, float(time_ma), frozenset((SUBDUCTION_TYPE,))
        )
        continental_rift_xyz = boundary_points(
            boundary_features, rotations, float(time_ma), frozenset((CONTINENTAL_RIFT_TYPE,))
        )
        ridge_xyz = boundary_points(
            boundary_features, rotations, float(time_ma), frozenset((MID_OCEAN_RIDGE_TYPE,))
        )
        subduction_km = distance_to_points(xyz, subduction_xyz)
        continental_rift_km = distance_to_points(xyz, continental_rift_xyz)
        ridge_km = distance_to_points(xyz, ridge_xyz)
        # 真实大陆裂谷沿用论文 400 km；洋中脊只是早期年代的代理，收紧到 150 km。
        divergence_km = np.minimum(continental_rift_km, ridge_km * (400.0 / 150.0))
        arc_mask = subduction_km < 450.0

        state.arc_memory_ma = np.maximum(state.arc_memory_ma - 1, 0)
        state.arc_memory_ma[arc_mask] = 10
        collision_candidates = (~arc_mask) & (state.arc_memory_ma > 0)
        collision_tracking = state.arc_memory_ma > 0
        other_plate_km = nearest_other_plate_distance(
            xyz, state.plate_ids, collision_tracking, 600.0
        )
        converging = (
            collision_candidates
            & (other_plate_km < 500.0)
            & (other_plate_km + 1.0 < state.previous_other_plate_km)
        )
        state.collision_timer_ma = np.maximum(state.collision_timer_ma - 1, 0)
        state.collision_timer_ma[converging] = 40
        state.previous_other_plate_km[collision_tracking] = other_plate_km[collision_tracking]

        approaching_divergence = divergence_km + 1.0 < state.previous_divergence_km
        rift_trigger = (divergence_km < 400.0) & approaching_divergence
        state.rift_timer_ma = np.maximum(state.rift_timer_ma - 1, 0)
        state.rift_timer_ma[rift_trigger] = 40
        state.previous_divergence_km = divergence_km

        # 1 m/Ma 的背景生长与低起伏处约 1 m/Ma 的最低侵蚀互相抵消。
        state.elevation_m += 1.0
        state.elevation_m[arc_mask] += growth_increment(
            state.elevation_m[arc_mask], scale=300.0, decay=0.001
        )
        collision_mask = (state.collision_timer_ma > 0) & ~arc_mask
        state.elevation_m[collision_mask] += growth_increment(
            state.elevation_m[collision_mask], scale=700.0, decay=0.0003
        )

        rift_mask = (state.rift_timer_ma > 0) & ~arc_mask & ~collision_mask
        remaining = np.maximum(state.rift_timer_ma[rift_mask].astype(np.float64), 1.0)
        state.elevation_m[rift_mask] -= (state.elevation_m[rift_mask] + 200.0) / remaining

        # 论文的局部起伏侵蚀无法削低宽而平的远古高原；简化节点会放大该问题。
        inactive_highland = ~arc_mask & ~collision_mask & ~rift_mask & (state.elevation_m > 150.0)
        state.elevation_m[inactive_highland] -= (
            state.elevation_m[inactive_highland] - 150.0
        ) * 0.003

        relief_m = local_relief(xyz, state.elevation_m)
        state.elevation_m -= erosion_from_relief(relief_m)
        state.elevation_m = np.clip(state.elevation_m, -500.0, 7000.0)

        trace.append({
            "time_ma": time_ma,
            "arc_nodes": int(arc_mask.sum()),
            "collision_nodes": int(collision_mask.sum()),
            "rift_nodes": int(rift_mask.sum()),
            "minimum_elevation_m": float(state.elevation_m.min()),
            "median_elevation_m": float(np.median(state.elevation_m)),
            "maximum_elevation_m": float(state.elevation_m.max()),
        })
        if time_ma in output_times:
            snapshots[time_ma] = make_snapshot(time_ma, xyz, state, arc_mask)
        if time_ma % 50 == 0:
            print(
                f"{time_ma:4d} Ma: arc={arc_mask.sum():4d}, "
                f"collision={collision_mask.sum():4d}, rift={rift_mask.sum():4d}, "
                f"elevation={state.elevation_m.min():.0f}..{state.elevation_m.max():.0f} m"
            )
    return snapshots, trace


def grid_xyz(width: int, height: int) -> np.ndarray:
    longitude = -180.0 + (np.arange(width, dtype=np.float64) + 0.5) / width * 360.0
    latitude = 90.0 - (np.arange(height, dtype=np.float64) + 0.5) / height * 180.0
    lon_grid, lat_grid = np.meshgrid(np.deg2rad(longitude), np.deg2rad(latitude))
    cos_lat = np.cos(lat_grid)
    return np.column_stack((
        (cos_lat * np.cos(lon_grid)).ravel(),
        (cos_lat * np.sin(lon_grid)).ravel(),
        np.sin(lat_grid).ravel(),
    ))


def interpolate_snapshot(
    snapshot: Snapshot,
    land_mask: Image.Image,
    width: int,
    height: int,
) -> np.ndarray:
    targets = grid_xyz(width, height)
    neighbour_count = min(4, len(snapshot.xyz))
    chord, indices = cKDTree(snapshot.xyz).query(targets, k=neighbour_count)
    if neighbour_count == 1:
        chord = chord[:, None]
        indices = indices[:, None]
    weights = 1.0 / np.maximum(chord, 1e-6) ** 2
    values = (weights * snapshot.elevation_m[indices]).sum(axis=1) / weights.sum(axis=1)
    elevation = values.reshape((height, width))
    land = np.asarray(land_mask.convert("L"), dtype=np.uint8) >= 128
    elevation[~land] = -4000.0
    return elevation


def colorize_elevation(elevation_m: np.ndarray) -> Image.Image:
    stops = np.asarray((
        -7000, -6000, -5000, -4000, -3000, -2000, -1000, -200, -1,
        0, 250, 750, 1500, 3000, 5000, 7000,
    ), dtype=np.float64)
    colors = np.asarray((
        (3, 15, 48), (4, 28, 72), (6, 48, 105), (8, 70, 135),
        (15, 93, 156), (27, 120, 176), (49, 151, 194), (91, 184, 207),
        (150, 211, 220), (225, 205, 145), (206, 174, 101), (180, 139, 70),
        (151, 104, 53), (110, 74, 48), (154, 143, 128), (226, 225, 216),
    ), dtype=np.float64)
    rgb = np.empty((*elevation_m.shape, 3), dtype=np.uint8)
    for channel in range(3):
        rgb[..., channel] = np.interp(elevation_m, stops, colors[:, channel]).astype(np.uint8)
    return Image.fromarray(rgb)


def export_snapshots(
    snapshots: dict[int, Snapshot],
    coastlines: pygplates.FeatureCollection,
    rotations: pygplates.RotationModel,
    out_dir: Path,
    width: int,
    height: int,
    calibration: HypsometricCalibration | None,
) -> list[dict[str, object]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    metadata: list[dict[str, object]] = []
    for time_ma in sorted(snapshots):
        snapshot = snapshots[time_ma]
        land_mask = draw_reconstruction(coastlines, rotations, float(time_ma), width, height)
        elevation = interpolate_snapshot(snapshot, land_mask, width, height)
        land = np.asarray(land_mask.convert("L"), dtype=np.uint8) >= 128
        if calibration is not None:
            elevation[land] = calibration.apply(elevation[land])
        elevation[land] = np.maximum(elevation[land], 0.0)
        stem = f"topography_{time_ma:04d}Ma"
        np.savez_compressed(
            out_dir / f"{stem}.npz",
            elevation_m=elevation.astype(np.float32),
            land_mask=(np.asarray(land_mask, dtype=np.uint8) >= 128),
        )
        colorize_elevation(elevation).save(out_dir / f"{stem}.png")
        land_values = elevation[land]
        metadata.append({
            "time_ma": time_ma,
            "minimum_land_elevation_m": float(land_values.min()),
            "median_land_elevation_m": float(np.median(land_values)),
            "p90_land_elevation_m": float(np.percentile(land_values, 90)),
            "p99_land_elevation_m": float(np.percentile(land_values, 99)),
            "maximum_land_elevation_m": float(land_values.max()),
            "land_below_zero_cell_count": int((elevation[land] < 0.0).sum()),
            "ocean_not_minus_4000_cell_count": int((elevation[~land] != -4000.0).sum()),
            "arc_node_fraction": float(snapshot.arc_mask.mean()),
            "collision_node_fraction": float(snapshot.collision_mask.mean()),
            "rift_node_fraction": float(snapshot.rift_mask.mean()),
            "grid": f"{width}x{height}",
            "image": str(out_dir / f"{stem}.png"),
            "data": str(out_dir / f"{stem}.npz"),
        })
        print(f"已导出 {time_ma} Ma 高程图")
    return metadata


def read_netcdf_elevation(path: Path) -> np.ndarray:
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as archive:
            members = [
                name for name in archive.namelist()
                if name.endswith("_0Ma.nc") and not name.startswith("__MACOSX/")
            ]
            if len(members) != 1:
                raise ValueError(f"无法唯一定位 0 Ma NetCDF：{members}")
            with NamedTemporaryFile(suffix=".nc") as temporary:
                temporary.write(archive.read(members[0]))
                temporary.flush()
                with Dataset(temporary.name) as dataset:
                    return np.asarray(dataset.variables["z"][:], dtype=np.float64)
    with Dataset(path) as dataset:
        return np.asarray(dataset.variables["z"][:], dtype=np.float64)


def sample_reference_elevation(elevation: np.ndarray, xyz: np.ndarray) -> np.ndarray:
    latitude, longitude = xyz_to_lat_lon(xyz)
    height, width = elevation.shape
    # 实测的 PALEOMAP NetCDF 数组第 0 行为北端，最后一列与日期变更线相接。
    y = np.rint((90.0 - latitude) / 180.0 * (height - 1)).astype(np.int64)
    x = np.rint((longitude + 180.0) / 360.0 * (width - 1)).astype(np.int64)
    return elevation[np.clip(y, 0, height - 1), np.clip(x, 0, width - 1)]


def build_hypsometric_calibration(
    snapshot: Snapshot,
    reference_netcdf: Path,
) -> HypsometricCalibration:
    reference_grid = read_netcdf_elevation(reference_netcdf)
    reference = sample_reference_elevation(reference_grid, snapshot.xyz)
    valid = reference > 0.0
    quantiles = np.linspace(0.0, 1.0, 41)
    source = np.quantile(snapshot.elevation_m[valid], quantiles)
    target = np.quantile(reference[valid], quantiles)
    unique_source, unique_indices = np.unique(source, return_index=True)
    unique_target = target[unique_indices]
    if len(unique_source) < 8:
        raise ValueError("现代高程分位校准点不足")
    return HypsometricCalibration(unique_source, unique_target)


def region_mask(xyz: np.ndarray, bounds: tuple[float, float, float, float]) -> np.ndarray:
    latitude, longitude = xyz_to_lat_lon(xyz)
    min_lat, max_lat, min_lon, max_lon = bounds
    return (
        (latitude >= min_lat) & (latitude <= max_lat)
        & (longitude >= min_lon) & (longitude <= max_lon)
    )


def validate_modern_snapshot(
    snapshot: Snapshot,
    reference_netcdf: Path,
    calibration: HypsometricCalibration | None,
) -> dict[str, object]:
    reference_grid = read_netcdf_elevation(reference_netcdf)
    reference = sample_reference_elevation(reference_grid, snapshot.xyz)
    valid = reference > 0.0
    predicted_all = snapshot.elevation_m.copy()
    if calibration is not None:
        predicted_all = calibration.apply(predicted_all)
    predicted_all = np.maximum(predicted_all, 0.0)
    predicted = predicted_all[valid]
    actual = reference[valid]
    correlation = spearmanr(predicted, actual).statistic
    threshold = 1000.0
    predicted_high = predicted >= threshold
    actual_high = actual >= threshold
    true_positive = int((predicted_high & actual_high).sum())
    false_positive = int((predicted_high & ~actual_high).sum())
    false_negative = int((~predicted_high & actual_high).sum())
    precision = true_positive / max(true_positive + false_positive, 1)
    recall = true_positive / max(true_positive + false_negative, 1)
    f1 = 2.0 * precision * recall / max(precision + recall, 1e-12)
    random = np.random.default_rng(20250901)
    null_correlations: list[float] = []
    null_f1: list[float] = []
    for _ in range(100):
        shuffled = random.permutation(predicted)
        null_correlations.append(float(spearmanr(shuffled, actual).statistic))
        shuffled_high = shuffled >= threshold
        null_tp = int((shuffled_high & actual_high).sum())
        null_fp = int((shuffled_high & ~actual_high).sum())
        null_fn = int((~shuffled_high & actual_high).sum())
        null_precision = null_tp / max(null_tp + null_fp, 1)
        null_recall = null_tp / max(null_tp + null_fn, 1)
        null_f1.append(2.0 * null_precision * null_recall / max(null_precision + null_recall, 1e-12))

    regions = {
        "himalaya": (25.0, 38.0, 65.0, 105.0),
        "andes": (-55.0, 15.0, -82.0, -65.0),
        "rockies": (30.0, 60.0, -130.0, -105.0),
        "east_african_rift": (-20.0, 15.0, 25.0, 45.0),
        "australian_interior": (-35.0, -15.0, 120.0, 145.0),
        "sahara": (15.0, 30.0, -10.0, 30.0),
    }
    region_results: dict[str, object] = {}
    for name, bounds in regions.items():
        mask = region_mask(snapshot.xyz, bounds) & (reference > 0.0)
        region_results[name] = {
            "node_count": int(mask.sum()),
            "arc_node_fraction": float(snapshot.arc_mask[mask].mean()) if mask.any() else None,
            "collision_node_fraction": float(snapshot.collision_mask[mask].mean()) if mask.any() else None,
            "rift_node_fraction": float(snapshot.rift_mask[mask].mean()) if mask.any() else None,
            "raw_predicted_p90_m": float(np.percentile(snapshot.elevation_m[mask], 90)) if mask.any() else None,
            "predicted_median_m": float(np.median(predicted_all[mask])) if mask.any() else None,
            "predicted_p90_m": float(np.percentile(predicted_all[mask], 90)) if mask.any() else None,
            "reference_median_m": float(np.median(reference[mask])) if mask.any() else None,
            "reference_p90_m": float(np.percentile(reference[mask], 90)) if mask.any() else None,
        }

    finite = np.isfinite(snapshot.elevation_m)
    return {
        "reference": str(reference_netcdf),
        "reference_role": "现代空间分布交叉验证，不参与推演",
        "valid_node_count": int(valid.sum()),
        "finite_fraction": float(finite.mean()),
        "raw_elevation_range_m": [
            float(snapshot.elevation_m.min()), float(snapshot.elevation_m.max())
        ],
        "calibrated_elevation_range_m": [float(predicted_all.min()), float(predicted_all.max())],
        "spearman_rank_correlation": float(correlation),
        "highland_threshold_m": threshold,
        "highland_precision": precision,
        "highland_recall": recall,
        "highland_f1": f1,
        "random_permutation_baseline": {
            "sample_count": 100,
            "spearman_mean": float(np.mean(null_correlations)),
            "spearman_standard_deviation": float(np.std(null_correlations)),
            "highland_f1_mean": float(np.mean(null_f1)),
            "highland_f1_standard_deviation": float(np.std(null_f1)),
        },
        "predicted_quantiles_m": {
            "p50": float(np.percentile(predicted, 50)),
            "p90": float(np.percentile(predicted, 90)),
            "p99": float(np.percentile(predicted, 99)),
        },
        "reference_quantiles_m": {
            "p50": float(np.percentile(actual, 50)),
            "p90": float(np.percentile(actual, 90)),
            "p99": float(np.percentile(actual, 99)),
        },
        "regions": region_results,
    }


def validate_snapshots(snapshots: dict[int, Snapshot]) -> dict[str, object]:
    checks: dict[str, object] = {}
    for time_ma, snapshot in sorted(snapshots.items()):
        norm_error = np.abs(np.linalg.norm(snapshot.xyz, axis=1) - 1.0)
        checks[str(time_ma)] = {
            "all_finite": bool(np.isfinite(snapshot.elevation_m).all()),
            "maximum_unit_sphere_error": float(norm_error.max()),
            "minimum_elevation_m": float(snapshot.elevation_m.min()),
            "maximum_elevation_m": float(snapshot.elevation_m.max()),
            "within_configured_bounds": bool(
                snapshot.elevation_m.min() >= -500.0 and snapshot.elevation_m.max() <= 7000.0
            ),
        }
    return checks


def assert_acceptance(report_validation: dict[str, object], exported: list[dict[str, object]]) -> None:
    numerical = report_validation["numerical_checks"]
    if not isinstance(numerical, dict):
        raise ValueError("数值验证结果格式错误")
    for time_ma, check in numerical.items():
        if not isinstance(check, dict):
            raise ValueError(f"{time_ma} Ma 数值验证结果格式错误")
        if not check["all_finite"] or not check["within_configured_bounds"]:
            raise ValueError(f"{time_ma} Ma 出现非有限值或越界高程")
        if float(check["maximum_unit_sphere_error"]) >= 1e-12:
            raise ValueError(f"{time_ma} Ma 板块旋转结果偏离单位球")
    for snapshot in exported:
        if snapshot["land_below_zero_cell_count"] != 0:
            raise ValueError(f"{snapshot['time_ma']} Ma 陆地仍有负高程")
        if snapshot["ocean_not_minus_4000_cell_count"] != 0:
            raise ValueError(f"{snapshot['time_ma']} Ma 海陆裁切失败")

    modern = report_validation.get("modern_cross_validation")
    if not isinstance(modern, dict):
        return
    baseline = modern["random_permutation_baseline"]
    if not isinstance(baseline, dict):
        raise ValueError("随机基线格式错误")
    correlation_threshold = float(baseline["spearman_mean"]) + 3.0 * float(
        baseline["spearman_standard_deviation"]
    )
    f1_threshold = float(baseline["highland_f1_mean"]) + 3.0 * float(
        baseline["highland_f1_standard_deviation"]
    )
    if float(modern["spearman_rank_correlation"]) <= correlation_threshold:
        raise ValueError("现代高程空间信号未显著优于随机位置")
    if float(modern["highland_f1"]) <= f1_threshold:
        raise ValueError("现代高地识别未显著优于随机位置")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-zip", type=Path,
                        default=Path("Data/raw/gplates/Muller_etal_2022_SE_v1.2.4.zip"))
    parser.add_argument("--model-dir", type=Path,
                        default=Path("Data/processed/gplates/muller2022"))
    parser.add_argument("--out-dir", type=Path,
                        default=Path(".local/research/paleotopography-prototype"))
    parser.add_argument("--global-node-count", type=int, default=12000)
    parser.add_argument("--oldest-time-ma", type=int, default=970)
    parser.add_argument("--times", type=int, nargs="+",
                        default=[0, 50, 100, 160, 200, 250, 400, 540, 750, 970])
    parser.add_argument("--width", type=int, default=720)
    parser.add_argument("--height", type=int, default=360)
    parser.add_argument("--modern-reference-netcdf", type=Path)
    args = parser.parse_args()
    if not (0 <= min(args.times) <= max(args.times) <= args.oldest_time_ma):
        raise ValueError("输出年代必须位于 0 到 oldest-time-ma 之间")

    model_dir = ensure_model(args.model_zip, args.model_dir)
    rotations = pygplates.RotationModel(str(model_dir / ROTATION_PATH))
    coastlines = pygplates.FeatureCollection(str(model_dir / LAND_GEOMETRY_PATH))
    state, node_stats = build_nodes(
        coastlines,
        rotations,
        model_dir / STATIC_POLYGONS_PATH,
        args.global_node_count,
    )
    if len(state.plate_ids) < 1000:
        raise ValueError(f"有效大陆节点过少：{len(state.plate_ids)}")
    print(f"大陆节点：{len(state.plate_ids)}，板块：{node_stats['plate_count']}")
    boundary_features = load_boundary_features(model_dir)
    requested_times = set(args.times)
    if args.modern_reference_netcdf:
        requested_times.add(0)
    snapshots, trace = simulate(
        state,
        rotations,
        boundary_features,
        args.oldest_time_ma,
        requested_times,
    )
    calibration: HypsometricCalibration | None = None
    if args.modern_reference_netcdf:
        calibration = build_hypsometric_calibration(
            snapshots[0], args.modern_reference_netcdf
        )
    exported = export_snapshots(
        snapshots, coastlines, rotations, args.out_dir, args.width, args.height, calibration
    )
    validation: dict[str, object] = {
        "numerical_checks": validate_snapshots(snapshots),
    }
    if args.modern_reference_netcdf:
        validation["modern_cross_validation"] = validate_modern_snapshot(
            snapshots[0], args.modern_reference_netcdf, calibration
        )
    assert_acceptance(validation, exported)

    report = {
        "method": "Merdith et al. 2025 inspired continental-node forward model",
        "model": "MULLER2022 v1.2.4 paleomagnetic reference frame",
        "scope": "大陆大尺度高程原型；无 LIP、合成洋壳年龄、海侵和动态地形",
        "time_step_ma": 1,
        "oldest_time_ma": args.oldest_time_ma,
        "node_stats": node_stats,
        "parameters": {
            "arc_distance_km": 450,
            "collision_proximity_km": 500,
            "collision_duration_ma": 40,
            "rift_distance_km": 400,
            "rift_duration_ma": 40,
            "arc_growth": {"scale": 300, "decay": 0.001},
            "collision_growth": {"scale": 700, "decay": 0.0003},
            "erosion": "301 - 200 * atan((2000 - local_relief) * 0.007)",
            "local_neighbour_count": 21,
            "inactive_highland_relaxation_per_ma": 0.003,
            "elevation_clip_m": [-500, 7000],
        },
        "known_deviations": [
            "节点从现代露出陆地采样，而不是完整 COB 有效年代节点集",
            "大陆碰撞使用弧终止、异板块接近和距离收敛的简化判据",
            "裂谷使用离散边界接近的简化判据",
            "为抑制简化节点产生的永久宽高原，对非活动高地加入 0.3%/Ma 松弛",
            "未加入 LIP 数据库",
            "海洋统一显示为 -4000 m，不属于推演结果",
        ],
        "hypsometric_calibration": calibration.to_json() if calibration else None,
        "snapshots": exported,
        "validation": validation,
        "trace": trace,
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    report_path = args.out_dir / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"报告：{report_path}")


if __name__ == "__main__":
    main()
