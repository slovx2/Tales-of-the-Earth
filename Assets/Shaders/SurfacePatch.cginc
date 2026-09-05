#ifndef EARTH_SURFACE_PATCH_INCLUDED
#define EARTH_SURFACE_PATCH_INCLUDED
// 通用局部表面替换接口，默认关闭，不包含任何地质事件语义。
float4 _SurfacePatch;
float _SurfacePatchVisibility;
float SurfacePatchNoise(float2 pixel)
{
    return frac(52.9829189 * frac(dot(floor(pixel), float2(0.06711056, 0.00583715))));
}
void ClipSurfacePatch(float3 direction, float2 pixel)
{
    if (_SurfacePatchVisibility > 0 && dot(direction, _SurfacePatch.xyz) > _SurfacePatch.w)
    {
        float relativeRadius = sqrt(max(0, (1-dot(direction, _SurfacePatch.xyz)) / max(1e-7, 1-_SurfacePatch.w)));
        float feather = 1-smoothstep(0.8, 1, relativeRadius);
        clip(SurfacePatchNoise(pixel) - _SurfacePatchVisibility * feather);
    }
}
#endif
