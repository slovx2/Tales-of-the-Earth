using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using UnityEngine;
using UnityEngine.Rendering;

[RequireComponent(typeof(MeshFilter), typeof(MeshRenderer))]
public sealed class DynamicLandRenderer : MonoBehaviour
{
    // 为字典、托管数组和 Mesh 上传临时缓冲预留余量，数据缓存本身控制在 480 MiB 内。
    private const long PreviewCacheLimitBytes = 480L * 1024L * 1024L;
    [SerializeField] private string datasetRelativePath = "EarthGeometry/land_frames.bin";
    [SerializeField] private string previewDatasetRelativePath = "EarthGeometryPreview/land_frames.bin";

    private EarthGeometryDataset dataset;
    private EarthGeometryDataset formalDataset;
    private EarthGeometryDataset previewDataset;
    private bool previewMode;
    private float currentTimeMa;
    private readonly Dictionary<int, CachedFrame> previewCache = new Dictionary<int, CachedFrame>();
    private long previewCacheBytes;
    private Mesh landMesh;
    private int activeFrameIndex = -1;
    private double totalLoadMilliseconds;
    private int loadCount;

    public float FrameResolutionMa => dataset != null ? dataset.TimeResolutionMa : 0f;
    public bool IsPreviewMode => previewMode;
    public bool PreviewAvailable => previewDataset != null;
    public long PreviewCacheBytes => previewCacheBytes;
    public int PreviewCachedFrameCount => previewCache.Count;
    public float CoastlineResolutionKm => dataset != null ? dataset.CoastlineResolutionKm : 0f;
    public float MaxTimeMa => dataset != null ? dataset.MaxTimeMa : 0f;
    public float ActiveFrameTimeMa { get; private set; } = -1f;
    public int ActiveVertexCount { get; private set; }
    public int ActiveTriangleCount { get; private set; }
    public double LastLoadMilliseconds { get; private set; }
    public double MaximumLoadMilliseconds { get; private set; }
    public double AverageLoadMilliseconds => loadCount > 0 ? totalLoadMilliseconds / loadCount : 0.0;

    private void Awake()
    {
        string datasetPath = Path.Combine(Application.streamingAssetsPath, datasetRelativePath);
        if (!File.Exists(datasetPath))
        {
            throw new FileNotFoundException("找不到地球几何帧数据", datasetPath);
        }

        formalDataset = new EarthGeometryDataset(datasetPath);
        dataset = formalDataset;
        string previewPath = Path.Combine(Application.streamingAssetsPath, previewDatasetRelativePath);
        if (File.Exists(previewPath))
        {
            // 1 Ma 预览文件可能超过 500 MiB，只保留索引和当前滑动窗口帧。
            previewDataset = new EarthGeometryDataset(previewPath);
        }
        landMesh = new Mesh
        {
            name = "Dynamic Earth Land",
            indexFormat = IndexFormat.UInt32,
            bounds = new Bounds(Vector3.zero, Vector3.one * 2.1f),
        };
        landMesh.MarkDynamic();
        GetComponent<MeshFilter>().sharedMesh = landMesh;
        SetTimeMa(0f);
    }

