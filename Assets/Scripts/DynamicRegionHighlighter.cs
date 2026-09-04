using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;
using UnityEngine.Rendering;

[RequireComponent(typeof(SphereCollider))]
public sealed class DynamicRegionHighlighter : MonoBehaviour
{
    private static readonly string[] TopologyTypeSuffixes =
    {
        "板块", "大陆", "陆块", "地块", "地体", "克拉通", "盆地", "台地",
        "组合体", "岛弧", "增生区", "核心",
    };
    [SerializeField] private string datasetRelativePath = "EarthRegions/region_frames.bin";
    [SerializeField] private SphereCollider earthCollider;
    [SerializeField] private Material outlineMaterial;
    [SerializeField] private float outlineRadius = 0.5045f;
    [SerializeField] private float hoverLeafWidthPixels = 3f;
    [SerializeField] private float selectedLeafWidthPixels = 4f;

    private readonly List<LineRenderer> outlineLines = new List<LineRenderer>();
    private readonly List<float> outlinePixelWidths = new List<float>();
    private readonly List<BreadcrumbItem> hoveredBreadcrumb = new List<BreadcrumbItem>();
    private readonly List<BreadcrumbItem> selectedBreadcrumb = new List<BreadcrumbItem>();
    private EarthRegionDataset dataset;
    private EarthRegionNameCatalog nameCatalog;
    private EarthRegionDataset.LoadedFrame activeFrame;
    private EarthRegionDataset.SelectionKey[] selectedPath;
    private Camera activeCamera;
    private int activeFrameIndex = -1;
    private ulong hoveredRegionId;
    private ulong selectedRegionId;

    public float FrameResolutionMa => dataset != null ? dataset.FrameResolutionMa : 0f;
    public float MaxTimeMa => dataset != null ? dataset.MaxTimeMa : 0f;
    public float MinimumAreaKm2 => dataset != null ? dataset.MinimumAreaKm2 : 0f;
    public float ActiveFrameTimeMa => activeFrame != null ? activeFrame.TimeMa : -1f;
    public int ActiveRegionCount => activeFrame != null ? activeFrame.Nodes.Length : 0;
    public int LocalizedRegionCount => nameCatalog != null ? nameCatalog.Count : 0;
    public string HoveredRegionName => GetRegionDisplayName(hoveredRegionId);
    public string SelectedRegionName => GetRegionDisplayName(selectedRegionId);
    public string HoveredRegionOriginalName => GetRegionSourceName(hoveredRegionId);
    public string SelectedRegionOriginalName => GetRegionSourceName(selectedRegionId);
    public IReadOnlyList<BreadcrumbItem> HoveredBreadcrumb => hoveredBreadcrumb;
    public IReadOnlyList<BreadcrumbItem> SelectedBreadcrumb => selectedBreadcrumb;

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
        for (int index = 0; index < outlineLines.Count; index++)
        {
            if (outlineLines[index].gameObject.activeSelf)
            {
                outlineLines[index].widthMultiplier =
                    PixelsToLocalWidth(camera, outlinePixelWidths[index]);
            }
        }
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

