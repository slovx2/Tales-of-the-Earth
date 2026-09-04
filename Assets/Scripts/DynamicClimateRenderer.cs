using System;
using System.Diagnostics;
using System.IO;
using UnityEngine;

/// <summary>把当前年代气候帧上传到两张可复用纹理，并绑定 DynamicLand 材质。</summary>
public sealed class DynamicClimateRenderer : MonoBehaviour
{
    [SerializeField] private string datasetRelativePath = "EarthClimate/climate_frames.bin";
    [SerializeField] private Renderer landRenderer;

    private EarthClimateDataset dataset;
    private Texture2D climateTexture;
    private Texture2D climateClassTexture;
    private byte[] frameBytes;
    private byte[] climateBytes;
    private byte[] classBytes;
    private int activeFrameIndex = -1;
    private float currentTimeMa;
    private string datasetPath;
    private bool retryLoad;
    private long loadedFileLength;

    public bool ClimateAvailable { get; private set; }
    public int Width => dataset != null ? dataset.Width : 0;
    public int Height => dataset != null ? dataset.Height : 0;
    public float FrameResolutionMa => dataset != null ? dataset.TimeResolutionMa : 0f;
    public float MaxTimeMa => dataset != null ? dataset.MaxTimeMa : 0f;
    public float ActiveFrameTimeMa { get; private set; } = -1f;
    public double LastUploadMilliseconds { get; private set; }

    private void Awake()
    {
        if (landRenderer == null) landRenderer = FindRenderer("Dynamic Land");
        datasetPath = Path.Combine(Application.streamingAssetsPath, datasetRelativePath);
        TryLoadDataset();
    }

    private void Update()
    {
        // 支持在 Play Mode 期间生成/替换气候文件，不必重启场景。
        if (dataset == null && retryLoad && File.Exists(datasetPath))
        {
            retryLoad = false;
            TryLoadDataset();
        }
        else if (dataset != null && File.Exists(datasetPath) &&
                 new FileInfo(datasetPath).Length != loadedFileLength)
        {
            // 离线编译器替换了整份帧文件时，自动丢弃旧索引并加载新文件。
            DisposeDatasetResources();
            TryLoadDataset();
        }
    }

    private void TryLoadDataset()
    {
        if (!File.Exists(datasetPath))
        {
            retryLoad = true;
            ClimateAvailable = false;
            landRenderer?.sharedMaterial.SetFloat("_ClimateAvailable", 0f);
            UnityEngine.Debug.LogWarning($"未找到气候帧数据，使用中性陆地色：{datasetPath}");
            return;
        }
        try
        {
            dataset = new EarthClimateDataset(datasetPath);
            loadedFileLength = new FileInfo(datasetPath).Length;
            CreateTextures();
            BindTextures();
            SetTimeMa(0f);
            UnityEngine.Debug.Log($"气候帧已加载：{dataset.Width}×{dataset.Height}，覆盖 0–{dataset.MaxTimeMa:0} Ma");
        }
        catch (Exception exception) when (exception is IOException || exception is InvalidDataException)
        {
            UnityEngine.Debug.LogWarning($"气候数据不可用，将回退中性陆地颜色：{exception.Message}");
            dataset?.Dispose();
            dataset = null;
            loadedFileLength = 0;
            ClimateAvailable = false;
        }
    }

    public void SetTimeMa(float timeMa)
    {
        if (dataset == null) { ClimateAvailable = false; return; }
        currentTimeMa = timeMa;
        bool requestedAvailable = timeMa <= dataset.MaxTimeMa + dataset.TimeResolutionMa * 0.5f;
        int frameIndex = Mathf.Clamp(Mathf.RoundToInt(timeMa / dataset.TimeResolutionMa), 0, dataset.FrameCount - 1);
        if (frameIndex == activeFrameIndex)
        {
            ClimateAvailable = requestedAvailable;
            landRenderer?.sharedMaterial.SetFloat("_ClimateAvailable", ClimateAvailable ? 1f : 0f);
            return;
        }
        Stopwatch timer = Stopwatch.StartNew();
        dataset.LoadNearestFrame(timeMa, frameBytes);
        int samples = dataset.Width * dataset.Height;
        Buffer.BlockCopy(frameBytes, 0, climateBytes, 0, samples * 8);
        Buffer.BlockCopy(frameBytes, samples * 8, classBytes, 0, samples * 4);
        climateTexture.LoadRawTextureData(climateBytes);
        climateClassTexture.LoadRawTextureData(classBytes);
        climateTexture.Apply(false, false);
        climateClassTexture.Apply(false, false);
        activeFrameIndex = frameIndex;
        ActiveFrameTimeMa = dataset.GetFrameTime(frameIndex);
        ClimateAvailable = requestedAvailable;
        landRenderer?.sharedMaterial.SetFloat("_ClimateAvailable", ClimateAvailable ? 1f : 0f);
        timer.Stop();
        LastUploadMilliseconds = timer.Elapsed.TotalMilliseconds;
    }

    private void CreateTextures()
    {
        int samples = dataset.Width * dataset.Height;
        frameBytes = new byte[samples * EarthClimateDataset.BytesPerSample];
        climateBytes = new byte[samples * 8];
        classBytes = new byte[samples * 4];
        climateTexture = new Texture2D(dataset.Width, dataset.Height, TextureFormat.RGBAHalf, false, true)
        {
            name = "Dynamic Earth Climate", wrapMode = TextureWrapMode.Repeat, filterMode = FilterMode.Bilinear,
        };
        climateClassTexture = new Texture2D(dataset.Width, dataset.Height, TextureFormat.RGBA32, false, true)
        {
            name = "Dynamic Earth Climate Classes", wrapMode = TextureWrapMode.Repeat, filterMode = FilterMode.Point,
        };
    }

    private void BindTextures()
    {
        if (landRenderer == null || landRenderer.sharedMaterial == null) return;
        Material material = landRenderer.sharedMaterial;
        material.SetTexture("_ClimateTex", climateTexture);
        material.SetTexture("_ClimateClassTex", climateClassTexture);
        material.SetVector("_ClimateGrid", new Vector4(dataset.Width, dataset.Height, 1f / dataset.Width, 1f / dataset.Height));
        material.SetFloat("_ClimateAvailable", 1f);
    }

    private Renderer FindRenderer(string objectName)
    {
        Transform child = transform.Find(objectName);
        return child != null ? child.GetComponent<Renderer>() : null;
    }

    private void OnDestroy()
    {
        DisposeDatasetResources();
    }

    private void DisposeDatasetResources()
    {
        dataset?.Dispose();
        dataset = null;
        if (climateTexture != null) Destroy(climateTexture);
        if (climateClassTexture != null) Destroy(climateClassTexture);
        climateTexture = null;
        climateClassTexture = null;
        activeFrameIndex = -1;
    }
}
