using UnityEngine;

namespace EarthEvents
{
    /// <summary>确定性展示时钟。Evaluate 可随机访问，不依赖上一帧粒子状态。</summary>
    public sealed partial class ImpactSequencePlayer : MonoBehaviour
    {
        [SerializeField] private ImpactEventDefinition definition;
        [SerializeField] private Transform earth;
        [SerializeField] private Renderer oceanRenderer, landRenderer;
        [SerializeField] private Material rockMaterial, smokeMaterial, glowMaterial, waveMaterial, dustMaterial;
        private Transform visualRoot, asteroid;
        private Mesh asteroidMesh;
        private Material asteroidMaterial;
        private ImpactSurface surface;
        private ImpactWave airWave, seaWave;
        private ImpactDustLayer dust;
        private ParticleSystem smoke, glow;
        private readonly ParticleSystem.Particle[] smokeParticles = new ParticleSystem.Particle[240];
        private readonly ParticleSystem.Particle[] glowParticles = new ParticleSystem.Particle[256];
        private readonly Vector4[] seeds = new Vector4[256];
        private int smokeCount, glowCount;
        private Vector3 site, north, right, incoming;
        private double elapsed;
        private bool initialized;
        public ImpactEventDefinition Definition => definition;
        public bool IsPlaying { get; private set; }
        public float PlaybackSeconds { get; private set; }
        public bool IsCompleted { get; private set; }
        public bool HasPersistentCrater => initialized && surface.IsVisible;
        public float GlobalDustCoverage => initialized ? dust.Coverage : 0f;
        public bool DustVisible
        {
            get => !initialized || dust.Visible;
            set { Initialize(); dust.Visible = value; }
        }
        public int VisibleParticleCount => smokeCount + glowCount;
        public bool AutomaticAdvance { get; set; } = true;
        public string StageLabel => PlaybackSeconds < 3f ? "斜向接近" :
            PlaybackSeconds < 6f ? "进入大气 · 白热尾流" : PlaybackSeconds < 7f ? "接触 · 瞬时闪光" :
            PlaybackSeconds < 18f ? "开挖 · 巨大撞击羽流与峰环" : PlaybackSeconds < 35f ? "海水回涌 · 烟尘向外扩散" :
            PlaybackSeconds < 60f ? "烟炱与粉尘扩散至全球 · 时间压缩" :
            "撞击寒冬 · 长期遮蔽天空（艺术化复原）";

        public void Configure(ImpactEventDefinition data, Transform globe, Renderer ocean, Renderer land,
            Material rock, Material smokeTemplate, Material glowTemplate, Material wave, Material dustTemplate)
        {
            definition = data; earth = globe; oceanRenderer = ocean; landRenderer = land;
            rockMaterial = rock; smokeMaterial = smokeTemplate; glowMaterial = glowTemplate; waveMaterial = wave;
            dustMaterial = dustTemplate;
        }

        private void Initialize()
        {
            if (initialized) return;
            if (definition == null || earth == null || rockMaterial == null || smokeMaterial == null ||
                glowMaterial == null || waveMaterial == null || dustMaterial == null)
                throw new System.InvalidOperationException("撞击动画缺少配置、地球引用或材质。");
            GameObject root = new GameObject("Impact Visuals（地球局部坐标）");
            visualRoot = root.transform; visualRoot.SetParent(earth, false);
            // Unity 内置球半径 0.5；这里将动画坐标统一为单位半径。
            visualRoot.localScale = Vector3.one * 0.5f;
            site = definition.SiteDirection;
            north = Vector3.ProjectOnPlane(Vector3.forward, site).normalized;
            right = Vector3.Cross(north, site).normalized;
            float bearing = definition.arrivalBearingDegrees * Mathf.Deg2Rad;
            float angle = definition.impactAngleDegrees * Mathf.Deg2Rad;
            incoming = site * Mathf.Sin(angle) + (north * Mathf.Cos(bearing) - right * Mathf.Sin(bearing)) * Mathf.Cos(angle);
            System.Random random = new System.Random(definition.randomSeed);
            for (int i = 0; i < seeds.Length; i++)
                seeds[i] = new Vector4((float)random.NextDouble(), (float)random.NextDouble(),
                    (float)random.NextDouble(), (float)random.NextDouble());
            surface = new ImpactSurface(visualRoot, definition, rockMaterial, new[] { oceanRenderer, landRenderer });
            airWave = new ImpactWave(visualRoot, "大气冲击波", site, waveMaterial);
            seaWave = new ImpactWave(visualRoot, "近场水波", site, waveMaterial);
            dust = new ImpactDustLayer(visualRoot, definition, dustMaterial);
            smoke = CreateParticles("蒸汽与岩石羽流", smokeMaterial, smokeParticles.Length);
            glow = CreateParticles("白热前缘、尾流与喷出物", glowMaterial, glowParticles.Length);
            asteroidMaterial = new Material(rockMaterial) { name = "小行星运行时材质" };
            GameObject stone = new GameObject("小行星（12 km × 显示倍率）");
            asteroid = stone.transform; asteroid.SetParent(visualRoot, false);
            asteroidMesh = BuildAsteroid();
            stone.AddComponent<MeshFilter>().sharedMesh = asteroidMesh;
            stone.AddComponent<MeshRenderer>().sharedMaterial = asteroidMaterial;
            initialized = true;
            visualRoot.gameObject.SetActive(false);
        }

