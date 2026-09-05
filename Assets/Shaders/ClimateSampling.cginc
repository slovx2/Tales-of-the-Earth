#ifndef EARTH_CLIMATE_SAMPLING_INCLUDED
#define EARTH_CLIMATE_SAMPLING_INCLUDED

// 调用方提供气候纹理、网格尺寸与 climateColor；编号始终逐格解码，不对编号插值。
float _ClimateBoundarySharpness;
struct ClimateSurface
{
    float3 color;
    float4 fields;
    float snowEligible;
    float coverage;
};

void AccumulateClimateAppearance(float category, float weight, inout float4 first, inout float3 second)
{
    // 按视觉颜色归并同色的 Köppen 子类，防止多个森林子类被误当作互相竞争的颜色。
    if (category >= 12.5) first.z += weight;
    else if (category >= 11.5) first.w += weight;
    else if (category >= 9.5) second.x += weight;
    else if (category >= 8.5) second.z += weight;
    else if (category >= 5.5) first.z += weight;
    else if (category >= 2.5) second.y += weight;
    else if (category >= 1.5) first.y += weight;
    else first.x += weight;
}

void AccumulateClimateCell(float2 cell, float weight, inout ClimateSurface result,
    inout float4 first, inout float3 second)
{
    float2 uv = (cell + 0.5) * _ClimateGrid.zw;
    // 经度首尾相连，纬度夹在两极最外层像素中心；不依赖纹理全局 Repeat 设置。
    uv.x = frac(uv.x);
    uv.y = clamp(uv.y, 0.5 * _ClimateGrid.w, 1.0 - 0.5 * _ClimateGrid.w);
    float4 category = tex2Dlod(_ClimateClassTex, float4(uv, 0, 0));
    float primary = floor(category.r * 255.0 + 0.5);
    float secondary = floor(category.g * 255.0 + 0.5);
    float valid = step(0.5, primary) * step(0.003, category.a);
    weight *= valid;
    float3 color = lerp(climateColor(primary), climateColor(secondary), saturate(category.b * 2.0));
    result.color += color * weight;
    float transition = saturate(category.b * 2.0);
    AccumulateClimateAppearance(primary, weight * (1.0 - transition), first, second);
    AccumulateClimateAppearance(secondary, weight * transition, first, second);
    result.fields += tex2Dlod(_ClimateTex, float4(uv, 0, 0)) * weight;
    result.snowEligible += step(1.5, primary) * weight;
    result.coverage += weight;
}

ClimateSurface SampleClimateSurface(float2 uv)
{
    float2 position = uv * _ClimateGrid.xy - 0.5;
    float2 cell = floor(position);
    float2 blend = frac(position);
    ClimateSurface result;
    result.color = 0;
    result.fields = 0;
    result.snowEligible = 0;
    result.coverage = 0;
    float4 first = 0;
    float3 second = 0;
    AccumulateClimateCell(cell, (1.0 - blend.x) * (1.0 - blend.y), result, first, second);
    AccumulateClimateCell(cell + float2(1, 0), blend.x * (1.0 - blend.y), result, first, second);
    AccumulateClimateCell(cell + float2(0, 1), (1.0 - blend.x) * blend.y, result, first, second);
    AccumulateClimateCell(cell + float2(1, 1), blend.x * blend.y, result, first, second);
    // 海洋、无效类别不贡献颜色或温度。仅对有效陆地样本重新归一化，避免串色。
    float inverseWeight = rcp(max(result.coverage, 0.00001));
    result.color *= inverseWeight;
    result.fields *= inverseWeight;
    result.snowEligible *= inverseWeight;
    if (_ClimateBoundarySharpness > 1.0 && result.coverage > 0.00001)
    {
        // 收窄颜色之间的混合区，而不是锐化格子坐标或整幅画面。
        // 始终是已有颜色的非负归一化混合，不产生亮边、暗边或不存在的类别。
        float sharpness = clamp(_ClimateBoundarySharpness, 1.0, 3.0);
        first = pow(saturate(first * inverseWeight), sharpness);
        second = pow(saturate(second * inverseWeight), sharpness);
        float total = dot(first, float4(1, 1, 1, 1)) + dot(second, float3(1, 1, 1));
        result.color = (climateColor(1) * first.x + climateColor(2) * first.y +
            climateColor(13) * first.z + climateColor(12) * first.w +
            climateColor(11) * second.x + climateColor(3) * second.y +
            climateColor(9) * second.z) / max(total, 0.00001);
    }
    // 全部邻居无效时回退中性地表；在支持域末端平滑退出，避免新的硬边缘。
    result.coverage = smoothstep(0.0, 0.15, result.coverage);
    return result;
}
#endif