    public void SetTimeMa(float timeMa)
    {
        if (dataset == null)
        {
            return;
        }

        currentTimeMa = timeMa;
        int requestedFrame = Mathf.Clamp(
            Mathf.RoundToInt(timeMa / dataset.TimeResolutionMa),
            0,
            dataset.FrameCount - 1);
        if (requestedFrame == activeFrameIndex)
        {
            return;
        }

        Stopwatch stopwatch = Stopwatch.StartNew();
        int frameVertexCount;
        int frameIndexCount;
        float frameTimeMa;
        Vector3[] frameVertices;
        int[] frameIndices;
        if (previewMode && previewCache.TryGetValue(requestedFrame, out CachedFrame cachedFrame))
        {
            frameVertexCount = cachedFrame.VertexCount;
            frameIndexCount = cachedFrame.IndexCount;
            frameTimeMa = cachedFrame.TimeMa;
            frameVertices = cachedFrame.Vertices;
            frameIndices = cachedFrame.Indices;
        }
        else
        {
            EarthGeometryDataset.LoadedFrame frame = dataset.LoadNearestFrame(timeMa);
            frameVertexCount = frame.VertexCount;
            frameIndexCount = frame.IndexCount;
            frameTimeMa = frame.TimeMa;
            frameVertices = frame.Vertices;
            frameIndices = frame.Indices;
            if (previewMode)
            {
                frameVertices = new Vector3[frame.VertexCount];
                frameIndices = new int[frame.IndexCount];
                Array.Copy(frame.Vertices, frameVertices, frame.VertexCount);
                Array.Copy(frame.Indices, frameIndices, frame.IndexCount);
                CachedFrame newFrame = new CachedFrame(frame.FrameIndex, frame.TimeMa, frame.VertexCount,
                                                        frame.IndexCount, frameVertices, frameIndices);
                previewCache[frame.FrameIndex] = newFrame;
                previewCacheBytes += newFrame.ByteSize;
                TrimPreviewCache(frame.FrameIndex);
            }
        }
        landMesh.Clear(false);
        MeshUpdateFlags flags = MeshUpdateFlags.DontRecalculateBounds |
                                MeshUpdateFlags.DontValidateIndices |
                                MeshUpdateFlags.DontNotifyMeshUsers;
        landMesh.SetVertices(frameVertices, 0, frameVertexCount, flags);
        landMesh.SetIndices(frameIndices, 0, frameIndexCount, MeshTopology.Triangles, 0, false);
        landMesh.bounds = new Bounds(Vector3.zero, Vector3.one * 2.1f);
        landMesh.UploadMeshData(false);
        stopwatch.Stop();

        activeFrameIndex = frame.FrameIndex;
        ActiveFrameTimeMa = frameTimeMa;
        ActiveVertexCount = frameVertexCount;
        ActiveTriangleCount = frameIndexCount / 3;
        LastLoadMilliseconds = stopwatch.Elapsed.TotalMilliseconds;
        MaximumLoadMilliseconds = Math.Max(MaximumLoadMilliseconds, LastLoadMilliseconds);
        totalLoadMilliseconds += LastLoadMilliseconds;
        loadCount++;
    }

    public void SetPreviewMode(bool enabled)
    {
        if (enabled == previewMode || (enabled && previewDataset == null)) return;
        previewMode = enabled;
        dataset = previewMode ? previewDataset : formalDataset;
        activeFrameIndex = -1;
        SetTimeMa(currentTimeMa);
    }

    private void TrimPreviewCache(int currentFrameIndex)
    {
        if (previewCacheBytes <= PreviewCacheLimitBytes) return;
        List<int> candidates = new List<int>(previewCache.Keys);
        candidates.Sort((left, right) =>
        {
            int leftDistance = Math.Abs(left - currentFrameIndex);
            int rightDistance = Math.Abs(right - currentFrameIndex);
            return rightDistance.CompareTo(leftDistance);
        });
        for (int index = 0; index < candidates.Count && previewCacheBytes > PreviewCacheLimitBytes; index++)
        {
            int frameIndex = candidates[index];
            if (frameIndex == currentFrameIndex) continue;
            if (previewCache.TryGetValue(frameIndex, out CachedFrame frame))
            {
                previewCache.Remove(frameIndex);
                previewCacheBytes -= frame.ByteSize;
            }
        }
    }

    private sealed class CachedFrame
    {
        public readonly int FrameIndex;
        public readonly float TimeMa;
        public readonly int VertexCount;
        public readonly int IndexCount;
        public readonly Vector3[] Vertices;
        public readonly int[] Indices;
        public long ByteSize => (long)VertexCount * 3L * sizeof(float) +
                                (long)IndexCount * sizeof(int);

        public CachedFrame(int frameIndex, float timeMa, int vertexCount, int indexCount,
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

    private void OnDestroy()
    {
        if (previewDataset != null && previewDataset != formalDataset) previewDataset.Dispose();
        formalDataset?.Dispose();
        if (landMesh != null)
        {
            Destroy(landMesh);
        }
    }
}