        EarthRegionDataset.SelectionKey[] previousPath = selectedPath;
        activeFrame = dataset.LoadNearestFrame(timeMa);
        ValidateLocalizedNames(activeFrame);
        activeFrameIndex = activeFrame.FrameIndex;
        hoveredRegionId = 0;
        if (activeFrame.TryResolveSelection(previousPath, out EarthRegionDataset.RegionNode selected))
        {
            selectedRegionId = selected.InstanceId;
            selectedPath = activeFrame.CreateSelectionPath(selected);
        }
        else
        {
            selectedRegionId = 0;
            selectedPath = null;
        }
        RefreshPresentation();
    }

    public void UpdateHover(Camera camera, Vector2 screenPosition)
    {
        activeCamera = camera;
        ulong nextRegionId = 0;
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
        ulong regionId = FindRegionId(localDirection.normalized);
        SetHoveredRegion(regionId);
        return regionId != 0;
    }

    public void ClearHover()
    {
        SetHoveredRegion(0);
    }

    public void SelectHoveredOrClear()
    {
        selectedRegionId = hoveredRegionId;
        if (TryGetNode(selectedRegionId, out EarthRegionDataset.RegionNode selected))
        {
            selectedPath = activeFrame.CreateSelectionPath(selected);
        }
        else
        {
            selectedPath = null;
        }
        RefreshPresentation();
    }

    public void ClearSelection()
    {
        selectedRegionId = 0;
        selectedPath = null;
        RefreshPresentation();
    }

    public bool TryGetRepresentativeDirection(out Vector3 direction)
    {
        if (activeFrame != null)
        {
            for (int index = activeFrame.Nodes.Length - 1; index >= 0; index--)
            {
                EarthRegionDataset.RegionNode node = activeFrame.Nodes[index];
                if (node.Interactable && node.Polygons.Length > 0 && !string.IsNullOrEmpty(node.Name))
                {
                    direction = node.Polygons[0].ConeCenter;
                    return true;
                }
            }
        }
        direction = Vector3.zero;
        return false;
    }

    private ulong FindRegionId(Vector3 point)
    {
        if (activeFrame == null || point.sqrMagnitude < 0.99f)
        {
            return 0;
        }
        EarthRegionDataset.RegionNode best = null;
        foreach (EarthRegionDataset.RegionNode node in activeFrame.Nodes)
        {
            if (!node.Interactable || !NodeContains(point, node))
            {
                continue;
            }
            if (best == null || node.Level > best.Level ||
                (node.Level == best.Level && (node.AreaKm2 < best.AreaKm2 ||
                 (Mathf.Approximately(node.AreaKm2, best.AreaKm2) &&
                  node.InstanceId < best.InstanceId))))
            {
                best = node;
            }
        }
        return best != null ? best.InstanceId : 0;
    }

    private static bool NodeContains(Vector3 point, EarthRegionDataset.RegionNode node)
    {
        foreach (EarthRegionDataset.RegionPolygon polygon in node.Polygons)
        {
            if (Vector3.Dot(point, polygon.ConeCenter) + 1e-5f >= polygon.ConeMinimumDot &&
                PolygonContains(point, polygon))
            {
                return true;
            }
        }
        return false;
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

    private void SetHoveredRegion(ulong regionId)
    {
        if (hoveredRegionId == regionId)
        {
            return;
        }
        hoveredRegionId = regionId;
        RefreshPresentation();
    }

    private bool TryGetNode(ulong instanceId, out EarthRegionDataset.RegionNode node)
    {
        if (activeFrame != null && instanceId != 0)
        {
            return activeFrame.TryGetNode(instanceId, out node);
        }
        node = null;
        return false;
    }

    private string GetRegionSourceName(ulong instanceId)
    {
        return TryGetNode(instanceId, out EarthRegionDataset.RegionNode node)
            ? node.Name
            : null;
    }

    private string GetRegionDisplayName(ulong instanceId)
    {
        return TryGetNode(instanceId, out EarthRegionDataset.RegionNode node)
            ? GetDisplayName(node)
            : null;
    }

    private string GetDisplayName(EarthRegionDataset.RegionNode node)
    {
        if (!string.IsNullOrEmpty(node.Name))
        {
            string displayName = nameCatalog.GetDisplayName(
                node.Name, node.Kind == EarthRegionDataset.RegionNodeKind.Topology);
            if (node.Kind == EarthRegionDataset.RegionNodeKind.Topology &&
                !HasTopologyTypeSuffix(displayName))
            {
                displayName += "板块";
            }
            return displayName;
        }
        return node.Kind == EarthRegionDataset.RegionNodeKind.Topology
            ? $"未命名板块（{node.PlateId}）"
            : $"未命名陆地区域（{node.PlateId}）";
    }

    private static bool HasTopologyTypeSuffix(string value)
    {
        foreach (string suffix in TopologyTypeSuffixes)
        {
            if (value.EndsWith(suffix, StringComparison.Ordinal))
            {
                return true;
            }
        }
        return false;
    }

    private void ValidateLocalizedNames(EarthRegionDataset.LoadedFrame frame)
    {
        foreach (EarthRegionDataset.RegionNode node in frame.Nodes)
        {
            if (!string.IsNullOrEmpty(node.Name))
            {
                nameCatalog.GetDisplayName(node.Name);
            }
        }
    }

    private void RefreshPresentation()
    {
        BuildBreadcrumb(hoveredRegionId, hoveredBreadcrumb);
        BuildBreadcrumb(selectedRegionId, selectedBreadcrumb);

        Dictionary<ulong, OutlineRequest> requests = new Dictionary<ulong, OutlineRequest>();
        AddOutlineChain(selectedRegionId, true, requests);
        AddOutlineChain(hoveredRegionId, false, requests);
        List<OutlineRequest> ordered = new List<OutlineRequest>(requests.Values);
        ordered.Sort((first, second) =>
        {
            int levelComparison = first.Node.Level.CompareTo(second.Node.Level);
            return levelComparison != 0
                ? levelComparison
                : first.Node.InstanceId.CompareTo(second.Node.InstanceId);
        });
        RenderOutlines(ordered);
    }

    private void BuildBreadcrumb(ulong instanceId, List<BreadcrumbItem> destination)
    {
        destination.Clear();
        if (!TryGetNode(instanceId, out EarthRegionDataset.RegionNode node))
        {
            return;
        }
        foreach (EarthRegionDataset.RegionNode ancestor in activeFrame.GetAncestorChain(node))
        {
            destination.Add(new BreadcrumbItem(
                GetDisplayName(ancestor), ancestor.Name, ancestor.Level, GetLevelColor(ancestor.Level)));
        }
    }

    private void AddOutlineChain(ulong instanceId, bool selected,
                                 Dictionary<ulong, OutlineRequest> requests)
    {
        if (!TryGetNode(instanceId, out EarthRegionDataset.RegionNode node))
        {
            return;
        }
        EarthRegionDataset.RegionNode[] chain = activeFrame.GetAncestorChain(node);
        for (int index = 0; index < chain.Length; index++)
        {
            float leafWidth = selected ? selectedLeafWidthPixels : hoverLeafWidthPixels;
            float width = Mathf.Min(selected ? 12f : 11f,
                leafWidth + (chain.Length - 1 - index) * 2f);
            OutlineRequest request = new OutlineRequest(chain[index], selected, width);
            if (!requests.TryGetValue(chain[index].InstanceId, out OutlineRequest existing) ||
                (selected && !existing.Selected))
            {
                requests[chain[index].InstanceId] = request;
            }
        }
    }

    private void RenderOutlines(List<OutlineRequest> requests)
    {
        int used = 0;
        foreach (OutlineRequest request in requests)
        {
            Color color = GetLevelColor(request.Node.Level);
            color.a = request.Selected ? 1f : 0.9f;
            float radius = outlineRadius + Mathf.Min(request.Node.Level, 10) * 0.00015f;
            foreach (EarthRegionDataset.RegionPolygon polygon in request.Node.Polygons)
            {
                foreach (EarthRegionDataset.RegionRing ring in polygon.Rings)
                {
                    LineRenderer line = GetLine(used);
                    line.startColor = color;
                    line.endColor = color;
                    line.sortingOrder = request.Node.Level;
                    line.positionCount = ring.Vertices.Length;
                    line.loop = true;
                    for (int vertexIndex = 0; vertexIndex < ring.Vertices.Length; vertexIndex++)
                    {
                        line.SetPosition(vertexIndex, ring.Vertices[vertexIndex] * radius);
                    }
                    outlinePixelWidths[used] = request.WidthPixels;
                    line.gameObject.SetActive(true);
                    used++;
                }
            }
        }
        for (int index = used; index < outlineLines.Count; index++)
        {
            outlineLines[index].gameObject.SetActive(false);
        }
        LateUpdate();
    }

    private LineRenderer GetLine(int index)
    {
        if (index < outlineLines.Count)
        {
            return outlineLines[index];
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
        outlineLines.Add(line);
        outlinePixelWidths.Add(1f);
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

    public static Color GetLevelColor(int level)
    {
        switch (level)
        {
            case 1: return new Color32(0xFF, 0x9F, 0x1C, 0xFF);
            case 2: return new Color32(0xB5, 0x6C, 0xFF, 0xFF);
            case 3: return new Color32(0x35, 0xA7, 0xFF, 0xFF);
            case 4: return new Color32(0x4E, 0xD4, 0x7B, 0xFF);
            default: return Color.white;
        }
    }

    private void OnDestroy()
    {
        dataset?.Dispose();
        foreach (LineRenderer line in outlineLines)
        {
            if (line != null)
            {
                Destroy(line.gameObject);
            }
        }
    }

    public readonly struct BreadcrumbItem
    {
        public readonly string DisplayName;
        public readonly string OriginalName;
        public readonly int Level;
        public readonly Color Color;

        public BreadcrumbItem(string displayName, string originalName, int level, Color color)
        {
            DisplayName = displayName;
            OriginalName = originalName;
            Level = level;
            Color = color;
        }
    }

    private readonly struct OutlineRequest
    {
        public readonly EarthRegionDataset.RegionNode Node;
        public readonly bool Selected;
        public readonly float WidthPixels;

        public OutlineRequest(EarthRegionDataset.RegionNode node, bool selected, float widthPixels)
        {
            Node = node;
            Selected = selected;
            WidthPixels = widthPixels;
        }
    }
}
