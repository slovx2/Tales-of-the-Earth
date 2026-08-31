#!/usr/bin/env python3
"""将 Natural Earth land Shapefile 离线栅格化为 Unity 可用的海陆纹理。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import zipfile
from pathlib import Path
from typing import Iterable, Sequence

import shapefile  # type: ignore[import-untyped]
from PIL import Image, ImageDraw, ImageFilter


SOURCE_URL = "https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_land.zip"
SOURCE_SHA256 = "e547d749445eaa0964aba76738090ec88f5e63c4585122170f98c67a7ea922dc"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_source(zip_path: Path, extract_dir: Path) -> Path:
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(extract_dir)
    shp_path = extract_dir / "ne_10m_land.shp"
    if not shp_path.exists():
        raise FileNotFoundError(f"未找到 {shp_path}")
    return shp_path


def project_point(longitude: float, latitude: float, width: int, height: int) -> tuple[float, float]:
    x = (longitude + 180.0) / 360.0 * width
    y = (90.0 - latitude) / 180.0 * height
    return x, y


def wrapped_chunks(points: Sequence[Sequence[float]], width: int, height: int) -> Iterable[list[tuple[float, float]]]:
    """切开跨越 ±180° 的环，避免 Pillow 画出横跨整张地图的错误连线。"""
    projected = [project_point(float(p[0]), float(p[1]), width, height) for p in points]
    if not projected:
        return
    chunk: list[tuple[float, float]] = [projected[0]]
    for point in projected[1:]:
        previous = chunk[-1]
        if abs(point[0] - previous[0]) > width * 0.5:
            if len(chunk) >= 3:
                yield chunk
            chunk = [point]
        else:
            chunk.append(point)
    if len(chunk) >= 3:
        yield chunk


def draw_shapes(shp_path: Path, width: int, height: int) -> Image.Image:
    # 4x 超采样后缩小，海岸线边缘更适合球体材质。
    scale = 4
    canvas = Image.new("L", (width * scale, height * scale), 0)
    draw = ImageDraw.Draw(canvas)
    reader = shapefile.Reader(str(shp_path))
    for shape in reader.iterShapes():
        points = shape.points
        for start, end in zip(shape.parts, list(shape.parts[1:]) + [len(points)]):
            ring = points[start:end]
            for chunk in wrapped_chunks(ring, width * scale, height * scale):
                draw.polygon(chunk, fill=255)
    return canvas.resize((width, height), Image.Resampling.LANCZOS)


def colorize(mask: Image.Image, width: int, height: int) -> Image.Image:
    """把真实海陆 mask 着色为具有纬度和海岸过渡的游戏化材质。"""
    mask = mask.convert("L")
    # 轻微海岸辉光让球体边缘在缩放时更清楚，不改变陆地轮廓。
    coast = mask.filter(ImageFilter.GaussianBlur(radius=1.2))
    output = Image.new("RGB", (width, height))
    source = mask.load()
    coast_pixels = coast.load()
    pixels = output.load()
    for y in range(height):
        latitude = 90.0 - (y + 0.5) / height * 180.0
        latitude_factor = abs(latitude) / 90.0
        for x in range(width):
            value = source[x, y]
            wave = 0.5 + 0.5 * math.sin(x * 0.021 + y * 0.013)
            if value > 128:
                # 纬度和低频波动带来森林、草原、荒漠的层次；极区使用冰雪色。
                if latitude > 70.0 or latitude < -60.0:
                    snow = max(0.0, min(1.0, (abs(latitude) - 55.0) / 30.0))
                    base = (76, 132, 64)
                    target = (218, 229, 224)
                    pixels[x, y] = tuple(int(base[i] * (1 - snow) + target[i] * snow) for i in range(3))
                else:
                    dry = max(0.0, min(1.0, (latitude_factor - 0.25) * 0.9 + wave * 0.12))
                    pixels[x, y] = (int(52 + dry * 102), int(122 + dry * 48), int(58 + dry * 4))
            else:
                depth = 0.5 + 0.5 * (1.0 - latitude_factor)
                pixels[x, y] = (int(5 + depth * 5), int(34 + depth * 30), int(78 + depth * 62))
            if 20 < value < 235:
                # 抗锯齿像素中的海岸水色过渡。
                blend = max(0.0, min(1.0, (coast_pixels[x, y] - 90) / 150.0))
                r, g, b = pixels[x, y]
                pixels[x, y] = (int(r * (1 - blend) + 70 * blend), int(g * (1 - blend) + 150 * blend), int(b * (1 - blend) + 170 * blend))
    return output


def make_roughness(mask: Image.Image, width: int, height: int) -> Image.Image:
    """生成材质粗糙度：海洋更光滑，陆地更粗糙，海岸保留平滑过渡。"""
    softened = mask.filter(ImageFilter.GaussianBlur(radius=1.4)).load()
    output = Image.new("L", (width, height))
    pixels = output.load()
    for y in range(height):
        for x in range(width):
            land = softened[x, y] / 255.0
            # Unity 粗糙度约定：0=镜面，255=完全粗糙。
            pixels[x, y] = int(48 + land * 150)
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", type=Path, default=Path("Data/raw/natural_earth/ne_10m_land.zip"))
    parser.add_argument("--out", type=Path, default=Path("Assets/Textures/earth_modern.png"))
    parser.add_argument("--mask-out", type=Path, default=Path("Assets/Textures/earth_modern_mask.png"))
    parser.add_argument("--roughness-out", type=Path, default=Path("Assets/Textures/earth_modern_roughness.png"))
    parser.add_argument("--width", type=int, default=2048)
    parser.add_argument("--height", type=int, default=1024)
    args = parser.parse_args()

    actual_sha = sha256(args.zip)
    if actual_sha != SOURCE_SHA256:
        raise ValueError(f"Natural Earth 压缩包校验失败：{actual_sha}")
    source_dir = args.zip.parent / "extracted"
    shp_path = extract_source(args.zip, source_dir)
    mask = draw_shapes(shp_path, args.width, args.height)
    image = colorize(mask, args.width, args.height)
    roughness = make_roughness(mask, args.width, args.height)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    image.save(args.out, format="PNG", optimize=True)
    mask.save(args.mask_out, format="PNG", optimize=True)
    roughness.save(args.roughness_out, format="PNG", optimize=True)
    metadata = {
        "source": SOURCE_URL,
        "source_sha256": SOURCE_SHA256,
        "dataset": "Natural Earth 10m physical land",
        "projection": "equirectangular",
        "width": args.width,
        "height": args.height,
        "land_rgb": [77, 139, 62],
        "ocean_rgb": [7, 48, 102],
        "derived_assets": {
            "land_mask": str(args.mask_out),
            "roughness": str(args.roughness_out),
            "roughness_model": "ocean=48, land=198, coastline blurred 1.4px",
        },
    }
    args.out.with_suffix(".json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    print(f"已生成 {args.out} ({args.width}x{args.height})")


if __name__ == "__main__":
    main()
