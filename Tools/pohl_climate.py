"""Pohl/FOAM 气候场到项目球面网格的映射与 Köppen 分类。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Optional

import numpy as np
from netCDF4 import Dataset
from scipy.spatial import cKDTree


MONTH_DAYS = np.asarray(
    (31.0, 28.25, 31.0, 30.0, 31.0, 30.0, 31.0, 31.0, 30.0, 31.0, 30.0, 31.0),
    dtype=np.float32,
)

# Pohl 数据集 Table 3 使用的类别编码。
KOPPEN_ET = 1
KOPPEN_EF = 2
KOPPEN_DW = 3
KOPPEN_DS = 4
KOPPEN_DF = 5
KOPPEN_CW = 6
KOPPEN_CS = 7
KOPPEN_CF = 8
KOPPEN_BW = 9
KOPPEN_BS = 10
KOPPEN_AW = 11
KOPPEN_AM = 12
KOPPEN_AF = 13


@dataclass(frozen=True)
class PohlClimateSlice:
    time_ma: float
    longitudes: np.ndarray
    latitudes: np.ndarray
    temperature_monthly: np.ndarray
    precipitation_monthly: np.ndarray
    runoff_monthly: np.ndarray
    land_mask: np.ndarray
    published_koppen: np.ndarray


@dataclass(frozen=True)
class MappedClimateFields:
    temperature_monthly: np.ndarray
    precipitation_monthly: np.ndarray
    runoff_monthly: np.ndarray
    confidence: np.ndarray


@dataclass(frozen=True)
class ClassifiedClimate:
    """目标网格上的连续气候统计与 Köppen 前两级类别。"""

    annual_temperature: np.ndarray
    annual_precipitation: np.ndarray
    annual_runoff: np.ndarray
    primary_class: np.ndarray
    secondary_class: np.ndarray
    blend_weight: np.ndarray
    valid: np.ndarray
    confidence: np.ndarray


def _filled(variable: object) -> np.ndarray:
    """把 NetCDF 掩膜数组转换为带 NaN 的 float32。"""
    value = variable[:]  # type: ignore[index]
    return np.asarray(np.ma.filled(value, np.nan), dtype=np.float32)


def load_pohl_slice(path: Path, time_ma: Optional[float] = None) -> PohlClimateSlice:
    """读取一个 Pohl NetCDF，并转换为 month×latitude×longitude。"""
    with Dataset(str(path), "r") as dataset:
        required = {"lon", "lat", "time", "topo", "koppen", "tssub1", "precip", "rnf"}
        missing = required.difference(dataset.variables)
        if missing:
            raise ValueError(f"{path} 缺少 Pohl 变量：{sorted(missing)}")

        longitudes = _filled(dataset.variables["lon"])
        latitudes = _filled(dataset.variables["lat"])
        months = _filled(dataset.variables["time"])
        if longitudes.ndim != 1 or latitudes.ndim != 1 or months.shape != (12,):
            raise ValueError(f"{path} 的经纬度或月份维度无效")
        if not np.all(np.diff(longitudes) > 0.0) or not np.all(np.diff(latitudes) > 0.0):
            raise ValueError(f"{path} 的经纬度必须严格递增")
        for variable_name, expected_tokens in (("tssub1", ("deg", "c")),
                                                ("precip", ("mm", "day")),
                                                ("rnf", ("mm", "day"))):
            units = str(getattr(dataset.variables[variable_name], "units", "")).lower()
            if units and not all(token in units for token in expected_tokens):
                raise ValueError(f"{path} 的 {variable_name} 单位异常：{units}")

        topography = _filled(dataset.variables["topo"]).T
        published_koppen = _filled(dataset.variables["koppen"]).T
        temperature = np.transpose(_filled(dataset.variables["tssub1"]), (2, 1, 0))
        precipitation = np.transpose(_filled(dataset.variables["precip"]), (2, 1, 0))
        runoff = np.transpose(_filled(dataset.variables["rnf"]), (2, 1, 0))
        expected = (12, len(latitudes), len(longitudes))
        if temperature.shape != expected or precipitation.shape != expected or runoff.shape != expected:
            raise ValueError(f"{path} 的月度气候数组尺寸无效")

        land_mask = np.isfinite(topography)
        land_mask &= np.isfinite(temperature).all(axis=0)
        land_mask &= np.isfinite(precipitation).all(axis=0)
        land_mask &= np.isfinite(runoff).all(axis=0)
        if not land_mask.any():
            raise ValueError(f"{path} 没有有效陆地气候单元")

    if time_ma is None:
        match = re.search(r"(?:^|_)(\d+(?:\.\d+)?)Ma(?:_|\.)", path.name, re.IGNORECASE)
        try:
            time_ma = float(match.group(1) if match else path.stem.rsplit("_", 1)[-1])
        except (AttributeError, ValueError) as exception:
            raise ValueError(f"无法从文件名解析年代：{path.name}") from exception
    return PohlClimateSlice(
        time_ma=float(time_ma),
        longitudes=longitudes,
        latitudes=latitudes,
        temperature_monthly=temperature,
        precipitation_monthly=precipitation,
        runoff_monthly=runoff,
        land_mask=land_mask,
        published_koppen=published_koppen,
    )


def target_cell_centres(width: int, height: int) -> tuple[np.ndarray, np.ndarray]:
    """返回项目等经纬网格的单元中心，纬度从北向南排列。"""
    if width <= 0 or height <= 0:
        raise ValueError("目标网格尺寸必须为正数")
    longitudes = (np.arange(width, dtype=np.float64) + 0.5) / width * 360.0 - 180.0
    latitudes = 90.0 - (np.arange(height, dtype=np.float64) + 0.5) / height * 180.0
    return longitudes, latitudes


def lon_lat_to_xyz(longitudes: np.ndarray, latitudes: np.ndarray) -> np.ndarray:
    longitude_radians = np.radians(longitudes)
    latitude_radians = np.radians(latitudes)
    cosine = np.cos(latitude_radians)
    return np.column_stack((
        cosine * np.cos(longitude_radians),
        cosine * np.sin(longitude_radians),
        np.sin(latitude_radians),
    ))


def _latitude_band_fallback(
    source_latitudes: np.ndarray,
    source_values: np.ndarray,
    target_latitudes: np.ndarray,
) -> np.ndarray:
    result = np.empty((len(target_latitudes), source_values.shape[1]), dtype=np.float32)
    hemisphere_medians = {
        -1: np.nanmedian(source_values[source_latitudes < 0.0], axis=0),
        1: np.nanmedian(source_values[source_latitudes >= 0.0], axis=0),
    }
    for index, latitude in enumerate(target_latitudes):
        band_start = np.floor((latitude + 90.0) / 10.0) * 10.0 - 90.0
        band_mask = (source_latitudes >= band_start) & (source_latitudes < band_start + 10.0)
        if band_mask.any():
            result[index] = np.nanmedian(source_values[band_mask], axis=0)
        else:
            result[index] = hemisphere_medians[1 if latitude >= 0.0 else -1]
    return result


def map_slice_to_target(
    climate: PohlClimateSlice,
    width: int = 360,
    height: int = 180,
    maximum_distance_degrees: float = 10.0,
    neighbour_count: int = 32,
) -> MappedClimateFields:
    """以球面逆距离平方加权，把一个 Pohl 时间片映射到目标网格。"""
    if maximum_distance_degrees <= 0.0 or neighbour_count <= 0:
        raise ValueError("邻近搜索参数必须为正数")
    source_lon_grid, source_lat_grid = np.meshgrid(climate.longitudes, climate.latitudes)
    source_mask = climate.land_mask.reshape(-1)
    source_longitudes = source_lon_grid.reshape(-1)[source_mask]
    source_latitudes = source_lat_grid.reshape(-1)[source_mask]
    source_xyz = lon_lat_to_xyz(source_longitudes, source_latitudes)

    combined = np.concatenate((
        np.moveaxis(climate.temperature_monthly, 0, -1),
        np.moveaxis(climate.precipitation_monthly, 0, -1),
        np.moveaxis(climate.runoff_monthly, 0, -1),
    ), axis=-1).reshape((-1, 36))[source_mask]
    finite = np.isfinite(combined).all(axis=1)
    source_xyz = source_xyz[finite]
    source_latitudes = source_latitudes[finite]
    combined = combined[finite]
    if len(combined) == 0:
        raise ValueError("Pohl 时间片没有可映射的完整气候值")

    target_longitudes, target_latitudes_axis = target_cell_centres(width, height)
    target_lon_grid, target_lat_grid = np.meshgrid(target_longitudes, target_latitudes_axis)
    target_longitudes_flat = target_lon_grid.reshape(-1)
    target_latitudes_flat = target_lat_grid.reshape(-1)
    target_xyz = lon_lat_to_xyz(target_longitudes_flat, target_latitudes_flat)

    radius_radians = np.radians(maximum_distance_degrees)
    maximum_chord = 2.0 * np.sin(radius_radians * 0.5)
    count = min(neighbour_count, len(combined))
    distances, indices = cKDTree(source_xyz).query(
        target_xyz,
        k=count,
        distance_upper_bound=maximum_chord,
        workers=-1,
    )
    if count == 1:
        distances = distances[:, None]
        indices = indices[:, None]
    valid = indices < len(combined)
    safe_indices = np.minimum(indices, len(combined) - 1)
    angular_distances = 2.0 * np.arcsin(np.clip(distances * 0.5, 0.0, 1.0))
    weights = np.where(valid, 1.0 / np.maximum(angular_distances, 1e-4) ** 2, 0.0)
    weight_sum = weights.sum(axis=1)
    mapped = np.zeros((len(target_xyz), combined.shape[1]), dtype=np.float64)
    mapped[:] = np.einsum("nk,nkf->nf", weights, combined[safe_indices])
    has_neighbours = weight_sum > 0.0
    mapped[has_neighbours] /= weight_sum[has_neighbours, None]
    if not has_neighbours.all():
        mapped[~has_neighbours] = _latitude_band_fallback(
            source_latitudes,
            combined,
            target_latitudes_flat[~has_neighbours],
        )

    nearest = np.where(valid, angular_distances, np.inf).min(axis=1)
    density = np.minimum(valid.sum(axis=1) / 8.0, 1.0)
    distance_score = np.clip(1.0 - nearest / radius_radians, 0.0, 1.0)
    confidence = 0.35 + 0.65 * distance_score * density
    confidence[~has_neighbours] = 0.2
    fields = mapped.astype(np.float32).reshape((height, width, 36))
    return MappedClimateFields(
        temperature_monthly=np.moveaxis(fields[..., 0:12], -1, 0),
        precipitation_monthly=np.moveaxis(fields[..., 12:24], -1, 0),
        runoff_monthly=np.moveaxis(fields[..., 24:36], -1, 0),
        confidence=confidence.astype(np.float32).reshape((height, width)),
    )


def interpolate_mapped_fields(
    older: MappedClimateFields,
    younger: MappedClimateFields,
    fraction: float,
) -> MappedClimateFields:
    """线性插值连续变量；类别在插值后重新计算。"""
    if older.temperature_monthly.shape != younger.temperature_monthly.shape:
        raise ValueError("插值两端网格尺寸不一致")
    t = float(np.clip(fraction, 0.0, 1.0))
    return MappedClimateFields(
        temperature_monthly=(older.temperature_monthly * (1.0 - t) + younger.temperature_monthly * t).astype(np.float32),
        precipitation_monthly=(older.precipitation_monthly * (1.0 - t) + younger.precipitation_monthly * t).astype(np.float32),
        runoff_monthly=(older.runoff_monthly * (1.0 - t) + younger.runoff_monthly * t).astype(np.float32),
        confidence=(older.confidence * (1.0 - t) + younger.confidence * t).astype(np.float32),
    )


def precipitation_mm_day_to_monthly(precipitation: np.ndarray) -> np.ndarray:
    """按月天数把 Pohl 的 mm/day 转为 Köppen 使用的 mm/month。"""
    values = np.asarray(precipitation, dtype=np.float32)
    if values.shape[0] != 12:
        raise ValueError("降水月度轴必须长度为 12")
    return values * MONTH_DAYS.reshape((12,) + (1,) * (values.ndim - 1))


def classify_koppen(
    temperature_monthly: np.ndarray,
    precipitation_monthly: np.ndarray,
    latitudes: np.ndarray,
) -> np.ndarray:
    """按 Pohl/FAO 常用 Köppen–Geiger 阈值返回 1–13 编码。"""
    temperature = np.asarray(temperature_monthly, dtype=np.float32)
    precipitation = np.asarray(precipitation_monthly, dtype=np.float32)
    if temperature.shape != precipitation.shape or temperature.shape[0] != 12:
        raise ValueError("温度和降水必须为相同的 month×... 数组")
    annual_temperature = np.nanmean(temperature, axis=0)
    annual_precipitation = np.nansum(precipitation, axis=0)
    warmest = np.nanmax(temperature, axis=0)
    coldest = np.nanmin(temperature, axis=0)
    # 季节性指标：南半球夏季为 10–3 月，北半球为 4–9 月。
    shape = temperature.shape[1:]
    latitude_grid = np.asarray(latitudes, dtype=np.float32)
    if latitude_grid.shape != shape:
        latitude_grid = np.broadcast_to(latitude_grid, shape)
    north = latitude_grid >= 0.0
    month_axis = np.broadcast_to(np.arange(12, dtype=np.int32).reshape(12, *([1] * len(shape))), temperature.shape)
    summer_mask = ((month_axis >= 3) & (month_axis <= 8) & north[None, ...]) | \
                  (((month_axis >= 9) | (month_axis <= 2)) & ~north[None, ...])
    summer_precip = np.where(summer_mask, precipitation, np.nan)
    winter_precip = np.where(~summer_mask, precipitation, np.nan)
    summer_total = np.nansum(summer_precip, axis=0)
    winter_total = np.nansum(winter_precip, axis=0)
    driest_summer = np.nanmin(summer_precip, axis=0)
    driest_winter = np.nanmin(winter_precip, axis=0)
    wettest_summer = np.nanmax(summer_precip, axis=0)
    wettest_winter = np.nanmax(winter_precip, axis=0)

    # Köppen 的干燥阈值，夏季降水占比决定修正项。
    summer_fraction = np.divide(summer_total, annual_precipitation, out=np.zeros_like(summer_total), where=annual_precipitation > 0)
    threshold = 20.0 * annual_temperature + np.where(summer_fraction >= 0.7, 280.0,
                                                       np.where(summer_fraction <= 0.3, 0.0, 140.0))
    threshold = np.maximum(threshold, 0.0)
    classes = np.full(shape, KOPPEN_CF, dtype=np.uint8)
    valid = np.isfinite(annual_temperature) & np.isfinite(annual_precipitation)
    aridity = annual_precipitation < threshold
    classes[np.where(valid & aridity & (annual_precipitation < threshold * 0.5))] = KOPPEN_BW
    classes[np.where(valid & aridity & (annual_precipitation >= threshold * 0.5))] = KOPPEN_BS
    tropical = valid & (coldest >= 18.0) & ~aridity
    classes[np.where(tropical & (driest_summer >= 60.0))] = KOPPEN_AF
    classes[np.where(tropical & (driest_summer >= 100.0 - annual_precipitation / 25.0) & (driest_summer < 60.0))] = KOPPEN_AM
    classes[np.where(tropical & (driest_summer < 100.0 - annual_precipitation / 25.0))] = KOPPEN_AW
    polar = valid & (warmest < 10.0) & ~aridity
    classes[np.where(polar & (warmest < 0.0))] = KOPPEN_EF
    classes[np.where(polar & (warmest >= 0.0))] = KOPPEN_ET
    cold = valid & ~tropical & ~polar & ~aridity
    classes[np.where(cold & (coldest <= 0.0))] = KOPPEN_DF
    classes[np.where(cold & (coldest > 0.0))] = KOPPEN_CF
    # C/D 级的夏干与冬干子类；仅在存在明显季节差异时改变第二级。
    dry_summer = cold & (driest_summer < 40.0) & (driest_summer < wettest_winter / 3.0)
    dry_winter = cold & (driest_winter < wettest_summer / 10.0)
    classes[np.where(dry_summer & (coldest > 0.0))] = KOPPEN_CS
    classes[np.where(dry_winter & (coldest > 0.0))] = KOPPEN_CW
    classes[np.where(dry_summer & (coldest <= 0.0))] = KOPPEN_DS
    classes[np.where(dry_winter & (coldest <= 0.0))] = KOPPEN_DW
    classes[~valid] = 0
    return classes


def majority_filter(classes: np.ndarray, land_mask: np.ndarray) -> np.ndarray:
    """3×3 陆地多数滤波；海洋单元始终保持 0。"""
    values = np.asarray(classes, dtype=np.uint8)
    land = np.asarray(land_mask, dtype=bool)
    if values.shape != land.shape or values.ndim != 2:
        raise ValueError("类别和陆地掩膜必须为相同二维数组")
    result = values.copy()
    candidates = np.zeros(values.shape + (14,), dtype=np.uint8)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            shifted_class = np.roll(values, (dy, dx), axis=(0, 1))
            shifted_land = np.roll(land, (dy, dx), axis=(0, 1))
            for category in range(1, 14):
                candidates[..., category] += (shifted_class == category) & shifted_land
    best = np.argmax(candidates, axis=-1).astype(np.uint8)
    replace = land & (best > 0)
    result[replace] = best[replace]
    result[~land] = 0
    return result


def compute_transition(
    classes: np.ndarray,
    land_mask: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """检查八邻域边界，输出主类、次类和 0–0.5 软混合权重。"""
    primary = np.asarray(classes, dtype=np.uint8).copy()
    land = np.asarray(land_mask, dtype=bool)
    secondary = primary.copy()
    blend = np.zeros(primary.shape, dtype=np.float32)
    counts = np.zeros(primary.shape + (14,), dtype=np.uint8)
    different = np.zeros(primary.shape, dtype=np.uint8)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            neighbour = np.roll(primary, (dy, dx), axis=(0, 1))
            neighbour_land = np.roll(land, (dy, dx), axis=(0, 1))
            boundary = land & neighbour_land & (neighbour > 0) & (neighbour != primary)
            different += boundary
            for category in range(1, 14):
                counts[..., category] += boundary & (neighbour == category)
    has_boundary = different > 0
    secondary[has_boundary] = np.argmax(counts[has_boundary], axis=-1).astype(np.uint8)
    blend[has_boundary] = np.minimum(0.5, different[has_boundary].astype(np.float32) / 16.0)
    primary[~land] = secondary[~land] = 0
    return primary, secondary, blend


def classify_and_transition(
    mapped: MappedClimateFields,
    latitudes: np.ndarray,
    land_mask: np.ndarray,
) -> ClassifiedClimate:
    """完成月度单位转换、Köppen 分类、去噪和边界过渡参数生成。"""
    monthly_precipitation = precipitation_mm_day_to_monthly(mapped.precipitation_monthly)
    classes = classify_koppen(mapped.temperature_monthly, monthly_precipitation, latitudes)
    valid = np.asarray(land_mask, dtype=bool) & (mapped.confidence > 0.0)
    classes = majority_filter(classes, valid)
    primary, secondary, blend = compute_transition(classes, valid)
    annual_temperature = np.nanmean(mapped.temperature_monthly, axis=0).astype(np.float32)
    annual_precipitation = np.nansum(monthly_precipitation, axis=0).astype(np.float32)
    annual_runoff = np.nansum(mapped.runoff_monthly * MONTH_DAYS.reshape(12, 1, 1), axis=0).astype(np.float32)
    return ClassifiedClimate(annual_temperature, annual_precipitation, annual_runoff,
                             primary, secondary, blend, valid, mapped.confidence.astype(np.float32))
