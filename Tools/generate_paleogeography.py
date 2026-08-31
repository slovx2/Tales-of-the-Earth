#!/usr/bin/env python3
"""使用 pyGPlates 离线重建 MULLER2022 露出陆地关键帧并输出 Unity 纹理。"""

from __future__ import annotations

import argparse
import json
import math
import zipfile
from pathlib import Path

import pygplates
from PIL import Image, ImageDraw

from rasterize_natural_earth import colorize, make_roughness, sha256


MODEL_SHA256 = "add1f4975360ecd259517b99860f4fb0d176170d909333387e8022c69255bbcd"
MODEL_URL = "https://zenodo.org/api/records/13636799/files/Muller_etal_2022_SE_v1.2.4.zip/content"
ROTATION_PATH = Path("Rotations/1000_0_rotfile.rot")
LAND_GEOMETRY_PATH = Path("Coastlines/shapes_coastlines_Merdith_etal.gpmlz")
LAND_DEFINITION = "当时海岸线围成的露出陆地；不使用广义大陆地壳范围"


def ensure_model(zip_path: Path, model_dir: Path) -> Path:
    if sha256(zip_path) != MODEL_SHA256:
        raise ValueError("MULLER2022 压缩包 SHA-256 校验失败")
    marker = model_dir / "Muller_etal_2022_SE_v1.2.4.gproj"
    if not marker.exists():
        model_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(model_dir)
    return model_dir


def ring_to_pixels(ring: object, width: int, height: int, scale: int) -> list[tuple[float, float]]:
    # pyGPlates 返回 [(纬度, 经度), ...]，而纹理是经度横轴、纬度纵轴。
    pixels: list[tuple[float, float]] = []
    map_width = width * scale
    previous_x: float | None = None
    for point in ring:
        latitude, longitude = point.to_lat_lon()
        x = (float(longitude) + 180.0) / 360.0 * map_width
        # 解开跨越 ±180° 的环，避免 Pillow 在整张地图上画一条错误横线。
        if previous_x is not None:
            while x - previous_x > map_width * 0.5:
                x -= map_width
            while previous_x - x > map_width * 0.5:
                x += map_width
        previous_x = x
        y = (90.0 - float(latitude)) / 180.0 * height * scale
        pixels.append((x, y))
    return pixels


def draw_wrapped_polygon(draw: ImageDraw.ImageDraw, ring: object, width: int, height: int,
                         scale: int, fill: int) -> None:
    points = ring_to_pixels(ring, width, height, scale)
    map_width = width * scale
    for offset in (-map_width, 0.0, map_width):
        draw.polygon([(x + offset, y) for x, y in points], fill=fill)


def draw_reconstruction(feature_collection: object, rotation_model: object, time_ma: float,
                        width: int, height: int) -> Image.Image:
    scale = 3
    canvas = Image.new("L", (width * scale, height * scale), 0)
    draw = ImageDraw.Draw(canvas)
    reconstructed: list[object] = []
    pygplates.reconstruct(feature_collection, rotation_model, reconstructed, time_ma)
    for feature_geometry in reconstructed:
        geometry = feature_geometry.get_reconstructed_geometry()  # type: ignore[attr-defined]
        if not hasattr(geometry, "get_exterior_ring_points"):
            continue
        exterior = geometry.get_exterior_ring_points()
        draw_wrapped_polygon(draw, exterior, width, height, scale, 255)
        for interior_index in range(geometry.get_number_of_interior_rings()):
            interior = geometry.get_interior_ring_points(interior_index)
            draw_wrapped_polygon(draw, interior, width, height, scale, 0)
    return canvas.resize((width, height), Image.Resampling.LANCZOS)


def spherical_land_fraction(mask: Image.Image) -> float:
    """按纬度面积权重计算陆地占地球表面的比例。"""
    grayscale = mask.convert("L")
    width, height = grayscale.size
    data = grayscale.tobytes()
    land_area = 0.0
    globe_area = 0.0
    for y in range(height):
        latitude = 90.0 - (y + 0.5) / height * 180.0
        weight = math.cos(math.radians(latitude))
        row = data[y * width:(y + 1) * width]
        land_area += sum(value >= 128 for value in row) * weight
        globe_area += width * weight
    return land_area / globe_area


