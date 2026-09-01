using System;
using System.IO;
using UnityEngine;

public sealed class EarthGeometryDataset : IDisposable
{
    private const int FileVersion = 1;

    private readonly FileStream stream;
    private readonly BinaryReader reader;
    private readonly FrameEntry[] frames;
    private readonly byte[] vertexBytes;
    private readonly byte[] indexBytes;
    private readonly float[] vertexComponents;
    private readonly Vector3[] vertices;
    private readonly int[] indices;

    public int FrameCount => frames.Length;
    public float TimeResolutionMa { get; }
    public float CoastlineResolutionKm { get; }
    public float MaxTimeMa => frames.Length > 0 ? frames[frames.Length - 1].TimeMa : 0f;

    public EarthGeometryDataset(string path)
    {
        stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
        reader = new BinaryReader(stream);
        string magic = new string(reader.ReadChars(4));
        int version = reader.ReadInt32();
        if (magic != "TEG1" || version != FileVersion)
        {
            throw new InvalidDataException($"不支持的地球几何数据：{magic} v{version}");
        }

        int frameCount = reader.ReadInt32();
        TimeResolutionMa = reader.ReadSingle();
        CoastlineResolutionKm = reader.ReadSingle();
        if (frameCount <= 0 || TimeResolutionMa <= 0f || CoastlineResolutionKm <= 0f)
        {
            throw new InvalidDataException("地球几何数据头无效");
        }

        frames = new FrameEntry[frameCount];
        int maximumVertexCount = 0;
        int maximumIndexCount = 0;
        for (int index = 0; index < frameCount; index++)
        {
            frames[index] = new FrameEntry(
                reader.ReadSingle(),
                reader.ReadInt64(),
                reader.ReadInt32(),
                reader.ReadInt32(),
                reader.ReadInt32());
            maximumVertexCount = Math.Max(maximumVertexCount, frames[index].VertexCount);
            maximumIndexCount = Math.Max(maximumIndexCount, frames[index].IndexCount);
        }

        vertexBytes = new byte[maximumVertexCount * 3 * sizeof(float)];
        indexBytes = new byte[maximumIndexCount * sizeof(int)];
        vertexComponents = new float[maximumVertexCount * 3];
        vertices = new Vector3[maximumVertexCount];
        indices = new int[maximumIndexCount];
    }

    public LoadedFrame LoadNearestFrame(float timeMa)
    {
        int frameIndex = Mathf.Clamp(Mathf.RoundToInt(timeMa / TimeResolutionMa), 0, frames.Length - 1);
        FrameEntry frame = frames[frameIndex];
        int vertexByteCount = frame.VertexCount * 3 * sizeof(float);
        int indexByteCount = frame.IndexCount * sizeof(int);
        if (vertexByteCount + indexByteCount != frame.ByteLength)
        {
            throw new InvalidDataException($"{frame.TimeMa:0} Ma 帧长度无效");
        }

        stream.Position = frame.Offset;
        ReadFully(vertexBytes, vertexByteCount);
        ReadFully(indexBytes, indexByteCount);
        Buffer.BlockCopy(vertexBytes, 0, vertexComponents, 0, vertexByteCount);
        Buffer.BlockCopy(indexBytes, 0, indices, 0, indexByteCount);
        for (int index = 0; index < frame.VertexCount; index++)
        {
            int component = index * 3;
            // 数据采用数学经度坐标（+Y=东经）；Unity 从相机前方观察球面时，
            // 该约定会让地理东向落到屏幕左侧。运行时转换到显示坐标，
            // 只反射 Y 轴，保持北极 (+Z) 和所有经纬度数据不变。
            vertices[index] = new Vector3(
                vertexComponents[component],
                -vertexComponents[component + 1],
                vertexComponents[component + 2]);
        }
        // Y 轴反射会反转三角形绕序；交换每个三角形的后两个顶点以保持正面朝外。
        for (int index = 0; index < frame.IndexCount; index += 3)
        {
            int second = indices[index + 1];
            indices[index + 1] = indices[index + 2];
            indices[index + 2] = second;
        }
        return new LoadedFrame(frameIndex, frame.TimeMa, frame.VertexCount, frame.IndexCount, vertices, indices);
    }

    private void ReadFully(byte[] buffer, int count)
    {
        int offset = 0;
        while (offset < count)
        {
            int read = stream.Read(buffer, offset, count - offset);
            if (read == 0)
            {
                throw new EndOfStreamException("地球几何数据意外结束");
            }
            offset += read;
        }
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
        public readonly int VertexCount;
        public readonly int IndexCount;

        public FrameEntry(float timeMa, long offset, int byteLength, int vertexCount, int indexCount)
        {
            TimeMa = timeMa;
            Offset = offset;
            ByteLength = byteLength;
            VertexCount = vertexCount;
            IndexCount = indexCount;
        }
    }

    public readonly struct LoadedFrame
    {
        public readonly int FrameIndex;
        public readonly float TimeMa;
        public readonly int VertexCount;
        public readonly int IndexCount;
        public readonly Vector3[] Vertices;
        public readonly int[] Indices;

        public LoadedFrame(int frameIndex, float timeMa, int vertexCount, int indexCount,
                           Vector3[] vertices, int[] indices)
        {
            FrameIndex = frameIndex;
            TimeMa = timeMa;
            VertexCount = vertexCount;
            IndexCount = indexCount;
            Vertices = vertices;
            Indices = indices;
        }
    }
}
