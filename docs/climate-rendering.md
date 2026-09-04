# Pohl + FOAM + Köppen 气候先验

## 离线生成

```bash
uv run python Tools/download_pohl_data.py --out-dir Data/raw/pohl2022
uv run python Tools/build_muller_climate_masks.py --out-dir Data/processed/muller2022/masks
uv run python Tools/build_runtime_climate.py \
  --pohl-dir Data/raw/pohl2022 \
  --mask-dir Data/processed/muller2022/masks
```

`--mask-dir` 中每个 `land_0000Ma.npy` 是当前 MULLER2022 几何管线生成的
`360×180` 海陆掩膜。气候编译器先在球面上对 Pohl 有效陆地点做 10° 内逆距离平方
加权，再插值到逐 1 Ma，重新计算 Köppen 类别，并生成陆地边界的主/次类过渡权重。
正式生成不提供掩膜时会拒绝；省略掩膜仅用于单元测试的全陆调试场。

运行时帧文件位于 `Assets/StreamingAssets/EarthClimate/`（已加入 Git 忽略）。每个样本
包含年平均温度、年降水、年径流、映射置信度（4×float16）以及主类、次类、过渡权重和
有效置信度（4×uint8）。`DynamicClimateRenderer` 将它们上传为 RGBAHalf/RGBA32，
`DynamicLand.shader` 在同一材质内混合类别。541 Ma 及更早年代自动关闭气候先验并回退
中性陆地颜色；海陆轮廓仍完全来自 MULLER2022 动态网格。

Pohl 原始文件、DOI、许可证和逐文件 SHA-256 记录在 `Data/DATA_SOURCES.json` 与
下载后生成的 `Data/raw/pohl2022/MANIFEST.json` 中。
