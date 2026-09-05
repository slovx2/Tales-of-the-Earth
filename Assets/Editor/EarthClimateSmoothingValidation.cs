using System;
using System.IO;
using UnityEditor;
using UnityEngine;

/// <summary>在真实 GPU 上检查分类插值、海岸有效性与经纬边界，并截图比较同一场景。</summary>
[InitializeOnLoad]
public static class EarthClimateSmoothingValidation
{
    private const string Output = ".local/validation/land-texture";
    private const string Session = "EarthClimate.SmoothingValidation";
    private static int frames;
    private static double nextPoll;

    static EarthClimateSmoothingValidation() { EditorApplication.update += Update; }

    [MenuItem("Earth Demo/Validate Climate Smoothing")]
    public static void Run()
    {
        Directory.CreateDirectory(Output);
        if (File.Exists(Output + "/failure.txt")) File.Delete(Output + "/failure.txt");
        ValidateSamples();
        frames = 0;
        SessionState.SetBool(Session, true);
        if (!EditorApplication.isPlaying) EditorApplication.EnterPlaymode();
    }

    private static void Update()
    {
        try
        {
            if (!EditorApplication.isCompiling && EditorApplication.timeSinceStartup > nextPoll)
            {
                nextPoll = EditorApplication.timeSinceStartup + 1;
                if (File.Exists(Output + "/request.txt"))
                {
                    string command = File.ReadAllText(Output + "/request.txt").Trim();
                    File.Delete(Output + "/request.txt");
                    if (command != "validate") throw new InvalidOperationException("未知气候验收命令");
                    Run();
                }
            }
            if (!SessionState.GetBool(Session, false) || !EditorApplication.isPlaying || ++frames < 20) return;
            CaptureScene();
            SessionState.SetBool(Session, false);
            EditorApplication.isPlaying = false;
        }
        catch (Exception exception)
        {
            SessionState.SetBool(Session, false);
            Directory.CreateDirectory(Output);
            File.WriteAllText(Output + "/failure.txt", exception.ToString());
            Debug.LogException(exception);
        }
    }

    private static void Require(bool condition, string message)
    { if (!condition) throw new InvalidOperationException("气候平滑验收失败：" + message); }

    private static void ValidateSamples()
    {
        Shader shader = Shader.Find("Hidden/Earth/ClimateSamplingTest");
        Require(shader != null && !ShaderUtil.ShaderHasError(shader), "采样 Shader 编译");
        Material material = new Material(shader);
        Texture2D classes = new Texture2D(2, 2, TextureFormat.RGBA32, false, true) { filterMode = FilterMode.Point };
        Texture2D fields = new Texture2D(2, 2, TextureFormat.RGBAFloat, false, true) { filterMode = FilterMode.Point };
        RenderTexture target = new RenderTexture(1, 1, 0, RenderTextureFormat.ARGBFloat, RenderTextureReadWrite.Linear);
        Texture2D readback = new Texture2D(1, 1, TextureFormat.RGBAFloat, false, true);
        RenderTexture previous = RenderTexture.active;
        try
        {
            target.Create();
            Color32 forest = new Color32(13, 13, 0, 255), desert = new Color32(9, 9, 0, 255);
            classes.SetPixels32(new[] { forest, desert, forest, desert }); classes.Apply();
            fields.SetPixels(new[] { new Color(24, 3000, 50, 1), new Color(40, 100, 2, 1),
                new Color(24, 3000, 50, 1), new Color(40, 100, 2, 1) }); fields.Apply();
            material.SetTexture("_ClimateClassTex", classes); material.SetTexture("_ClimateTex", fields);
            material.SetVector("_ClimateGrid", new Vector4(2, 2, .5f, .5f));
            Func<float, float, Color> sample = (u, v) =>
            {
                material.SetVector("_ProbeUv", new Vector4(u, v, 0, 0));
                Graphics.Blit(null, target, material);
                RenderTexture.active = target;
                readback.ReadPixels(new Rect(0, 0, 1, 1), 0, 0); readback.Apply();
                return readback.GetPixel(0, 0);
            };
            Color middle = sample(.5f, .5f);
            Require(Mathf.Abs(middle.r - .5f) < .005f && Mathf.Abs(middle.g - .5f) < .005f && middle.b < .005f,
                "先解码颜色再插值，不生成中间编号对应的蓝色类别");
            Color left = sample(.4999f, .5f), right = sample(.5001f, .5f);
            Require(Mathf.Abs(left.r - right.r) < .002f, "类别边界连续");
            Color seamLeft = sample(-.0001f, .5f), seamRight = sample(.0001f, .5f);
            Require(Mathf.Abs(seamLeft.r - seamRight.r) < .002f, "日期变更线首尾连续");
            foreach (float sharpness in new[] { 1.8f, 2.4f, 3f })
            {
                material.SetFloat("_ClimateBoundarySharpness", sharpness);
                Color quarter = sample(.375f, .5f);
                Require(quarter.r < .2f && quarter.g > .8f, "锐化后过渡区收窄");
                Require(Mathf.Abs(sample(.4999f, .5f).r - sample(.5001f, .5f).r) < .002f,
                    "锐化后仍保持连续边界");
                Require(Mathf.Abs(sample(-.0001f, .5f).r - sample(.0001f, .5f).r) < .002f,
                    "锐化后经度接缝连续");
                for (int i = 0; i <= 16; i++)
                {
                    Color value = sample(.25f + i / 32f, .5f);
                    Require(value.r >= 0f && value.g >= 0f && value.b < .005f &&
                        Mathf.Abs(value.r + value.g - 1f) < .005f, "锐化保持已有色域，不产生亮暗晕边");
                }
            }
            material.SetFloat("_ClimateBoundarySharpness", 1.8f);
            classes.SetPixels32(new[] { forest, forest, forest, desert }); classes.Apply();
            Color singleForest = sample(.5f, .5f);
            Color32 otherForest = new Color32(6, 6, 0, 255);
            classes.SetPixels32(new[] { forest, otherForest, otherForest, desert }); classes.Apply();
            Require(Mathf.Abs(singleForest.r - sample(.5f, .5f).r) < .005f,
                "同色森林子类归并后锐化结果一致");
            // 无效海洋格故意保留极端连续值，确保归一化不会让它污染陆地。
            classes.SetPixels32(new[] { forest, new Color32(), forest, new Color32() }); classes.Apply();
            Color coast = sample(.5f, .5f);
            Require(coast.g > .995f && coast.r < .005f && coast.b < .005f, "海岸忽略无效类别");
            material.SetFloat("_OutputFields", 1);
            Color coastFields = sample(.5f, .5f);
            Require(Mathf.Abs(coastFields.g * 4096 - 3000) < 1f, "连续气候值保留范围并忽略海洋");
            material.SetFloat("_OutputFields", 0);
            classes.SetPixels32(new[] { forest, forest, desert, desert }); classes.Apply();
            Require(sample(.5f, -.1f).g > .995f && sample(.5f, 1.1f).r > .995f, "两极夹边，不跨半球取样");
            classes.SetPixels32(new Color32[4]); classes.Apply();
            Color absent = sample(.5f, .5f);
            Require(absent.a == 0f && absent.r == 0f && !float.IsNaN(absent.g), "全部无效时安全回退");
            File.WriteAllText(Output + "/gpu-tests.txt", "PASS\n颜色插值、边界连续、经度接缝、海岸无效样本、连续变量范围、两极夹边、全部无效回退；锐化收窄过渡、三档强度连续性与色域检查、同色子类归并。\n");
        }
        finally
        {
            RenderTexture.active = previous; target.Release();
            UnityEngine.Object.DestroyImmediate(material); UnityEngine.Object.DestroyImmediate(classes);
            UnityEngine.Object.DestroyImmediate(fields); UnityEngine.Object.DestroyImmediate(target);
            UnityEngine.Object.DestroyImmediate(readback);
        }
    }

