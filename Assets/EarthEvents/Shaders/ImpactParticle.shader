Shader "EarthEvents/ImpactParticle"
{
    Properties { _Glow ("自发光混合", Range(0,1)) = 0 }
    SubShader
    {
        Tags { "Queue"="Transparent+10" "RenderType"="Transparent" }
        Blend SrcAlpha OneMinusSrcAlpha
        ZWrite Off
        Cull Off
        Pass
        {
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "UnityCG.cginc"
            float _Glow;
            struct appdata { float4 vertex:POSITION; float4 color:COLOR; float2 uv:TEXCOORD0; };
            struct v2f { float4 pos:SV_POSITION; float4 color:COLOR; float2 uv:TEXCOORD0; };
            v2f vert(appdata v) { v2f o; o.pos=UnityObjectToClipPos(v.vertex); o.color=v.color; o.uv=v.uv; return o; }
            float hash(float2 p) { return frac(sin(dot(p,float2(127.1,311.7)))*43758.5453); }
            float noise(float2 p)
            {
                float2 a=floor(p), f=frac(p); f=f*f*(3-2*f);
                return lerp(lerp(hash(a),hash(a+float2(1,0)),f.x),
                    lerp(hash(a+float2(0,1)),hash(a+1),f.x),f.y);
            }
            fixed4 frag(v2f i):SV_Target
            {
                float2 p=i.uv*2-1;
                float n=noise(i.uv*8)*0.65+noise(i.uv*19)*0.35;
                float edge=1-dot(p,p);
                float a=smoothstep(0,0.6,edge-(n-0.5)*0.35);
                // 发光团使用柔软的径向衰减，避免高亮喷出物变成边缘清晰的黄色圆片。
                a=lerp(a,exp(-dot(p,p)*4.5)*smoothstep(0,0.35,edge),_Glow);
                float shading=0.45+0.55*saturate(sqrt(saturate(edge))*0.85-p.x*0.22+p.y*0.3);
                float3 color=i.color.rgb*lerp(shading*(0.65+n*0.5),1.25,_Glow);
                return float4(color,i.color.a*a);
            }
            ENDCG
        }
    }
}
