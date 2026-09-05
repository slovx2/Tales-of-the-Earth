using UnityEngine;

namespace EarthEvents
{
    public sealed partial class ImpactSequencePlayer
    {
        private void AddParticle(bool luminous, Vector3 position, float size, Color color, float rotation = 0f)
        {
            if (color.a <= 0.002f || size <= 0.0001f) return;
            ParticleSystem.Particle particle = new ParticleSystem.Particle
            {
                position = position, startSize = size, startColor = color,
                startLifetime = 10000f, remainingLifetime = 10000f,
                rotation = rotation, randomSeed = 1,
            };
            if (luminous && glowCount < glowParticles.Length) glowParticles[glowCount++] = particle;
            else if (!luminous && smokeCount < smokeParticles.Length) smokeParticles[smokeCount++] = particle;
        }

        private void EvaluateApproach(float t)
        {
            bool visible = t < definition.impactSecond;
            asteroid.gameObject.SetActive(visible);
            if (!visible) return;
            float progress = Mathf.Clamp01(definition.approach.Evaluate(t));
            Vector3 position = site * 1.006f + incoming * ((1f - progress) * 0.65f);
            asteroid.localPosition = position;
            asteroid.localScale = Vector3.one * definition.DisplayAsteroidDiameter;
            asteroid.localRotation = Quaternion.Euler(t * 39f, t * 61f, t * 17f);
            float heat = Mathf.SmoothStep(0f, 1f, (t - 2.5f) / 3.2f);
            asteroidMaterial.SetFloat("_Heat", heat);
            // 大气接近阶段渐亮；远处只有很弱的光晕，不画持续燃烧的太空彗尾。
            for (int i = 0; i < 72; i++)
            {
                float fraction = i / 71f;
                Vector4 seed = seeds[i];
                float length = definition.trailLengthR * heat;
                Vector3 offset = (right * Mathf.Sin(fraction * 18f - t * 8f) + north * (seed.y - 0.5f)) *
                    (0.0015f + fraction * 0.008f) * heat;
                Vector3 p = position + incoming * (fraction * length) + offset;
                Color color = Color.Lerp(new Color(1f, 0.96f, 0.74f), new Color(0.95f, 0.23f, 0.03f),
                    Mathf.SmoothStep(0f, 1f, fraction * 2f));
                color.a = heat * Mathf.Pow(1f - fraction, 0.8f) * 0.9f;
                float size = definition.glowDiameterR * (0.45f - fraction * 0.32f) * (0.75f + seed.z * 0.3f);
                AddParticle(true, p, size, color, seed.w * 360f);
            }
            AddParticle(true, position, definition.glowDiameterR,
                new Color(1f, 0.53f, 0.10f, heat * 0.30f));
            AddParticle(true, position - incoming * 0.002f, definition.glowDiameterR * 0.35f,
                new Color(1f, 0.99f, 0.90f, heat));
        }

