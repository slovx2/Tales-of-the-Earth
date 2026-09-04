#!/usr/bin/env python3
"""把古地形/古海深 NPZ 编译为 Unity 可按年代流式读取的半精度高度场。"""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

import numpy as np

from rasterize_natural_earth import sha256


MAGIC = b"TET1"
VERSION = 1
HEADER_FORMAT = "<4siffiii"
ENTRY_FORMAT = "<fqii"


def resample_bilinear(terrain: np.ndarray, target_width: int,
                      target_height: int) -> np.ndarray:
    """将等经纬度高度场双线性重采样到目标网格，水平方向环绕。"""
    source_height, source_width = terrain.shape
    if (source_width, source_height) == (target_width, target_height):
        return terrain

    source_x = np.linspace(0.0, source_width, target_width, endpoint=False)
    x0 = np.floor(source_x).astype(np.int32)
    x1 = (x0 + 1) % source_width
    x_weight = (source_x - x0).astype(np.float32)
    source_y = np.linspace(0.0, source_height - 1.0, target_height)
    y0 = np.floor(source_y).astype(np.int32)
    y1 = np.minimum(y0 + 1, source_height - 1)
    y_weight = (source_y - y0).astype(np.float32)

    top = (terrain[y0[:, None], x0[None, :]] * (1.0 - x_weight)[None, :] +
           terrain[y0[:, None], x1[None, :]] * x_weight[None, :])
    bottom = (terrain[y1[:, None], x0[None, :]] * (1.0 - x_weight)[None, :] +
              terrain[y1[:, None], x1[None, :]] * x_weight[None, :])
    return (top * (1.0 - y_weight)[:, None] + bottom * y_weight[:, None]).astype(
        np.float32, copy=False)


def write_dataset(source_dir: Path, out: Path, max_time_ma: int, time_step_ma: int,
                  target_width: int | None, target_height: int | None) -> None:
    times = list(range(0, max_time_ma + 1, time_step_ma))
    header_size = struct.calcsize(HEADER_FORMAT)
    entry_size = struct.calcsize(ENTRY_FORMAT)
    entries: list[tuple[float, int, int, int]] = []
    out.parent.mkdir(parents=True, exist_ok=True)
    width = height = None
    source_width = source_height = None
    with out.open("wb") as stream:
        stream.write(struct.pack(HEADER_FORMAT, MAGIC, VERSION, float(time_step_ma), 0.0, 0, 0, 0))
        stream.write(b"\0" * (entry_size * len(times)))
        for time_ma in times:
            source = source_dir / f"terrain_{time_ma:04d}Ma.npz"
            if not source.exists():
                raise FileNotFoundError(f"缺少古地形/海深帧：{source}")
            with np.load(source) as archive:
                terrain = np.asarray(archive["elevation_m"], dtype=np.float32)
            if terrain.ndim != 2:
                raise ValueError(f"{source} 高程场不是二维数组")
            current_height, current_width = terrain.shape
            if source_width is None:
                source_height, source_width = current_height, current_width
            if terrain.shape != (source_height, source_width):
                raise ValueError(f"{source} 网格尺寸不一致：{terrain.shape} != {(source_height, source_width)}")
            if not np.isfinite(terrain).all():
                raise ValueError(f"{source} 含 NaN 或无穷值")
            if target_width is not None and target_height is not None:
                terrain = resample_bilinear(terrain, target_width, target_height)
            if width is None:
                height, width = terrain.shape
            if terrain.shape != (height, width):
                raise ValueError(f"{source} 输出网格尺寸不一致：{terrain.shape} != {(height, width)}")
            # float16 将单帧压到约 126 KiB；对 0–7000 m 地形保留米级到数米级精度。
            payload = terrain.astype("<f2", copy=False).tobytes()
            offset = stream.tell()
            stream.write(payload)
            entries.append((float(time_ma), offset, len(payload), len(payload) // 2))
        assert width is not None and height is not None
        stream.seek(0)
        stream.write(struct.pack(HEADER_FORMAT, MAGIC, VERSION, float(time_step_ma), 0.0,
                                 int(width), int(height), len(times)))
        for entry in entries:
            stream.write(struct.pack(ENTRY_FORMAT, *entry))

    metadata = {
        "format": "Tales Earth Terrain",
        "format_version": VERSION,
        "source": str(source_dir),
        "time_resolution_ma": time_step_ma,
        "max_time_ma": max_time_ma,
        "grid": f"{width}x{height}",
        "source_grid": f"{source_width}x{source_height}",
        "resampling": "双线性重采样（经度方向环绕）" if target_width is not None else "无",
        "encoding": "little-endian IEEE-754 float16 metres; positive land elevation, negative ocean depth",
        "storage": "逐年代单帧半精度高度场，Unity 仅上传当前帧到可复用 RHalf Texture2D",
        "file": str(out),
        "file_size_bytes": out.stat().st_size,
        "file_sha256": sha256(out),
        "frames": len(entries),
    }
    out.with_suffix(".json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    print(f"已生成 {out}：{out.stat().st_size / 1024 / 1024:.1f} MiB，{len(entries)} 帧，网格 {width}x{height}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path,
                        default=Path(".local/research/paleobathymetry-prototype"))
    parser.add_argument("--out", type=Path,
                        default=Path("Assets/StreamingAssets/EarthTerrain/terrain_frames.bin"))
    parser.add_argument("--width", type=int, default=None,
                        help="输出网格宽度；与 --height 同时提供时执行双线性重采样")
    parser.add_argument("--height", type=int, default=None,
                        help="输出网格高度；与 --width 同时提供时执行双线性重采样")
    parser.add_argument("--max-time-ma", type=int, default=970)
    parser.add_argument("--time-step-ma", type=int, default=1)
    args = parser.parse_args()
    if args.max_time_ma < 0 or args.time_step_ma <= 0:
        parser.error("最大年代必须非负，时间步长必须为正")
    if (args.width is None) != (args.height is None) or (
            args.width is not None and (args.width <= 0 or args.height <= 0)):
        parser.error("--width 和 --height 必须同时提供且为正数")
    write_dataset(args.source_dir, args.out, args.max_time_ma, args.time_step_ma,
                  args.width, args.height)


if __name__ == "__main__":
    main()
