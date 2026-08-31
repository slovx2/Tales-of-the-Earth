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
            Require(controller != null, "Play Mode 中找不到 EarthDemoController");
            Require(land != null, "Play Mode 中找不到 DynamicLandRenderer");
            Require(land.FrameResolutionMa > 0f, "几何帧时间分辨率无效");
            Require(land.CoastlineResolutionKm > 0f, "海岸线空间精度无效");

            controller.SetTimeMa(7.4f);
            Require(Mathf.Approximately(controller.CurrentTimeMa, 7f), "时间轴没有保持 1 Ma 精度");
            Require(Mathf.Approximately(controller.ActiveFrameTimeMa, 7f), "7 Ma 没有加载对应的 1 Ma 几何帧");

            controller.SetTimeMa(0f);
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

            Debug.Log(
                $"EARTH_DEMO_PLAY_VALIDATION_OK：{land.FrameResolutionMa:0} Ma/帧，" +
                $"海岸线 {land.CoastlineResolutionKm:0} km，平均切帧 {land.AverageLoadMilliseconds:0.0} ms，" +
                $"最大 {land.MaximumLoadMilliseconds:0.0} ms，动态网格和拖动均通过。");
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
}
