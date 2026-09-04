#!/usr/bin/env python3
"""下载并校验 Zenodo 上的 Pohl et al. 2022 FOAM 气候时间片。"""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path
from typing import Any


RECORD_URL = "https://zenodo.org/api/records/6620748"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download(url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "Tales-of-the-Earth/1.0"})
    with urllib.request.urlopen(request) as response, path.open("wb") as output:
        while True:
            block = response.read(1024 * 1024)
            if not block:
                break
            output.write(block)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=Path("Data/raw/pohl2022"))
    parser.add_argument("--record-url", default=RECORD_URL)
    args = parser.parse_args()
    with urllib.request.urlopen(args.record_url) as response:
        record: dict[str, Any] = json.load(response)
    files = record.get("files", [])
    netcdf_files = [item for item in files if str(item.get("key", "")).lower().endswith((".nc", ".nc.zip"))]
    if not netcdf_files:
        raise RuntimeError("Zenodo 记录中没有 NetCDF 文件")
    if len(netcdf_files) != 28:
        raise RuntimeError(f"Pohl 时间片数量应为 28，Zenodo 当前返回 {len(netcdf_files)}")
    manifest: dict[str, Any] = {
        "record_url": args.record_url,
        "doi": record.get("doi") or record.get("metadata", {}).get("doi"),
        "title": record.get("metadata", {}).get("title"),
        "license": record.get("metadata", {}).get("license", {}).get("id", "CC BY 4.0"),
        "files": [],
    }
    for item in netcdf_files:
        name = Path(str(item["key"])).name
        target = args.out_dir / name
        if not target.exists() or target.stat().st_size != int(item.get("size", -1)):
            print(f"下载 {name}")
            download(str(item["links"]["self"]), target)
        digest = sha256(target)
        expected = item.get("checksum", "").removeprefix("md5:")
        # Zenodo API 通常只提供 md5；仍记录 SHA-256 供项目生成物追溯。
        manifest["files"].append({"name": name, "size": target.stat().st_size,
                                  "sha256": digest, "zenodo_checksum": expected})
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(f"已准备 {len(netcdf_files)} 个 Pohl NetCDF：{args.out_dir}")


if __name__ == "__main__":
    main()
