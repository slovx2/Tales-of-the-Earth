# Tales of the Earth

基于 Unity 的三维地球演化原型。当前版本支持在 `0–1000 Ma` 时间轴上按 `1 Ma` 切换地球陆地几何，并可拖动旋转、滚轮缩放。

当前数据口径：

- 时间分辨率：`1 Ma/帧`，共 `1001` 帧
- 海岸线最大分段：约 `25 km`
- 大陆内部球面三角边：最大约 `250 km`
- 古地理数据：MULLER2022 v1.2.4
- 现代陆地参照：Natural Earth 10m physical land

## 快速开始

环境：

- Unity `2022.3.62f3c1`
- Python `3.9.20`
- `uv`

安装离线管线依赖并生成运行时数据：

```bash
uv sync --python 3.9.20
uv run python Tools/build_runtime_geometry.py
```

然后使用 Unity 打开项目，进入 `Assets/Scenes/EarthDemo.unity` 并点击 Play。

操作方式：

- 左键拖动：旋转地球
- 滚轮：缩放
- 底部时间轴：切换地质年代

## 工程索引

| 路径 | 用途 |
| --- | --- |
| `Assets/Scenes/EarthDemo.unity` | 当前演示场景 |
| `Assets/Scripts` | 时间轴、交互、运行时数据读取和动态网格更新 |
| `Assets/Shaders` | 海洋、陆地和大气层 Shader |
| `Assets/Editor` | 场景构建与 Unity 自动验收 |
| `Tools` | MULLER2022、Natural Earth 离线处理工具 |
| `Data/raw` | 纳入版本管理的原始数据压缩包 |
| `Data/DATA_SOURCES.json` | 数据来源、版本和 SHA-256 |
| `Assets/StreamingAssets/EarthGeometry` | 可重建的 Unity 运行时几何数据 |
| `docs` | 工程设计与数据文档 |
| `.local` | 本机日志、截图和临时验收产物，不进入 Git |

## 主要技术

- pyGPlates 按年代重建 MULLER2022 海岸线多边形。
- Mapbox Earcut 完成二维多边形三角化。
- 共享边球面细分保证大陆内部网格贴合球面。
- 自定义二进制帧格式保存单位球顶点和三角形索引。
- Unity 运行时只读取当前帧，并更新一个可复用的动态 Mesh。
- 海洋、陆地和大气层使用相互独立的渲染层与 Shader。
- Natural Earth 只用于校验 0 Ma 现代轮廓，不替换任何年代的数据。

## 数据生成参数

默认命令等价于：

```bash
uv run python Tools/build_runtime_geometry.py \
  --time-step-ma 1 \
  --coastline-km 25 \
  --surface-km 250 \
  --max-time-ma 1000
```

输出：

```text
Assets/StreamingAssets/EarthGeometry/land_frames.bin
Assets/StreamingAssets/EarthGeometry/land_frames.json
```

这些文件以及 `Data/processed` 都是可重建产物，不进入 Git。Unity 运行前必须存在 `land_frames.bin`。

## 文档

- [地球模型、数据管线、渲染技术与数据来源](docs/earth-model-and-data-pipeline.md)
- [地形与海深渲染设计](docs/terrain-rendering.md)
- [古地形数据验证与推演可行性](docs/paleotopography-data-research.md)
- [古地形推演原型与交叉验证](docs/paleotopography-prototype.md)
- [古海深推演原型与数据口径](docs/paleobathymetry-prototype.md)

## 验收

Unity Play Mode 验收会遍历全部年代、验证时间轴与拖动旋转，并把截图写入 `.local/validation`：

```bash
/Applications/Unity/Hub/Editor/2022.3.62f3c1/Unity.app/Contents/MacOS/Unity \
  -batchmode \
  -projectPath "$PWD" \
  -executeMethod EarthDemoPlayValidation.Run \
  -logFile "$PWD/.local/logs/unity-play-validation.log"
```
