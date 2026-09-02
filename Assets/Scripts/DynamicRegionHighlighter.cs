using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;
using UnityEngine.Rendering;

[RequireComponent(typeof(SphereCollider))]
public sealed class DynamicRegionHighlighter : MonoBehaviour
{
    [SerializeField] private string datasetRelativePath = "EarthRegions/region_frames.bin";
    [SerializeField] private SphereCollider earthCollider;
    [SerializeField] private Material outlineMaterial;
    [SerializeField] private float outlineRadius = 0.5045f;
    [SerializeField] private float hoverWidthPixels = 3f;
    [SerializeField] private float selectedWidthPixels = 4f;

    private readonly List<LineRenderer> hoverLines = new List<LineRenderer>();
    private readonly List<LineRenderer> selectedLines = new List<LineRenderer>();
    private EarthRegionDataset dataset;
    private EarthRegionNameCatalog nameCatalog;
    private EarthRegionDataset.LoadedFrame activeFrame;
    private Camera activeCamera;
    private int activeFrameIndex = -1;
    private int hoveredRegionId = -1;
    private int selectedRegionId = -1;
    private string selectedRegionName;

    public float FrameResolutionMa => dataset != null ? dataset.FrameResolutionMa : 0f;
    public float MaxTimeMa => dataset != null ? dataset.MaxTimeMa : 0f;
    public float MinimumAreaKm2 => dataset != null ? dataset.MinimumAreaKm2 : 0f;
    public float ActiveFrameTimeMa => activeFrame != null ? activeFrame.TimeMa : -1f;
    public int ActiveRegionCount => activeFrame != null ? activeFrame.Regions.Length : 0;
    public int LocalizedRegionCount => nameCatalog != null ? nameCatalog.Count : 0;
    public string HoveredRegionName => GetRegionDisplayName(hoveredRegionId);
    public string SelectedRegionName => GetRegionDisplayName(selectedRegionId);
    public string HoveredRegionOriginalName => GetRegionSourceName(hoveredRegionId);
    public string SelectedRegionOriginalName => GetRegionSourceName(selectedRegionId);

    private void Awake()
    {
        if (earthCollider == null)
        {
            earthCollider = GetComponent<SphereCollider>();
        }
        if (outlineMaterial == null)
        {
            throw new InvalidOperationException("区域高亮缺少描边材质");
        }
        string path = Path.Combine(Application.streamingAssetsPath, datasetRelativePath);
        if (!File.Exists(path))
        {
            throw new FileNotFoundException("找不到地球区域帧数据", path);
        }
        TextAsset nameCatalogAsset = Resources.Load<TextAsset>("EarthRegionNamesZhCn");
        if (nameCatalogAsset == null)
        {
            throw new FileNotFoundException("找不到陆地区域中文名称表");
        }
        nameCatalog = new EarthRegionNameCatalog(nameCatalogAsset.text);
        dataset = new EarthRegionDataset(path);
        SetTimeMa(0f);
    }

    private void LateUpdate()
    {
        Camera camera = activeCamera != null ? activeCamera : Camera.main;
        if (camera == null)
        {
            return;
        }
        SetPoolWidth(hoverLines, PixelsToLocalWidth(camera, hoverWidthPixels));
        SetPoolWidth(selectedLines, PixelsToLocalWidth(camera, selectedWidthPixels));
    }

    public void SetTimeMa(float timeMa)
    {
        if (dataset == null)
        {
            return;
        }
        int requestedFrame = Mathf.Clamp(
            Mathf.RoundToInt(timeMa / dataset.FrameResolutionMa), 0, dataset.FrameCount - 1);
        if (requestedFrame == activeFrameIndex)
        {
            return;
        }

        activeFrame = dataset.LoadNearestFrame(timeMa);
        ValidateLocalizedNames(activeFrame);
        activeFrameIndex = activeFrame.FrameIndex;
        hoveredRegionId = -1;
        if (!string.IsNullOrEmpty(selectedRegionName) &&
            activeFrame.TryGetRegion(selectedRegionName, out EarthRegionDataset.Region selected))
        {
            selectedRegionId = selected.Id;
        }
        else
        {
            selectedRegionId = -1;
            selectedRegionName = null;
        }
        RefreshOutlines();
    }

