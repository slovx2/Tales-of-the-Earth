using UnityEngine;

namespace EarthEvents
{
    /// <summary>球面波前，不使用会穿出地球或悬浮的平面圆环。</summary>
    public sealed class ImpactWave
    {
        private const int Segments = 192;
        private readonly Mesh mesh;
        private readonly MeshRenderer renderer;
        private readonly Vector3[] vertices = new Vector3[(Segments + 1) * 2];
        private readonly Color[] colors = new Color[(Segments + 1) * 2];
        private readonly Vector3 normal, right, north;
        public ImpactWave(Transform parent, string name, Vector3 site, Material material)
        {
            normal = site; north = Vector3.ProjectOnPlane(Vector3.forward, normal).normalized;
            right = Vector3.Cross(north, normal);
            GameObject obj = new GameObject(name); obj.transform.SetParent(parent, false);
            mesh = new Mesh { name = name }; mesh.MarkDynamic();
            obj.AddComponent<MeshFilter>().sharedMesh = mesh;
            renderer = obj.AddComponent<MeshRenderer>(); renderer.sharedMaterial = material;
            renderer.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            Vector2[] uv = new Vector2[vertices.Length]; int[] indices = new int[Segments * 6];
            for (int i = 0; i <= Segments; i++)
            {
                uv[i * 2] = new Vector2(i / (float)Segments, 0f);
                uv[i * 2 + 1] = new Vector2(i / (float)Segments, 1f);
                if (i == Segments) continue;
                int k = i * 6, v = i * 2;
                indices[k] = v; indices[k + 1] = v + 2; indices[k + 2] = v + 1;
                indices[k + 3] = v + 1; indices[k + 4] = v + 2; indices[k + 5] = v + 3;
            }
            mesh.vertices = vertices; mesh.uv = uv; mesh.triangles = indices; renderer.enabled = false;
        }
        public void Evaluate(float angle, float width, float height, Color color)
        {
            renderer.enabled = color.a > 0.001f;
            if (!renderer.enabled) return;
            for (int i = 0; i <= Segments; i++)
            {
                float azimuth = i * 2f * Mathf.PI / Segments;
                Vector3 tangent = right * Mathf.Cos(azimuth) + north * Mathf.Sin(azimuth);
                for (int side = 0; side < 2; side++)
                {
                    float a = Mathf.Max(0f, angle + (side - 0.5f) * width);
                    int index = i * 2 + side;
                    vertices[index] = (normal * Mathf.Cos(a) + tangent * Mathf.Sin(a)) * (1.005f + height);
                    colors[index] = color;
                }
            }
            mesh.vertices = vertices; mesh.colors = colors; mesh.RecalculateBounds();
        }
        public void Reset() { renderer.enabled = false; }
        public void Dispose() { Object.Destroy(mesh); }
    }
}
