using System;
using System.Collections.Generic;
using UnityEngine;

public enum TimelineScaleMode
{
    RealProportion,
    EqualPeriod,
}

public readonly struct GeologicEpoch
{
    public readonly string DisplayName;
    public readonly float OlderMa;
    public readonly float YoungerMa;

    public GeologicEpoch(string displayName, float olderMa, float youngerMa)
    {
        DisplayName = displayName;
        OlderMa = olderMa;
        YoungerMa = youngerMa;
    }
}

public readonly struct GeologicPeriod
{
    public readonly string DisplayName;
    public readonly float OlderMa;
    public readonly float YoungerMa;
    public readonly Color Color;
    public readonly GeologicEpoch[] Epochs;

    public GeologicPeriod(
        string displayName,
        float olderMa,
        float youngerMa,
        Color color,
        GeologicEpoch[] epochs)
    {
        DisplayName = displayName;
        OlderMa = olderMa;
        YoungerMa = youngerMa;
        Color = color;
        Epochs = epochs ?? Array.Empty<GeologicEpoch>();
    }

    public bool HasEpochs => Epochs.Length > 0;
}

public static class GeologicTimeScale
{
    private static readonly GeologicPeriod[] periods =
    {
        new GeologicPeriod("前寒武纪", 970f, 538.8f, new Color32(0x3A, 0x72, 0x88, 0xFF), null),
        new GeologicPeriod("寒武纪", 538.8f, 485.4f, new Color32(0x4D, 0x9B, 0xB5, 0xFF), new[]
        {
            new GeologicEpoch("幸运世", 538.8f, 521f),
            new GeologicEpoch("第二世", 521f, 509f),
            new GeologicEpoch("苗岭世", 509f, 497f),
            new GeologicEpoch("芙蓉世", 497f, 485.4f),
        }),
        new GeologicPeriod("奥陶纪", 485.4f, 443.8f, new Color32(0x4D, 0x83, 0xB2, 0xFF), new[]
        {
            new GeologicEpoch("早奥陶世", 485.4f, 470f),
            new GeologicEpoch("中奥陶世", 470f, 458.4f),
            new GeologicEpoch("晚奥陶世", 458.4f, 443.8f),
        }),
        new GeologicPeriod("志留纪", 443.8f, 419.2f, new Color32(0x3E, 0x9A, 0x9A, 0xFF), new[]
        {
            new GeologicEpoch("兰多维列世", 443.8f, 433.4f),
            new GeologicEpoch("文洛克世", 433.4f, 427.4f),
            new GeologicEpoch("卢德洛世", 427.4f, 423f),
            new GeologicEpoch("普里道利世", 423f, 419.2f),
        }),
        new GeologicPeriod("泥盆纪", 419.2f, 358.9f, new Color32(0x55, 0x98, 0x62, 0xFF), new[]
        {
            new GeologicEpoch("早泥盆世", 419.2f, 393.3f),
            new GeologicEpoch("中泥盆世", 393.3f, 382.7f),
            new GeologicEpoch("晚泥盆世", 382.7f, 358.9f),
        }),
        new GeologicPeriod("石炭纪", 358.9f, 298.9f, new Color32(0x5E, 0x8A, 0xC2, 0xFF), new[]
        {
            new GeologicEpoch("密西西比世", 358.9f, 323.2f),
            new GeologicEpoch("宾夕法尼亚世", 323.2f, 298.9f),
        }),
        new GeologicPeriod("二叠纪", 298.9f, 251.9f, new Color32(0x8A, 0x78, 0xB8, 0xFF), new[]
        {
            new GeologicEpoch("乌拉尔世", 298.9f, 273.01f),
            new GeologicEpoch("瓜达鲁普世", 273.01f, 259.51f),
            new GeologicEpoch("乐平世", 259.51f, 251.9f),
        }),
        new GeologicPeriod("三叠纪", 251.9f, 201.4f, new Color32(0xC6, 0x6C, 0x5B, 0xFF), new[]
        {
            new GeologicEpoch("早三叠世", 251.9f, 247.2f),
            new GeologicEpoch("中三叠世", 247.2f, 237f),
            new GeologicEpoch("晚三叠世", 237f, 201.4f),
        }),
        new GeologicPeriod("侏罗纪", 201.4f, 145f, new Color32(0xD6, 0x98, 0x35, 0xFF), new[]
        {
            new GeologicEpoch("早侏罗世", 201.4f, 174.7f),
            new GeologicEpoch("中侏罗世", 174.7f, 163.5f),
            new GeologicEpoch("晚侏罗世", 163.5f, 145f),
        }),
        new GeologicPeriod("白垩纪", 145f, 66f, new Color32(0xD3, 0x73, 0x57, 0xFF), new[]
        {
            new GeologicEpoch("早白垩世", 145f, 100.5f),
            new GeologicEpoch("晚白垩世", 100.5f, 66f),
        }),
        new GeologicPeriod("古近纪", 66f, 23.03f, new Color32(0x8A, 0x75, 0xB8, 0xFF), new[]
        {
            new GeologicEpoch("古新世", 66f, 56f),
            new GeologicEpoch("始新世", 56f, 33.9f),
            new GeologicEpoch("渐新世", 33.9f, 23.03f),
        }),
        new GeologicPeriod("新近纪", 23.03f, 2.58f, new Color32(0x4F, 0x94, 0x9D, 0xFF), new[]
        {
            new GeologicEpoch("中新世", 23.03f, 5.333f),
            new GeologicEpoch("上新世", 5.333f, 2.58f),
        }),
        new GeologicPeriod("第四纪", 2.58f, 0f, new Color32(0x4C, 0x78, 0xB5, 0xFF), new[]
        {
            new GeologicEpoch("更新世", 2.58f, 0.0117f),
            new GeologicEpoch("全新世", 0.0117f, 0f),
        }),
    };

