#!/usr/bin/env python3
"""按公开板块模型和 GDH1 关系近似推演古海洋深度。"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pygplates
from PIL import Image
from scipy.ndimage import gaussian_filter
from scipy.spatial import cKDTree
from scipy.stats import spearmanr

from generate_paleogeography import LAND_GEOMETRY_PATH, ROTATION_PATH, draw_reconstruction, ensure_model
from prototype_paleotopography import (
    EARTH_RADIUS_KM,
    MID_OCEAN_RIDGE_TYPE,
    boundary_points,
    colorize_elevation,
    finite_rotation_matrix,
    grid_xyz,
    load_boundary_features,
    read_netcdf_elevation,
    sample_reference_elevation,
)


TOPOLOGY_PATHS = (
    Path("Topologies/250-0_plate_bounds.gpml"),
    Path("Topologies/410-250_plate_bounds.gpml"),
    Path("Topologies/1000-410-Topologies.gpml"),
    Path("Topologies/1000-410-Convergence.gpml"),
    Path("Topologies/1000-410-Divergence.gpml"),
    Path("Topologies/1000-410-Transforms.gpml"),
    Path("Topologies/TopologyBuildingBlocks.gpml"),
)
CONTINENTAL_MARGIN_PATH = Path(
    "COB_Coasts/COB_polygons_and_coastlines_combined_1000_0_Merdith_etal.gpml"
)
MAX_SEAFLOOR_AGE_MA = 220.0
DEFAULT_HALF_SPREADING_RATE_KM_PER_MA = 30.0
RIDGE_RESET_DISTANCE_KM = 140.0
SHALLOW_CONTINENTAL_SEA_DEPTH_M = 160.0


@dataclass(frozen=True)
class OceanSnapshot:
    time_ma: int
    seafloor_age_ma: np.ndarray
    bathymetry_m: np.ndarray
    plate_ids: np.ndarray
    land_mask: np.ndarray
    continental_margin_mask: np.ndarray
    ridge_distance_km: np.ndarray


def gdh1_depth_m(seafloor_age_ma: np.ndarray) -> np.ndarray:
    """Stein & Stein (1992) GDH1；返回向下为负的海底基底高程。"""
    age = np.asarray(seafloor_age_ma, dtype=np.float64)
    depth = np.full(age.shape, np.nan, dtype=np.float64)
    valid = np.isfinite(age) & (age >= 0.0)
    young = valid & (age <= 20.0)
    old = valid & (age > 20.0)
    depth[young] = -(2600.0 + 365.0 * np.sqrt(age[young]))
    depth[old] = -(5651.0 - 2473.0 * np.exp(-0.0278 * age[old]))
    return depth


def grid_lat_lon(width: int, height: int) -> tuple[np.ndarray, np.ndarray]:
    longitude = -180.0 + (np.arange(width, dtype=np.float64) + 0.5) / width * 360.0
    latitude = 90.0 - (np.arange(height, dtype=np.float64) + 0.5) / height * 180.0
    lon_grid, lat_grid = np.meshgrid(longitude, latitude)
    return lat_grid.ravel(), lon_grid.ravel()


def xyz_to_nearest_grid_indices(xyz: np.ndarray, width: int, height: int) -> tuple[np.ndarray, np.ndarray]:
    latitude = np.rad2deg(np.arcsin(np.clip(xyz[:, 2], -1.0, 1.0)))
    longitude = np.rad2deg(np.arctan2(xyz[:, 1], xyz[:, 0]))
    x = np.rint((longitude + 180.0) / 360.0 * width - 0.5).astype(np.int64) % width
    y = np.rint((90.0 - latitude) / 180.0 * height - 0.5).astype(np.int64)
    return np.clip(y, 0, height - 1), x


def resolve_plate_grid(
    topology_sources: list[pygplates.FeatureCollection],
    rotations: pygplates.RotationModel,
    time_ma: float,
    width: int,
    height: int,
) -> tuple[np.ndarray, int, int]:
    """用球面点在多边形测试生成 plate ID；避免平面栅格化在大洋板块上取补集。"""
    resolved: list[pygplates.ResolvedTopologicalBoundary] = []
    pygplates.resolve_topologies(topology_sources, rotations, resolved, time_ma)
    polygons = [
        (item.get_resolved_boundary(), item.get_feature().get_reconstruction_plate_id())
        for item in resolved
        if isinstance(item, pygplates.ResolvedTopologicalBoundary)
    ]
    latitude, longitude = grid_lat_lon(width, height)
    ids = np.full(width * height, -1, dtype=np.int32)
    for index, point in enumerate(zip(latitude, longitude)):
        ids[index] = next(
            (plate_id for polygon, plate_id in polygons if polygon.is_point_in_polygon(point)),
            -1,
        )
    gap_mask = ids < 0
    gap_count = int(gap_mask.sum())
    if gap_count:
        gap_fraction = gap_count / len(ids)
        if gap_fraction > 0.005:
            raise ValueError(
                f"{time_ma:g} Ma 有 {gap_count} 个网格点未落入动态板块拓扑，"
                f"超过 0.5% 安全阈值"
            )
        # 拓扑线离散化偶尔留下亚像素缝隙；仅对极少数缝隙取球面最近的已解析格点。
        xyz = grid_xyz(width, height)
        _, nearest = cKDTree(xyz[~gap_mask]).query(xyz[gap_mask], k=1)
        ids[gap_mask] = ids[~gap_mask][nearest]
    return ids.reshape((height, width)), len(polygons), gap_count


def land_mask_at_time(
    coastlines: pygplates.FeatureCollection,
    rotations: pygplates.RotationModel,
    time_ma: float,
    width: int,
    height: int,
) -> np.ndarray:
    image = draw_reconstruction(coastlines, rotations, time_ma, width, height)
    return np.asarray(image.convert("L"), dtype=np.uint8) >= 128


def continental_margin_mask_at_time(
    continental_polygons: pygplates.FeatureCollection,
    coastlines: pygplates.FeatureCollection,
    rotations: pygplates.RotationModel,
    time_ma: float,
    width: int,
    height: int,
) -> tuple[np.ndarray, np.ndarray]:
    """返回露出陆地及 COB 大陆地壳中位于海平面以下的部分。"""
    land = land_mask_at_time(coastlines, rotations, time_ma, width, height)
    continental_image = draw_reconstruction(
        continental_polygons, rotations, time_ma, width, height
    )
    continental = np.asarray(continental_image.convert("L"), dtype=np.uint8) >= 128
    # 少量海岸线像素可能因两套几何的栅格边缘不同落到 COB 外，露出陆地优先。
    return land, continental & ~land


def distance_to_spherical_points(grid: np.ndarray, points: np.ndarray) -> np.ndarray:
    if len(points) == 0:
        return np.full(len(grid), np.inf, dtype=np.float64)
    chord, _ = cKDTree(points).query(grid, k=1)
    angle = 2.0 * np.arcsin(np.clip(chord * 0.5, 0.0, 1.0))
    return EARTH_RADIUS_KM * angle


def ridge_distance_grid(
    grid: np.ndarray,
    boundary_features: list[pygplates.Feature],
    rotations: pygplates.RotationModel,
    time_ma: float,
    height: int,
    width: int,
) -> np.ndarray:
    ridge_points = boundary_points(
        boundary_features,
        rotations,
        time_ma,
        frozenset((MID_OCEAN_RIDGE_TYPE,)),
        tessellation_degrees=max(0.5, 360.0 / width),
    )
    return distance_to_spherical_points(grid, ridge_points).reshape((height, width))


def stage_rotation_matrix(
    rotations: pygplates.RotationModel,
    plate_id: int,
    older_time_ma: float,
    younger_time_ma: float,
) -> np.ndarray:
    """返回把年轻年代坐标反推到较老年代坐标的旋转。"""
    older = finite_rotation_matrix(rotations.get_rotation(older_time_ma, plate_id))
    younger = finite_rotation_matrix(rotations.get_rotation(younger_time_ma, plate_id))
    return older @ younger.T


def advect_seafloor_age(
    older_age_ma: np.ndarray,
    older_plate_ids: np.ndarray,
    younger_plate_ids: np.ndarray,
    rotations: pygplates.RotationModel,
    older_time_ma: float,
    younger_time_ma: float,
    grid: np.ndarray,
) -> np.ndarray:
    """按年轻年代所属板块反向采样较老年代洋壳年龄场。"""
    height, width = younger_plate_ids.shape
    targets = grid.reshape((height, width, 3))
    result = np.full((height, width), np.nan, dtype=np.float64)
    elapsed_ma = older_time_ma - younger_time_ma
    for plate_id in np.unique(younger_plate_ids):
        mask = younger_plate_ids == plate_id
        stage = stage_rotation_matrix(
            rotations, int(plate_id), older_time_ma, younger_time_ma
        )
        source_xyz = targets[mask] @ stage.T
        source_y, source_x = xyz_to_nearest_grid_indices(source_xyz, width, height)
        same_plate = older_plate_ids[source_y, source_x] == plate_id
        source_age = older_age_ma[source_y, source_x]
        valid = same_plate & np.isfinite(source_age)
        values = np.full(source_age.shape, np.nan, dtype=np.float64)
        values[valid] = source_age[valid] + elapsed_ma
        result[mask] = values
    return result


def initialise_missing_ocean(
    age_ma: np.ndarray,
    oceanic_mask: np.ndarray,
    ridge_distance_km: np.ndarray,
    maximum_age_ma: float,
    spreading_rate_km_per_ma: float,
) -> tuple[np.ndarray, int]:
    missing = oceanic_mask & ~np.isfinite(age_ma)
    fallback = np.minimum(ridge_distance_km / spreading_rate_km_per_ma, maximum_age_ma)
    fallback[~np.isfinite(fallback)] = maximum_age_ma
    age_ma[missing] = fallback[missing]
    ridge = oceanic_mask & (ridge_distance_km <= RIDGE_RESET_DISTANCE_KM)
    age_ma[ridge] = 0.0
    age_ma[oceanic_mask] = np.clip(age_ma[oceanic_mask], 0.0, maximum_age_ma)
    age_ma[~oceanic_mask] = np.nan
    return age_ma, int(missing.sum())


def build_bathymetry(
    age_ma: np.ndarray,
    land_mask: np.ndarray,
    continental_margin_mask: np.ndarray,
) -> np.ndarray:
    """洋壳使用 GDH1，COB 大陆地壳的水下部分直接定义为浅海。"""
    bathymetry = gdh1_depth_m(age_ma)
    bathymetry[continental_margin_mask] = -SHALLOW_CONTINENTAL_SEA_DEPTH_M
    bathymetry[land_mask] = np.nan
    return bathymetry


def smooth_bathymetry(bathymetry_m: np.ndarray, land_mask: np.ndarray, sigma: float) -> np.ndarray:
    if sigma <= 0.0:
        return bathymetry_m
    filled = bathymetry_m.copy()
    filled[land_mask] = -SHALLOW_CONTINENTAL_SEA_DEPTH_M
    smoothed = gaussian_filter(filled, sigma=sigma, mode=("nearest", "wrap"))
    smoothed[land_mask] = np.nan
    return smoothed


def make_ocean_snapshot(
    time_ma: int,
    age_ma: np.ndarray,
    plate_ids: np.ndarray,
    land_mask: np.ndarray,
    continental_margin_mask: np.ndarray,
    ridge_distance_km: np.ndarray,
    smoothing_sigma: float,
) -> OceanSnapshot:
    bathymetry = build_bathymetry(age_ma, land_mask, continental_margin_mask)
    bathymetry = smooth_bathymetry(bathymetry, land_mask, smoothing_sigma)
    return OceanSnapshot(
        time_ma=time_ma,
        seafloor_age_ma=age_ma.copy(),
        bathymetry_m=bathymetry,
        plate_ids=plate_ids.copy(),
        land_mask=land_mask.copy(),
        continental_margin_mask=continental_margin_mask.copy(),
        ridge_distance_km=ridge_distance_km.copy(),
    )


def simulate_ocean(
    topology_sources: list[pygplates.FeatureCollection],
    coastlines: pygplates.FeatureCollection,
    continental_polygons: pygplates.FeatureCollection,
    rotations: pygplates.RotationModel,
    boundary_features: list[pygplates.Feature],
    oldest_time_ma: int,
    output_times: set[int],
    width: int,
    height: int,
    maximum_age_ma: float = MAX_SEAFLOOR_AGE_MA,
    spreading_rate_km_per_ma: float = DEFAULT_HALF_SPREADING_RATE_KM_PER_MA,
    smoothing_sigma: float = 0.65,
) -> tuple[dict[int, OceanSnapshot], list[dict[str, float | int]]]:
    grid = grid_xyz(width, height)
    plate_ids, topology_count, topology_gap_count = resolve_plate_grid(
        topology_sources, rotations, float(oldest_time_ma), width, height
    )
    land_mask, continental_margin_mask = continental_margin_mask_at_time(
        continental_polygons, coastlines, rotations, float(oldest_time_ma), width, height
    )
    oceanic_mask = ~land_mask & ~continental_margin_mask
    ridge_distance = ridge_distance_grid(
        grid, boundary_features, rotations, float(oldest_time_ma), height, width
    )
    age = np.full((height, width), np.nan, dtype=np.float64)
    age, initialised = initialise_missing_ocean(
        age, oceanic_mask, ridge_distance, maximum_age_ma, spreading_rate_km_per_ma
    )
    snapshots: dict[int, OceanSnapshot] = {}
    trace: list[dict[str, float | int]] = []
    if oldest_time_ma in output_times:
        snapshots[oldest_time_ma] = make_ocean_snapshot(
            oldest_time_ma,
            age,
            plate_ids,
            land_mask,
            continental_margin_mask,
            ridge_distance,
            smoothing_sigma,
        )
    trace.append({
        "time_ma": oldest_time_ma,
        "resolved_topology_count": topology_count,
        "topology_gap_filled_cell_count": topology_gap_count,
        "oceanic_crust_cell_count": int(oceanic_mask.sum()),
        "shallow_continental_sea_cell_count": int(continental_margin_mask.sum()),
        "advected_cell_count": 0,
        "fallback_initialised_cell_count": initialised,
        "ridge_cell_count": int(((ridge_distance <= RIDGE_RESET_DISTANCE_KM) & oceanic_mask).sum()),
        "median_seafloor_age_ma": float(np.nanmedian(age)),
    })

    for time_ma in range(oldest_time_ma - 1, -1, -1):
        younger_plate_ids, topology_count, topology_gap_count = resolve_plate_grid(
            topology_sources, rotations, float(time_ma), width, height
        )
        younger_land, younger_continental_margin = continental_margin_mask_at_time(
            continental_polygons, coastlines, rotations, float(time_ma), width, height
        )
        younger_oceanic = ~younger_land & ~younger_continental_margin
        younger_ridge_distance = ridge_distance_grid(
            grid, boundary_features, rotations, float(time_ma), height, width
        )
        advected = advect_seafloor_age(
            age,
            plate_ids,
            younger_plate_ids,
            rotations,
            float(time_ma + 1),
            float(time_ma),
            grid,
        )
        advected_count = int((np.isfinite(advected) & younger_oceanic).sum())
        age, fallback_count = initialise_missing_ocean(
            advected,
            younger_oceanic,
            younger_ridge_distance,
            maximum_age_ma,
            spreading_rate_km_per_ma,
        )
        plate_ids = younger_plate_ids
        land_mask = younger_land
        continental_margin_mask = younger_continental_margin
        oceanic_mask = younger_oceanic
        ridge_distance = younger_ridge_distance
        if time_ma in output_times:
            snapshots[time_ma] = make_ocean_snapshot(
                time_ma,
                age,
                plate_ids,
                land_mask,
                continental_margin_mask,
                ridge_distance,
                smoothing_sigma,
            )
        trace.append({
            "time_ma": time_ma,
            "resolved_topology_count": topology_count,
            "topology_gap_filled_cell_count": topology_gap_count,
            "oceanic_crust_cell_count": int(oceanic_mask.sum()),
            "shallow_continental_sea_cell_count": int(continental_margin_mask.sum()),
            "advected_cell_count": advected_count,
            "fallback_initialised_cell_count": fallback_count,
            "ridge_cell_count": int(((ridge_distance <= RIDGE_RESET_DISTANCE_KM) & oceanic_mask).sum()),
            "median_seafloor_age_ma": float(np.nanmedian(age)),
        })
        if time_ma % 25 == 0:
            ocean_count = max(int(oceanic_mask.sum()), 1)
            print(
                f"{time_ma:4d} Ma: ocean={ocean_count:6d}, "
                f"advected={advected_count / ocean_count:5.1%}, "
                f"fallback={fallback_count / ocean_count:5.1%}, "
                f"age_p50={np.nanmedian(age):5.1f} Ma"
            )
    return snapshots, trace


def resize_float_grid(values: np.ndarray, width: int, height: int) -> np.ndarray:
    image = Image.fromarray(values.astype(np.float32))
    return np.asarray(image.resize((width, height), Image.Resampling.BILINEAR), dtype=np.float64)


def load_land_elevation(path: Path, width: int, height: int, land_mask: np.ndarray) -> np.ndarray:
    if not path.exists():
        raise FileNotFoundError(f"缺少大陆高程原型：{path}")
    with np.load(path) as data:
        source = np.asarray(data["elevation_m"], dtype=np.float64)
    elevation = resize_float_grid(source, width, height)
    elevation[land_mask] = np.maximum(elevation[land_mask], 0.0)
    elevation[~land_mask] = np.nan
    return elevation


def export_snapshots(
    snapshots: dict[int, OceanSnapshot],
    out_dir: Path,
    land_topography_dir: Path,
) -> list[dict[str, object]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    exported: list[dict[str, object]] = []
    for time_ma, snapshot in sorted(snapshots.items()):
        height, width = snapshot.land_mask.shape
        land_elevation = load_land_elevation(
            land_topography_dir / f"topography_{time_ma:04d}Ma.npz",
            width,
            height,
            snapshot.land_mask,
        )
        terrain = snapshot.bathymetry_m.copy()
        terrain[snapshot.land_mask] = land_elevation[snapshot.land_mask]
        stem = f"paleobathymetry_{time_ma:04d}Ma"
        np.savez_compressed(
            out_dir / f"{stem}.npz",
            seafloor_age_ma=snapshot.seafloor_age_ma.astype(np.float32),
            bathymetry_m=snapshot.bathymetry_m.astype(np.float32),
            plate_id=snapshot.plate_ids,
            land_mask=snapshot.land_mask,
            continental_margin_mask=snapshot.continental_margin_mask,
        )
        preview = snapshot.bathymetry_m.copy()
        preview[snapshot.land_mask] = 80.0
        colorize_elevation(preview).save(out_dir / f"{stem}.png")
        terrain_stem = f"terrain_{time_ma:04d}Ma"
        np.savez_compressed(
            out_dir / f"{terrain_stem}.npz",
            elevation_m=terrain.astype(np.float32),
            land_mask=snapshot.land_mask,
            continental_margin_mask=snapshot.continental_margin_mask,
            seafloor_age_ma=snapshot.seafloor_age_ma.astype(np.float32),
        )
        colorize_elevation(terrain).save(out_dir / f"{terrain_stem}.png")
        sea = ~snapshot.land_mask
        oceanic = sea & ~snapshot.continental_margin_mask
        exported.append({
            "time_ma": time_ma,
            "grid": f"{width}x{height}",
            "oceanic_crust_cell_count": int(oceanic.sum()),
            "shallow_continental_sea_cell_count": int(snapshot.continental_margin_mask.sum()),
            "median_seafloor_age_ma": float(np.median(snapshot.seafloor_age_ma[oceanic])),
            "p90_seafloor_age_ma": float(np.percentile(snapshot.seafloor_age_ma[oceanic], 90)),
            "minimum_bathymetry_m": float(snapshot.bathymetry_m[sea].min()),
            "median_bathymetry_m": float(np.median(snapshot.bathymetry_m[sea])),
            "maximum_bathymetry_m": float(snapshot.bathymetry_m[sea].max()),
            "data": str(out_dir / f"{stem}.npz"),
            "preview": str(out_dir / f"{stem}.png"),
            "combined_terrain_data": str(out_dir / f"{terrain_stem}.npz"),
            "combined_terrain_preview": str(out_dir / f"{terrain_stem}.png"),
        })
        print(f"已导出 {time_ma} Ma 古海深与合并地形")
    return exported


def classification_f1(predicted: np.ndarray, actual: np.ndarray) -> float:
    true_positive = int((predicted & actual).sum())
    false_positive = int((predicted & ~actual).sum())
    false_negative = int((~predicted & actual).sum())
    precision = true_positive / max(true_positive + false_positive, 1)
    recall = true_positive / max(true_positive + false_negative, 1)
    return 2.0 * precision * recall / max(precision + recall, 1e-12)


def validate_modern_snapshot(
    snapshot: OceanSnapshot,
    reference_netcdf: Path,
) -> dict[str, object]:
    reference_grid = read_netcdf_elevation(reference_netcdf)
    reference = sample_reference_elevation(
        reference_grid, grid_xyz(*snapshot.land_mask.shape[::-1])
    ).reshape(snapshot.land_mask.shape)
    valid = (~snapshot.land_mask) & (reference < 0.0) & np.isfinite(snapshot.bathymetry_m)
    predicted = snapshot.bathymetry_m[valid]
    actual = reference[valid]
    correlation = float(spearmanr(predicted, actual).statistic)
    deep_threshold_m = -4000.0
    deep_f1 = classification_f1(predicted <= deep_threshold_m, actual <= deep_threshold_m)
    random = np.random.default_rng(20260901)
    null_correlation: list[float] = []
    null_f1: list[float] = []
    for _ in range(100):
        shuffled = random.permutation(predicted)
        null_correlation.append(float(spearmanr(shuffled, actual).statistic))
        null_f1.append(classification_f1(
            shuffled <= deep_threshold_m, actual <= deep_threshold_m
        ))

    latitude, longitude = grid_lat_lon(*snapshot.land_mask.shape[::-1])
    regions = {
        "pacific": (-55.0, 55.0, 120.0, -70.0),
        "atlantic": (-55.0, 65.0, -70.0, 20.0),
        "indian": (-55.0, 25.0, 20.0, 120.0),
    }
    region_results: dict[str, object] = {}
    flat_valid = valid.ravel()
    predicted_grid = snapshot.bathymetry_m.ravel()
    reference_flat = reference.ravel()
    for name, (min_lat, max_lat, min_lon, max_lon) in regions.items():
        if min_lon <= max_lon:
            longitude_mask = (longitude >= min_lon) & (longitude <= max_lon)
        else:
            longitude_mask = (longitude >= min_lon) | (longitude <= max_lon)
        mask = (
            (latitude >= min_lat)
            & (latitude <= max_lat)
            & longitude_mask
            & flat_valid
        )
        region_results[name] = {
            "cell_count": int(mask.sum()),
            "predicted_median_m": float(np.median(predicted_grid[mask])) if mask.any() else None,
            "reference_median_m": float(np.median(reference_flat[mask])) if mask.any() else None,
        }
    return {
        "reference": str(reference_netcdf),
        "reference_role": "0 Ma 海深空间交叉验证，不参与洋壳年龄推演",
        "valid_ocean_cell_count": int(valid.sum()),
        "spearman_rank_correlation": correlation,
        "deep_ocean_threshold_m": deep_threshold_m,
        "deep_ocean_f1": deep_f1,
        "random_permutation_baseline": {
            "sample_count": 100,
            "spearman_mean": float(np.mean(null_correlation)),
            "spearman_standard_deviation": float(np.std(null_correlation)),
            "deep_ocean_f1_mean": float(np.mean(null_f1)),
            "deep_ocean_f1_standard_deviation": float(np.std(null_f1)),
        },
        "predicted_quantiles_m": {
            "p10": float(np.percentile(predicted, 10)),
            "p50": float(np.percentile(predicted, 50)),
            "p90": float(np.percentile(predicted, 90)),
        },
        "reference_quantiles_m": {
            "p10": float(np.percentile(actual, 10)),
            "p50": float(np.percentile(actual, 50)),
            "p90": float(np.percentile(actual, 90)),
        },
        "regions": region_results,
    }


def validate_snapshots(snapshots: dict[int, OceanSnapshot]) -> dict[str, object]:
    checks: dict[str, object] = {}
    for time_ma, snapshot in sorted(snapshots.items()):
        sea = ~snapshot.land_mask
        oceanic = sea & ~snapshot.continental_margin_mask
        non_oceanic = ~oceanic
        ridge = oceanic & (snapshot.ridge_distance_km <= RIDGE_RESET_DISTANCE_KM)
        old_floor = oceanic & (snapshot.seafloor_age_ma >= 80.0)
        checks[str(time_ma)] = {
            "all_oceanic_crust_ages_finite": bool(np.isfinite(snapshot.seafloor_age_ma[oceanic]).all()),
            "all_non_oceanic_crust_ages_nan": bool(np.isnan(snapshot.seafloor_age_ma[non_oceanic]).all()),
            "all_sea_depths_negative": bool((snapshot.bathymetry_m[sea] < 0.0).all()),
            "all_land_depths_nan": bool(np.isnan(snapshot.bathymetry_m[snapshot.land_mask]).all()),
            "age_range_ma": [
                float(snapshot.seafloor_age_ma[oceanic].min()),
                float(snapshot.seafloor_age_ma[oceanic].max()),
            ],
            "bathymetry_range_m": [
                float(snapshot.bathymetry_m[sea].min()),
                float(snapshot.bathymetry_m[sea].max()),
            ],
            "shallow_continental_sea_cell_count": int(snapshot.continental_margin_mask.sum()),
            "ridge_cell_count": int(ridge.sum()),
            "old_floor_cell_count": int(old_floor.sum()),
            "ridge_median_depth_m": float(np.median(snapshot.bathymetry_m[ridge])) if ridge.any() else None,
            "old_floor_median_depth_m": float(np.median(snapshot.bathymetry_m[old_floor])) if old_floor.any() else None,
        }
    return checks


def assert_acceptance(validation: dict[str, object]) -> None:
    numerical = validation["numerical_checks"]
    if not isinstance(numerical, dict):
        raise ValueError("海深数值验证格式错误")
    for time_ma, value in numerical.items():
        if not isinstance(value, dict):
            raise ValueError(f"{time_ma} Ma 海深数值验证格式错误")
        required = (
            "all_oceanic_crust_ages_finite",
            "all_non_oceanic_crust_ages_nan",
            "all_sea_depths_negative",
            "all_land_depths_nan",
        )
        if not all(bool(value[key]) for key in required):
            raise ValueError(f"{time_ma} Ma 海深出现 NaN、符号或海陆掩膜错误")
        age_range = value["age_range_ma"]
        if not isinstance(age_range, list) or age_range[0] < 0.0 or age_range[1] > MAX_SEAFLOOR_AGE_MA:
            raise ValueError(f"{time_ma} Ma 洋壳年龄越界")
        ridge_depth = value["ridge_median_depth_m"]
        old_depth = value["old_floor_median_depth_m"]
        if ridge_depth is not None and old_depth is not None and float(ridge_depth) <= float(old_depth):
            raise ValueError(f"{time_ma} Ma 洋中脊没有比老洋壳更浅")

    modern = validation.get("modern_cross_validation")
    if not isinstance(modern, dict):
        return
    baseline = modern["random_permutation_baseline"]
    if not isinstance(baseline, dict):
        raise ValueError("现代海深随机基线格式错误")
    correlation_threshold = float(baseline["spearman_mean"]) + 3.0 * float(
        baseline["spearman_standard_deviation"]
    )
    f1_threshold = float(baseline["deep_ocean_f1_mean"]) + 3.0 * float(
        baseline["deep_ocean_f1_standard_deviation"]
    )
    if float(modern["spearman_rank_correlation"]) <= correlation_threshold:
        raise ValueError("现代海深空间信号未显著优于随机位置")
    if float(modern["deep_ocean_f1"]) <= f1_threshold:
        raise ValueError("现代深海识别未显著优于随机位置")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-zip", type=Path,
                        default=Path("Data/raw/gplates/Muller_etal_2022_SE_v1.2.4.zip"))
    parser.add_argument("--model-dir", type=Path,
                        default=Path("Data/processed/gplates/muller2022"))
    parser.add_argument("--out-dir", type=Path,
                        default=Path(".local/research/paleobathymetry-prototype"))
    parser.add_argument("--land-topography-dir", type=Path,
                        default=Path(".local/research/paleotopography-prototype"))
    parser.add_argument("--oldest-time-ma", type=int, default=970)
    parser.add_argument("--times", type=int, nargs="+",
                        default=[0, 50, 100, 160, 200, 250, 400, 540, 750, 970])
    parser.add_argument("--width", type=int, default=360)
    parser.add_argument("--height", type=int, default=180)
    parser.add_argument("--maximum-seafloor-age-ma", type=float, default=MAX_SEAFLOOR_AGE_MA)
    parser.add_argument("--half-spreading-rate-km-per-ma", type=float,
                        default=DEFAULT_HALF_SPREADING_RATE_KM_PER_MA)
    parser.add_argument("--smoothing-sigma", type=float, default=0.65)
    parser.add_argument("--modern-reference-netcdf", type=Path)
    args = parser.parse_args()
    if not (0 <= min(args.times) <= max(args.times) <= args.oldest_time_ma):
        raise ValueError("输出年代必须位于 0 到 oldest-time-ma 之间")
    if args.width < 36 or args.height < 18:
        raise ValueError("工作网格过小，至少需要 36x18")

    model_dir = ensure_model(args.model_zip, args.model_dir)
    rotations = pygplates.RotationModel(str(model_dir / ROTATION_PATH))
    coastlines = pygplates.FeatureCollection(str(model_dir / LAND_GEOMETRY_PATH))
    continental_polygons = pygplates.FeatureCollection(
        str(model_dir / CONTINENTAL_MARGIN_PATH)
    )
    boundary_features = load_boundary_features(model_dir)
    # 预加载一次；若逐年代把文件名传给 pyGPlates，会重复解析约 1.2 秒/年代。
    topology_sources = [
        pygplates.FeatureCollection(str(model_dir / path)) for path in TOPOLOGY_PATHS
    ]
    requested_times = set(args.times)
    if args.modern_reference_netcdf:
        requested_times.add(0)
    snapshots, trace = simulate_ocean(
        topology_sources,
        coastlines,
        continental_polygons,
        rotations,
        boundary_features,
        args.oldest_time_ma,
        requested_times,
        args.width,
        args.height,
        args.maximum_seafloor_age_ma,
        args.half_spreading_rate_km_per_ma,
        args.smoothing_sigma,
    )
    exported = export_snapshots(snapshots, args.out_dir, args.land_topography_dir)
    validation: dict[str, object] = {"numerical_checks": validate_snapshots(snapshots)}
    if args.modern_reference_netcdf:
        validation["modern_cross_validation"] = validate_modern_snapshot(
            snapshots[0], args.modern_reference_netcdf
        )
    assert_acceptance(validation)

    report = {
        "method": "MULLER2022 topology-advection synthetic seafloor age plus GDH1",
        "model": "MULLER2022 v1.2.4 paleomagnetic reference frame",
        "scope": "大尺度古海洋基底深度原型；与大陆高程合并，但无海沟、海山、LIP、沉积物和动态地形",
        "time_step_ma": 1,
        "oldest_time_ma": args.oldest_time_ma,
        "grid": f"{args.width}x{args.height}",
        "parameters": {
            "maximum_seafloor_age_ma": args.maximum_seafloor_age_ma,
            "fallback_half_spreading_rate_km_per_ma": args.half_spreading_rate_km_per_ma,
            "ridge_reset_distance_km": RIDGE_RESET_DISTANCE_KM,
            "continental_margin_source": str(CONTINENTAL_MARGIN_PATH),
            "shallow_continental_sea_depth_m": -SHALLOW_CONTINENTAL_SEA_DEPTH_M,
            "gaussian_smoothing_sigma_cells": args.smoothing_sigma,
            "age_depth_model": "Stein & Stein 1992 GDH1",
        },
        "known_deviations": [
            "最老年代和无法由上一年代同 plate ID 反向采样的海洋格点，以距洋中脊除以固定 30 km/Ma 半扩张速率初始化",
            "一度工作网格使用最近邻平流，边界附近存在离散误差",
            "MULLER2022 COB 到露出陆地之间统一定义为浅海，不代表该数据自带测深值",
            "未模拟海沟、海山、海底高原、LIP、沉积物和动态地形",
            "深时板块拓扑及扩张中心的不确定性会直接传递到海深",
        ],
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
