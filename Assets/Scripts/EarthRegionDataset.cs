using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using UnityEngine;

public sealed class EarthRegionDataset : IDisposable
{
    private const int FileVersion = 1;
    private readonly FileStream stream;
    private readonly BinaryReader reader;
    private readonly string[] names;
    private readonly FrameEntry[] frames;

    public int FrameCount => frames.Length;
    public float FrameResolutionMa { get; }
    public float CoastlineResolutionKm { get; }
    public float MinimumAreaKm2 { get; }
    public float MaxTimeMa => frames.Length > 0 ? frames[frames.Length - 1].TimeMa : 0f;

    public EarthRegionDataset(string path)
    {
        stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
        reader = new BinaryReader(stream, Encoding.UTF8);
        string magic = Encoding.ASCII.GetString(reader.ReadBytes(4));
        int version = reader.ReadInt32();
        if (magic != "TER1" || version != FileVersion)
        {
            throw new InvalidDataException($"不支持的地球区域数据：{magic} v{version}");
        }

        int frameCount = reader.ReadInt32();
        FrameResolutionMa = reader.ReadSingle();
        CoastlineResolutionKm = reader.ReadSingle();
        MinimumAreaKm2 = reader.ReadSingle();
        int nameCount = reader.ReadInt32();
        if (frameCount <= 0 || FrameResolutionMa <= 0f || CoastlineResolutionKm <= 0f ||
            MinimumAreaKm2 <= 0f || nameCount <= 0)
        {
            throw new InvalidDataException("地球区域数据头无效");
        }

        names = new string[nameCount];
        for (int index = 0; index < names.Length; index++)
        {
            int byteCount = reader.ReadUInt16();
            names[index] = Encoding.UTF8.GetString(ReadExactBytes(byteCount));
            if (string.IsNullOrEmpty(names[index]))
            {
                throw new InvalidDataException($"地球区域名称 {index} 为空");
            }
        }

        frames = new FrameEntry[frameCount];
        for (int index = 0; index < frames.Length; index++)
        {
            frames[index] = new FrameEntry(
                reader.ReadSingle(),
                reader.ReadInt64(),
                reader.ReadInt32(),
                reader.ReadInt32(),
                reader.ReadInt32(),
                reader.ReadInt32());
        }
    }

    public LoadedFrame LoadNearestFrame(float timeMa)
    {
        int frameIndex = Mathf.Clamp(
            Mathf.RoundToInt(timeMa / FrameResolutionMa), 0, frames.Length - 1);
        FrameEntry entry = frames[frameIndex];
        stream.Position = entry.Offset;
        long expectedEnd = entry.Offset + entry.ByteLength;
        Region[] regions = new Region[entry.RegionCount];
        Dictionary<int, Region> regionsById = new Dictionary<int, Region>(entry.RegionCount);
        Dictionary<string, Region> regionsByName = new Dictionary<string, Region>(entry.RegionCount);
        int polygonCount = 0;
        int vertexCount = 0;

        for (int regionIndex = 0; regionIndex < regions.Length; regionIndex++)
        {
            int nameId = reader.ReadInt32();
            float areaKm2 = reader.ReadSingle();
            int regionPolygonCount = reader.ReadInt32();
            if (nameId < 0 || nameId >= names.Length || areaKm2 < MinimumAreaKm2 || regionPolygonCount <= 0)
            {
                throw new InvalidDataException($"{entry.TimeMa:0} Ma 区域记录无效");
            }

            RegionPolygon[] polygons = new RegionPolygon[regionPolygonCount];
            for (int polygonIndex = 0; polygonIndex < polygons.Length; polygonIndex++)
            {
                Vector3 coneCenter = ToDisplayDirection(
                    reader.ReadSingle(), reader.ReadSingle(), reader.ReadSingle());
                float coneMinimumDot = reader.ReadSingle();
                int ringCount = reader.ReadInt32();
                if (coneMinimumDot < -1.001f || coneMinimumDot > 1.001f || ringCount <= 0)
                {
                    throw new InvalidDataException($"{entry.TimeMa:0} Ma 区域多边形无效");
                }

                RegionRing[] rings = new RegionRing[ringCount];
                for (int ringIndex = 0; ringIndex < rings.Length; ringIndex++)
                {
                    bool isHole = reader.ReadByte() != 0;
                    int ringVertexCount = reader.ReadInt32();
                    if (ringVertexCount < 3)
                    {
                        throw new InvalidDataException($"{entry.TimeMa:0} Ma 区域边界顶点不足");
                    }
                    Vector3[] vertices = new Vector3[ringVertexCount];
                    for (int vertexIndex = 0; vertexIndex < vertices.Length; vertexIndex++)
                    {
                        vertices[vertexIndex] = ToDisplayDirection(
                            reader.ReadInt16() / 32767f,
                            reader.ReadInt16() / 32767f,
                            reader.ReadInt16() / 32767f);
                    }
                    rings[ringIndex] = new RegionRing(isHole, vertices);
                    vertexCount += vertices.Length;
                }
                polygons[polygonIndex] = new RegionPolygon(coneCenter, coneMinimumDot, rings);
                polygonCount++;
            }

            Region region = new Region(nameId, names[nameId], areaKm2, polygons);
            regions[regionIndex] = region;
            regionsById.Add(nameId, region);
            regionsByName.Add(region.Name, region);
        }

        if (stream.Position != expectedEnd || polygonCount != entry.PolygonCount ||
            vertexCount != entry.VertexCount)
        {
            throw new InvalidDataException($"{entry.TimeMa:0} Ma 区域帧长度或统计不匹配");
        }
        return new LoadedFrame(
            frameIndex, entry.TimeMa, regions, regionsById, regionsByName, polygonCount, vertexCount);
    }