    public static IReadOnlyList<GeologicPeriod> Periods => periods;

    public static bool TryGetCurrent(
        float timeMa,
        out GeologicPeriod period,
        out GeologicEpoch epoch)
    {
        float clampedTime = Mathf.Clamp(timeMa, 0f, periods[0].OlderMa);
        for (int index = 0; index < periods.Length; index++)
        {
            GeologicPeriod candidate = periods[index];
            if (clampedTime <= candidate.OlderMa && clampedTime >= candidate.YoungerMa)
            {
                period = candidate;
                for (int epochIndex = 0; epochIndex < candidate.Epochs.Length; epochIndex++)
                {
                    GeologicEpoch candidateEpoch = candidate.Epochs[epochIndex];
                    if (clampedTime <= candidateEpoch.OlderMa &&
                        clampedTime >= candidateEpoch.YoungerMa)
                    {
                        epoch = candidateEpoch;
                        return true;
                    }
                }
                epoch = default;
                return true;
            }
        }
        period = periods[0];
        epoch = default;
        return false;
    }

    public static float TimeToNormalizedPosition(
        float timeMa,
        float maxTimeMa,
        TimelineScaleMode mode)
    {
        float maximum = Mathf.Max(0.001f, maxTimeMa);
        float clampedTime = Mathf.Clamp(timeMa, 0f, maximum);
        if (mode == TimelineScaleMode.RealProportion)
        {
            return Mathf.InverseLerp(maximum, 0f, clampedTime);
        }

        int periodIndex = FindPeriodIndex(clampedTime);
        GeologicPeriod period = periods[periodIndex];
        float span = Mathf.Max(0.001f, period.OlderMa - period.YoungerMa);
        float localPosition = Mathf.Clamp01((period.OlderMa - clampedTime) / span);
        return Mathf.Clamp01((periodIndex + localPosition) / periods.Length);
    }

    public static float NormalizedPositionToTime(
        float normalizedPosition,
        float maxTimeMa,
        TimelineScaleMode mode)
    {
        float maximum = Mathf.Max(0.001f, maxTimeMa);
        float normalized = Mathf.Clamp01(normalizedPosition);
        if (mode == TimelineScaleMode.RealProportion)
        {
            return Mathf.Lerp(maximum, 0f, normalized);
        }

        float scaled = normalized * periods.Length;
        int periodIndex = Mathf.Min(periods.Length - 1, Mathf.FloorToInt(scaled));
        float localPosition = periodIndex == periods.Length - 1
            ? 1f
            : scaled - periodIndex;
        GeologicPeriod period = periods[periodIndex];
        return Mathf.Lerp(period.OlderMa, period.YoungerMa, localPosition);
    }

    private static int FindPeriodIndex(float timeMa)
    {
        for (int index = 0; index < periods.Length; index++)
        {
            GeologicPeriod period = periods[index];
            if (timeMa <= period.OlderMa && timeMa >= period.YoungerMa)
            {
                return index;
            }
        }
        return timeMa > periods[0].OlderMa ? 0 : periods.Length - 1;
    }
}
