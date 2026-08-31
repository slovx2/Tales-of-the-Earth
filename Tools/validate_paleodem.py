#!/usr/bin/env python3
"""定量比较 PALEOMAP PaleoDEM 与当前 MULLER2022 海陆几何。"""

from __future__ import annotations

import argparse
import json
import re
import tempfile
import zipfile
from pathlib import Path

import numpy as np
from netCDF4 import Dataset
from PIL import Image

from generate_paleogeography import (
    LAND_GEOMETRY_PATH,
    ROTATION_PATH,
    draw_reconstruction,
    ensure_model,
)

import pygplates


TIME_PATTERN = re.compile(r"_(\d+)Ma\.nc$")


def archive_members_by_time(archive: zipfile.ZipFile) -> dict[int, str]:
    """读取压缩包中每个整数 Ma 对应的 NetCDF 文件。"""
    result: dict[int, str] = {}
    for member in archive.namelist():
        if member.startswith("__MACOSX/") or not member.endswith(".nc"):
            continue
        match = TIME_PATTERN.search(member)
        if match:
            result[int(match.group(1))] = member
    return result


def read_paleodem(archive: zipfile.ZipFile, member: str) -> tuple[np.ndarray, dict[str, object]]:
    """读取一个高程网格；返回原始数组及可复核的元数据。"""
    with tempfile.NamedTemporaryFile(suffix=".nc") as temporary:
        temporary.write(archive.read(member))
        temporary.flush()
        with Dataset(temporary.name) as dataset:
            latitude = np.asarray(dataset.variables["latitude"][:], dtype=np.float64)
            longitude = np.asarray(dataset.variables["longitude"][:], dtype=np.float64)
            elevation = np.asarray(dataset.variables["z"][:], dtype=np.float32)
            metadata = {
                "shape": list(elevation.shape),
                "latitude_range": [float(latitude.min()), float(latitude.max())],
                "longitude_range": [float(longitude.min()), float(longitude.max())],
                "elevation_range_m": [float(elevation.min()), float(elevation.max())],
                "elevation_units": str(dataset.variables["z"].units),
            }
    return elevation, metadata


def resize_land_mask(elevation: np.ndarray, size: tuple[int, int], flip_latitude: bool) -> np.ndarray:
    """按实测约定把 PaleoDEM 的正高程转换为北向上的海陆掩膜。"""
    source = elevation[:, :-1] > 0.0
    if flip_latitude:
        source = np.flipud(source)
    image = Image.fromarray(source.astype(np.uint8) * 255)
    resized = image.resize(size, Image.Resampling.NEAREST)
    return np.asarray(resized, dtype=np.uint8) >= 128


def image_land_mask(image: Image.Image) -> np.ndarray:
    return np.asarray(image.convert("L"), dtype=np.uint8) >= 128


def latitude_weights(height: int) -> np.ndarray:
    latitude = 90.0 - (np.arange(height, dtype=np.float64) + 0.5) / height * 180.0
    return np.cos(np.deg2rad(latitude))[:, None]


def compare_masks(candidate: np.ndarray, reference: np.ndarray) -> dict[str, float]:
    """返回球面面积加权的海陆一致度。"""
    if candidate.shape != reference.shape:
        raise ValueError(f"掩膜尺寸不一致：{candidate.shape} != {reference.shape}")
    weights = latitude_weights(candidate.shape[0])
    globe = float(weights.sum() * candidate.shape[1])
    intersection = float((weights * (candidate & reference)).sum())
    union = float((weights * (candidate | reference)).sum())
    candidate_only = float((weights * (candidate & ~reference)).sum())
    reference_only = float((weights * (~candidate & reference)).sum())
    return {
        "intersection_over_union": intersection / union,
        "globe_area_disagreement": (candidate_only + reference_only) / globe,
        "candidate_land_fraction": float((weights * candidate).sum()) / globe,
        "reference_land_fraction": float((weights * reference).sum()) / globe,
        "candidate_only_globe_fraction": candidate_only / globe,
        "reference_only_globe_fraction": reference_only / globe,
    }


