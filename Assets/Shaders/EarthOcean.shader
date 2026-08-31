Shader "Earth/DynamicOcean"
{
    Properties
    {
        _DeepColor ("深海", Color) = (0.015, 0.10, 0.28, 1)
        _ShallowColor ("浅海", Color) = (0.035, 0.30, 0.62, 1)
        _Smoothness ("光滑度", Range(0, 1)) = 0.82
        _Emission ("环境光", Range(0, 1)) = 0.07
    }

    SubShader
    {
        Tags { "RenderType"="Opaque" "Queue"="Geometry" }
        LOD 250

        CGPROGRAM
        #pragma surface surf Standard fullforwardshadows
        #pragma target 3.0

        fixed4 _DeepColor;
        fixed4 _ShallowColor;
        half _Smoothness;
        half _Emission;

        struct Input
        {
            float3 worldNormal;
        };

        void surf(Input IN, inout SurfaceOutputStandard o)
        {
            half latitude = abs(normalize(IN.worldNormal).y);
            fixed3 color = lerp(_ShallowColor.rgb, _DeepColor.rgb, latitude * 0.42);
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
