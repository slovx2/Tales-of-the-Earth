Shader "Earth/EarthSurface"
{
    Properties
    {
        _MainTex ("海陆颜色", 2D) = "white" {}
        _LandMask ("陆地掩膜", 2D) = "black" {}
        _Roughness ("粗糙度", 2D) = "gray" {}
        _OceanTint ("海洋反射色", Color) = (0.08, 0.32, 0.65, 1)
        _OceanEmission ("海洋环境光", Range(0, 1)) = 0.08
        _LandEmission ("陆地环境光", Range(0, 1)) = 0.02
    }

    SubShader
    {
        Tags { "RenderType"="Opaque" "Queue"="Geometry" }
        LOD 300

        CGPROGRAM
        #pragma surface surf Standard fullforwardshadows
        #pragma target 3.0

        sampler2D _MainTex;
        sampler2D _LandMask;
        sampler2D _Roughness;
        fixed4 _OceanTint;
        half _OceanEmission;
        half _LandEmission;

        struct Input
        {
            float2 uv_MainTex;
        };

        void surf(Input IN, inout SurfaceOutputStandard o)
        {
            fixed4 color = tex2D(_MainTex, IN.uv_MainTex);
            half land = tex2D(_LandMask, IN.uv_MainTex).r;
            half roughness = tex2D(_Roughness, IN.uv_MainTex).r;
            half ocean = 1.0 - land;

            o.Albedo = color.rgb;
            o.Metallic = 0.0;
            o.Smoothness = saturate(1.0 - roughness);
            // 海洋保持一点环境色，夜半球不会完全死黑；陆地只保留很弱的反射。
            o.Emission = _OceanTint.rgb * ocean * _OceanEmission + color.rgb * land * _LandEmission;
            o.Alpha = 1.0;
        }
        ENDCG
    }
    FallBack "Standard"
}
