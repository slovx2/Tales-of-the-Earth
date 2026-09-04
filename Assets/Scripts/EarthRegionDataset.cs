using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using UnityEngine;

public sealed class EarthRegionDataset : IDisposable
{
    private const int FileVersion = 2;
    private const uint InteractableFlag = 1;
    private readonly FileStream stream;
    private readonly BinaryReader reader;
    private readonly string[] strings;
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
        if (magic != "TER2" || version != FileVersion)
        {
            throw new InvalidDataException($"不支持的地球区域数据：{magic} v{version}");
        }

        int frameCount = reader.ReadInt32();
        FrameResolutionMa = reader.ReadSingle();
        CoastlineResolutionKm = reader.ReadSingle();
        MinimumAreaKm2 = reader.ReadSingle();
        int stringCount = reader.ReadInt32();
        if (frameCount <= 0 || FrameResolutionMa <= 0f || CoastlineResolutionKm <= 0f ||
            MinimumAreaKm2 <= 0f || stringCount <= 0)
        {
            throw new InvalidDataException("地球区域数据头无效");
        }

        strings = new string[stringCount];
        for (int index = 0; index < strings.Length; index++)
        {
            int byteCount = reader.ReadUInt16();
            strings[index] = Encoding.UTF8.GetString(ReadExactBytes(byteCount));
            if (string.IsNullOrEmpty(strings[index]))
            {
                throw new InvalidDataException($"地球区域字符串 {index} 为空");
            }
        }

