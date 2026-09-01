using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

public static class EarthDemoBuilder
{
    [MenuItem("Earth Demo/Build Demo Scene")]
    public static void Build()
    {
        const string datasetPath = "Assets/StreamingAssets/EarthGeometry/land_frames.bin";
        if (!File.Exists(datasetPath))
        {
            throw new FileNotFoundException(
                "缺少动态几何数据，请先运行 uv run python Tools/build_runtime_geometry.py",
                datasetPath);
        }

        Directory.CreateDirectory("Assets/Scenes");
        EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);

        GameObject cameraObject = new GameObject("Main Camera");
        Camera camera = cameraObject.AddComponent<Camera>();
        cameraObject.tag = "MainCamera";
        camera.clearFlags = CameraClearFlags.SolidColor;
        camera.backgroundColor = new Color(0.005f, 0.008f, 0.02f);
        camera.fieldOfView = 42f;
        camera.transform.position = new Vector3(0f, 0.2f, -6.2f);
        camera.transform.LookAt(new Vector3(0f, 0.12f, 0f));

        GameObject lightObject = new GameObject("Sun Light");
        Light light = lightObject.AddComponent<Light>();
        light.type = LightType.Directional;
        light.intensity = 1.2f;
        light.color = new Color(1f, 0.95f, 0.84f);
        light.transform.rotation = Quaternion.Euler(30f, -55f, 0f);

        GameObject earth = GameObject.CreatePrimitive(PrimitiveType.Sphere);
        earth.name = "Earth";
        earth.transform.localScale = Vector3.one * 2.35f;
        earth.transform.rotation = Quaternion.Euler(0f, 25f, -8f);

        Shader oceanShader = Shader.Find("Earth/DynamicOcean");
        if (oceanShader == null)
        {
            throw new FileNotFoundException("找不到 Earth/DynamicOcean Shader");
        }
        Material oceanMaterial = new Material(oceanShader) { name = "Dynamic Earth Ocean" };
        oceanMaterial.SetColor("_DeepColor", new Color(0.01f, 0.08f, 0.24f, 1f));
        oceanMaterial.SetColor("_ShallowColor", new Color(0.025f, 0.28f, 0.62f, 1f));
        oceanMaterial.SetFloat("_Smoothness", 0.48f);
        earth.GetComponent<Renderer>().sharedMaterial = oceanMaterial;

        GameObject land = new GameObject("Dynamic Land");
        land.transform.SetParent(earth.transform, false);
        // Unity 内置 Sphere 的半径是 0.5，运行时几何使用单位球坐标。
        land.transform.localScale = Vector3.one * 0.5f;
        land.AddComponent<MeshFilter>();
        MeshRenderer landMeshRenderer = land.AddComponent<MeshRenderer>();
        Shader landShader = Shader.Find("Earth/DynamicLand");
        if (landShader == null)
        {
            throw new FileNotFoundException("找不到 Earth/DynamicLand Shader");
        }
        Material landMaterial = new Material(landShader) { name = "Dynamic Earth Land" };
        landMaterial.SetColor("_ForestColor", new Color(0.055f, 0.19f, 0.07f, 1f));
        landMaterial.SetColor("_GrassColor", new Color(0.20f, 0.32f, 0.11f, 1f));
        landMaterial.SetColor("_DryGrassColor", new Color(0.43f, 0.36f, 0.16f, 1f));
        landMaterial.SetColor("_DesertColor", new Color(0.62f, 0.50f, 0.29f, 1f));
        landMaterial.SetColor("_RockColor", new Color(0.34f, 0.30f, 0.24f, 1f));
        landMaterial.SetColor("_SnowColor", new Color(0.86f, 0.90f, 0.89f, 1f));
        landMaterial.SetFloat("_BiomeScale", 3.8f);
        landMaterial.SetFloat("_DetailScale", 26f);
        landMaterial.SetFloat("_DetailStrength", 0.09f);
        landMeshRenderer.sharedMaterial = landMaterial;
        DynamicLandRenderer dynamicLand = land.AddComponent<DynamicLandRenderer>();

        DynamicTerrainRenderer dynamicTerrain = earth.AddComponent<DynamicTerrainRenderer>();
        SerializedObject serializedTerrain = new SerializedObject(dynamicTerrain);
        serializedTerrain.FindProperty("landRenderer").objectReferenceValue = landMeshRenderer;
        serializedTerrain.FindProperty("oceanRenderer").objectReferenceValue = earth.GetComponent<Renderer>();
        serializedTerrain.ApplyModifiedPropertiesWithoutUndo();

        GameObject atmosphere = GameObject.CreatePrimitive(PrimitiveType.Sphere);
        atmosphere.name = "Atmosphere Glow";
        atmosphere.transform.SetParent(earth.transform, false);
        atmosphere.transform.localScale = Vector3.one * 1.018f;
        Object.DestroyImmediate(atmosphere.GetComponent<Collider>());
        Shader atmosphereShader = Shader.Find("Earth/Atmosphere");
        if (atmosphereShader != null)
        {
            Material atmosphereMaterial = new Material(atmosphereShader) { name = "Earth Thin Atmosphere" };
            atmosphereMaterial.SetColor("_Color", new Color(0.12f, 0.42f, 1f, 1f));
            atmosphereMaterial.SetFloat("_Intensity", 0.72f);
            atmosphereMaterial.SetFloat("_Power", 3.2f);
            atmosphere.GetComponent<Renderer>().sharedMaterial = atmosphereMaterial;
        }

        EarthDemoController controller = earth.AddComponent<EarthDemoController>();
        SerializedObject serializedController = new SerializedObject(controller);
        serializedController.FindProperty("earth").objectReferenceValue = earth.transform;
        serializedController.FindProperty("landRenderer").objectReferenceValue = dynamicLand;
        serializedController.FindProperty("terrainRenderer").objectReferenceValue = dynamicTerrain;
        serializedController.ApplyModifiedPropertiesWithoutUndo();

        RenderSettings.ambientMode = UnityEngine.Rendering.AmbientMode.Trilight;
        RenderSettings.ambientSkyColor = new Color(0.03f, 0.05f, 0.12f);
        RenderSettings.ambientEquatorColor = new Color(0.01f, 0.02f, 0.05f);
        RenderSettings.ambientGroundColor = new Color(0.005f, 0.008f, 0.015f);

        EditorSceneManager.SaveScene(SceneManager.GetActiveScene(), "Assets/Scenes/EarthDemo.unity");
        EditorBuildSettings.scenes = new[]
        {
            new EditorBuildSettingsScene("Assets/Scenes/EarthDemo.unity", true),
        };
        AssetDatabase.SaveAssets();
        Debug.Log("Earth demo scene created with runtime geometry dataset.");
    }
}
