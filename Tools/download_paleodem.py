#!/usr/bin/env python3
"""按来源清单恢复本机 PaleoDEM 参照数据，并校验完整性。"""

from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    sources: dict[str, Any] = json.loads(
        (root / "Data/DATA_SOURCES.json").read_text(encoding="utf-8")
    )
    source = sources["paleomap_paleodem"]
    target = root / source["local"]
    expected = str(source["sha256"])
    if target.exists() and sha256(target) == expected:
        print(f"已存在且校验通过：{target.relative_to(root)}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".download")
    request = urllib.request.Request(
        str(source["url"]), headers={"User-Agent": "Tales-of-the-Earth/1.0"}
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            with temporary.open("wb") as output:
                for block in iter(lambda: response.read(1024 * 1024), b""):
                    output.write(block)
        if temporary.stat().st_size != int(source["size_bytes"]):
            raise ValueError("PaleoDEM 文件大小不匹配，保留原文件")
        if sha256(temporary) != expected:
            raise ValueError("PaleoDEM SHA-256 校验失败，保留原文件")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"已下载并校验：{target.relative_to(root)}")


if __name__ == "__main__":
    main()
