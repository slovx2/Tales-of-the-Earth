Shader "Hidden/Earth/ClimateSamplingTest"
{
    SubShader
    {
        Pass
        {
            ZTest Always Cull Off ZWrite Off
            CGPROGRAM
            #pragma vertex vert_img
            #pragma fragment frag
            #pragma target 3.0
            #include "UnityCG.cginc"
            sampler2D _ClimateTex, _ClimateClassTex;
            float4 _ClimateGrid;
            float4 _ProbeUv;
            float _OutputFields;
            float3 climateColor(float category)
            {
                if (category > 12.5 || (category >= 5.5 && category < 8.5)) return float3(0, 1, 0);
                if (category > 8.5 && category < 9.5) return float3(1, 0, 0);
                return float3(0, 0, 1);
            }
            #include "../Shaders/ClimateSampling.cginc"
            float4 frag(v2f_img i) : SV_Target
            {
                ClimateSurface result = SampleClimateSurface(_ProbeUv.xy);
                if (_OutputFields > 0.5) return float4(result.fields.rgb / 4096.0, result.fields.a);
                return float4(result.color, result.coverage);
            }
            ENDCG
        }
    }
}