        private ParticleSystem CreateParticles(string objectName, Material material, int capacity)
        {
            GameObject obj = new GameObject(objectName); obj.transform.SetParent(visualRoot, false);
            ParticleSystem system = obj.AddComponent<ParticleSystem>();
            system.Stop(true, ParticleSystemStopBehavior.StopEmittingAndClear);
            var main = system.main; main.playOnAwake = false; main.loop = false;
            main.maxParticles = capacity; main.startLifetime = 10000f; main.startSpeed = 0f;
            main.simulationSpace = ParticleSystemSimulationSpace.Local;
            main.scalingMode = ParticleSystemScalingMode.Hierarchy;
            main.simulationSpeed = 0f;
            var emission = system.emission; emission.enabled = false;
            var shape = system.shape; shape.enabled = false;
            ParticleSystemRenderer renderer = system.GetComponent<ParticleSystemRenderer>();
            renderer.sharedMaterial = material; renderer.renderMode = ParticleSystemRenderMode.Billboard;
            renderer.sortMode = ParticleSystemSortMode.Distance;
            renderer.maxParticleSize = 1f;
            renderer.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            return system;
        }

        public void Play()
        {
            if (IsPlaying || IsCompleted) return;
            Initialize(); elapsed = 0f; IsPlaying = true; Evaluate(0f);
        }
        public void Replay() { StopAndReset(); Play(); }
        private void Update()
        {
            if (IsPlaying && AutomaticAdvance) Advance(Time.unscaledDeltaTime);
            else if (IsCompleted && AutomaticAdvance) dust.AdvanceFlow(Time.unscaledDeltaTime);
        }
        public void Advance(float seconds)
        {
            if (!IsPlaying) return;
            elapsed += Mathf.Max(0f, seconds);
            Evaluate((float)System.Math.Min(elapsed, definition.durationSeconds));
            if (elapsed >= definition.durationSeconds)
            {
                IsPlaying = false;
                IsCompleted = true;
            }
        }

        public void Evaluate(float seconds)
        {
            Initialize();
            PlaybackSeconds = Mathf.Clamp(seconds, 0f, definition.durationSeconds);
            visualRoot.gameObject.SetActive(true);
            float t = PlaybackSeconds;
            const float visibility = 1f;
            smokeCount = 0; glowCount = 0;
            EvaluateApproach(t);
            EvaluatePlume(t, visibility);
            surface.Evaluate(t, visibility);
            dust.Evaluate(t);
            float sinceImpact = t - definition.impactSecond;
            float waveAlpha = sinceImpact > 0 && t < 35f ? Mathf.Exp(-sinceImpact * 0.13f) * 0.85f : 0f;
            airWave.Evaluate(0.02f + Mathf.Max(0f, sinceImpact) * 0.032f, 0.013f, 0.001f,
                new Color(0.9f, 0.85f, 0.69f, waveAlpha));
            float seaAge = t - 9f;
            seaWave.Evaluate(0.03f + Mathf.Max(0f, seaAge) * 0.005f, 0.006f, 0f,
                new Color(0.51f, 0.86f, 0.95f, seaAge > 0 && t < 40f ? Mathf.Exp(-seaAge * 0.12f) * 0.5f : 0f));
            smoke.SetParticles(smokeParticles, smokeCount);
            glow.SetParticles(glowParticles, glowCount);
        }

        public void StopAndReset()
        {
            IsPlaying = false; IsCompleted = false; elapsed = 0f; PlaybackSeconds = 0f;
            smokeCount = 0; glowCount = 0;
            if (!initialized) return;
            surface.Reset(); airWave.Reset(); seaWave.Reset();
            dust.Reset();
            smoke.Clear(); glow.Clear(); visualRoot.gameObject.SetActive(false);
        }
        private void OnDisable() { StopAndReset(); }
        private void OnDestroy()
        {
            if (!initialized) return;
            surface.Dispose(); airWave.Dispose(); seaWave.Dispose();
            dust.Dispose();
            Destroy(asteroidMesh); Destroy(asteroidMaterial);
            if (visualRoot != null) Destroy(visualRoot.gameObject);
        }

        private static Mesh BuildAsteroid()
        {
            const int columns = 24, rows = 16;
            Vector3[] v = new Vector3[(columns + 1) * (rows + 1)]; Color[] colors = new Color[v.Length];
            int[] indices = new int[columns * rows * 6]; int k = 0;
            for (int row = 0; row <= rows; row++)
            for (int col = 0; col <= columns; col++)
            {
                float lat = row * Mathf.PI / rows, lon = col * Mathf.PI * 2f / columns;
                Vector3 point = new Vector3(Mathf.Sin(lat) * Mathf.Cos(lon), Mathf.Cos(lat), Mathf.Sin(lat) * Mathf.Sin(lon));
                int i = row * (columns + 1) + col;
                float roughness = 1f + 0.13f * Mathf.Sin(point.x * 11f + point.z * 7f) * Mathf.Cos(point.y * 9f);
                v[i] = point * (0.5f * roughness); colors[i] = new Color(0.3f, 0.22f, 0.15f, 0.3f);
                if (row == rows || col == columns) continue;
                int next = i + columns + 1;
                indices[k++] = i; indices[k++] = i + 1; indices[k++] = next;
                indices[k++] = i + 1; indices[k++] = next + 1; indices[k++] = next;
            }
            Mesh mesh = new Mesh { name = "程序化不规则小行星" };
            mesh.vertices = v; mesh.colors = colors; mesh.triangles = indices;
            mesh.RecalculateNormals(); mesh.RecalculateBounds(); return mesh;
        }
    }
}
