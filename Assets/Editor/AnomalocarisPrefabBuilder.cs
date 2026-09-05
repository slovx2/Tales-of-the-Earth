using System.IO;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;

[InitializeOnLoad]
public static class AnomalocarisPrefabBuilder
{
    private const string FbxPath = "Assets/Models/Paleontology/Anomalocaris/Generated/Anomalocaris_canadensis_v01.fbx";
    private const string PrefabPath = "Assets/Models/Paleontology/Anomalocaris/Generated/Anomalocaris_canadensis_v01.prefab";

    static AnomalocarisPrefabBuilder()
    {
        EditorApplication.delayCall += EnsureAsset;
    }

    [MenuItem("Earth Demo/Build Anomalocaris Prefab")]
    public static void EnsureAsset()
    {
        if (!File.Exists(Path.Combine(Directory.GetCurrentDirectory(), FbxPath)))
            return;

        AssetDatabase.ImportAsset(FbxPath, ImportAssetOptions.ForceUpdate);
        var importer = AssetImporter.GetAtPath(FbxPath) as ModelImporter;
        if (importer != null)
        {
            importer.importCameras = false;
            importer.importLights = false;
            importer.globalScale = 1.0f;
            importer.SaveAndReimport();
        }

        var source = AssetDatabase.LoadAssetAtPath<GameObject>(FbxPath);
        if (source == null)
            return;

        var instance = (GameObject)PrefabUtility.InstantiatePrefab(source);
        instance.name = "Anomalocaris_canadensis_v01";
        ApplyMaterials(instance);
        // Keep the imported hierarchy intact; LODs can be authored later from the source blend.

        PrefabUtility.SaveAsPrefabAsset(instance, PrefabPath);
        Object.DestroyImmediate(instance);
        AssetDatabase.SaveAssets();
        AssetDatabase.Refresh();
        Debug.Log("Anomalocaris asset ready: " + PrefabPath);
    }
    private static void ApplyMaterials(GameObject root)
    {
        var materialFolder = "Assets/Models/Paleontology/Anomalocaris/Materials";
        if (!AssetDatabase.IsValidFolder(materialFolder))
            AssetDatabase.CreateFolder("Assets/Models/Paleontology/Anomalocaris", "Materials");
        var renderers = root.GetComponentsInChildren<Renderer>(true);
        foreach (var renderer in renderers)
        {
            var sourceMaterials = renderer.sharedMaterials;
            var mapped = new Material[sourceMaterials.Length];
            for (var i = 0; i < sourceMaterials.Length; i++)
            {
                var source = sourceMaterials[i];
                var name = source == null ? renderer.gameObject.name : source.name;
                var material = GetOrCreateMaterial(materialFolder, name);
                mapped[i] = material;
            }
            renderer.sharedMaterials = mapped;
        }
    }

    private static Material GetOrCreateMaterial(string folder, string sourceName)
    {
        var lower = sourceName.ToLowerInvariant();
        var safe = sourceName.Replace("/", "_").Replace("\\", "_");
        var path = folder + "/" + safe + "_Unity.mat";
        var material = AssetDatabase.LoadAssetAtPath<Material>(path);
        if (material == null)
        {
            material = new Material(Shader.Find("Standard"));
            AssetDatabase.CreateAsset(material, path);
        }
        if (lower.Contains("eye")) material.color = new Color(0.01f, 0.025f, 0.03f, 1f);
        else if (lower.Contains("mouth")) material.color = new Color(0.05f, 0.012f, 0.008f, 1f);
        else if (lower.Contains("tooth") || lower.Contains("spine")) material.color = new Color(0.72f, 0.42f, 0.16f, 1f);
        else if (lower.Contains("appendage") || lower.Contains("joint")) material.color = new Color(0.30f, 0.065f, 0.025f, 1f);
        else if (lower.Contains("flap") || lower.Contains("tail") || lower.Contains("plate")) material.color = new Color(0.40f, 0.22f, 0.07f, 1f);
        else if (lower.Contains("gill")) material.color = new Color(0.22f, 0.09f, 0.035f, 1f);
        else material.color = new Color(0.035f, 0.18f, 0.20f, 1f);
        material.SetFloat("_Glossiness", 0.32f);
        EditorUtility.SetDirty(material);
        return material;
    }

}

