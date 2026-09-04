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
        _DetailScale ("地表细节尺度", Range(8, 64)) = 26
        _DetailStrength ("地表细节强度", Range(0, 0.3)) = 0.09
        _TerrainTex ("古地形高度场", 2D) = "black" {}
        _TerrainGrid ("高度场网格", Vector) = (360, 180, 0.00278, 0.00556)
        _ClimateTex ("气候连续变量", 2D) = "black" {}
        _ClimateClassTex ("Köppen 类别", 2D) = "black" {}
        _ClimateGrid ("气候网格", Vector) = (360, 180, 0.00278, 0.00556)
        _ClimateAvailable ("气候数据可用", Float) = 0
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
            half _DetailScale;
            half _DetailStrength;
            sampler2D _TerrainTex;
            float4 _TerrainGrid;
            sampler2D _ClimateTex;
            sampler2D _ClimateClassTex;
            float4 _ClimateGrid;
            half _ClimateAvailable;
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

            fixed3 climateColor(float category)
            {
                if (category >= 12.5) return _ForestColor.rgb; // Af
                if (category >= 11.5) return lerp(_ForestColor.rgb, _GrassColor.rgb, 0.35); // Am
                if (category >= 10.5) return lerp(_GrassColor.rgb, _DryGrassColor.rgb, 0.35); // Aw
                if (category >= 9.5) return lerp(_GrassColor.rgb, _DryGrassColor.rgb, 0.35); // BS
                if (category >= 8.5) return _DesertColor.rgb; // BW
                if (category >= 5.5) return _ForestColor.rgb; // C/Df
                if (category >= 2.5) return lerp(_ForestColor.rgb, _DryGrassColor.rgb, 0.28); // Ds/Dw
                if (category >= 1.5) return _SnowColor.rgb; // EF
                return lerp(_SnowColor.rgb, _RockColor.rgb, 0.25); // ET
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
                // 运行时显示坐标将数学坐标的 Y 轴反射回来，保持高度场经度与陆地一致。
                float longitude = atan2(-sphere.y, sphere.x);
                float2 terrainUv = float2(longitude / 6.2831853 + 0.5,
                                           0.5 - asin(sphere.z) / 3.14159265);
                float elevation = tex2D(_TerrainTex, terrainUv).r;
                float elevationFactor = saturate((elevation - 150.0) / 2800.0);
                float detail = fbm(sphere * _DetailScale + float3(13.4, 53.1, 5.8));
                float ridges = 1.0 - abs(fbm(sphere * 12.0 + 73.2) * 2.0 - 1.0);

                // FBM 仅用于小尺度地表扰动和高程辅助，不再决定大陆级生物群系。
                float highland = max(smoothstep(0.72, 0.91, ridges),
                                     smoothstep(0.42, 0.82, elevationFactor));
                float mountainSnow = highland * smoothstep(0.68, 0.90, elevationFactor) * 0.8;
                float snow = saturate(mountainSnow);

                // 气候场决定大陆尺度生物群系；FBM 仅保留为小尺度表面扰动。
                fixed4 climate = tex2D(_ClimateTex, terrainUv);
                fixed4 climateClass = tex2D(_ClimateClassTex, terrainUv);
                float primary = floor(climateClass.r * 255.0 + 0.5);
                float secondary = floor(climateClass.g * 255.0 + 0.5);
                float transition = climateClass.b;
                fixed3 climateLand = climateColor(primary);
                fixed3 climateSecondary = climateColor(secondary);
                climateLand = lerp(climateLand, climateSecondary, saturate(transition * 2.0));
                float climateWeight = saturate(_ClimateAvailable) * step(0.003, climateClass.a) * saturate(climate.a + 0.15);
                // 连续变量用于类别内的轻微修正，避免类别纹理呈完全平坦色块。
                float wetness = saturate(climate.g / 2400.0);
                climateLand = lerp(climateLand, climateLand * (0.88 + wetness * 0.12), climateWeight);
                // 高海拔只提高裸岩和积雪权重，不改写 Köppen 主分类。
                float climateColdness = saturate((8.0 - climate.r) / 18.0);
                float climateSnow = step(1.5, primary) * max(smoothstep(0.45, 0.85, elevationFactor), climateColdness * 0.35);
                climateLand = lerp(climateLand, _SnowColor.rgb, climateSnow * 0.55);
                // 没有气候帧时不再伪造大陆级气候纹理，只保留中性陆地、地形和细节扰动。
                fixed3 neutralLand = lerp(_GrassColor.rgb, _DryGrassColor.rgb, 0.15);
                neutralLand = lerp(neutralLand, _RockColor.rgb, highland * 0.38);
                neutralLand = lerp(neutralLand, _SnowColor.rgb, snow * 0.45);
                fixed3 land = neutralLand;
                land = lerp(neutralLand, climateLand, climateWeight);

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