        frames = new FrameEntry[frameCount];
        for (int index = 0; index < frames.Length; index++)
        {
            frames[index] = new FrameEntry(
                reader.ReadSingle(), reader.ReadInt64(), reader.ReadInt32(),
                reader.ReadInt32(), reader.ReadInt32(), reader.ReadInt32());
        }
    }

    public LoadedFrame LoadNearestFrame(float timeMa)
    {
        int frameIndex = Mathf.Clamp(
            Mathf.RoundToInt(timeMa / FrameResolutionMa), 0, frames.Length - 1);
        FrameEntry entry = frames[frameIndex];
        stream.Position = entry.Offset;
        long expectedEnd = entry.Offset + entry.ByteLength;
        RegionNode[] nodes = new RegionNode[entry.NodeCount];
        Dictionary<ulong, RegionNode> nodesByInstance = new Dictionary<ulong, RegionNode>(entry.NodeCount);
        Dictionary<ulong, List<RegionNode>> nodesByStable =
            new Dictionary<ulong, List<RegionNode>>(entry.NodeCount);
        int polygonCount = 0;
        int vertexCount = 0;

        for (int nodeIndex = 0; nodeIndex < nodes.Length; nodeIndex++)
        {
            ulong instanceId = reader.ReadUInt64();
            ulong stableId = reader.ReadUInt64();
            int parentIndex = reader.ReadInt32();
            RegionNodeKind kind = (RegionNodeKind)reader.ReadInt32();
            int level = reader.ReadInt32();
            int plateId = reader.ReadInt32();
            int featureIdStringId = reader.ReadInt32();
            int nameStringId = reader.ReadInt32();
            float areaKm2 = reader.ReadSingle();
            uint flags = reader.ReadUInt32();
            int nodePolygonCount = reader.ReadInt32();
            if (instanceId == 0 || stableId == 0 || parentIndex < -1 || parentIndex >= nodeIndex ||
                (kind != RegionNodeKind.Topology && kind != RegionNodeKind.LandUnit) ||
                level <= 0 || featureIdStringId < 0 || featureIdStringId >= strings.Length ||
                nameStringId < -1 || nameStringId >= strings.Length || areaKm2 <= 0f ||
                nodePolygonCount <= 0)
            {
                throw new InvalidDataException($"{entry.TimeMa:0} Ma 区域节点 {nodeIndex} 无效");
            }
            if ((parentIndex < 0) != (level == 1) ||
                (parentIndex >= 0 && nodes[parentIndex].Level + 1 != level))
            {
                throw new InvalidDataException($"{entry.TimeMa:0} Ma 区域层级关系无效");
            }

            RegionPolygon[] polygons = new RegionPolygon[nodePolygonCount];
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
                    if (ringVertexCount < 3 || (ringIndex == 0 && isHole))
                    {
                        throw new InvalidDataException($"{entry.TimeMa:0} Ma 区域边界无效");
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

            RegionNode node = new RegionNode(
                nodeIndex, instanceId, stableId, parentIndex, kind, level, plateId,
                strings[featureIdStringId], nameStringId >= 0 ? strings[nameStringId] : string.Empty,
                areaKm2, (flags & InteractableFlag) != 0, polygons);
            nodes[nodeIndex] = node;
            if (!nodesByInstance.TryAdd(instanceId, node))
            {
                throw new InvalidDataException($"{entry.TimeMa:0} Ma 区域实例 ID 重复");
            }
            if (!nodesByStable.TryGetValue(stableId, out List<RegionNode> candidates))
            {
                candidates = new List<RegionNode>();
                nodesByStable.Add(stableId, candidates);
            }
            candidates.Add(node);
        }

        if (stream.Position != expectedEnd || polygonCount != entry.PolygonCount ||
            vertexCount != entry.VertexCount)
        {
            throw new InvalidDataException($"{entry.TimeMa:0} Ma 区域帧长度或统计不匹配");
        }
        return new LoadedFrame(
            frameIndex, entry.TimeMa, nodes, nodesByInstance, nodesByStable,
            polygonCount, vertexCount);
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
        public readonly int NodeCount;
        public readonly int PolygonCount;
        public readonly int VertexCount;

        public FrameEntry(float timeMa, long offset, int byteLength, int nodeCount,
                          int polygonCount, int vertexCount)
        {
            TimeMa = timeMa;
            Offset = offset;
            ByteLength = byteLength;
            NodeCount = nodeCount;
            PolygonCount = polygonCount;
            VertexCount = vertexCount;
        }
    }

    public enum RegionNodeKind
    {
        Topology = 1,
        LandUnit = 2,
    }

    public readonly struct SelectionKey
    {
        public readonly ulong InstanceId;
        public readonly ulong StableId;
        public readonly RegionNodeKind Kind;
        public readonly int ParentPlateId;

        public SelectionKey(ulong instanceId, ulong stableId, RegionNodeKind kind, int parentPlateId)
        {
            InstanceId = instanceId;
            StableId = stableId;
            Kind = kind;
            ParentPlateId = parentPlateId;
        }
    }

    public sealed class LoadedFrame
    {
        private readonly Dictionary<ulong, RegionNode> nodesByInstance;
        private readonly Dictionary<ulong, List<RegionNode>> nodesByStable;

        public int FrameIndex { get; }
        public float TimeMa { get; }
        public RegionNode[] Nodes { get; }
        public int PolygonCount { get; }
        public int VertexCount { get; }

        public LoadedFrame(int frameIndex, float timeMa, RegionNode[] nodes,
                           Dictionary<ulong, RegionNode> nodesByInstance,
                           Dictionary<ulong, List<RegionNode>> nodesByStable,
                           int polygonCount, int vertexCount)
        {
            FrameIndex = frameIndex;
            TimeMa = timeMa;
            Nodes = nodes;
            this.nodesByInstance = nodesByInstance;
            this.nodesByStable = nodesByStable;
            PolygonCount = polygonCount;
            VertexCount = vertexCount;
        }

        public bool TryGetNode(ulong instanceId, out RegionNode node) =>
            nodesByInstance.TryGetValue(instanceId, out node);

        public RegionNode[] GetAncestorChain(RegionNode node)
        {
            RegionNode[] chain = new RegionNode[node.Level];
            RegionNode current = node;
            for (int index = chain.Length - 1; index >= 0; index--)
            {
                chain[index] = current;
                if (index > 0)
                {
                    current = Nodes[current.ParentIndex];
                }
            }
            return chain;
        }

        public SelectionKey[] CreateSelectionPath(RegionNode node)
        {
            RegionNode[] chain = GetAncestorChain(node);
            SelectionKey[] keys = new SelectionKey[chain.Length];
            for (int index = 0; index < chain.Length; index++)
            {
                int parentPlateId = chain[index].ParentIndex >= 0
                    ? Nodes[chain[index].ParentIndex].PlateId
                    : chain[index].PlateId;
                keys[index] = new SelectionKey(
                    chain[index].InstanceId, chain[index].StableId,
                    chain[index].Kind, parentPlateId);
            }
            return keys;
        }

        public bool TryResolveSelection(SelectionKey[] previousPath, out RegionNode node)
        {
            if (previousPath != null)
            {
                for (int pathIndex = previousPath.Length - 1; pathIndex >= 0; pathIndex--)
                {
                    SelectionKey key = previousPath[pathIndex];
                    if (nodesByInstance.TryGetValue(key.InstanceId, out RegionNode exact) &&
                        exact.Kind == key.Kind)
                    {
                        node = exact;
                        return true;
                    }
                    if (!nodesByStable.TryGetValue(key.StableId, out List<RegionNode> candidates))
                    {
                        continue;
                    }
                    RegionNode best = null;
                    foreach (RegionNode candidate in candidates)
                    {
                        if (candidate.Kind != key.Kind)
                        {
                            continue;
                        }
                        int candidateParentPlate = candidate.ParentIndex >= 0
                            ? Nodes[candidate.ParentIndex].PlateId
                            : candidate.PlateId;
                        bool candidateMatchesParent = candidateParentPlate == key.ParentPlateId;
                        bool bestMatchesParent = best != null &&
                            (best.ParentIndex >= 0 ? Nodes[best.ParentIndex].PlateId : best.PlateId) ==
                            key.ParentPlateId;
                        if (best == null || (candidateMatchesParent && !bestMatchesParent) ||
                            (candidateMatchesParent == bestMatchesParent &&
                             (candidate.AreaKm2 > best.AreaKm2 ||
                              (Mathf.Approximately(candidate.AreaKm2, best.AreaKm2) &&
                               candidate.InstanceId < best.InstanceId))))
                        {
                            best = candidate;
                        }
                    }
                    if (best != null)
                    {
                        node = best;
                        return true;
                    }
                }
            }
            node = null;
            return false;
        }
    }

    public sealed class RegionNode
    {
        public int Index { get; }
        public ulong InstanceId { get; }
        public ulong StableId { get; }
        public int ParentIndex { get; }
        public RegionNodeKind Kind { get; }
        public int Level { get; }
        public int PlateId { get; }
        public string FeatureId { get; }
        public string Name { get; }
        public float AreaKm2 { get; }
        public bool Interactable { get; }
        public RegionPolygon[] Polygons { get; }

        public RegionNode(int index, ulong instanceId, ulong stableId, int parentIndex,
                          RegionNodeKind kind, int level, int plateId, string featureId,
                          string name, float areaKm2, bool interactable, RegionPolygon[] polygons)
        {
            Index = index;
            InstanceId = instanceId;
            StableId = stableId;
            ParentIndex = parentIndex;
            Kind = kind;
            Level = level;
            PlateId = plateId;
            FeatureId = featureId;
            Name = name;
            AreaKm2 = areaKm2;
            Interactable = interactable;
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
