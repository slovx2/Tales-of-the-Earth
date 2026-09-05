#!/usr/bin/env python3
"""用工程同源板块模型重建撞击点，记录坐标、板块归属和输入哈希。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pygplates

from rasterize_natural_earth import sha256


def reconstruct_site() -> dict[str, Any]:
    root = Path("Data/processed/gplates/muller2022")
    rotation_path = root / "Rotations/1000_0_rotfile.rot"
    static_path = root / "StaticPolygons/shapes_static_polygons_Merdith_etal.gpml"
    coastline_path = root / "Coastlines/shapes_coastlines_Merdith_etal.gpmlz"
    model = pygplates.RotationModel(str(rotation_path))
    point = pygplates.PointOnSphere(21.30, -89.54)
    reconstructed: list[Any] = []
    pygplates.reconstruct(pygplates.FeatureCollection(str(static_path)), model, reconstructed, 0)
    matches = [item for item in reconstructed if
               item.get_reconstructed_geometry().is_point_in_polygon(point)]
    if len(matches) != 1:
        raise ValueError(f"撞击点必须唯一归属静态板块，实际匹配 {len(matches)} 个")
    feature = matches[0].get_feature()
    plate_id = feature.get_reconstruction_plate_id()
    past = model.get_rotation(66, plate_id, anchor_plate_id=0) * point
    lat, lon = past.to_lat_lon()
    x, y, z = past.to_xyz()
    land: list[Any] = []
    pygplates.reconstruct(pygplates.FeatureCollection(str(coastline_path)), model, land, 66)
    on_land = any(item.get_reconstructed_geometry().is_point_in_polygon(past) for item in land)
    return {
        "event": "Chicxulub", "event_time_ma": 66,
        "modern_latitude_longitude": [21.30, -89.54],
        "reconstructed_latitude_longitude": [lat, lon],
        "unity_unit_direction": [x, -y, z],
        "plate_id": plate_id, "plate_name": feature.get_name(),
        "feature_id": feature.get_feature_id().get_string(),
        "model": "MULLER2022 v1.2.4", "anchor_plate_id": 0,
        "is_exposed_land": on_land,
        "inputs": [{"path": str(p), "sha256": sha256(p)} for p in
                   (rotation_path, static_path, coastline_path)],
        "coordinate_source": "https://doi.org/10.1002/rog.20007",
        "interpretation": "古坐标为当前板块模型的重建结果，不代表精确实测古经纬度。",
    }


if __name__ == "__main__":
    result = reconstruct_site()
    output = Path("Assets/EarthEvents/Data/chicxulub-site.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