def spherical_mask_comparison(mask: Image.Image, reference: Image.Image) -> dict[str, float]:
    """比较两张等经纬投影陆地掩膜，避免极区像素面积失真。"""
    candidate = mask.convert("L")
    baseline = reference.convert("L")
    if candidate.size != baseline.size:
        raise ValueError(f"现代参考掩膜尺寸不一致：{baseline.size} != {candidate.size}")

    width, height = candidate.size
    candidate_data = candidate.tobytes()
    baseline_data = baseline.tobytes()
    intersection = 0.0
    union = 0.0
    disagreement = 0.0
    globe_area = 0.0
    for y in range(height):
        latitude = 90.0 - (y + 0.5) / height * 180.0
        weight = math.cos(math.radians(latitude))
        start = y * width
        end = start + width
        for candidate_value, baseline_value in zip(candidate_data[start:end], baseline_data[start:end]):
            candidate_land = candidate_value >= 128
            baseline_land = baseline_value >= 128
            if candidate_land and baseline_land:
                intersection += weight
            if candidate_land or baseline_land:
                union += weight
            if candidate_land != baseline_land:
                disagreement += weight
        globe_area += width * weight
    return {
        "intersection_over_union": intersection / union,
        "globe_area_disagreement": disagreement / globe_area,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", type=Path, default=Path("Data/raw/gplates/Muller_etal_2022_SE_v1.2.4.zip"))
    parser.add_argument("--model-dir", type=Path, default=Path("Data/processed/gplates/muller2022"))
    parser.add_argument("--out-dir", type=Path, default=Path("Assets/Textures/paleo"))
    parser.add_argument("--width", type=int, default=2048)
    parser.add_argument("--height", type=int, default=1024)
    parser.add_argument("--modern-reference-mask", type=Path,
                        default=Path("Assets/Textures/earth_modern_mask.png"))
    parser.add_argument("--minimum-modern-iou", type=float, default=0.95)
    parser.add_argument("--times", type=float, nargs="+",
                        default=[0, 20, 50, 100, 150, 200, 250, 300, 400, 500, 600, 700, 800, 900, 1000])
    args = parser.parse_args()

    model_dir = ensure_model(args.zip, args.model_dir)
    rotation_file = model_dir / ROTATION_PATH
    land_geometry_file = model_dir / LAND_GEOMETRY_PATH
    rotation_model = pygplates.RotationModel(str(rotation_file))
    land_geometries = pygplates.FeatureCollection(str(land_geometry_file))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    index: list[dict[str, object]] = []
    modern_validation: dict[str, object] | None = None
    for time_ma in sorted(set(args.times)):
        mask = draw_reconstruction(land_geometries, rotation_model, time_ma, args.width, args.height)
        albedo = colorize(mask, args.width, args.height)
        roughness = make_roughness(mask, args.width, args.height)
        stem = f"earth_{int(time_ma):04d}Ma"
        albedo_path = args.out_dir / f"{stem}.png"
        mask_path = args.out_dir / f"{stem}_mask.png"
        roughness_path = args.out_dir / f"{stem}_roughness.png"
        albedo.save(albedo_path, format="PNG", optimize=True)
        mask.save(mask_path, format="PNG", optimize=True)
        roughness.save(roughness_path, format="PNG", optimize=True)
        keyframe = {
            "time_ma": time_ma,
            "albedo": str(albedo_path),
            "land_mask": str(mask_path),
            "roughness": str(roughness_path),
            "spherical_land_fraction": spherical_land_fraction(mask),
        }
        index.append(keyframe)
        if time_ma == 0 and args.modern_reference_mask.exists():
            reference = Image.open(args.modern_reference_mask)
            comparison = spherical_mask_comparison(mask, reference)
            modern_validation = {
                "reference": str(args.modern_reference_mask),
                "role": "仅验证统一管线的 0 Ma 输出，不参与任何年代的纹理生成",
                **comparison,
                "minimum_intersection_over_union": args.minimum_modern_iou,
            }
            if comparison["intersection_over_union"] < args.minimum_modern_iou:
                raise ValueError(
                    "0 Ma 露出陆地与现代参考不一致："
                    f"IoU={comparison['intersection_over_union']:.4f} < {args.minimum_modern_iou:.4f}"
                )
        print(f"已生成 {albedo_path}")

    metadata = {
        "model": "MULLER2022",
        "model_url": MODEL_URL,
        "model_sha256": MODEL_SHA256,
        "land_definition": LAND_DEFINITION,
        "geometry_role": "time-dependent exposed-land coastline polygons",
        "geometry_source": str(LAND_GEOMETRY_PATH),
        "geometry_sha256": sha256(land_geometry_file),
        "rotation_source": str(ROTATION_PATH),
        "rotation_sha256": sha256(rotation_file),
        "times_ma": [item["time_ma"] for item in index],
        "projection": "equirectangular",
        "width": args.width,
        "height": args.height,
        "uniform_processing": "所有年代使用相同的重建、跨日期变更线处理、超采样和着色规则",
        "modern_validation": modern_validation,
        "keyframes": index,
    }
    (args.out_dir / "index.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
