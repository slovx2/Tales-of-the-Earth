#!/usr/bin/env python3
"""编译 Pohl/FOAM 气候先验为 Unity 可流式读取的 360×180 帧。"""

from __future__ import annotations

import argparse
import json
import re
import struct
from pathlib import Path
from typing import Iterable

import numpy as np

from pohl_climate import (
    ClassifiedClimate,
    classify_and_transition,
    interpolate_mapped_fields,
    load_pohl_slice,
    map_slice_to_target,
    target_cell_centres,
)
from rasterize_natural_earth import sha256


MAGIC = b"TEC1"
VERSION = 1
HEADER_FORMAT = "<4sifffi"  # magic, version, time step, width, height, frame count
ENTRY_FORMAT = "<fqii"       # time Ma, payload offset, payload bytes, sample count
TIME_PATTERN = re.compile(r"(?P<time>\d+(?:\.\d+)?)Ma_", re.IGNORECASE)


def discover_pohl_files(source_dir: Path) -> list[tuple[float, Path]]:
    """按文件名年代排序，拒绝重复年代。"""
    found: list[tuple[float, Path]] = []
    for path in sorted(source_dir.glob("*.nc")):
        match = TIME_PATTERN.search(path.name)
        if match:
            found.append((float(match.group("time")), path))
    if not found:
        raise FileNotFoundError(f"{source_dir} 中没有形如 0Ma_*.nc 的 Pohl 文件")
    found.sort(key=lambda item: item[0])
    if len({time for time, _ in found}) != len(found):
        raise ValueError("Pohl 文件包含重复年代")
    return found


def load_land_mask(path: Path, width: int, height: int) -> np.ndarray:
    """读取与目标网格一致的 bool 掩膜；支持 npy/npz。"""
    if path.suffix.lower() == ".npz":
        with np.load(path) as archive:
            key = "land_mask" if "land_mask" in archive else archive.files[0]
            mask = np.asarray(archive[key])
    else:
        mask = np.asarray(np.load(path))
    if mask.shape != (height, width):
        raise ValueError(f"海陆掩膜尺寸 {mask.shape} != {(height, width)}：{path}")
    return mask.astype(bool)


def nearest_land_mask(mask_dir: Path | None, time_ma: float, width: int, height: int,
                      allow_all_land_debug: bool = False) -> np.ndarray:
    if mask_dir is None:
        if not allow_all_land_debug:
            raise ValueError("正式生成必须提供 --mask-dir；全陆掩膜仅可显式用于调试")
        return np.ones((height, width), dtype=bool)
    exact = mask_dir / f"land_{int(round(time_ma)):04d}Ma.npy"
    if not exact.exists():
        exact = mask_dir / f"land_{int(round(time_ma)):04d}Ma.npz"
    if not exact.exists():
        raise FileNotFoundError(f"缺少 MULLER2022 海陆掩膜：{exact}")
    return load_land_mask(exact, width, height)


def encode_frame(climate: ClassifiedClimate) -> bytes:
    """按 Unity 读取器约定写出平面布局：连续变量区 + 类别区。"""
    height, width = climate.primary_class.shape
    continuous = np.stack((climate.annual_temperature, climate.annual_precipitation,
                           climate.annual_runoff, np.where(climate.valid, climate.confidence, 0.0)), axis=-1)
    continuous_bytes = continuous.astype("<f2", copy=False).tobytes()
    classes = np.empty((height, width, 4), dtype=np.uint8)
    classes[..., 0] = climate.primary_class
    classes[..., 1] = climate.secondary_class
    classes[..., 2] = np.rint(np.clip(climate.blend_weight, 0.0, 0.5) * 255.0).astype(np.uint8)
    classes[..., 3] = np.where(climate.valid, np.rint(np.clip(climate.confidence, 0.0, 1.0) * 255.0), 0).astype(np.uint8)
    return continuous_bytes + classes.tobytes()


def interpolate_pair(
    left: tuple[float, object], right: tuple[float, object], target_time: float
) -> object:
    left_time, left_fields = left
    right_time, right_fields = right
    if right_time <= left_time:
        return left_fields
    fraction = (target_time - left_time) / (right_time - left_time)
    return interpolate_mapped_fields(left_fields, right_fields, fraction)


