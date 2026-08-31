# Tales of the Earth

Unity 3D 地球演化原型。运行时使用海洋球体和按时间读取的陆地几何网格；拖动底部时间轴可以在 `0–1000 Ma` 之间切换，当前数据口径为 `1 Ma/帧`、海岸线最大分段约 `25 km`。

## 环境

- Unity `2022.3.62f3c1`
- Python `3.9.20`
- `uv`

安装离线管线依赖：

```bash
uv sync --python 3.9.20
```

## 数据口径

- 古地理海岸线与旋转模型：MULLER2022 v1.2.4，覆盖 `0–1000 Ma`
- 现代陆地参照：Natural Earth 10m physical land
- 原始压缩包位于 `Data/raw`
- 来源 URL、版本和 SHA-256 位于 `Data/DATA_SOURCES.json`

`Data/processed`、Unity 运行时几何和渲染纹理都属于可重建产物，不进入 Git。

## 生成运行时几何

下面的默认命令会生成 `1001` 帧、约 `2.2 GiB` 的二进制数据：

```bash
uv run python Tools/build_runtime_geometry.py
```

等价的完整参数为：

```bash
uv run python Tools/build_runtime_geometry.py \
  --time-step-ma 1 \
  --coastline-km 25 \
  --max-time-ma 1000
```

生成结果：

```text
Assets/StreamingAssets/EarthGeometry/land_frames.bin
Assets/StreamingAssets/EarthGeometry/land_frames.json
```

Unity 运行时通过 `FileStream` 只读取当前帧，不会把 1001 帧全部载入内存。

## 在 Unity 中运行

1. 使用 Unity `2022.3.62f3c1` 打开项目目录。
2. 在菜单中选择 `Earth Demo > Build Demo Scene`。
3. 打开 `Assets/Scenes/EarthDemo.unity`。
4. 点击 Play。

操作方式：

- 左键拖动：旋转地球
- 滚轮：缩放
- 底部时间轴：按 `1 Ma` 切换几何帧

## 可选纹理管线

生成 Natural Earth 现代地球参照纹理：

```bash
uv run python Tools/rasterize_natural_earth.py
```

生成旧版古地理纹理关键帧：

```bash
uv run python Tools/generate_paleogeography.py
```

这些纹理当前不参与动态几何渲染，主要保留为数据对照和表现试验。

## 本地验收

验收截图、Unity 日志和临时结果统一放在 `.local`，该目录不会提交到 Git。