        private void EvaluatePlume(float t, float visibility)
        {
            float age = t - definition.impactSecond;
            if (age <= 0f || visibility <= 0f) return;
            // 闪光局限于撞击地点，不覆盖整个屏幕。
            if (age < 3f)
            {
                float pulse = Mathf.Pow(1f - age / 3f, 2f);
                AddParticle(true, site * 1.035f, 0.12f + age * 0.11f,
                    new Color(1f, 0.91f, 0.65f, pulse));
                AddParticle(true, site * 1.045f, 0.055f + age * 0.04f,
                    new Color(1f, 1f, 0.96f, pulse));
            }
            // 弹道喷出物：初始向外向上，随后回落；每个样本可按时间直接求值。
            for (int i = 0; i < 80; i++)
            {
                Vector4 seed = seeds[i + 72];
                float life = 5f + seed.w * 8f;
                float u = age / life;
                if (u >= 1f) continue;
                float azimuth = seed.x * 2f * Mathf.PI;
                Vector3 tangent = right * Mathf.Cos(azimuth) + north * Mathf.Sin(azimuth);
                float distance = u * (0.055f + seed.y * 0.18f);
                float height = Mathf.Sin(u * Mathf.PI) * (0.04f + seed.z * 0.10f);
                Vector3 p = (site * Mathf.Cos(distance) + tangent * Mathf.Sin(distance)) * (1.005f + height);
                Color color = Color.Lerp(new Color(1f, 0.66f, 0.18f), new Color(0.39f, 0.29f, 0.19f), u);
                color.a = (1f - u) * visibility * 0.8f;
                AddParticle(u < 0.6f, p, (0.006f + seed.w * 0.012f) * (1f + u), color);
            }

            float growth = Mathf.Clamp01(definition.plume.Evaluate(t));
            float rise = Mathf.Lerp(0.008f, definition.plumeHeightR, growth);
            float expansion = Mathf.Lerp(0.015f, definition.plumeWidthR, Mathf.Sqrt(growth));
            float fade = Mathf.Pow(1f - Mathf.SmoothStep(0f, 1f, (t - 23f) / 17f), 2f) * visibility;
            float hot = 1f - Mathf.SmoothStep(0f, 1f, age / 9f);
            Vector3 drift = right * (Mathf.Max(0f, t - 20f) * 0.008f);

            // 不规则上升柱；后半程迅速变薄，露出坑底和峰环。
            for (int i = 0; i < 42; i++)
            {
                Vector4 seed = seeds[i + 120];
                float h = seed.x;
                float angle = seed.y * Mathf.PI * 2f + t * (0.12f + seed.z * 0.08f);
                float spread = (0.01f + h * 0.018f) * (0.4f + growth);
                Vector3 p = site * (1.006f + h * rise) + drift * h +
                    (right * Mathf.Cos(angle) + north * Mathf.Sin(angle)) * spread * seed.z;
                Color color = Color.Lerp(new Color(1f, 0.64f, 0.23f), new Color(0.52f, 0.47f, 0.39f), 1f - hot);
                color.a = fade * 0.8f * (1f - Mathf.SmoothStep(0f, 1f, (t - 22f) / 12f));
                AddParticle(false, p, 0.02f + growth * 0.035f + seed.w * 0.015f, color, angle * Mathf.Rad2Deg);
            }

            // 顶部由翻卷的环状云团和内层填充组成；各团高度、大小、灰度不同。
            for (int i = 0; i < 100; i++)
            {
                Vector4 seed = seeds[i + 40];
                float azimuth = seed.x * Mathf.PI * 2f;
                float curl = age * 0.28f + seed.y * Mathf.PI * 2f;
                float radius = expansion * (0.13f + seed.z * 0.26f + Mathf.Cos(curl) * 0.035f);
                float h = rise + expansion * (0.06f * Mathf.Sin(curl) + 0.10f * seed.w);
                Vector3 p = site * (1.006f + h) + drift +
                    (right * Mathf.Cos(azimuth) + north * Mathf.Sin(azimuth)) * radius;
                Color steam = Color.Lerp(new Color(0.34f, 0.29f, 0.23f), new Color(0.81f, 0.80f, 0.73f), seed.w);
                Color color = Color.Lerp(steam, new Color(1f, 0.72f, 0.3f), hot);
                color.a = fade * (0.45f + seed.y * 0.25f);
                AddParticle(false, p, expansion * (0.18f + seed.w * 0.17f), color, curl * Mathf.Rad2Deg);
            }
            // 低层水汽与碎屑雾沿地表展开，稍后让出坑形。
            for (int i = 0; i < 30; i++)
            {
                Vector4 seed = seeds[i + 210];
                float angle = seed.x * Mathf.PI * 2f;
                float distance = 0.018f + Mathf.Min(age, 18f) * 0.008f;
                Vector3 tangent = right * Mathf.Cos(angle) + north * Mathf.Sin(angle);
                Vector3 p = (site * Mathf.Cos(distance) + tangent * Mathf.Sin(distance)) * 1.009f;
                AddParticle(false, p, 0.025f + seed.z * 0.03f,
                    new Color(0.65f, 0.56f, 0.42f, Mathf.Clamp01(1f - age / 25f) * visibility * 0.5f));
            }
        }
    }
}
