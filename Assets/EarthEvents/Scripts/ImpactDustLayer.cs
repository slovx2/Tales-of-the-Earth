using UnityEngine;

namespace EarthEvents
{
    /// <summary>从撞击区扩散到整个球面的烟尘壳层，与局部羽流、地表完全独立。</summary>
    public sealed class ImpactDustLayer
    {
        private readonly ImpactEventDefinition definition;
        private readonly Mesh mesh;
        private readonly Material[] materials = new Material[2];
        private readonly MeshRenderer[] renderers = new MeshRenderer[2];
        private float flowTime;
        private bool visible = true;
        public float Coverage { get; private set; }
        public bool Visible
        {
            get => visible;
            set { visible = value; UpdateVisibility(); }
        }

        public ImpactDustLayer(Transform parent, ImpactEventDefinition data, Material template)
        {
            definition = data;
            mesh = BuildShell();
            for (int i = 0; i < materials.Length; i++)
            {
                GameObject obj = new GameObject(i == 0 ? "全球烟尘主层" : "高空翻卷尘云");
                obj.transform.SetParent(parent, false);
                obj.transform.localScale = Vector3.one * (1.024f + i * 0.012f);
                obj.AddComponent<MeshFilter>().sharedMesh = mesh;
                renderers[i] = obj.AddComponent<MeshRenderer>();
                renderers[i].shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
                materials[i] = new Material(template) { name = "全球烟尘运行时层 " + i };
                materials[i].SetVector("_Site", data.SiteDirection);
                materials[i].SetFloat("_Layer", i);
                materials[i].renderQueue = 3020 + i;
                renderers[i].sharedMaterial = materials[i];
            }
            Reset();
        }

        public void Evaluate(float seconds)
        {
            Coverage = Mathf.SmoothStep(0f, 1f, Mathf.InverseLerp(
                definition.dustStartSecond, definition.dustGlobalSecond, seconds));
            flowTime = seconds;
            float onset = Mathf.SmoothStep(0f, 1f, (seconds - definition.dustStartSecond) / 5f);
            for (int i = 0; i < materials.Length; i++)
            {
                materials[i].SetFloat("_Spread", Mathf.Lerp(0.05f, 3.9f, Coverage));
                materials[i].SetFloat("_Opacity", onset * definition.dustOpacity);
                materials[i].SetFloat("_FlowTime", flowTime);
            }
            UpdateVisibility();
        }

        public void AdvanceFlow(float seconds)
        {
            // 演出完成后仅保留缓慢云层运动，不重播入射或重建坑体。
            flowTime += Mathf.Max(0f, seconds);
            for (int i = 0; i < materials.Length; i++) materials[i].SetFloat("_FlowTime", flowTime);
        }
        private void UpdateVisibility()
        {
            for (int i = 0; i < renderers.Length; i++) renderers[i].enabled = visible && Coverage > 0f;
        }
        public void Reset() { Coverage = 0f; flowTime = 0f; UpdateVisibility(); }
        public void Dispose()
        {
            Object.Destroy(mesh);
            foreach (Material material in materials) Object.Destroy(material);
        }

        private static Mesh BuildShell()
        {
            const int columns = 128, rows = 64;
            Vector3[] vertices = new Vector3[(columns + 1) * (rows + 1)];
            int[] indices = new int[columns * rows * 6]; int cursor = 0;
            for (int row = 0; row <= rows; row++)
            for (int col = 0; col <= columns; col++)
            {
                float latitude = row * Mathf.PI / rows, longitude = col * Mathf.PI * 2f / columns;
                int i = row * (columns + 1) + col;
                vertices[i] = new Vector3(Mathf.Sin(latitude) * Mathf.Cos(longitude), Mathf.Cos(latitude),
                    Mathf.Sin(latitude) * Mathf.Sin(longitude));
                if (row == rows || col == columns) continue;
                int next = i + columns + 1;
                indices[cursor++] = i; indices[cursor++] = i + 1; indices[cursor++] = next;
                indices[cursor++] = i + 1; indices[cursor++] = next + 1; indices[cursor++] = next;
            }
            Mesh mesh = new Mesh { name = "无接缝球面烟尘壳" };
            mesh.vertices = vertices; mesh.normals = vertices; mesh.triangles = indices;
            mesh.RecalculateBounds(); return mesh;
        }
    }
}