def write_dataset(
    pohl_dir: Path,
    out: Path,
    mask_dir: Path | None,
    width: int = 360,
    height: int = 180,
    max_time_ma: int = 540,
    time_step_ma: int = 1,
    allow_all_land_debug: bool = False,
) -> None:
    if (width, height) != (360, 180):
        raise ValueError("运行时气候网格固定为 360×180")
    files = discover_pohl_files(pohl_dir)
    if files[0][0] > 0 or files[-1][0] < max_time_ma:
        raise ValueError(f"Pohl 时间片必须覆盖 0–{max_time_ma} Ma，实际 {files[0][0]}–{files[-1][0]} Ma")
    mapped: list[tuple[float, object]] = []
    for time_ma, path in files:
        mapped.append((time_ma, map_slice_to_target(load_pohl_slice(path), width, height)))
    _, latitudes = target_cell_centres(width, height)
    latitude_grid = np.broadcast_to(latitudes[:, None], (height, width))
    times = list(range(0, max_time_ma + 1, time_step_ma))
    entries: list[tuple[float, int, int, int]] = []
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("wb") as stream:
        stream.write(struct.pack(HEADER_FORMAT, MAGIC, VERSION, float(time_step_ma), float(width), float(height), len(times)))
        stream.write(b"\0" * (struct.calcsize(ENTRY_FORMAT) * len(times)))
        for target_time in times:
            right_index = next((i for i, item in enumerate(mapped) if item[0] >= target_time), len(mapped) - 1)
            left_index = max(0, right_index - (0 if mapped[right_index][0] == target_time else 1))
            fields = interpolate_pair(mapped[left_index], mapped[right_index], target_time)
            mask = nearest_land_mask(mask_dir, target_time, width, height, allow_all_land_debug)
            climate = classify_and_transition(fields, latitude_grid, mask)
            payload = encode_frame(climate)
            offset = stream.tell()
            stream.write(payload)
            entries.append((float(target_time), offset, len(payload), width * height))
        stream.seek(struct.calcsize(HEADER_FORMAT))
        for entry in entries:
            stream.write(struct.pack(ENTRY_FORMAT, *entry))
    metadata = {
        "format": "Tales Earth Climate",
        "format_version": VERSION,
        "source": "Pohl et al. 2022 / FOAM; Köppen–Geiger recomputed after mapping",
        "time_resolution_ma": time_step_ma,
        "time_coverage_ma": [0, max_time_ma],
        "grid": f"{width}x{height}",
        "frame_count": len(times),
        "encoding": "planar continuous RGBAHalf (annual temperature/precipitation/runoff/confidence) followed by RGBA32 (primary/secondary/blend/confidence)",
        "file_size_bytes": out.stat().st_size,
        "file_sha256": sha256(out),
        "pohl_files": [{"time_ma": t, "file": str(p), "sha256": sha256(p)} for t, p in files],
        "land_mask_source": str(mask_dir) if mask_dir else "debug all-land fallback",
    }
    out.with_suffix(".json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    print(f"已生成 {out}：{out.stat().st_size / 1024 / 1024:.1f} MiB，{len(times)} 帧")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pohl-dir", type=Path, required=True)
    parser.add_argument("--mask-dir", type=Path, default=None,
                        help="MULLER2022 逐 Ma land_0000Ma.npy 掩膜目录；正式生成必填")
    parser.add_argument("--out", type=Path, default=Path("Assets/StreamingAssets/EarthClimate/climate_frames.bin"))
    parser.add_argument("--max-time-ma", type=int, default=540)
    parser.add_argument("--time-step-ma", type=int, default=1)
    parser.add_argument("--allow-all-land-debug", action="store_true",
                        help="允许无 MULLER 掩膜时使用全陆调试场（不可用于正式数据）")
    args = parser.parse_args()
    if args.max_time_ma < 0 or args.time_step_ma <= 0:
        parser.error("最大年代必须非负，时间步长必须为正")
    write_dataset(args.pohl_dir, args.out, args.mask_dir, max_time_ma=args.max_time_ma,
                  time_step_ma=args.time_step_ma, allow_all_land_debug=args.allow_all_land_debug)


if __name__ == "__main__":
    main()
