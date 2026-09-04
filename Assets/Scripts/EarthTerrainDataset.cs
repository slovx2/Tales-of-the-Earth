using System;
using System.IO;
using UnityEngine;

public sealed class EarthTerrainDataset : IDisposable
{
    private const int FileVersion = 1;
    private readonly Stream stream;
    private readonly BinaryReader reader;
    private readonly FrameEntry[] frames;
    private readonly byte[] bytes;

    public int Width { get; }
    public int Height { get; }
    public float TimeResolutionMa { get; }
    public int FrameCount => frames.Length;
    public float MaxTimeMa => frames.Length == 0 ? 0f : frames[frames.Length - 1].TimeMa;

    public EarthTerrainDataset(string path, bool preloadToMemory = false)
    {
        stream = preloadToMemory
            ? new MemoryStream(File.ReadAllBytes(path), writable: false)
            : new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
        reader = new BinaryReader(stream);
        string magic = new string(reader.ReadChars(4));
        int version = reader.ReadInt32();
        if (magic != "TET1" || version != FileVersion)
        {
            throw new InvalidDataException($"不支持的地球地形数据：{magic} v{version}");
        }

        TimeResolutionMa = reader.ReadSingle();
        reader.ReadSingle(); // reserved
        Width = reader.ReadInt32();
        Height = reader.ReadInt32();
        int frameCount = reader.ReadInt32();
        if (Width <= 0 || Height <= 0 || TimeResolutionMa <= 0f || frameCount <= 0)
        {
            throw new InvalidDataException("地球地形数据头无效");
        }

        frames = new FrameEntry[frameCount];
        int maxByteLength = 0;
        for (int index = 0; index < frameCount; index++)
        {
            frames[index] = new FrameEntry(reader.ReadSingle(), reader.ReadInt64(),
                                           reader.ReadInt32(), reader.ReadInt32());
            maxByteLength = Math.Max(maxByteLength, frames[index].ByteLength);
        }
        bytes = new byte[maxByteLength];
    }

    public int LoadNearestFrame(float timeMa, byte[] destination)
    {
        int frameIndex = Mathf.Clamp(Mathf.RoundToInt(timeMa / TimeResolutionMa), 0, frames.Length - 1);
        FrameEntry frame = frames[frameIndex];
        if (frame.ByteLength != Width * Height * sizeof(ushort) || destination.Length < frame.ByteLength)
        {
            throw new InvalidDataException($"{frame.TimeMa:0} Ma 地形帧长度无效");
        }
        stream.Position = frame.Offset;
        ReadFully(bytes, frame.ByteLength);
        Buffer.BlockCopy(bytes, 0, destination, 0, frame.ByteLength);
        return frameIndex;
    }

    public float GetFrameTime(int index) => frames[index].TimeMa;

    private void ReadFully(byte[] buffer, int count)
    {
        int offset = 0;
        while (offset < count)
        {
            int read = stream.Read(buffer, offset, count - offset);
            if (read == 0) throw new EndOfStreamException("地球地形数据意外结束");
            offset += read;
        }
    }

    public void Dispose() { reader.Dispose(); stream.Dispose(); }

    private readonly struct FrameEntry
    {
        public readonly float TimeMa;
        public readonly long Offset;
        public readonly int ByteLength;
        public readonly int SampleCount;
        public FrameEntry(float timeMa, long offset, int byteLength, int sampleCount)
        {
            TimeMa = timeMa; Offset = offset; ByteLength = byteLength; SampleCount = sampleCount;
        }
    }
}
