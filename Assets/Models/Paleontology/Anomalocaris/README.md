# Anomalocaris canadensis v02

中等细节、静态展示模型，基于布尔吉斯页岩资料制作。v02 增加统一平滑/倒角处理，并在 FBX 中保留解剖层级。模型长度参数以 0.25 m 完整标本为基准，预留 0.25–1.0 m 的缩放范围。

## 文件

- `Anomalocaris_canadensis_v01.blend`：可编辑 Blender 源文件
- `Generated/Anomalocaris_canadensis_v01.fbx`：Unity 可导入模型
- `Generated/anomalocaris_turntable.png`：首轮三分之四角度检查渲染
- `generate_anomalocaris.py`：可重复执行的参数化生成脚本

## Unity 展示场景

- `Assets/Scenes/AnomalocarisPreview.unity`：奇虾独立预览场景，包含专用相机和灯光。
- `Assets/Scenes/EarthDemo.unity`：地球演化主场景，不放置奇虾实例或临时几何体，避免影响原有展示。

## 结构

模型集合包括身体、16 对游泳叶片、鳃状小片、头部、柄眼、14 节捕食附肢、三叉状刺、三辐口器和尾扇。FBX 根节点为 `Anomalocaris_Rig`，下分 7 个解剖分组，便于 Unity 中单独调整。

## 资料与授权

- Royal Ontario Museum, [Anomalocaris canadensis](https://burgess-shale.rom.on.ca/fossils/anomalocaris-canadensis/)：形态、标本、尺寸和官方复原参考。ROM 图片仅作参考，未打包进资产。
- Daley & Edgecombe (2014), [Morphology of Anomalocaris canadensis from the Burgess Shale](https://doi.org/10.1666/13-067)：形态综合修订。
- De Vivo, Lautenschlager & Vinther (2021), [Three-dimensional modelling, disparity and ecology of the first Cambrian apex predators](https://doi.org/10.1098/rspb.2021.1176)：数字附肢建模与功能分析。
- Wikimedia Commons 的公开化石照片可作参考；如将其复制进项目，需保留原页面要求的 CC BY/CC BY-SA 署名信息。

体色、软组织厚度、游泳姿态和部分口器功能属于复原推测，不能直接从化石确定。