// Preview scene helper is kept in the same editor utility so the asset can be verified from Unity.
public static class AnomalocarisPreviewScene
{
    private const string PrefabPath = "Assets/Models/Paleontology/Anomalocaris/Generated/Anomalocaris_canadensis_v01.prefab";
    private const string ScenePath = "Assets/Scenes/AnomalocarisPreview.unity";

    [MenuItem("Earth Demo/Create Anomalocaris Preview Scene")]
    public static void CreatePreviewScene()
    {
        var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(PrefabPath);
        if (prefab == null)
        {
            Debug.LogError("Anomalocaris prefab not found: " + PrefabPath);
            return;
        }
        var scene = UnityEditor.SceneManagement.EditorSceneManager.NewScene(
            UnityEditor.SceneManagement.NewSceneSetup.EmptyScene,
            UnityEditor.SceneManagement.NewSceneMode.Single);
        var instance = (GameObject)PrefabUtility.InstantiatePrefab(prefab);
        instance.name = "Anomalocaris_canadensis_v01";
        instance.transform.position = Vector3.zero;

        var cameraObject = new GameObject("PreviewCamera");
        var camera = cameraObject.AddComponent<Camera>();
        camera.transform.position = new Vector3(0.42f, -0.42f, 0.26f);
        camera.transform.LookAt(new Vector3(0f, 0f, 0f));
        camera.fieldOfView = 35f;
        sceneCamera(camera);

        RenderSettings.ambientMode = AmbientMode.Flat;
        RenderSettings.ambientLight = new Color(0.22f, 0.27f, 0.32f, 1f);
        RenderSettings.fog = false;
        var lightObject = new GameObject("PreviewKeyLight");
        var light = lightObject.AddComponent<Light>();
        light.type = LightType.Point;
        light.intensity = 7.0f;
        light.range = 2.0f;
        light.transform.position = new Vector3(0.20f, -0.25f, 0.30f);
        var fillObject = new GameObject("PreviewFillLight");
        var fill = fillObject.AddComponent<Light>();
        fill.type = LightType.Point;
        fill.intensity = 3.0f;
        fill.range = 1.5f;
        fill.transform.position = new Vector3(-0.18f, 0.20f, 0.12f);

        UnityEditor.SceneManagement.EditorSceneManager.SaveScene(scene, ScenePath);
        Selection.activeObject = instance;
        Debug.Log("Anomalocaris preview scene ready: " + ScenePath);
    }

    private static void sceneCamera(Camera camera)
    {
        UnityEngine.SceneManagement.SceneManager.SetActiveScene(camera.gameObject.scene);
        camera.tag = "MainCamera";
    }
}

public static class EarthDemoTemporaryCleanup
{
    private const string EarthDemoPath = "Assets/Scenes/EarthDemo.unity";

    [MenuItem("Earth Demo/Clean Earth Demo Temporary Objects")]
    public static void CleanEarthDemo()
    {
        var scene = UnityEditor.SceneManagement.EditorSceneManager.OpenScene(
            EarthDemoPath, UnityEditor.SceneManagement.OpenSceneMode.Single);
        foreach (var root in scene.GetRootGameObjects())
        {
            if (root.name == "Cylinder" || root.name.StartsWith("Anomalocaris"))
                Object.DestroyImmediate(root);
        }
        UnityEditor.SceneManagement.EditorSceneManager.SaveScene(scene, EarthDemoPath);
        Debug.Log("EarthDemo temporary objects cleaned; Anomalocaris remains in its preview scene.");
    }
}
