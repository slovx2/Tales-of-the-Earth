#!/usr/bin/env python3
"""统计正式/预览运行时数据的帧大小、范围和理论驻留内存。"""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path
from typing import Any, BinaryIO, Dict, List, Tuple


def _read_entries(stream: BinaryIO, entry_format: str, count: int) -> List[Tuple[Any, ...]]:
    size = struct.calcsize(entry_format)
    return [struct.unpack(entry_format, stream.read(size)) for _ in range(count)]


def read_geometry(path: Path) -> Dict[str, Any]:
    with path.open("rb") as stream:
        magic, version, count, resolution, coastline = struct.unpack(
            "<4siiff", stream.read(struct.calcsize("<4siiff")))
        entries = _read_entries(stream, "<fqiii", count)
    payloads = [entry[2] for entry in entries]
    vertices = [entry[3] for entry in entries]
    indices = [entry[4] for entry in entries]
    return {
        "kind": "geometry",
        "magic": magic.decode("ascii"),
        "version": version,
        "file_size_bytes": path.stat().st_size,
        "frame_count": count,
        "time_resolution_ma": resolution,
        "coastline_resolution_km": coastline,
        "frame_payload_bytes": _summary(payloads),
        "vertex_count": _summary(vertices),
        "index_count": _summary(indices),
        "theoretical_raw_resident_bytes": sum(payloads),
    }


def read_terrain(path: Path) -> Dict[str, Any]:
    with path.open("rb") as stream:
        magic, version, resolution, _, width, height, count = struct.unpack(
            "<4siffiii", stream.read(struct.calcsize("<4siffiii")))
        entries = _read_entries(stream, "<fqii", count)
    payloads = [entry[2] for entry in entries]
    return {
        "kind": "terrain",
        "magic": magic.decode("ascii"),
        "version": version,
        "file_size_bytes": path.stat().st_size,
        "frame_count": count,
        "time_resolution_ma": resolution,
        "grid": f"{width}x{height}",
        "frame_payload_bytes": _summary(payloads),
        "theoretical_raw_resident_bytes": sum(payloads),
    }


def read_regions(path: Path) -> Dict[str, Any]:
    with path.open("rb") as stream:
        magic, version, count, resolution, coastline, minimum_area, string_count = struct.unpack(
            "<4siifffi", stream.read(struct.calcsize("<4siifffi")))
        for _ in range(string_count):
            length = struct.unpack("<H", stream.read(2))[0]
            stream.seek(length, 1)
        entries = _read_entries(stream, "<fqiiii", count)
    payloads = [entry[2] for entry in entries]
    nodes = [entry[3] for entry in entries]
    polygons = [entry[4] for entry in entries]
    vertices = [entry[5] for entry in entries]
    return {
        "kind": "regions",
        "magic": magic.decode("ascii"),
        "version": version,
        "file_size_bytes": path.stat().st_size,
        "frame_count": count,
        "time_resolution_ma": resolution,
        "coastline_resolution_km": coastline,
        "minimum_area_km2": minimum_area,
        "frame_payload_bytes": _summary(payloads),
        "node_count": _summary(nodes),
        "polygon_count": _summary(polygons),
        "vertex_count": _summary(vertices),
        "theoretical_raw_resident_bytes": sum(payloads),
    }


def _summary(values: List[int]) -> Dict[str, float]:
    if not values:
        return {"min": 0, "max": 0, "average": 0}
    return {
        "min": min(values),
        "max": max(values),
        "average": sum(values) / len(values),
    }


def build_report(formal_root: Path, preview_root: Path) -> Dict[str, Any]:
    formal = {
        "geometry": read_geometry(formal_root / "EarthGeometry/land_frames.bin"),
        "terrain": read_terrain(formal_root / "EarthTerrain/terrain_frames.bin"),
        "regions": read_regions(formal_root / "EarthRegions/region_frames.bin"),
    }
    preview = {
        "geometry": read_geometry(preview_root / "EarthGeometryPreview/land_frames.bin"),
        "terrain": read_terrain(preview_root / "EarthTerrainPreview/terrain_frames.bin"),
    }
    formal_size = sum(item["file_size_bytes"] for item in formal.values())
    preview_size = sum(item["file_size_bytes"] for item in preview.values())
    preview_raw = sum(item["theoretical_raw_resident_bytes"] for item in preview.values())
    for kind, preview_item in preview.items():
        formal_size_for_kind = formal[kind]["file_size_bytes"]
        preview_item["file_size_ratio_vs_formal"] = (
            preview_item["file_size_bytes"] / formal_size_for_kind
            if formal_size_for_kind else 0)
    return {
        "formal": formal,
        "preview": preview,
        "totals": {
            "formal_file_size_bytes": formal_size,
            "preview_file_size_bytes": preview_size,
            "preview_file_size_ratio": preview_size / formal_size if formal_size else 0,
            "preview_theoretical_raw_resident_bytes": preview_raw,
            "preview_under_500mb": preview_raw <= 500 * 1024 * 1024,
            "preview_includes": ["geometry", "terrain"],
            "regions_runtime_source": "formal",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path("."))
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    report = build_report(args.project_root / "Assets/StreamingAssets",
                          args.project_root / "Assets/StreamingAssets")
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
