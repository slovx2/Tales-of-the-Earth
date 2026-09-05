using UnityEngine;

namespace EarthEvents
{
    [CreateAssetMenu(menuName = "Earth/撞击事件配置")]
    public sealed class ImpactEventDefinition : ScriptableObject
    {
        [Header("科学基准（km、Ma、度；与显示倍率分开）")]
        public float eventTimeMa = 66f;
        public Vector2 modernLatitudeLongitude = new Vector2(21.3f, -89.54f);
        public Vector2 reconstructedLatitudeLongitude = new Vector2(24.95932f, -62.17533f);
        public int plateId = 205;
        public string plateModel = "MULLER2022 v1.2.4 / 1000_0_rotfile.rot / anchor 0";
        public float earthRadiusKm = 6371f;
        public float asteroidDiameterKm = 12f;
        public float craterDiameterKm = 180f;
        [Tooltip("速度、倾角和来向为模型复原参数，并非确定测量值。")]
        public float impactSpeedKmPerSecond = 20f;
        public float impactAngleDegrees = 60f;
        public float arrivalBearingDegrees = 45f;
        [TextArea(3, 9)] public string sources =
            "年代：https://www.lpi.usra.edu/science/kring/Chicxulub/\n" +
            "位置、坑形：https://doi.org/10.1002/rog.20007\n" +
            "尺寸：https://www.lpi.usra.edu/features/chicxulub/\n" +
            "轨迹模型：https://doi.org/10.1038/s41467-020-15269-x\n" +
            "回涌：https://doi.org/10.1073/pnas.1909479116\n" +
            "长期烟尘：https://doi.org/10.1038/s41561-023-01290-4";

        [Header("展示参数（长度以地球半径 R 为单位）")]
        [Min(1f)] public float asteroidScale = 6f;
        [Min(1f)] public float craterScale = 2.5f;
        public float glowDiameterR = 0.10f;
        public float trailLengthR = 0.75f;
        public float plumeHeightR = 0.20f;
        public float plumeWidthR = 0.30f;
        public int randomSeed = 660205;
        [Min(60f)] public float durationSeconds = 75f;
        [Header("全球烟尘（展示时间，不等同真实扩散速度）")]
        public float dustStartSecond = 18f;
        public float dustGlobalSecond = 60f;
        [Range(0f, 1f)] public float dustOpacity = 0.92f;
        public float impactSecond = 6f;
        public AnimationCurve approach = AnimationCurve.EaseInOut(0f, 0f, 6f, 1f);
        public AnimationCurve excavation = AnimationCurve.EaseInOut(6f, 0f, 12f, 1f);
        public AnimationCurve plume = AnimationCurve.EaseInOut(7f, 0f, 19f, 1f);
        public AnimationCurve resurge = AnimationCurve.EaseInOut(18f, 0f, 32f, 1f);

        public Vector3 SiteDirection
        {
            get
            {
                float lat = reconstructedLatitudeLongitude.x * Mathf.Deg2Rad;
                float lon = reconstructedLatitudeLongitude.y * Mathf.Deg2Rad;
                // 运行时地球使用数据坐标 (x, -y, z)。
                return new Vector3(Mathf.Cos(lat) * Mathf.Cos(lon),
                    -Mathf.Cos(lat) * Mathf.Sin(lon), Mathf.Sin(lat));
            }
        }
        public float DisplayCraterRadius => craterDiameterKm * craterScale / (2f * earthRadiusKm);
        public float DisplayAsteroidDiameter => asteroidDiameterKm * asteroidScale / earthRadiusKm;
    }
}
