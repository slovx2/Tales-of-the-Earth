using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

[InitializeOnLoad]
public static class EarthDemoStartup
{
    public const string DemoScenePath = "Assets/Scenes/EarthDemo.unity";

    static EarthDemoStartup()
    {
        if (!Application.isBatchMode)
        {
            EditorApplication.delayCall += OpenDemoSceneWhenProjectIsEmpty;
        }
    }

    [MenuItem("Earth Demo/Open Demo Scene")]
    public static void OpenDemoScene()
    {
        if (AssetDatabase.LoadAssetAtPath<SceneAsset>(DemoScenePath) == null)
        {
            Debug.LogError($"找不到演示场景：{DemoScenePath}");
            return;
        }

        if (EditorApplication.isPlaying)
        {
            EditorApplication.isPlaying = false;
        }
        EditorSceneManager.OpenScene(DemoScenePath, OpenSceneMode.Single);
        Selection.activeObject = AssetDatabase.LoadAssetAtPath<SceneAsset>(DemoScenePath);
        Debug.Log($"已打开 Earth Evolution 演示场景：{DemoScenePath}");
    }

    private static void OpenDemoSceneWhenProjectIsEmpty()
    {
        if (EditorApplication.isPlayingOrWillChangePlaymode)
        {
            return;
        }

        Scene activeScene = SceneManager.GetActiveScene();
        if (string.IsNullOrEmpty(activeScene.path))
        {
            OpenDemoScene();
        }
    }
}