    public void UpdateHover(Camera camera, Vector2 screenPosition)
    {
        activeCamera = camera;
        int nextRegionId = -1;
        if (camera != null && earthCollider != null)
        {
            Ray ray = camera.ScreenPointToRay(screenPosition);
            if (earthCollider.Raycast(ray, out RaycastHit hit, camera.farClipPlane))
            {
                Vector3 localDirection = transform.InverseTransformPoint(hit.point).normalized;
                nextRegionId = FindRegionId(localDirection);
            }
        }
        SetHoveredRegion(nextRegionId);
    }

    public bool UpdateHoverAtLocalDirection(Vector3 localDirection)
    {
        int regionId = FindRegionId(localDirection.normalized);
        SetHoveredRegion(regionId);
        return regionId >= 0;
    }

    public void ClearHover()
    {
        SetHoveredRegion(-1);
    }

    public void SelectHoveredOrClear()
    {
        selectedRegionId = hoveredRegionId;
        selectedRegionName = GetRegionSourceName(selectedRegionId);
        RefreshOutlines();
    }

    public void ClearSelection()
    {
        selectedRegionId = -1;
        selectedRegionName = null;
        RefreshOutlines();
    }

    public bool TryGetRepresentativeDirection(out Vector3 direction)
    {
        if (activeFrame != null && activeFrame.Regions.Length > 0 &&
            activeFrame.Regions[0].Polygons.Length > 0)
        {
            direction = activeFrame.Regions[0].Polygons[0].ConeCenter;
            return true;
        }
        direction = Vector3.zero;
        return false;
    }

    private int FindRegionId(Vector3 point)
    {
        if (activeFrame == null || point.sqrMagnitude < 0.99f)
        {
            return -1;
        }
        EarthRegionDataset.Region best = null;
        foreach (EarthRegionDataset.Region region in activeFrame.Regions)
        {
            bool contains = false;
            foreach (EarthRegionDataset.RegionPolygon polygon in region.Polygons)
            {
                if (Vector3.Dot(point, polygon.ConeCenter) + 1e-5f < polygon.ConeMinimumDot)
                {
                    continue;
                }
                if (PolygonContains(point, polygon))
                {
                    contains = true;
                    break;
                }
            }
            if (contains && (best == null || region.AreaKm2 < best.AreaKm2 ||
                (Mathf.Approximately(region.AreaKm2, best.AreaKm2) && region.Id < best.Id)))
            {
                best = region;
            }
        }
        return best != null ? best.Id : -1;
    }

    private static bool PolygonContains(Vector3 point, EarthRegionDataset.RegionPolygon polygon)
    {
        if (polygon.Rings.Length == 0 || !RingContains(point, polygon.Rings[0].Vertices))
        {
            return false;
        }
        for (int index = 1; index < polygon.Rings.Length; index++)
        {
            if (polygon.Rings[index].IsHole && RingContains(point, polygon.Rings[index].Vertices))
            {
                return false;
            }
        }
        return true;
    }

    private static bool RingContains(Vector3 point, Vector3[] vertices)
    {
        double winding = 0.0;
        for (int index = 0; index < vertices.Length; index++)
        {
            Vector3 first = vertices[index];
            Vector3 second = vertices[(index + 1) % vertices.Length];
            Vector3 firstTangent = first - point * Vector3.Dot(point, first);
            Vector3 secondTangent = second - point * Vector3.Dot(point, second);
            float firstLength = firstTangent.magnitude;
            float secondLength = secondTangent.magnitude;
            if (firstLength < 1e-6f || secondLength < 1e-6f)
            {
                return true;
            }
            firstTangent /= firstLength;
            secondTangent /= secondLength;
            winding += Math.Atan2(
                Vector3.Dot(point, Vector3.Cross(firstTangent, secondTangent)),
                Vector3.Dot(firstTangent, secondTangent));
        }
        return Math.Abs(winding) > Math.PI;
    }

    private void SetHoveredRegion(int regionId)
    {
        if (hoveredRegionId == regionId)
        {
            return;
        }
        hoveredRegionId = regionId;
        RefreshOutlines();
    }

    private string GetRegionSourceName(int regionId)
    {
        return activeFrame != null && regionId >= 0 &&
               activeFrame.TryGetRegion(regionId, out EarthRegionDataset.Region region)
            ? region.Name
            : null;
    }

    private string GetRegionDisplayName(int regionId)
    {
        string sourceName = GetRegionSourceName(regionId);
        return sourceName != null ? nameCatalog.GetDisplayName(sourceName) : null;
    }

