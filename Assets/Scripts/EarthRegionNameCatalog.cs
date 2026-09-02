using System;
using System.Collections.Generic;
using UnityEngine;

public sealed class EarthRegionNameCatalog
{
    private readonly Dictionary<string, string> displayNames;

    public string LanguageCode { get; }
    public int Count => displayNames.Count;

    public EarthRegionNameCatalog(string json)
    {
        CatalogDocument document = JsonUtility.FromJson<CatalogDocument>(json);
        if (document == null || document.languageCode != "zh-CN" ||
            document.regions == null || document.regions.Length == 0)
        {
            throw new InvalidOperationException("陆地区域中文名称表无效");
        }

        LanguageCode = document.languageCode;
        displayNames = new Dictionary<string, string>(document.regions.Length, StringComparer.Ordinal);
        foreach (CatalogEntry entry in document.regions)
        {
            if (entry == null || string.IsNullOrWhiteSpace(entry.source) ||
                string.IsNullOrWhiteSpace(entry.display))
            {
                throw new InvalidOperationException("陆地区域中文名称表包含空项");
            }
            if (!displayNames.TryAdd(entry.source, entry.display))
            {
                throw new InvalidOperationException($"陆地区域中文名称重复：{entry.source}");
            }
        }
    }

    public string GetDisplayName(string sourceName)
    {
        if (!displayNames.TryGetValue(sourceName, out string displayName))
        {
            throw new KeyNotFoundException($"陆地区域缺少中文名称：{sourceName}");
        }
        return displayName;
    }

    [Serializable]
    private sealed class CatalogDocument
    {
        public string languageCode;
        public CatalogEntry[] regions;
    }

    [Serializable]
    private sealed class CatalogEntry
    {
        public string source;
        public string display;
    }
}