def best_longitude_shift(candidate: np.ndarray, reference: np.ndarray) -> dict[str, float]:
    """在 1° 诊断网格上搜索最佳纯经度偏移，判断是否只是中央经线不同。"""
    size = (360, 180)
    candidate_small = np.asarray(
        Image.fromarray(candidate.astype(np.uint8) * 255).resize(size, Image.Resampling.NEAREST)
    ) >= 128
    reference_small = np.asarray(
        Image.fromarray(reference.astype(np.uint8) * 255).resize(size, Image.Resampling.NEAREST)
    ) >= 128
    best_iou = -1.0
    best_shift = 0
    for shift in range(-180, 180):
        shifted = np.roll(candidate_small, shift, axis=1)
        iou = compare_masks(shifted, reference_small)["intersection_over_union"]
        if iou > best_iou:
            best_iou = iou
            best_shift = shift
    return {"shift_degrees": float(best_shift), "intersection_over_union": best_iou}


def make_comparison_image(candidate: np.ndarray, reference: np.ndarray) -> Image.Image:
    """棕色=一致陆地，粉色=PaleoDEM 独有，青色=MULLER2022 独有。"""
    height, width = candidate.shape
    rgb = np.empty((height, width, 3), dtype=np.uint8)
    rgb[:] = (8, 32, 62)
    rgb[candidate & reference] = (186, 145, 79)
    rgb[candidate & ~reference] = (238, 91, 141)
    rgb[~candidate & reference] = (55, 205, 218)
    return Image.fromarray(rgb)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paleodem-zip", type=Path, required=True)
    parser.add_argument("--model-zip", type=Path,
                        default=Path("Data/raw/gplates/Muller_etal_2022_SE_v1.2.4.zip"))
    parser.add_argument("--model-dir", type=Path,
                        default=Path("Data/processed/gplates/muller2022"))
    parser.add_argument("--modern-reference", type=Path,
                        default=Path("Assets/Textures/earth_modern_mask.png"))
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--times", type=int, nargs="+", default=[0, 100, 250, 400, 540])
    parser.add_argument("--width", type=int, default=2048)
    parser.add_argument("--height", type=int, default=1024)
    args = parser.parse_args()

    model_dir = ensure_model(args.model_zip, args.model_dir)
    rotations = pygplates.RotationModel(str(model_dir / ROTATION_PATH))
    coastlines = pygplates.FeatureCollection(str(model_dir / LAND_GEOMETRY_PATH))
    args.out_dir.mkdir(parents=True, exist_ok=True)

    report: dict[str, object] = {
        "paleodem_archive": str(args.paleodem_zip),
        "comparison_size": [args.width, args.height],
        "land_rule": "PaleoDEM elevation > 0 metres",
        "epochs": [],
    }
    modern_reference = image_land_mask(Image.open(args.modern_reference))
    with zipfile.ZipFile(args.paleodem_zip) as archive:
        members = archive_members_by_time(archive)
        available_times = sorted(members)
        report["coverage"] = {
            "time_min_ma": min(available_times),
            "time_max_ma": max(available_times),
            "time_slice_count": len(available_times),
            "times_ma": available_times,
        }

        for time_ma in args.times:
            if time_ma not in members:
                raise ValueError(f"PaleoDEM 不含 {time_ma} Ma")
            elevation, grid_metadata = read_paleodem(archive, members[time_ma])
            # 0 Ma 对 Natural Earth 的实测显示：数组第 0 行必须解释为北端。
            paleodem_land = resize_land_mask(elevation, (args.width, args.height), flip_latitude=False)
            muller_image = draw_reconstruction(
                coastlines, rotations, float(time_ma), args.width, args.height
            )
            muller_land = image_land_mask(muller_image)
            comparison = compare_masks(paleodem_land, muller_land)
            epoch: dict[str, object] = {
                "time_ma": time_ma,
                "paleodem_member": members[time_ma],
                "grid": grid_metadata,
                "versus_muller2022": comparison,
                "best_pure_longitude_shift": best_longitude_shift(paleodem_land, muller_land),
            }
            if time_ma == 0:
                north_first = compare_masks(paleodem_land, modern_reference)
                south_first_land = resize_land_mask(
                    elevation, (args.width, args.height), flip_latitude=True
                )
                epoch["row_order_validation_against_natural_earth"] = {
                    "array_row_0_as_north": north_first,
                    "array_row_0_as_south": compare_masks(south_first_land, modern_reference),
                    "selected": "array_row_0_as_north",
                }
            image_path = args.out_dir / f"paleodem_vs_muller_{time_ma:04d}Ma.png"
            make_comparison_image(paleodem_land, muller_land).save(image_path)
            epoch["comparison_image"] = str(image_path)
            report["epochs"].append(epoch)  # type: ignore[union-attr]
            print(f"{time_ma:4d} Ma: IoU={comparison['intersection_over_union']:.4f}")

    report_path = args.out_dir / "validation.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"验证报告：{report_path}")


if __name__ == "__main__":
    main()