    private byte[] ReadExactBytes(int count)
    {
        byte[] bytes = reader.ReadBytes(count);
        if (bytes.Length != count)
        {
            throw new EndOfStreamException("地球区域数据意外结束");
        }
        return bytes;
    }

    private static Vector3 ToDisplayDirection(float x, float y, float z)
    {
        Vector3 direction = new Vector3(x, -y, z);
        float length = direction.magnitude;
        if (length <= 1e-8f)
        {
            throw new InvalidDataException("地球区域方向向量为零");
        }
        return direction / length;
    }

    public void Dispose()
    {
        reader.Dispose();
        stream.Dispose();
    }

    private readonly struct FrameEntry
    {
        public readonly float TimeMa;
        public readonly long Offset;
        public readonly int ByteLength;
        public readonly int RegionCount;
        public readonly int PolygonCount;
        public readonly int VertexCount;

        public FrameEntry(float timeMa, long offset, int byteLength, int regionCount,
                          int polygonCount, int vertexCount)
        {
            TimeMa = timeMa;
            Offset = offset;
            ByteLength = byteLength;
            RegionCount = regionCount;
            PolygonCount = polygonCount;
            VertexCount = vertexCount;
        }
    }

    public sealed class LoadedFrame
    {
        private readonly Dictionary<int, Region> regionsById;
        private readonly Dictionary<string, Region> regionsByName;

        public int FrameIndex { get; }
        public float TimeMa { get; }
        public Region[] Regions { get; }
        public int PolygonCount { get; }
        public int VertexCount { get; }

        public LoadedFrame(int frameIndex, float timeMa, Region[] regions,
                           Dictionary<int, Region> regionsById,
                           Dictionary<string, Region> regionsByName,
                           int polygonCount, int vertexCount)
        {
            FrameIndex = frameIndex;
            TimeMa = timeMa;
            Regions = regions;
            this.regionsById = regionsById;
            this.regionsByName = regionsByName;
            PolygonCount = polygonCount;
            VertexCount = vertexCount;
        }

        public bool TryGetRegion(int id, out Region region) => regionsById.TryGetValue(id, out region);
        public bool TryGetRegion(string name, out Region region) => regionsByName.TryGetValue(name, out region);
    }

    public sealed class Region
    {
        public int Id { get; }
        public string Name { get; }
        public float AreaKm2 { get; }
        public RegionPolygon[] Polygons { get; }

        public Region(int id, string name, float areaKm2, RegionPolygon[] polygons)
        {
            Id = id;
            Name = name;
            AreaKm2 = areaKm2;
            Polygons = polygons;
        }
    }

    public readonly struct RegionPolygon
    {
        public readonly Vector3 ConeCenter;
        public readonly float ConeMinimumDot;
        public readonly RegionRing[] Rings;

        public RegionPolygon(Vector3 coneCenter, float coneMinimumDot, RegionRing[] rings)
        {
            ConeCenter = coneCenter;
            ConeMinimumDot = coneMinimumDot;
            Rings = rings;
        }
    }

    public readonly struct RegionRing
    {
        public readonly bool IsHole;
        public readonly Vector3[] Vertices;

        public RegionRing(bool isHole, Vector3[] vertices)
        {
            IsHole = isHole;
            Vertices = vertices;
        }
    }
}
