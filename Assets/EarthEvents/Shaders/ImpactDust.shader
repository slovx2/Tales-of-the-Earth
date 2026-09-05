Shader "EarthEvents/ImpactDust"
{
    Properties
    {
        _Site ("撞击点方向", Vector) = (0,0,1,0)
        _Spread ("扩散角度", Float) = 0
        _Opacity ("烟尘密度", Range(0,1)) = 0
        _FlowTime ("展示流动时间", Float) = 0
        _Layer ("壳层", Float) = 0
    }
    SubShader
    {
        Tags { "Queue"="Transparent+20" "RenderType"="Transparent" }
        Cull Back
        ZWrite Off
        Blend SrcAlpha OneMinusSrcAlpha
        Pass
        {
            CGPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma target 3.0
            #include "UnityCG.cginc"
            #include "Lighting.cginc"
            float3 _Site;
            float _Spread, _Opacity, _FlowTime, _Layer;
            struct appdata { float4 vertex:POSITION; };
            struct v2f { float4 pos:SV_POSITION; float3 local:TEXCOORD0; float3 world:TEXCOORD1; };
            v2f vert(appdata v)
            {
                v2f o; o.pos=UnityObjectToClipPos(v.vertex); o.local=v.vertex.xyz;
                o.world=mul(unity_ObjectToWorld,v.vertex).xyz; return o;
            }
            float hash(float3 p)
            { p=frac(p*0.1031); p+=dot(p,p.yzx+33.33); return frac((p.x+p.y)*p.z); }
            float noise(float3 p)
            {
                float3 a=floor(p), f=frac(p); f=f*f*(3-2*f);
                return lerp(lerp(lerp(hash(a),hash(a+float3(1,0,0)),f.x),
                    lerp(hash(a+float3(0,1,0)),hash(a+float3(1,1,0)),f.x),f.y),
                    lerp(lerp(hash(a+float3(0,0,1)),hash(a+float3(1,0,1)),f.x),
                    lerp(hash(a+float3(0,1,1)),hash(a+1),f.x),f.y),f.z);
            }
            float fbm(float3 p)
            {
                return noise(p)*0.53 + noise(p*2.03+13.1)*0.27 +
                    noise(p*4.07+7.8)*0.13 + noise(p*8.13+27.3)*0.07;
            }
            fixed4 frag(v2f i):SV_Target
            {
                float3 n=normalize(i.local);
                float drift=_FlowTime*0.008;
                float3 p=n*(5.0+_Layer*4.0) + float3(drift,0,-drift*0.7)+_Layer*17;
                float3 warp=float3(noise(p+19),noise(p+43),noise(p+7))-0.5;
                float cloud=fbm(p+warp*2.5);
                float detail=noise(p*18+warp*4);
                float angularDistance=acos(clamp(dot(n,_Site),-1,1));
                float frontNoise=noise(n*8)*0.45 + sin(atan2(n.y,n.x)*3+n.z*4)*0.12;
                float covered=1-smoothstep(_Spread-0.4,_Spread+0.15,angularDistance+frontNoise);
                float density=smoothstep(0.20,0.72,cloud);
                float3 normal=normalize(UnityObjectToWorldNormal(n));
                float sunlight=saturate(dot(normal,normalize(_WorldSpaceLightPos0.xyz)));
                float light=0.38+0.62*sunlight;
                float3 lower=lerp(float3(0.12,0.105,0.09),float3(0.55,0.47,0.36),density);
                float3 upper=lerp(float3(0.21,0.185,0.15),float3(0.68,0.61,0.50),density);
                float3 color=lerp(lower,upper,_Layer)*light*(0.85+detail*0.3);
                float alpha=lerp(0.73+density*0.27,density*0.58,_Layer)*_Opacity*covered;
                return float4(color,alpha);
            }
            ENDCG
        }
    }
}
