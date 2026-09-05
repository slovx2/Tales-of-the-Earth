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

## 近景平滑渲染

运行时仍使用原来的 360×180 气候帧，不扩大或重新生成数据。类别纹理保持 Point 采样，
`ClimateSampling.cginc` 在周围四个格子中心读取主类、次类与过渡权重，先解码成地表颜色，
再进行双线性混合。类别编号本身不插值；积雪适用权重也随邻近样本连续变化。

无效海洋格子不贡献颜色或连续气候变量，剩余有效陆地样本重新归一化。全部邻居无效时
平滑退回中性陆地色，海岸线仍完全由 MULLER2022 网格决定。经度循环取样，纬度在两极
夹边，防止沿用 Repeat 设置时南北极串色。温度、降水等数据使用 float 精度计算。

`_ClimateBoundaryWarp` 默认 0.12 格，可在材质中调至 0。它以球面连续噪声轻微扰动
视觉过渡，不移动几何轮廓，不提供额外的真实气候细节；现有小尺度明暗细节继续保留。

`_ClimateBoundarySharpness` 默认 3.0，范围 1–3，设为 1 即原平滑版。它先归并同色的
Köppen 子类，再对各地表颜色的混合占比做幂次收紧并归一化，使宽而模糊的交界更清楚。
这一步不改变采样坐标、温度或降水，也不增加纹理采样；结果始终在参与混合的原有颜色
范围内，避免常规全屏锐化的明暗晕边。它只调整视觉过渡，不表示更准确的气候边界。

`Earth Demo > Validate Climate Smoothing` 在 GPU 上检查颜色插值、海岸有效性、经度接缝、
两极与无数据回退，并输出 0、66、540、541 Ma 的固定近景截图到
`.local/validation/land-texture/`。测试 Shader 只位于 Editor 目录，运行时无需增加纹理或依赖。
其中 `sharpen/` 输出 1、2.4、3.0 三档强度的同视角截图；GPU 测试还覆盖锐化后的
边界连续性、同色子类归并和色域约束。
