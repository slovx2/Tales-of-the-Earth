using UnityEngine;

namespace EarthEvents
{
    /// <summary>可撤销的球面局部替换。资源在初始化时分配，播放时仅改写顶点。</summary>
    public sealed class ImpactSurface
    {
        private const int Segments = 96, Rings = 24;
        private static readonly int PatchId = Shader.PropertyToID("_SurfacePatch");
        private static readonly int VisibilityId = Shader.PropertyToID("_SurfacePatchVisibility");
        private readonly Mesh mesh;
        private readonly MeshRenderer renderer;
        private readonly Material material;
        private readonly Vector3[] vertices = new Vector3[(Segments + 1) * (Rings + 1)];
        private readonly Color[] colors = new Color[(Segments + 1) * (Rings + 1)];
        private readonly Vector2[] terrainNoise = new Vector2[(Segments + 1) * (Rings + 1)];
        private readonly Renderer[] surfaces;
        private readonly MaterialPropertyBlock block = new MaterialPropertyBlock();
        private readonly Vector4[] savedPatch;
        private readonly float[] savedVisibility;
        private readonly ImpactEventDefinition definition;
        private readonly Vector3 normal, right, north;
        private bool masking;
        public bool IsVisible => renderer.enabled;

        public ImpactSurface(Transform parent, ImpactEventDefinition data, Material template, Renderer[] targets)
        {
            definition = data; surfaces = targets;
            normal = data.SiteDirection;
            north = Vector3.ProjectOnPlane(Vector3.forward, normal).normalized;
            right = Vector3.Cross(north, normal).normalized;
            savedPatch = new Vector4[targets.Length]; savedVisibility = new float[targets.Length];
            material = new Material(template) { name = "撞击坑运行时材质" };
            material.SetFloat("_IsSurfacePatch", 1f);
            GameObject obj = new GameObject("岩石坑与回涌");
            obj.transform.SetParent(parent, false);
            mesh = new Mesh { name = "局部峰环坑" }; mesh.MarkDynamic();
            obj.AddComponent<MeshFilter>().sharedMesh = mesh;
            renderer = obj.AddComponent<MeshRenderer>(); renderer.sharedMaterial = material;
            renderer.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            int[] indices = new int[Segments * Rings * 6];
            int cursor = 0;
            for (int row = 0; row < Rings; row++)
            for (int col = 0; col < Segments; col++)
            {
                int a = row * (Segments + 1) + col, b = a + 1, c = a + Segments + 1, d = c + 1;
                indices[cursor++] = a; indices[cursor++] = c; indices[cursor++] = b;
                indices[cursor++] = b; indices[cursor++] = c; indices[cursor++] = d;
            }
            Vector2[] uv = new Vector2[vertices.Length];
            for (int row = 0; row <= Rings; row++)
            for (int col = 0; col <= Segments; col++)
            {
                uv[row * (Segments + 1) + col] = new Vector2(row / (float)Rings, col / (float)Segments);
                float azimuth = col * (2f * Mathf.PI / Segments);
                float x = row / (float)Rings * Mathf.Cos(azimuth), y = row / (float)Rings * Mathf.Sin(azimuth);
                float seed = data.randomSeed * 0.001f;
                terrainNoise[row * (Segments + 1) + col] = new Vector2(
                    Mathf.PerlinNoise(x * 9f + seed, y * 9f + 3.7f),
                    Mathf.PerlinNoise(x * 27f + seed + 11f, y * 27f + 17.3f));
            }
            mesh.vertices = vertices; mesh.uv = uv; mesh.triangles = indices;
            renderer.enabled = false;
        }