    private static void CaptureScene()
    {
        EarthDemoController controller = UnityEngine.Object.FindObjectOfType<EarthDemoController>();
        DynamicLandRenderer land = UnityEngine.Object.FindObjectOfType<DynamicLandRenderer>();
        Require(controller != null && land != null, "演示场景就绪");
        GameObject events = GameObject.Find("EarthEventLayer");
        bool eventsActive = events != null && events.activeSelf;
        if (events != null) events.SetActive(false);
        Material material = land.GetComponent<Renderer>().sharedMaterial;
        Shader current = material.shader;
        float originalSharpness = material.GetFloat("_ClimateBoundarySharpness");
        Directory.CreateDirectory(Output + "/sharpen");
        Require(!ShaderUtil.ShaderHasError(current), "地表 Shader 编译");
        Camera camera = controller.ViewCamera;
        RenderTexture previous = camera.targetTexture;
        float aspect = camera.aspect;
        RenderTexture target = new RenderTexture(1920, 1080, 24) { antiAliasing = 2 };
        Texture2D readback = new Texture2D(1920, 1080, TextureFormat.RGB24, false);
        RenderTexture previousActive = RenderTexture.active;
        try
        {
            target.Create(); camera.targetTexture = target; camera.aspect = 1920f / 1080f;
            foreach (float age in new[] { 0f, 66f, 540f, 541f })
            {
                controller.SetTimeMa(age); controller.ResetView();
                // 固定北美近景，所有年代和前后版本使用相同坐标、相机与几何。
                float latitude = 40f * Mathf.Deg2Rad, longitude = -90f * Mathf.Deg2Rad;
                Vector3 site = new Vector3(Mathf.Cos(latitude) * Mathf.Cos(longitude),
                    -Mathf.Cos(latitude) * Mathf.Sin(longitude), Mathf.Sin(latitude));
                Vector3 normal = (-camera.transform.forward * .75f + camera.transform.up * .6f).normalized;
                Vector3 north = Vector3.ProjectOnPlane(Vector3.forward, site).normalized;
                controller.EarthTransform.rotation = Quaternion.LookRotation(normal, camera.transform.up) *
                    Quaternion.Inverse(Quaternion.LookRotation(site, north));
                float radius = controller.EarthTransform.lossyScale.x * .5f;
                camera.transform.position = controller.EarthTransform.position + normal * radius -
                    camera.transform.forward * radius * 1.6f;
                foreach (float sharpness in new[] { 1f, 2.4f, 3f })
                {
                    material.SetFloat("_ClimateBoundarySharpness", sharpness);
                    camera.Render(); RenderTexture.active = target;
                    readback.ReadPixels(new Rect(0, 0, 1920, 1080), 0, 0); readback.Apply();
                    File.WriteAllBytes(Output + "/sharpen/" + age + "Ma-sharpness-" +
                        sharpness.ToString("F1", System.Globalization.CultureInfo.InvariantCulture) + ".png",
                        readback.EncodeToPNG());
                }
            }
            Debug.Log("CLIMATE_SMOOTHING_VALIDATION_OK：GPU 专项与四个年代同视角截图完成。");
        }
        finally
        {
            material.SetFloat("_ClimateBoundarySharpness", originalSharpness);
            camera.targetTexture = previous; camera.aspect = aspect; RenderTexture.active = previousActive;
            target.Release(); UnityEngine.Object.DestroyImmediate(target); UnityEngine.Object.DestroyImmediate(readback);
            if (events != null) events.SetActive(eventsActive);
        }
    }
}
