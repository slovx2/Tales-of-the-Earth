Shader "Earth/DynamicLand"
{
    Properties
    {
        _LowlandColor ("低地", Color) = (0.16, 0.43, 0.13, 1)
        _DrylandColor ("干燥地", Color) = (0.55, 0.53, 0.20, 1)
        _PolarColor ("极地", Color) = (0.82, 0.88, 0.86, 1)
        _Emission ("环境光", Range(0, 1)) = 0.025
        _SurfaceOffset ("球面偏移", Range(1.0, 1.02)) = 1.003
    }

    SubShader
    {
        Tags { "RenderType"="Opaque" "Queue"="Geometry+1" }
        LOD 200
        Offset -1, -1

        Pass
        {
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma target 3.0
            #include "UnityCG.cginc"

            fixed4 _LowlandColor;
            fixed4 _DrylandColor;
            fixed4 _PolarColor;
            half _Emission;
            half _SurfaceOffset;

            struct appdata
            {
                float4 vertex : POSITION;
            };

            struct v2f
            {
                float4 position : SV_POSITION;
                float3 worldNormal : TEXCOORD0;
                float latitude : TEXCOORD1;
            };

            v2f vert(appdata input)
            {
                v2f output;
                float3 spherePosition = normalize(input.vertex.xyz);
                output.position = UnityObjectToClipPos(float4(spherePosition * _SurfaceOffset, 1.0));
                output.worldNormal = UnityObjectToWorldNormal(spherePosition);
                output.latitude = abs(spherePosition.y);
                return output;
            }

            fixed4 frag(v2f input) : SV_Target
            {
                float3 normal = normalize(input.worldNormal);
                half dry = saturate((input.latitude - 0.18) * 1.15);
                fixed3 land = lerp(_LowlandColor.rgb, _DrylandColor.rgb, dry * 0.45);
                half polar = smoothstep(0.72, 0.93, input.latitude);
                land = lerp(land, _PolarColor.rgb, polar);
                half lighting = 0.30 + 0.70 * saturate(dot(normal, normalize(_WorldSpaceLightPos0.xyz)));
                return fixed4(land * lighting + land * _Emission, 1.0);
            }
            ENDCG
        }
    }
    FallBack Off
}
