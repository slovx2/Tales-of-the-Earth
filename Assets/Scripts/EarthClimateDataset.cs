using System;
using System.IO;
using UnityEngine;

/// <summary>气候连续变量与 Köppen 类别的逐年代二进制数据。</summary>
public sealed class EarthClimateDataset : IDisposable
{
    private const int FileVersion = 1;
    private readonly Stream stream;
    private readonly BinaryReader reader;
    private readonly FrameEntry[] frames;
    private readonly byte[] scratch;

    public int Width { get; }
    public int Height { get; }
    public float TimeResolutionMa { get; }
    public int FrameCount => frames.Length;
    public float MaxTimeMa => frames.Length == 0 ? 0f : frames[frames.Length - 1].TimeMa;
    public const int BytesPerSample = 12;

    public EarthClimateDataset(string path, bool preloadToMemory = false)
    {
        stream = preloadToMemory
            ? new MemoryStream(File.ReadAllBytes(path), writable: false)
            : new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
        reader = new BinaryReader(stream);
        string magic = new string(reader.ReadChars(4));
        int version = reader.ReadInt32();
        if (magic != "TEC1" || version != FileVersion)
            throw new InvalidDataException($"不支持的地球气候数据：{magic} v{version}");
        TimeResolutionMa = reader.ReadSingle();
        Width = Mathf.RoundToInt(reader.ReadSingle());
        Height = Mathf.RoundToInt(reader.ReadSingle());
        int frameCount = reader.ReadInt32();
        if (Width <= 0 || Height <= 0 || TimeResolutionMa <= 0f || frameCount <= 0)
            throw new InvalidDataException("地球气候数据头无效");
        frames = new FrameEntry[frameCount];
        int maxBytes = 0;
        for (int index = 0; index < frameCount; index++)
        {
            frames[index] = new FrameEntry(reader.ReadSingle(), reader.ReadInt64(),
                                           reader.ReadInt32(), reader.ReadInt32());
            maxBytes = Math.Max(maxBytes, frames[index].ByteLength);
        }
        scratch = new byte[maxBytes];
    }

    public int LoadNearestFrame(float timeMa, byte[] destination)
    {
        int frameIndex = Mathf.Clamp(Mathf.RoundToInt(timeMa / TimeResolutionMa), 0, frames.Length - 1);
        FrameEntry frame = frames[frameIndex];
        int expected = Width * Height * BytesPerSample;
        if (frame.ByteLength != expected || frame.SampleCount != Width * Height || destination.Length < expected)
            throw new InvalidDataException($"{frame.TimeMa:0} Ma 气候帧长度无效");
        stream.Position = frame.Offset;
        ReadFully(scratch, frame.ByteLength);
        Buffer.BlockCopy(scratch, 0, destination, 0, frame.ByteLength);
        return frameIndex;
    }

    public float GetFrameTime(int index) => frames[index].TimeMa;

    private void ReadFully(byte[] buffer, int count)
    {
        int offset = 0;
        while (offset < count)
        {
            int read = stream.Read(buffer, offset, count - offset);
            if (read == 0) throw new EndOfStreamException("地球气候数据意外结束");
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
