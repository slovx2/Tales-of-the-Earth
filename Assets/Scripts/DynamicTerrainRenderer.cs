using System;
using System.Diagnostics;
using System.IO;
using UnityEngine;

/// <summary>按时间轴把当前古地形/海深帧上传到一张可复用的 RHalf 纹理。</summary>
public sealed class DynamicTerrainRenderer : MonoBehaviour
{
    [SerializeField] private string datasetRelativePath = "EarthTerrain/terrain_frames.bin";
    [SerializeField] private Renderer landRenderer;
    [SerializeField] private Renderer oceanRenderer;

    private EarthTerrainDataset dataset;
    private Texture2D terrainTexture;
    private byte[] frameBytes;
    private int activeFrameIndex = -1;

    public float FrameResolutionMa => dataset != null ? dataset.TimeResolutionMa : 0f;
    public float MaxTimeMa => dataset != null ? dataset.MaxTimeMa : 0f;
    public int Width => dataset != null ? dataset.Width : 0;
    public int Height => dataset != null ? dataset.Height : 0;
    public float ActiveFrameTimeMa { get; private set; } = -1f;
    public double LastUploadMilliseconds { get; private set; }

    private void Awake()
    {
        string path = Path.Combine(Application.streamingAssetsPath, datasetRelativePath);
        if (!File.Exists(path)) throw new FileNotFoundException("找不到地球地形帧数据", path);
        dataset = new EarthTerrainDataset(path);
        frameBytes = new byte[dataset.Width * dataset.Height * sizeof(ushort)];
        terrainTexture = new Texture2D(dataset.Width, dataset.Height, TextureFormat.RHalf, false, true)
        {
            name = "Dynamic Earth Terrain",
            wrapMode = TextureWrapMode.Repeat,
            filterMode = FilterMode.Bilinear,
            anisoLevel = 0,
        };
        if (landRenderer == null) landRenderer = FindRenderer("Dynamic Land");
        if (oceanRenderer == null) oceanRenderer = GetComponent<Renderer>();
        BindTexture(landRenderer);
        BindTexture(oceanRenderer);
        SetTimeMa(0f);
    }

    public void SetTimeMa(float timeMa)
    {
        if (dataset == null) return;
        int frameIndex = Mathf.Clamp(Mathf.RoundToInt(timeMa / dataset.TimeResolutionMa), 0, dataset.FrameCount - 1);
        if (frameIndex == activeFrameIndex) return;
        Stopwatch timer = Stopwatch.StartNew();
        dataset.LoadNearestFrame(timeMa, frameBytes);
        terrainTexture.LoadRawTextureData(frameBytes);
        terrainTexture.Apply(false, false);
        timer.Stop();
        activeFrameIndex = frameIndex;
        ActiveFrameTimeMa = dataset.GetFrameTime(frameIndex);
        LastUploadMilliseconds = timer.Elapsed.TotalMilliseconds;
    }

    private void BindTexture(Renderer renderer)
    {
        if (renderer == null || renderer.sharedMaterial == null || !renderer.sharedMaterial.HasProperty("_TerrainTex")) return;
        renderer.sharedMaterial.SetTexture("_TerrainTex", terrainTexture);
        renderer.sharedMaterial.SetVector("_TerrainGrid", new Vector4(dataset.Width, dataset.Height, 1f / dataset.Width, 1f / dataset.Height));
    }

    private Renderer FindRenderer(string objectName)
    {
        Transform child = transform.Find(objectName);
        return child != null ? child.GetComponent<Renderer>() : null;
    }

    private void OnDestroy()
    {
        dataset?.Dispose();
        if (terrainTexture != null) Destroy(terrainTexture);
    }
}
