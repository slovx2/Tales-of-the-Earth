# 从 GitHub 恢复项目

仓库保留 Unity 源码、场景、预制体、材质、模型源文件、数据管线、原始数据来源清单和 Git 历史。Unity 缓存、Python 环境、逐年代运行时数据、截图和旧验证副本不进入版本管理。

## 环境与依赖

- Unity `2022.3.62f3c1`
- Python `3.9.20`
- Python 与 Unity 包的精确版本分别见 `uv.lock`、`pyproject.toml` 和 `Packages/packages-lock.json`。

```bash
git clone https://github.com/slovx2/Tales-of-the-Earth.git
cd Tales-of-the-Earth
uv sync --frozen --python 3.9.20
uv run --frozen python -m unittest discover -s Tools/tests -p 'test_*.py'
```

## 重建运行时数据

以下命令会生成数 GB 数据；完整地形推演需要较长时间。删除的本地旧截图、日志和性能测试输出不作为源码备份的一部分。

```bash
# 地球几何、可选的拖动预览和区域边界
uv run --frozen python Tools/build_runtime_geometry.py
uv run --frozen python Tools/build_runtime_geometry.py \
  --time-step-ma 5 --coastline-km 100 --surface-km 750 \
  --max-time-ma 1000 \
  --out Assets/StreamingAssets/EarthGeometryPreview/land_frames.bin
uv run --frozen python Tools/build_runtime_regions.py

# 恢复校准参照，再生成 0–970 Ma 的完整地形与海深
uv run --frozen python Tools/download_paleodem.py
uv run --frozen python Tools/prototype_paleotopography.py \
  --out-dir .local/research/paleotopography-runtime \
  --times $(seq 0 970) \
  --modern-reference-netcdf .local/research/paleodem/Scotese_Wright_2018_Maps_1-88_6minX6min_PaleoDEMS_nc.zip
uv run --frozen python Tools/prototype_paleobathymetry.py \
  --out-dir .local/research/paleobathymetry-runtime \
  --land-topography-dir .local/research/paleotopography-runtime \
  --times $(seq 0 970) \
  --modern-reference-netcdf .local/research/paleodem/Scotese_Wright_2018_Maps_1-88_6minX6min_PaleoDEMS_nc.zip
uv run --frozen python Tools/build_runtime_terrain.py \
  --source-dir .local/research/paleobathymetry-runtime \
  --out Assets/StreamingAssets/EarthTerrain/terrain_frames.bin

# 气候原始时间片、海陆掩膜与运行时气候
uv run --frozen python Tools/download_pohl_data.py --out-dir Data/raw/pohl2022
uv run --frozen python Tools/build_muller_climate_masks.py --out-dir Data/processed/muller2022/masks
uv run --frozen python Tools/build_runtime_climate.py \
  --pohl-dir Data/raw/pohl2022 --mask-dir Data/processed/muller2022/masks
```

然后在 Unity 中打开 `Assets/Scenes/EarthDemo.unity`。奇虾独立展示场景为 `Assets/Scenes/AnomalocarisPreview.unity`，对应 Blender 源文件和 Unity 模型均已保留。

原始数据的 URL、版本和校验值见 `Data/DATA_SOURCES.json`；Pohl 气候文件清单见 `Data/raw/pohl2022/MANIFEST.json`。参考资料的授权说明以各来源文档为准。

## 清理范围

- `Library`、`Temp`、`Logs`、`UserSettings`、`.venv` 和 Python 字节码可由工具重建。
- `Assets/StreamingAssets/Earth*`、`Assets/Textures/earth_modern*`、`Assets/Textures/paleo*`、`Data/processed` 是管线输出。
- `.local/validation` 中的 before/fixed 旧数据副本、截图、日志和性能输出不再保留。
- 根目录的 `earth_evolution.sln`、`earth_evolution_demo.sln` 等旧解决方案与 `.csproj` 为 Unity 自动生成文件。
- 已跟踪源码中未发现内容完全相同的重复文件；不按名称中的 `v01` 推断模型过期，也不删除 Unity 正在引用的模型和 `.meta`。
