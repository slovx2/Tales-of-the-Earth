# 地球模型、数据管线、渲染技术与数据来源

## 1. 当前系统目标

当前版本提供一个可交互的三维地球演化模型：

- 时间范围为 `0–1000 Ma`。
- 时间分辨率为 `1 Ma/帧`，共 `1001` 帧。
- 每一帧是一套独立的球面陆地三角网格。
- 运行时只加载当前年代，不把全部帧载入内存。
- 时间轴切换几何帧；当前不做相邻年代的形状插值。
- 视觉对象由海洋球、动态陆地和大气层组成。

这里的“陆地”定义为 MULLER2022 在对应年代提供的海岸线多边形所包围的露出陆地，不表示广义大陆地壳，也不直接表示板块边界、地形高程或海底地貌。

## 2. 数据来源与职责

### 2.1 MULLER2022 v1.2.4

来源：

- 数据包：[Muller_etal_2022_SE_v1.2.4.zip](https://zenodo.org/api/records/13636799/files/Muller_etal_2022_SE_v1.2.4.zip/content)
- SHA-256：`add1f4975360ecd259517b99860f4fb0d176170d909333387e8022c69255bbcd`
- 本地原始文件：`Data/raw/gplates/Muller_etal_2022_SE_v1.2.4.zip`

运行时几何使用其中两类文件：

- 海岸线多边形：`Coastlines/shapes_coastlines_Merdith_etal.gpmlz`
- 旋转模型：`Rotations/1000_0_rotfile.rot`

MULLER2022 是所有年代陆地几何的唯一生成来源。0 Ma 和古地球采用完全相同的重建、三角化和球面细分规则。

### 2.2 Natural Earth 10m physical land

来源：

- 数据包：[ne_10m_land.zip](https://naturalearth.s3.amazonaws.com/10m_physical/ne_10m_land.zip)
- SHA-256：`e547d749445eaa0964aba76738090ec88f5e63c4585122170f98c67a7ea922dc`
- 本地原始文件：`Data/raw/natural_earth/ne_10m_land.zip`

Natural Earth 的职责仅限于现代地球准确性参照：

- 生成现代陆地参考掩膜。
- 与 MULLER2022 的 0 Ma 输出做球面面积加权比较。
- 帮助发现海岸线口径、投影或几何处理错误。

Natural Earth 不参与任何运行时帧的几何生成，也不会替换 MULLER2022 的 0 Ma 数据。

### 2.3 来源记录

机器可读的数据 URL、版本和校验值统一记录在 `Data/DATA_SOURCES.json`。数据引用和授权要求以各原始数据包内的说明及其发布页面为准。

## 3. 离线数据管线

主入口是 `Tools/build_runtime_geometry.py`。

### 3.1 输入校验与解包

管线首先校验 MULLER2022 原始压缩包的 SHA-256。校验通过后，将内容解包到 `Data/processed/gplates/muller2022`。`Data/processed` 是可重建中间目录，不进入 Git。

### 3.2 按年代重建

pyGPlates 加载海岸线 FeatureCollection 和 RotationModel，并对 `0–1000 Ma` 的每个整数年代执行重建。每个年代输出一组球面多边形要素。

### 3.3 海岸线采样

每个球面多边形的外环和内环先按最大约 `25 km` 的分段长度加密。该参数由 `--coastline-km` 控制，决定海岸边界的空间精度。

连续重复点和闭环末尾重复点会被清理，避免零长度边影响后续三角化。

### 3.4 多边形三角化

每个球面多边形独立处理：

1. 以多边形内部质心为中心建立局部切平面。
2. 使用方位等距投影把外环和内环映射到二维。
3. 使用 Mapbox Earcut 对带孔二维多边形进行三角化。
4. 根据球面朝外方向统一三角形绕序。

三角化只决定多边形拓扑，最终顶点仍保存为单位球三维坐标。

### 3.5 大陆内部球面细分

海岸线采样只约束边界，Earcut 生成的大陆内部边仍可能很长。因此管线对所有共享长边做一致细分：

- 当前最长球面三角边约束为 `250 km`，由 `--surface-km` 控制。
- 同一条共享边只生成一个中点，邻接三角形使用相同的新顶点。
- 新中点归一化到单位球面。
- 根据每个三角形被切分的边数生成一致的新拓扑。
- 输出前重新统计最长边；超过阈值和 float32 容差时立即终止。

海岸线精度与大陆内部球面精度是两个独立参数。前者控制轮廓，后者保证渲染表面贴合球体。

### 3.6 帧聚合与输出

同一年代的全部要素逐个三角化，然后把顶点和索引拼接为一个帧网格。全部帧写入：

```text
Assets/StreamingAssets/EarthGeometry/land_frames.bin
Assets/StreamingAssets/EarthGeometry/land_frames.json
```

二进制文件供 Unity 随机读取；JSON 文件保存来源哈希、生成参数、文件哈希和每帧统计信息。

`Assets/StreamingAssets/EarthTerrain/terrain_frames.bin` 是按 `1 Ma` 编译的 `360×180` 半精度有符号高度场。它由 `Tools/build_runtime_terrain.py` 从古地形/古海深合并 NPZ 生成，属于可重建运行时产物，不进入 Git。`DynamicTerrainRenderer` 按时间轴读取单帧并上传复用的 `RHalf Texture2D`，海洋和陆地材质共享该纹理。

## 4. 运行时二进制格式

格式名为 `Tales Earth Geometry`，当前 Magic 为 `TEG1`、版本为 `1`，所有字段使用小端序。

### 4.1 文件头

结构：`<4siiff`

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| magic | 4 bytes | `TEG1` |
| version | int32 | 格式版本 |
| frame_count | int32 | 帧数量 |
| time_step_ma | float32 | 时间分辨率 |
| coastline_km | float32 | 海岸线分段参数 |

### 4.2 帧索引表

每帧结构：`<fqiii`

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| time_ma | float32 | 当前年代 |
| offset | int64 | 帧数据在文件中的偏移 |
| byte_length | int32 | 帧数据字节数 |
| vertex_count | int32 | 顶点数 |
| index_count | int32 | 索引数 |

### 4.3 帧数据

每帧数据连续存储：

1. `vertex_count × float32 × 3` 的单位球 XYZ 顶点。
2. `index_count × uint32` 的三角形索引。

大陆内部球面分辨率、源数据哈希和详细统计记录在同名 JSON 元数据中。

## 5. Unity 运行时结构

### 5.1 数据读取

`EarthGeometryDataset` 在初始化时读取文件头和完整帧索引表，并按数据集中的最大帧尺寸预分配复用缓冲区。

切换年代时：

1. 根据时间分辨率选择最近的帧索引。
2. 使用 `FileStream.Position` 跳到帧偏移。
3. 只读取当前帧的顶点和索引。
4. 校验帧长度和数据头。

运行时不会缓存 1001 个 Mesh，也不会把完整二进制文件读入内存。

### 5.2 动态陆地网格

`DynamicLandRenderer` 持有一个 `IndexFormat.UInt32` 的可复用 Mesh。切帧时执行：

- 清空现有 Mesh 数据。
- 写入当前帧顶点和索引。
- 复用固定球体 Bounds，跳过不必要的 Bounds 重算。
- 上传 Mesh，同时保留 CPU 端数据供后续切帧复用。

### 5.3 时间轴与交互

`EarthDemoController` 负责：

- 把时间轴值取整到 `1 Ma`。
- 调用动态陆地渲染器切换帧。
- 使用相机屏幕坐标轴计算拖动旋转。
- 处理滚轮缩放。
- 提供视角重置：将地理北极（数据坐标 `+Z`）对齐到屏幕正上方，并恢复默认相机距离；按钮和 `R` 键使用同一逻辑。
- 在底部显示年代、实际几何帧、顶点数和切帧耗时。

## 6. 渲染技术

### 6.1 海洋层

海洋使用 Unity 球体和 `Earth/DynamicOcean` Surface Shader：

- 当前深浅蓝根据球面方向做基础视觉渐变，尚不代表真实海深。
- 使用 Standard 光照模型和弱镜面反射，避免高光遮挡大陆。
- 通过少量环境发光保留暗部海洋颜色。

### 6.2 陆地层

陆地使用动态三角网格和 `Earth/DynamicLand` 顶点/片元 Shader：

- 顶点阶段再次归一化单位球位置。
- `_SurfaceOffset = 1.003`，让陆地略高于海洋表面。
- 使用归一化球面方向作为平滑法线。
- 以绝对古纬度和球面连续三维 FBM 生成森林、草地、旱地、沙漠、岩石和冰雪自然色。
- 程序纹理没有经纬度接缝，并随大陆所在古纬度改变外观。
- 当前生物群落与高地纹理只用于视觉，不代表真实古气候或古地形数据。
- 渲染队列位于海洋之后，并使用深度 Offset 减少表面闪烁。

大陆内部 `250 km` 球面细分保证三角形内部不会因跨度过大而落到海洋球之后。

### 6.3 大气层

大气层使用略大于地球的透明球体和 `Earth/Atmosphere` Shader：

- 正面剔除，只绘制背面形成边缘光。
- 使用视线方向与法线夹角计算 Fresnel 风格的轮廓强度。
- 关闭深度写入并使用透明混合。

## 7. 现代参照与离线校验

`Tools/rasterize_natural_earth.py` 把 Natural Earth land Shapefile 栅格化为现代陆地参考掩膜。

`Tools/generate_paleogeography.py` 可以把 MULLER2022 重建结果栅格化，并在 0 Ma 使用球面面积权重计算与现代参考的：

- Intersection over Union。
- 全球面积不一致比例。
- 球面陆地面积占比。

这条栅格管线用于数据校验和表现参考，不参与动态几何渲染。

Unity 侧的 `EarthDemoPlayValidation` 会：

- 验证 `1 Ma` 时间精度。
- 遍历全部几何帧并检查非空。
- 检查动态 Mesh 顶点数量。
- 验证横向拖动后纵向旋转仍使用相机屏幕右轴。
- 生成 0 Ma 和抽样年代截图到 `.local/validation`。

## 8. 当前表现边界

- 年代之间按 `1 Ma` 离散切换，没有连续形状插值。
- 陆地高程和海洋深度当前只参与 Shader 像素着色，不改变球面顶点位置。
- 古海深包含大尺度海盆/大陆架近似，不包含洋流、海沟、海山、LIP、沉积物和动态地形。
- 当前没有单独渲染板块边界、板块 ID 或地质属性。
- Natural Earth 只校验现代轮廓，古地球准确性由 MULLER2022 模型及统一管线决定。

## 9. 可重建产物与版本管理

以下内容不进入 Git：

- `Data/processed`
- `Assets/StreamingAssets/EarthGeometry`
- 生成的参考纹理
- `.local` 中的日志、截图和临时数据

Git 保存离线管线源码、Unity 源码与场景、Shader、原始数据压缩包和数据来源清单。这样可以从固定版本与固定 SHA-256 的输入完整重建运行时数据。