        public void Evaluate(float seconds, float visibility)
        {
            if (seconds <= definition.impactSecond || visibility <= 0.001f) { Reset(); return; }
            if (!masking)
            {
                for (int i = 0; i < surfaces.Length; i++)
                {
                    if (surfaces[i] == null) continue;
                    surfaces[i].GetPropertyBlock(block);
                    savedPatch[i] = block.GetVector(PatchId);
                    savedVisibility[i] = block.GetFloat(VisibilityId);
                }
                masking = true;
            }
            float growth = Mathf.Lerp(0.12f, 1f, definition.excavation.Evaluate(seconds));
            float craterRadius = definition.DisplayCraterRadius * growth;
            float extent = craterRadius * 1.5f;
            float collapse = Mathf.SmoothStep(0f, 1f, (seconds - 8f) / 4f);
            float resurge = definition.resurge.Evaluate(seconds);
            for (int row = 0; row <= Rings; row++)
            {
                float fraction = row / (float)Rings;
                float distance = fraction * 1.5f;
                float angle = fraction * extent;
                for (int col = 0; col <= Segments; col++)
                {
                    float azimuth = col * (2f * Mathf.PI / Segments);
                    Vector3 tangent = right * Mathf.Cos(azimuth) + north * Mathf.Sin(azimuth);
                    int index = row * (Segments + 1) + col;
                    Vector2 noise = terrainNoise[index];
                    // 总体仍近圆形；坍塌块、峰环偏移和局部破碎打破同心圆观感。
                    float irregular = 1f + 0.075f * Mathf.Sin(azimuth * 3f + 0.6f) +
                        0.060f * Mathf.Sin(azimuth * 7f) + 0.035f * Mathf.Cos(azimuth * 13f + 1.1f);
                    float r = distance * irregular;
                    float bowl = -0.009f * growth * Mathf.Clamp01(1f - r * r);
                    float blocks = 0.55f + noise.x * 0.8f + 0.16f * Mathf.Sin(azimuth * 11f + 0.3f);
                    float rim = 0.004f * blocks * growth * Mathf.Exp(-Mathf.Pow((r - 0.94f) / 0.09f, 2f));
                    float peakRadius = 0.43f + 0.065f * Mathf.Sin(azimuth * 2f + 1f) + 0.04f * Mathf.Cos(azimuth * 5f);
                    float peak = 0.005f * collapse * growth * blocks *
                        Mathf.Exp(-Mathf.Pow((r - peakRadius) / (0.08f + noise.x * 0.07f), 2f));
                    float rebound = 0.004f * Mathf.Sin(collapse * Mathf.PI) * Mathf.Exp(-r * r * 22f);
                    float roughness = ((noise.x - 0.5f) * 0.0024f + (noise.y - 0.5f) * 0.0013f) *
                        growth * (1f - Mathf.SmoothStep(0f, 1f, (r - 1f) / 0.25f));
                    float height = bowl + rim + peak + rebound + roughness;
                    float water = resurge * Mathf.SmoothStep(0f, 1f, (r - (1f - resurge)) * 5f);
                    water *= 1f - Mathf.Clamp01((rim + peak) / 0.0025f);
                    height = Mathf.Lerp(height, Mathf.Max(height, -0.001f), water);
                    vertices[index] = (normal * Mathf.Cos(angle) + tangent * Mathf.Sin(angle)) * (1.0034f + height);
                    Color rock = Color.Lerp(new Color(0.11f, 0.075f, 0.05f), new Color(0.46f, 0.33f, 0.19f),
                        Mathf.Clamp01((rim + peak) / 0.004f));
                    float ocean = Mathf.Max(Mathf.SmoothStep(0f, 1f, (r - 1.05f) / 0.3f), water * 0.85f);
                    rock *= 0.62f + noise.x * 0.55f + noise.y * 0.2f;
                    colors[index] = Color.Lerp(rock, new Color(0.025f, 0.21f, 0.33f), ocean);
                    colors[index].a = (1f - ocean) * Mathf.Clamp01(1f - r * 1.7f);
                }
            }
            mesh.vertices = vertices; mesh.colors = colors; mesh.RecalculateNormals(); mesh.RecalculateBounds();
            material.SetFloat("_Visibility", visibility);
            material.SetFloat("_Heat", Mathf.Clamp01(1f - (seconds - 9f) / 16f));
            renderer.enabled = true;
            for (int i = 0; i < surfaces.Length; i++)
            {
                if (surfaces[i] == null) continue;
                surfaces[i].GetPropertyBlock(block);
                // 基础表面的开口缩在坑网格实心区内，羽化处保留海面垫底，避免近景出现黑色针孔。
                block.SetVector(PatchId, new Vector4(normal.x, normal.y, normal.z, Mathf.Cos(extent * 0.8f)));
                block.SetFloat(VisibilityId, visibility);
                surfaces[i].SetPropertyBlock(block);
            }
        }

        public void Reset()
        {
            renderer.enabled = false;
            if (!masking) return;
            for (int i = 0; i < surfaces.Length; i++)
            {
                if (surfaces[i] == null) continue;
                // 每次先读取其他系统的最新属性，只还原本模块拥有的两个值。
                surfaces[i].GetPropertyBlock(block);
                block.SetVector(PatchId, savedPatch[i]);
                block.SetFloat(VisibilityId, savedVisibility[i]);
                surfaces[i].SetPropertyBlock(block);
            }
            masking = false;
        }

        public void Dispose() { Reset(); Object.Destroy(mesh); Object.Destroy(material); }
    }
}
