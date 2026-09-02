using System;
using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

[InitializeOnLoad]
public static class EarthDemoPlayValidation
{
    private const string SessionKey = "EarthDemo.PlayValidation";
    private static int framesAfterPlay;

    static EarthDemoPlayValidation()
    {
        if (SessionState.GetBool(SessionKey, false))
        {
            EditorApplication.playModeStateChanged += OnPlayModeChanged;
            EditorApplication.update += ValidateWhilePlaying;
        }
    }

    [MenuItem("Earth Demo/Run Play Validation")]
    public static void Run()
    {
        SessionState.SetBool(SessionKey, true);
        framesAfterPlay = 0;
        EditorApplication.playModeStateChanged -= OnPlayModeChanged;
        EditorApplication.playModeStateChanged += OnPlayModeChanged;
        EditorApplication.update -= ValidateWhilePlaying;
        EditorApplication.update += ValidateWhilePlaying;
        EditorSceneManager.OpenScene(EarthDemoStartup.DemoScenePath);
        EditorApplication.EnterPlaymode();
    }

    private static void OnPlayModeChanged(PlayModeStateChange state)
    {
        if (state == PlayModeStateChange.EnteredPlayMode)
        {
            framesAfterPlay = 0;
        }
    }

    private static void ValidateWhilePlaying()
    {
        if (!SessionState.GetBool(SessionKey, false) || !EditorApplication.isPlaying || ++framesAfterPlay < 10)
        {
            return;
        }

        try
        {
            EarthDemoController controller = UnityEngine.Object.FindObjectOfType<EarthDemoController>();
            DynamicLandRenderer land = UnityEngine.Object.FindObjectOfType<DynamicLandRenderer>();
            DynamicTerrainRenderer terrain = UnityEngine.Object.FindObjectOfType<DynamicTerrainRenderer>();
            DynamicRegionHighlighter regions = UnityEngine.Object.FindObjectOfType<DynamicRegionHighlighter>();
            Require(controller != null, "Play Mode 中找不到 EarthDemoController");
            Require(land != null, "Play Mode 中找不到 DynamicLandRenderer");
            Require(terrain != null && terrain.Width == 360 && terrain.Height == 180,
                    "Play Mode 中动态高度场未加载");
            Require(regions != null, "Play Mode 中动态区域未加载");
            Require(land.FrameResolutionMa > 0f, "几何帧时间分辨率无效");
            Require(Mathf.Approximately(regions.FrameResolutionMa, 1f), "区域帧没有保持 1 Ma 精度");
            Require(Mathf.Approximately(regions.MinimumAreaKm2, 250000f), "区域面积阈值不是 25 万 km²");
            Require(regions.ActiveRegionCount == 149, "0 Ma 过滤后的区域数量不是 149");
            Require(regions.LocalizedRegionCount == 642, "中文区域名称没有覆盖全部 642 个原始名称");
            Require(land.CoastlineResolutionKm > 0f, "海岸线空间精度无效");
            Material landMaterial = land.GetComponent<Renderer>().sharedMaterial;
            Require(landMaterial != null && landMaterial.HasProperty("_BiomeScale"),
                    "Play Mode 未加载卫星风格陆地材质");
            Require(landMaterial.GetFloat("_BiomeScale") > 0f &&
                    landMaterial.GetFloat("_DetailStrength") > 0f,
                    "卫星风格陆地材质参数无效");
            Require(landMaterial.GetTexture("_TerrainTex") != null,
                    "Play Mode 中陆地材质未绑定高度场");
            Renderer oceanRenderer = GameObject.Find("Earth").GetComponent<Renderer>();
            Require(oceanRenderer.sharedMaterial.GetTexture("_TerrainTex") != null,
                    "Play Mode 中海洋材质未绑定海深场");

            controller.SetTimeMa(7.4f);
            Require(Mathf.Approximately(controller.CurrentTimeMa, 7f), "时间轴没有保持 1 Ma 精度");
            Require(Mathf.Approximately(controller.ActiveFrameTimeMa, 7f), "7 Ma 没有加载对应的 1 Ma 几何帧");
            Require(Mathf.Approximately(terrain.ActiveFrameTimeMa, 7f), "7 Ma 没有加载对应的地形帧");
            Require(Mathf.Approximately(regions.ActiveFrameTimeMa, 7f), "7 Ma 没有加载对应的区域帧");

            controller.SetTimeMa(0f);
            Require(regions.TryGetRepresentativeDirection(out Vector3 representative),
                    "0 Ma 区域缺少代表点");
            Require(regions.UpdateHoverAtLocalDirection(representative), "代表点没有命中区域");
            string hoveredName = regions.HoveredRegionName;
            string hoveredOriginalName = regions.HoveredRegionOriginalName;
            Require(!string.IsNullOrEmpty(hoveredName), "悬停区域名称为空");
            Require(ContainsChinese(hoveredName), "悬停区域未默认显示中文名");
            Require(!string.IsNullOrEmpty(hoveredOriginalName) && hoveredOriginalName != hoveredName,
                    "悬停区域没有同时保留英文原名和中文显示名");
            regions.SelectHoveredOrClear();
            Require(regions.SelectedRegionName == hoveredName, "点击选择没有保存悬停区域");
            Require(regions.SelectedRegionOriginalName == hoveredOriginalName,
                    "点击选择没有保存英文原名");
            controller.SetTimeMa(1f);
            Require(regions.SelectedRegionName == hoveredName, "同名区域没有跨年代延续选择");
            Require(regions.SelectedRegionOriginalName == hoveredOriginalName,
                    "英文原名没有跨年代延续选择");
            controller.SetTimeMa(0f);
            Vector3 facingDirection = (Camera.main.transform.position - controller.transform.position).normalized;
            controller.transform.rotation = Quaternion.FromToRotation(
                controller.transform.TransformDirection(representative), facingDirection) *
                controller.transform.rotation;
            Vector3 representativeWorld = controller.transform.TransformPoint(representative * 0.5f);
            Vector3 representativeScreen = Camera.main.WorldToScreenPoint(representativeWorld);
            regions.UpdateHover(Camera.main, representativeScreen);
            Require(regions.HoveredRegionName == hoveredName, "屏幕射线没有命中预期区域");
            CapturePlayFrame(Camera.main, ".local/validation/earth_dynamic_geometry_0000Ma.png");

            for (float timeMa = 0f; timeMa <= land.MaxTimeMa; timeMa += land.FrameResolutionMa)
            {
                controller.SetTimeMa(timeMa);
                Require(land.ActiveVertexCount > 0 && land.ActiveTriangleCount > 0,
                        $"{timeMa:0} Ma 动态网格为空");
            }

            float captureTime = Mathf.Round(Mathf.Min(200f, land.MaxTimeMa * 0.5f));
            controller.SetTimeMa(captureTime);
            MeshFilter meshFilter = land.GetComponent<MeshFilter>();
            Require(meshFilter != null && meshFilter.sharedMesh != null, "运行时动态陆地 Mesh 无效");
            Require(meshFilter.sharedMesh.vertexCount == land.ActiveVertexCount, "运行时 Mesh 顶点数不同步");
            CapturePlayFrame(Camera.main, ".local/validation/earth_dynamic_geometry.png");

            controller.RotateByScreenDelta(new Vector2(700f, 0f));
            Quaternion beforeVerticalDrag = controller.transform.rotation;
            controller.RotateByScreenDelta(new Vector2(0f, 100f));
            Quaternion verticalRotation = controller.transform.rotation * Quaternion.Inverse(beforeVerticalDrag);
            verticalRotation.ToAngleAxis(out float verticalAngle, out Vector3 verticalAxis);
            float axisAlignment = Mathf.Abs(Vector3.Dot(verticalAxis.normalized, Camera.main.transform.right.normalized));
            Require(Mathf.Abs(Mathf.DeltaAngle(verticalAngle, 35f)) < 0.1f, "纵向拖动旋转角度不连续");
            Require(axisAlignment > 0.999f, "横拖后纵向旋转轴未保持在相机屏幕右轴");

            controller.ResetView();
            Vector3 centerScreen = Camera.main.WorldToScreenPoint(controller.transform.position);
            Vector3 northScreen = Camera.main.WorldToScreenPoint(
                controller.transform.position + controller.transform.TransformDirection(Vector3.forward));
            Vector2 northDelta = new Vector2(northScreen.x - centerScreen.x, northScreen.y - centerScreen.y);
            Require(northDelta.y > 0f && Mathf.Abs(northDelta.x) < northDelta.y * 0.01f,
                    "重置视角后北极没有朝向屏幕正上方");

            Debug.Log(
                $"EARTH_DEMO_PLAY_VALIDATION_OK：{land.FrameResolutionMa:0} Ma/帧，" +
                $"海岸线 {land.CoastlineResolutionKm:0} km，平均切帧 {land.AverageLoadMilliseconds:0.0} ms，" +
                $"最大 {land.MaximumLoadMilliseconds:0.0} ms，动态网格、区域选择和拖动均通过。");
            Finish(0);
        }
        catch (Exception exception)
        {
            Debug.LogException(exception);
            Finish(1);
        }
    }