    private void ValidateLocalizedNames(EarthRegionDataset.LoadedFrame frame)
    {
        foreach (EarthRegionDataset.Region region in frame.Regions)
        {
            nameCatalog.GetDisplayName(region.Name);
        }
    }

    private void RefreshOutlines()
    {
        EarthRegionDataset.Region selected = null;
        EarthRegionDataset.Region hovered = null;
        if (activeFrame != null)
        {
            if (selectedRegionId >= 0)
            {
                activeFrame.TryGetRegion(selectedRegionId, out selected);
            }
            if (hoveredRegionId >= 0 && hoveredRegionId != selectedRegionId)
            {
                activeFrame.TryGetRegion(hoveredRegionId, out hovered);
            }
        }
        RenderRegion(selected, selectedLines, new Color(1f, 1f, 1f, 1f));
        RenderRegion(hovered, hoverLines, new Color(1f, 1f, 1f, 0.9f));
        Camera camera = activeCamera != null ? activeCamera : Camera.main;
        if (camera != null)
        {
            SetPoolWidth(hoverLines, PixelsToLocalWidth(camera, hoverWidthPixels));
            SetPoolWidth(selectedLines, PixelsToLocalWidth(camera, selectedWidthPixels));
        }
    }

    private void RenderRegion(EarthRegionDataset.Region region, List<LineRenderer> pool, Color color)
    {
        int used = 0;
        if (region != null)
        {
            foreach (EarthRegionDataset.RegionPolygon polygon in region.Polygons)
            {
                foreach (EarthRegionDataset.RegionRing ring in polygon.Rings)
                {
                    LineRenderer line = GetLine(pool, used++);
                    line.startColor = color;
                    line.endColor = color;
                    line.positionCount = ring.Vertices.Length;
                    line.loop = true;
                    for (int index = 0; index < ring.Vertices.Length; index++)
                    {
                        line.SetPosition(index, ring.Vertices[index] * outlineRadius);
                    }
                    line.gameObject.SetActive(true);
                }
            }
        }
        for (int index = used; index < pool.Count; index++)
        {
            pool[index].gameObject.SetActive(false);
        }
    }

    private LineRenderer GetLine(List<LineRenderer> pool, int index)
    {
        if (index < pool.Count)
        {
            return pool[index];
        }
        GameObject lineObject = new GameObject("Region Outline");
        lineObject.transform.SetParent(transform, false);
        LineRenderer line = lineObject.AddComponent<LineRenderer>();
        line.useWorldSpace = false;
        line.sharedMaterial = outlineMaterial;
        line.alignment = LineAlignment.View;
        line.textureMode = LineTextureMode.Stretch;
        line.numCornerVertices = 2;
        line.numCapVertices = 2;
        line.shadowCastingMode = ShadowCastingMode.Off;
        line.receiveShadows = false;
        line.lightProbeUsage = LightProbeUsage.Off;
        line.reflectionProbeUsage = ReflectionProbeUsage.Off;
        line.widthMultiplier = 0.005f;
        pool.Add(line);
        return line;
    }

    private float PixelsToLocalWidth(Camera camera, float pixels)
    {
        float worldWidth;
        if (camera.orthographic)
        {
            worldWidth = camera.orthographicSize * 2f * pixels / Mathf.Max(1f, camera.pixelHeight);
        }
        else
        {
            float distance = Vector3.Distance(camera.transform.position, transform.position);
            float visibleHeight = 2f * distance * Mathf.Tan(camera.fieldOfView * 0.5f * Mathf.Deg2Rad);
            worldWidth = visibleHeight * pixels / Mathf.Max(1f, camera.pixelHeight);
        }
        Vector3 scale = transform.lossyScale;
        float uniformScale = (Mathf.Abs(scale.x) + Mathf.Abs(scale.y) + Mathf.Abs(scale.z)) / 3f;
        return worldWidth / Mathf.Max(1e-5f, uniformScale);
    }

    private static void SetPoolWidth(List<LineRenderer> pool, float width)
    {
        foreach (LineRenderer line in pool)
        {
            if (line.gameObject.activeSelf)
            {
                line.widthMultiplier = width;
            }
        }
    }

    private void OnDestroy()
    {
        dataset?.Dispose();
        DestroyPool(hoverLines);
        DestroyPool(selectedLines);
    }

    private static void DestroyPool(List<LineRenderer> pool)
    {
        foreach (LineRenderer line in pool)
        {
            if (line != null)
            {
                Destroy(line.gameObject);
            }
        }
    }
}
