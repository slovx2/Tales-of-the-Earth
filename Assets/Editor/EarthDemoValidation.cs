using System;
using System.IO;
using UnityEditor.SceneManagement;
using UnityEngine;

public static class EarthDemoValidation
{
    public static void ValidateAndCapture()
    {
        EditorSceneManager.OpenScene(EarthDemoStartup.DemoScenePath);
        GameObject earth = GameObject.Find("Earth");
        GameObject land = GameObject.Find("Dynamic Land");
        Camera camera = Camera.main;
        EarthDemoController controller = earth != null ? earth.GetComponent<EarthDemoController>() : null;
        DynamicLandRenderer dynamicLand = land != null ? land.GetComponent<DynamicLandRenderer>() : null;
        Renderer oceanRenderer = earth != null ? earth.GetComponent<Renderer>() : null;
        Renderer landRenderer = land != null ? land.GetComponent<Renderer>() : null;

        Require(earth != null, "场景缺少 Earth 对象");
        Require(camera != null, "场景缺少 Main Camera");
        Require(controller != null, "Earth 缺少 EarthDemoController");
        Require(dynamicLand != null, "场景缺少 DynamicLandRenderer");
        Require(oceanRenderer != null && oceanRenderer.sharedMaterial != null, "Earth 缺少海洋材质");
        Require(oceanRenderer.sharedMaterial.shader.name == "Earth/DynamicOcean", "Earth 未使用动态海洋 Shader");
        Require(landRenderer != null && landRenderer.sharedMaterial != null, "动态陆地缺少材质");
        Require(landRenderer.sharedMaterial.shader.name == "Earth/DynamicLand", "陆地未使用动态几何 Shader");
        Require(landRenderer.sharedMaterial.HasProperty("_ForestColor"), "陆地材质缺少卫星风格森林色");
        Require(landRenderer.sharedMaterial.HasProperty("_BiomeScale"), "陆地材质缺少球面生物群落参数");
        Require(landRenderer.sharedMaterial.GetFloat("_DetailStrength") > 0f,
                "陆地卫星风格细节未启用");
        Require(GameObject.Find("Atmosphere Glow") != null, "场景缺少大气层");
        Require(File.Exists(Path.Combine(Application.streamingAssetsPath, "EarthGeometry/land_frames.bin")),
                "缺少运行时几何数据集");

        Debug.Log("EARTH_DEMO_VALIDATION_OK：动态几何场景、海洋/陆地 Shader 和数据集均通过。");
    }

    private static void Require(bool condition, string message)
    {
        if (!condition)
        {
            throw new InvalidOperationException(message);
        }
    }
}