    private static void CapturePlayFrame(Camera camera, string outputPath)
    {
        Require(camera != null, "Play Mode 缺少主相机");
        RenderTexture target = new RenderTexture(1280, 720, 24, RenderTextureFormat.ARGB32);
        Texture2D screenshot = new Texture2D(1280, 720, TextureFormat.RGB24, false);
        camera.targetTexture = target;
        camera.Render();
        RenderTexture.active = target;
        screenshot.ReadPixels(new Rect(0, 0, 1280, 720), 0, 0);
        screenshot.Apply();
        string outputDirectory = Path.GetDirectoryName(outputPath);
        if (!string.IsNullOrEmpty(outputDirectory))
        {
            Directory.CreateDirectory(outputDirectory);
        }
        File.WriteAllBytes(outputPath, screenshot.EncodeToPNG());
        camera.targetTexture = null;
        RenderTexture.active = null;
        UnityEngine.Object.Destroy(screenshot);
        target.Release();
        UnityEngine.Object.Destroy(target);
    }

    private static void Finish(int exitCode)
    {
        SessionState.SetBool(SessionKey, false);
        EditorApplication.update -= ValidateWhilePlaying;
        EditorApplication.playModeStateChanged -= OnPlayModeChanged;
        EditorApplication.ExitPlaymode();
        EditorApplication.delayCall += () => EditorApplication.Exit(exitCode);
    }

    private static void Require(bool condition, string message)
    {
        if (!condition)
        {
            throw new InvalidOperationException(message);
        }
    }

    private static bool ContainsChinese(string value)
    {
        foreach (char character in value)
        {
            if (character >= '\u4e00' && character <= '\u9fff')
            {
                return true;
            }
        }
        return false;
    }
}
