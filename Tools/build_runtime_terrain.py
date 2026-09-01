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


def write_dataset(source_dir: Path, out: Path, max_time_ma: int, time_step_ma: int) -> None:
    times = list(range(0, max_time_ma + 1, time_step_ma))
    header_size = struct.calcsize(HEADER_FORMAT)
    entry_size = struct.calcsize(ENTRY_FORMAT)
    entries: list[tuple[float, int, int, int]] = []
    out.parent.mkdir(parents=True, exist_ok=True)
    width = height = None
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
            if width is None:
                height, width = terrain.shape
            if terrain.shape != (height, width):
                raise ValueError(f"{source} 网格尺寸不一致：{terrain.shape} != {(height, width)}")
            if not np.isfinite(terrain).all():
                raise ValueError(f"{source} 含 NaN 或无穷值")
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
    parser.add_argument("--max-time-ma", type=int, default=970)
    parser.add_argument("--time-step-ma", type=int, default=1)
    args = parser.parse_args()
    if args.max_time_ma < 0 or args.time_step_ma <= 0:
        parser.error("最大年代必须非负，时间步长必须为正")
    write_dataset(args.source_dir, args.out, args.max_time_ma, args.time_step_ma)


if __name__ == "__main__":
    main()
