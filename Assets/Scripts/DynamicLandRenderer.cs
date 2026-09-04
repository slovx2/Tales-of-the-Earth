using System;
using System.Diagnostics;
using System.IO;
using UnityEngine;
using UnityEngine.Rendering;

[RequireComponent(typeof(MeshFilter), typeof(MeshRenderer))]
public sealed class DynamicLandRenderer : MonoBehaviour
{
    [SerializeField] private string datasetRelativePath = "EarthGeometry/land_frames.bin";
    [SerializeField] private string previewDatasetRelativePath = "EarthGeometryPreview/land_frames.bin";

    private EarthGeometryDataset dataset;
    private EarthGeometryDataset formalDataset;
    private EarthGeometryDataset previewDataset;
    private bool previewMode;
    private float currentTimeMa;
    private Mesh landMesh;
    private int activeFrameIndex = -1;
    private double totalLoadMilliseconds;
    private int loadCount;

    public float FrameResolutionMa => dataset != null ? dataset.TimeResolutionMa : 0f;
    public bool IsPreviewMode => previewMode;
    public bool PreviewAvailable => previewDataset != null;
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
            previewDataset = new EarthGeometryDataset(previewPath, preloadToMemory: true);
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
        EarthGeometryDataset.LoadedFrame frame = dataset.LoadNearestFrame(timeMa);
        landMesh.Clear(false);
        MeshUpdateFlags flags = MeshUpdateFlags.DontRecalculateBounds |
                                MeshUpdateFlags.DontValidateIndices |
                                MeshUpdateFlags.DontNotifyMeshUsers;
        landMesh.SetVertices(frame.Vertices, 0, frame.VertexCount, flags);
        landMesh.SetIndices(frame.Indices, 0, frame.IndexCount, MeshTopology.Triangles, 0, false);
        landMesh.bounds = new Bounds(Vector3.zero, Vector3.one * 2.1f);
        landMesh.UploadMeshData(false);
        stopwatch.Stop();

        activeFrameIndex = frame.FrameIndex;
        ActiveFrameTimeMa = frame.TimeMa;
        ActiveVertexCount = frame.VertexCount;
        ActiveTriangleCount = frame.IndexCount / 3;
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
