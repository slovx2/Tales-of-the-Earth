Shader "Earth/DynamicOcean"
{
    Properties
    {
        _DeepColor ("深海", Color) = (0.015, 0.10, 0.28, 1)
        _ShallowColor ("浅海", Color) = (0.035, 0.30, 0.62, 1)
        _Smoothness ("光滑度", Range(0, 1)) = 0.82
        _Emission ("环境光", Range(0, 1)) = 0.07
        _TerrainTex ("古地形海深场", 2D) = "black" {}
        _TerrainGrid ("高度场网格", Vector) = (360, 180, 0.00278, 0.00556)
        _SurfacePatch ("局部表面方向与角半径余弦", Vector) = (0,0,1,1)
        _SurfacePatchVisibility ("局部表面替换强度", Range(0,1)) = 0
    }

    SubShader
    {
        Tags { "RenderType"="Opaque" "Queue"="Geometry" }
        LOD 250

        CGPROGRAM
        #pragma surface surf Standard fullforwardshadows
        #pragma target 3.0
        #include "SurfacePatch.cginc"

        fixed4 _DeepColor;
        fixed4 _ShallowColor;
        half _Smoothness;
        half _Emission;
        sampler2D _TerrainTex;
        float4 _TerrainGrid;

        struct Input
        {
            float3 worldNormal;
            float3 worldPos;
            float4 screenPos;
        };

        void surf(Input IN, inout SurfaceOutputStandard o)
        {
            float3 sphere = normalize(mul(unity_WorldToObject, float4(IN.worldPos, 1.0)).xyz);
            ClipSurfacePatch(sphere, IN.screenPos.xy / IN.screenPos.w * _ScreenParams.xy);
            // 与 DynamicLand 相同：显示坐标的 Y 轴相对数据坐标反射。
            float longitude = atan2(-sphere.y, sphere.x);
            float2 terrainUv = float2(longitude / 6.2831853 + 0.5,
                                       0.5 - asin(sphere.z) / 3.14159265);
            float depth = max(0.0, -tex2D(_TerrainTex, terrainUv).r);
            half depthFactor = smoothstep(120.0, 5200.0, depth);
            fixed3 color = lerp(_ShallowColor.rgb, _DeepColor.rgb, depthFactor);
            o.Albedo = color;
            o.Metallic = 0.0;
            o.Smoothness = _Smoothness;
            o.Emission = color * _Emission;
            o.Alpha = 1.0;
        }
        ENDCG
    }
    FallBack "Standard"
}
