Shader "Earth/DynamicLand"
{
    Properties
    {
        _ForestColor ("森林", Color) = (0.055, 0.19, 0.07, 1)
        _GrassColor ("草地", Color) = (0.20, 0.32, 0.11, 1)
        _DryGrassColor ("旱地", Color) = (0.43, 0.36, 0.16, 1)
        _DesertColor ("沙漠", Color) = (0.62, 0.50, 0.29, 1)
        _RockColor ("岩石", Color) = (0.34, 0.30, 0.24, 1)
        _SnowColor ("冰雪", Color) = (0.86, 0.90, 0.89, 1)
        _BiomeScale ("生物群落尺度", Range(1, 10)) = 3.8
        _DetailScale ("地表细节尺度", Range(8, 64)) = 26
        _DetailStrength ("地表细节强度", Range(0, 0.3)) = 0.09
        _TerrainTex ("古地形高度场", 2D) = "black" {}
        _TerrainGrid ("高度场网格", Vector) = (360, 180, 0.00278, 0.00556)
        _Emission ("环境光", Range(0, 1)) = 0.035
        _SurfaceOffset ("球面偏移", Range(1.0, 1.02)) = 1.003
    }

    SubShader
    {
        Tags { "RenderType"="Opaque" "Queue"="Geometry+1" }
        LOD 260
        Offset -1, -1

        Pass
        {
            Tags { "LightMode"="ForwardBase" }

            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma multi_compile_fwdbase
            #pragma target 3.0
            #include "UnityCG.cginc"
            #include "Lighting.cginc"

            fixed4 _ForestColor;
            fixed4 _GrassColor;
            fixed4 _DryGrassColor;
            fixed4 _DesertColor;
            fixed4 _RockColor;
            fixed4 _SnowColor;
            half _BiomeScale;
            half _DetailScale;
            half _DetailStrength;
            sampler2D _TerrainTex;
            float4 _TerrainGrid;
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
                float3 spherePosition : TEXCOORD1;
            };

            float hash31(float3 p)
            {
                p = frac(p * 0.1031);
                p += dot(p, p.yzx + 33.33);
                return frac((p.x + p.y) * p.z);
            }

            float valueNoise(float3 p)
            {
                float3 cell = floor(p);
                float3 fraction = frac(p);
                float3 blend = fraction * fraction * (3.0 - 2.0 * fraction);

                float n000 = hash31(cell + float3(0, 0, 0));
                float n100 = hash31(cell + float3(1, 0, 0));
                float n010 = hash31(cell + float3(0, 1, 0));
                float n110 = hash31(cell + float3(1, 1, 0));
                float n001 = hash31(cell + float3(0, 0, 1));
                float n101 = hash31(cell + float3(1, 0, 1));
                float n011 = hash31(cell + float3(0, 1, 1));
                float n111 = hash31(cell + float3(1, 1, 1));

                float lower = lerp(lerp(n000, n100, blend.x), lerp(n010, n110, blend.x), blend.y);
                float upper = lerp(lerp(n001, n101, blend.x), lerp(n011, n111, blend.x), blend.y);
                return lerp(lower, upper, blend.z);
            }

            float fbm(float3 p)
            {
                float total = valueNoise(p) * 0.5333;
                total += valueNoise(p * 2.03 + 11.7) * 0.2667;
                total += valueNoise(p * 4.11 + 29.1) * 0.1333;
                total += valueNoise(p * 8.23 + 47.3) * 0.0667;
                return total;
            }

            v2f vert(appdata input)
            {
                v2f output;
                float3 spherePosition = normalize(input.vertex.xyz);
                output.position = UnityObjectToClipPos(float4(spherePosition * _SurfaceOffset, 1.0));
                output.worldNormal = UnityObjectToWorldNormal(spherePosition);
                output.spherePosition = spherePosition;
                return output;
            }

            fixed4 frag(v2f input) : SV_Target
            {
                float3 sphere = normalize(input.spherePosition);
                float latitude = abs(sphere.z);
                float longitude = atan2(sphere.y, sphere.x);
                float2 terrainUv = float2(longitude / 6.2831853 + 0.5,
                                           0.5 - asin(sphere.z) / 3.14159265);
                float elevation = tex2D(_TerrainTex, terrainUv).r;
                float elevationFactor = saturate((elevation - 150.0) / 2800.0);
                float macro = fbm(sphere * _BiomeScale + float3(7.1, 19.3, 31.7));
                float moistureNoise = fbm(sphere * (_BiomeScale * 1.37) + float3(41.2, 3.7, 17.9));
                float detail = fbm(sphere * _DetailScale + float3(13.4, 53.1, 5.8));
                float ridges = 1.0 - abs(fbm(sphere * 12.0 + 73.2) * 2.0 - 1.0);

                float climateLatitude = saturate(
                    latitude + (macro - 0.5) * 0.20 + (moistureNoise - 0.5) * 0.08);

                float subtropicalBand = smoothstep(0.15, 0.30, climateLatitude) *
                                         (1.0 - smoothstep(0.38, 0.57, climateLatitude));
                float equatorialHumidity = 1.0 - smoothstep(0.08, 0.29, climateLatitude);
                float humidity = saturate(
                    0.28 + moistureNoise * 0.64 + equatorialHumidity * 0.15 -
                    subtropicalBand * 0.34 - climateLatitude * 0.10);
                float dryness = saturate(1.0 - humidity + (macro - 0.5) * 0.22);

                float desert = smoothstep(0.61, 0.87, dryness) *
                               (1.0 - smoothstep(0.70, 0.84, climateLatitude));
                float forest = smoothstep(0.48, 0.78, humidity) * (1.0 - desert);
                float dryGrass = smoothstep(0.32, 0.64, dryness) * (1.0 - desert);

                fixed3 land = _GrassColor.rgb;
                land = lerp(land, _DryGrassColor.rgb, dryGrass);
                land = lerp(land, _DesertColor.rgb, desert);
                land = lerp(land, _ForestColor.rgb, forest * 0.88);

                // 高地场仅用于打破纯色，真实山脉位置由后续古高程场负责。
                float highland = max(smoothstep(0.72, 0.91, ridges + (macro - 0.5) * 0.22),
                                     smoothstep(0.42, 0.82, elevationFactor));
                highland *= 1.0 - forest * 0.55;
                land = lerp(land, _RockColor.rgb, highland * 0.38);

                float polarClimate = smoothstep(
                    0.84, 0.97, climateLatitude + (detail - 0.5) * 0.04);
                float mountainSnow = highland * smoothstep(0.68, 0.90, elevationFactor) * 0.8;
                float snow = saturate(max(polarClimate, mountainSnow));
                land = lerp(land, _SnowColor.rgb, snow);

                float surfaceVariation = lerp(1.0 - _DetailStrength, 1.0 + _DetailStrength, detail);
                land *= surfaceVariation;

                float3 normal = normalize(input.worldNormal);
                float ndotl = saturate(dot(normal, normalize(_WorldSpaceLightPos0.xyz)));
                float diffuse = 0.46 + 0.54 * ndotl;
                fixed3 lit = land * diffuse * _LightColor0.rgb;
                return fixed4(lit + land * _Emission, 1.0);
            }
            ENDCG
        }
    }
    FallBack Off
}
