Shader "EarthEvents/ImpactRock"
{
    Properties
    {
        _Visibility ("显现", Range(0,1)) = 1
        _Heat ("余热", Range(0,1)) = 0
        _IsSurfacePatch ("球面边缘融合", Float) = 0
    }
    SubShader
    {
        Tags { "Queue"="Geometry+2" "RenderType"="Opaque" }
        Pass
        {
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "UnityCG.cginc"
            #include "Lighting.cginc"
            #include "../../Shaders/SurfacePatch.cginc"
            float _Visibility, _Heat, _IsSurfacePatch;
            struct appdata { float4 vertex:POSITION; float3 normal:NORMAL; float4 color:COLOR; float2 uv:TEXCOORD0; };
            struct v2f { float4 pos:SV_POSITION; float3 normal:TEXCOORD0; float4 color:COLOR;
                float3 local:TEXCOORD1; float radius:TEXCOORD2; };
            v2f vert(appdata v)
            {
                v2f o; o.pos=UnityObjectToClipPos(v.vertex);
                o.normal=UnityObjectToWorldNormal(v.normal); o.color=v.color; o.local=v.vertex.xyz;
                o.radius=v.uv.x;
                return o;
            }
            float rockHash(float3 p)
            { p=frac(p*0.1031); p+=dot(p,p.yzx+33.33); return frac((p.x+p.y)*p.z); }
            float rockNoise(float3 p)
            {
                float3 a=floor(p), f=frac(p); f=f*f*(3-2*f);
                return lerp(lerp(lerp(rockHash(a),rockHash(a+float3(1,0,0)),f.x),
                    lerp(rockHash(a+float3(0,1,0)),rockHash(a+float3(1,1,0)),f.x),f.y),
                    lerp(lerp(rockHash(a+float3(0,0,1)),rockHash(a+float3(1,0,1)),f.x),
                    lerp(rockHash(a+float3(0,1,1)),rockHash(a+1),f.x),f.y),f.z);
            }
            fixed4 frag(v2f i):SV_Target
            {
                float feather=lerp(1,1-smoothstep(0.8,1,i.radius),_IsSurfacePatch);
                clip(_Visibility * feather - SurfacePatchNoise(i.pos.xy));
                // 不重复的岩块、细碎角砾和扭曲裂隙，避免规则条纹或同心圆纹理。
                float block=rockNoise(i.local*370+11.3);
                float grain=rockNoise(i.local*1800+23.1);
                float detail=block*0.65+grain*0.35;
                float crack=1-smoothstep(0.015,0.065,abs(rockNoise(i.local*760+block*2)-0.5));
                float light = 0.35 + 0.65*saturate(dot(normalize(i.normal),normalize(_WorldSpaceLightPos0.xyz)));
                float3 color = i.color.rgb*(0.62+detail*0.65)*(1-crack*0.4)*light;
                color += float3(1.8,0.22,0.015)*i.color.a*_Heat*(0.3+0.7*crack);
                return float4(color,1);
            }
            ENDCG
        }
    }
}
