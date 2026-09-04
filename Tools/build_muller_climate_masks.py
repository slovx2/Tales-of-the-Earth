#!/usr/bin/env python3
"""用现有 MULLER2022 海岸线管线生成气候编译器所需的逐 Ma 海陆掩膜。"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pygplates

from generate_paleogeography import (
    LAND_GEOMETRY_PATH,
    ROTATION_PATH,
    draw_reconstruction,
    ensure_model,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", type=Path, default=Path("Data/raw/gplates/Muller_etal_2022_SE_v1.2.4.zip"))
    parser.add_argument("--model-dir", type=Path, default=Path("Data/processed/gplates/muller2022"))
    parser.add_argument("--out-dir", type=Path, default=Path("Data/processed/muller2022/masks"))
    parser.add_argument("--max-time-ma", type=int, default=540)
    parser.add_argument("--start-time-ma", type=int, default=0)
    parser.add_argument("--end-time-ma", type=int, default=None)
    parser.add_argument("--time-step-ma", type=int, default=1)
    args = parser.parse_args()
    if args.max_time_ma < 0 or args.time_step_ma <= 0:
        parser.error("最大年代必须非负，时间步长必须为正")
    end_time = args.max_time_ma if args.end_time_ma is None else min(args.end_time_ma, args.max_time_ma)
    if args.start_time_ma < 0 or args.start_time_ma > end_time:
        parser.error("起止年代范围无效")
    model_dir = ensure_model(args.zip, args.model_dir)
    rotation_model = pygplates.RotationModel(str(model_dir / ROTATION_PATH))
    features = pygplates.FeatureCollection(str(model_dir / LAND_GEOMETRY_PATH))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for time_ma in range(args.start_time_ma, end_time + 1, args.time_step_ma):
        image = draw_reconstruction(features, rotation_model, float(time_ma), 360, 180)
        mask = np.asarray(image, dtype=np.uint8) >= 128
        np.save(args.out_dir / f"land_{time_ma:04d}Ma.npy", mask)
        if time_ma % 20 == 0:
            print(f"{time_ma:03d} Ma")


if __name__ == "__main__":
    main()
