using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace EarthEvents.Editor
{
    [InitializeOnLoad]
    public static class EarthEventBuilder
    {
        [System.Serializable]
        private sealed class ReconstructedSite
        {
            public float[] reconstructed_latitude_longitude;
            public int plate_id;
        }
        private const string Root = "Assets/EarthEvents";
        static EarthEventBuilder() { EarthDemoBuilder.SceneCreated += Install; }

        [MenuItem("Earth Demo/Events/Install Impact Layer")]
        public static void InstallIntoOpenScene()
        {
            if (EditorApplication.isPlaying) throw new System.InvalidOperationException("请先退出 Play Mode。");
            EarthDemoController controller = Object.FindObjectOfType<EarthDemoController>();
            if (controller == null) throw new System.InvalidOperationException("当前场景没有地球控制器。");
            Install(controller);
            EditorSceneManager.MarkSceneDirty(controller.gameObject.scene);
            EditorSceneManager.SaveScene(controller.gameObject.scene);
        }

        private static Material MaterialAsset(string name, string shader, float glow = 0f)
        {
            string path = Root + "/Materials/" + name + ".mat";
            Material result = AssetDatabase.LoadAssetAtPath<Material>(path);
            if (result != null) return result;
            Shader program = Shader.Find(shader);
            if (program == null) throw new System.InvalidOperationException("缺少 Shader：" + shader);
            result = new Material(program) { name = name };
            if (result.HasProperty("_Glow")) result.SetFloat("_Glow", glow);
            AssetDatabase.CreateAsset(result, path); return result;
        }

        public static void Install(EarthDemoController controller)
        {
            foreach (string directory in new[] { "Materials", "Data", "Prefabs" })
                Directory.CreateDirectory(Root + "/" + directory);
            AssetDatabase.Refresh();
            string definitionPath = Root + "/Data/Chicxulub.asset";
            ImpactEventDefinition data = AssetDatabase.LoadAssetAtPath<ImpactEventDefinition>(definitionPath);
            if (data == null)
            {
                data = ScriptableObject.CreateInstance<ImpactEventDefinition>();
                AssetDatabase.CreateAsset(data, definitionPath);
            }
            string sitePath = Root + "/Data/chicxulub-site.json";
            if (!File.Exists(sitePath)) throw new FileNotFoundException("先运行 Tools/build_impact_site.py", sitePath);
            ReconstructedSite site = JsonUtility.FromJson<ReconstructedSite>(File.ReadAllText(sitePath));
            if (site.reconstructed_latitude_longitude == null || site.reconstructed_latitude_longitude.Length != 2)
                throw new System.InvalidOperationException("撞击点坐标数据无效。");
            data.reconstructedLatitudeLongitude = new Vector2(site.reconstructed_latitude_longitude[0],
                site.reconstructed_latitude_longitude[1]);
            data.plateId = site.plate_id;
            EditorUtility.SetDirty(data);
            Material rock = MaterialAsset("Impact Rock", "EarthEvents/ImpactRock");
            Material smoke = MaterialAsset("Impact Steam", "EarthEvents/ImpactParticle");
            Material glow = MaterialAsset("Impact Fire", "EarthEvents/ImpactParticle", 1f);
            Material wave = MaterialAsset("Impact Wave", "EarthEvents/ImpactWave");
            Material dust = MaterialAsset("Impact Dust", "EarthEvents/ImpactDust");
            string prefabPath = Root + "/Prefabs/EarthEventLayer.prefab";
            GameObject prefab = AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath);
            if (prefab == null)
            {
                GameObject template = new GameObject("EarthEventLayer");
                ImpactSequencePlayer templatePlayer = template.AddComponent<ImpactSequencePlayer>();
                templatePlayer.Configure(data, null, null, null, rock, smoke, glow, wave, dust);
                template.AddComponent<EarthEventLayer>().Configure(null, templatePlayer);
                prefab = PrefabUtility.SaveAsPrefabAsset(template, prefabPath);
                Object.DestroyImmediate(template);
            }
            else
            {
                GameObject contents = PrefabUtility.LoadPrefabContents(prefabPath);
                try
                {
                    contents.GetComponent<ImpactSequencePlayer>().Configure(data, null, null, null,
                        rock, smoke, glow, wave, dust);
                    PrefabUtility.SaveAsPrefabAsset(contents, prefabPath);
                }
                finally { PrefabUtility.UnloadPrefabContents(contents); }
            }
            EarthEventLayer existing = Object.FindObjectOfType<EarthEventLayer>(true);
            GameObject root = existing != null ? existing.gameObject :
                (GameObject)PrefabUtility.InstantiatePrefab(prefab, controller.gameObject.scene);
            ImpactSequencePlayer player = root.GetComponent<ImpactSequencePlayer>();
            // 编辑阶段 Awake 尚未运行，直接取已存在的场景对象。
            Transform earth = controller.transform;
            Renderer land = earth.GetComponentInChildren<DynamicLandRenderer>().GetComponent<Renderer>();
            player.Configure(data, earth, earth.GetComponent<Renderer>(), land, rock, smoke, glow, wave, dust);
            root.GetComponent<EarthEventLayer>().Configure(controller, player);
            PrefabUtility.RecordPrefabInstancePropertyModifications(player);
            PrefabUtility.RecordPrefabInstancePropertyModifications(root.GetComponent<EarthEventLayer>());
            EditorUtility.SetDirty(root);
            AssetDatabase.SaveAssets();
            Debug.Log("独立撞击事件层已安装；66 Ma 正式帧停留时播放。");
        }
    }
}
