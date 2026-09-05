using System.Collections.Generic;
using System.Text;
using UnityEngine;

public sealed class EarthDemoController : MonoBehaviour
{
    private const float GuiScaleMultiplier = 0.6f;
    private const float CameraVerticalFramingOffset = -0.45f;
    private const float TimelinePrimaryUpdateInterval = 1f / 24f;
    private const float TimelineRegionUpdateInterval = 1f / 10f;

    [SerializeField] private Transform earth;
    [SerializeField] private DynamicLandRenderer landRenderer;
    [SerializeField] private DynamicTerrainRenderer terrainRenderer;
    [SerializeField] private DynamicClimateRenderer climateRenderer;
    [SerializeField] private DynamicRegionHighlighter regionHighlighter;
    [SerializeField] private float dragSensitivity = 0.35f;
    [SerializeField] private float zoomSensitivity = 1.2f;
    [SerializeField] private Vector2 guiReferenceResolution = new Vector2(960f, 540f);
    [SerializeField] private TimelineScaleMode timelineScaleMode = TimelineScaleMode.RealProportion;

    private bool dragging;
    private bool pointerTracking;
    private bool timelineDragging;
    private bool hasPendingTimelineTime;
    private Vector3 lastMouse;
    private Vector3 pointerDownPosition;
    private Camera demoCamera;
    private float timeMa;
    private float pendingTimelineTimeMa;
    private float lastPrimaryTimelineUpdateTime = float.NegativeInfinity;
    private float lastRegionTimelineUpdateTime = float.NegativeInfinity;
    private float lastPrimaryAppliedTimeMa = float.NaN;
    private float lastRegionAppliedTimeMa = float.NaN;
    private GUIStyle timelinePanelStyle;
    private GUIStyle timelineInputStyle;
    private GUIStyle titleStyle;
    private GUIStyle detailStyle;
    private GUIStyle breadcrumbStyle;
    private GUIStyle periodLabelStyle;
    private GUIStyle narrowPeriodLabelStyle;
    private GUIStyle currentTimeStyle;
    private GUIStyle modeActiveStyle;
    private GUIStyle modeInactiveStyle;
    private GUIStyle resetButtonStyle;
    private GUIStyle regionPanelStyle;
    private GUIStyle regionLabelStyle;
    private Texture2D panelTexture;
    private Texture2D whiteTexture;
    private Texture2D transparentTexture;
    private Texture2D modeActiveTexture;
    private Texture2D modeInactiveTexture;
    private Texture2D resetTexture;
    private Vector3 defaultCameraPosition;

    public float CurrentTimeMa => timeMa;
    public float ActiveFrameTimeMa => landRenderer != null ? landRenderer.ActiveFrameTimeMa : -1f;
    public TimelineScaleMode CurrentTimelineScaleMode => timelineScaleMode;

    // 通用观察接口：事件层只订阅状态，不参与地球数据加载。
    public readonly struct TimelineState
    {
        public readonly float TimeMa;
        public readonly bool IsDragging;
        public readonly bool FormalFrameReady;
        public TimelineState(float time, bool drag, bool ready)
        { TimeMa = time; IsDragging = drag; FormalFrameReady = ready; }
    }
    public event System.Action<TimelineState> TimelineStateChanged;
    public event System.Action ViewManipulated;
    public readonly List<System.Func<Vector2, bool>> AdditionalUiHitTests =
        new List<System.Func<Vector2, bool>>();
    public TimelineState CurrentTimelineState => new TimelineState(timeMa, timelineDragging,
        !timelineDragging && landRenderer != null && !landRenderer.IsPreviewMode &&
        Mathf.Approximately(ActiveFrameTimeMa, timeMa) &&
        (terrainRenderer == null || Mathf.Approximately(terrainRenderer.ActiveFrameTimeMa, timeMa)));
    public Transform EarthTransform => earth;
    public Camera ViewCamera => demoCamera;

    private void Awake()
    {
        demoCamera = Camera.main;
        if (earth == null)
        {
            earth = transform;
        }
        if (landRenderer == null)
        {
            landRenderer = earth.GetComponentInChildren<DynamicLandRenderer>();
        }
        if (terrainRenderer == null)
        {
            terrainRenderer = earth.GetComponent<DynamicTerrainRenderer>();
        }
        if (climateRenderer == null)
        {
            climateRenderer = earth.GetComponent<DynamicClimateRenderer>();
        }
        if (regionHighlighter == null)
        {
            regionHighlighter = earth.GetComponent<DynamicRegionHighlighter>();
        }
        if (demoCamera != null)
        {
            // UI 时间轴固定在底部，运行时把相机整体下移以抬高地球画面。
            Vector3 framingPosition = demoCamera.transform.position;
            framingPosition.y += CameraVerticalFramingOffset;
            demoCamera.transform.position = framingPosition;
            // 相机下移后重新对准地球附近的观察中心，避免沿用场景中偏低的
            // LookAt 目标导致地球整体被推到屏幕上方。
            Vector3 framingTarget = earth.position;
            framingTarget.y -= 0.45f;
            demoCamera.transform.LookAt(framingTarget);
            defaultCameraPosition = demoCamera.transform.position;
        }
        ResetView();
        SetTimeMa(0f);
        Application.targetFrameRate = 60;
    }

    private void Update()
    {
        if (Input.GetKeyDown(KeyCode.R))
        {
            ResetView();
        }
        bool pointerOverUi = IsPointerOverUi(Input.mousePosition, GetGuiScale());
        if (Input.GetMouseButtonDown(0) && !pointerOverUi)
        {
            pointerTracking = true;
            dragging = false;
            pointerDownPosition = Input.mousePosition;
            lastMouse = Input.mousePosition;
        }
        if (pointerTracking && Input.GetMouseButton(0))
        {
            if (!dragging && (Input.mousePosition - pointerDownPosition).sqrMagnitude >= 36f)
            {
                dragging = true;
            }
            if (dragging)
            {
                Vector2 delta = Input.mousePosition - lastMouse;
                RotateByScreenDelta(delta);
                lastMouse = Input.mousePosition;
            }
        }
        if (Input.GetMouseButtonUp(0))
        {
            if (pointerTracking && !dragging && !pointerOverUi)
            {
                regionHighlighter?.UpdateHover(demoCamera, Input.mousePosition);
                regionHighlighter?.SelectHoveredOrClear();
            }
            pointerTracking = false;
            dragging = false;
        }
        else if (!Input.GetMouseButton(0) && pointerTracking)
        {
            pointerTracking = false;
            dragging = false;
        }

        if (demoCamera != null)
        {
            float scroll = Input.mouseScrollDelta.y;
            if (Mathf.Abs(scroll) > 0.001f)
            {
                ViewManipulated?.Invoke();
                // 沿当前观察射线缩放，保留近景构图的横向偏移，避免动画视角首次滚轮跳回远处。
                Vector3 position = demoCamera.transform.position + demoCamera.transform.forward * scroll * zoomSensitivity;
                Vector3 offset = position - earth.position;
                float minimumDistance = earth.lossyScale.x * 0.5f * 1.12f;
                demoCamera.transform.position = earth.position + offset.normalized *
                    Mathf.Clamp(offset.magnitude, minimumDistance, 10f);
            }
        }

        if (dragging || timelineDragging || pointerOverUi)
        {
            regionHighlighter?.ClearHover();
        }
        else
        {
            regionHighlighter?.UpdateHover(demoCamera, Input.mousePosition);
        }

        if (timelineDragging && !Input.GetMouseButton(0))
        {
            EndTimelineDrag();
            ApplyPendingTimelineTime(true);
        }
        else
        {
            ApplyPendingTimelineTime(false);
        }
    }

    private void OnGUI()
    {
        EnsureGuiStyles();
        float guiScale = GetGuiScale();
        float guiWidth = Screen.width / guiScale;
        float guiHeight = Screen.height / guiScale;
        Matrix4x4 previousGuiMatrix = GUI.matrix;
        GUI.matrix = Matrix4x4.Scale(new Vector3(guiScale, guiScale, 1f));

        GUI.Label(new Rect(24f, 18f, 560f, 30f), "EARTH EVOLUTION · 动态几何原型", titleStyle);
        DrawCurrentGeologicBreadcrumb(guiWidth);
        if (GUI.Button(GetResetButtonRect(guiWidth), "重置视角（北极朝上）", resetButtonStyle))
        {
            ResetView();
        }

        Rect regionPanel = GetRegionPanelRect(guiWidth);
        GUI.Box(regionPanel, GUIContent.none, regionPanelStyle);
        DrawOutlineRect(regionPanel, new Color(0.38f, 0.62f, 0.82f, 0.85f));
        string hovered = regionHighlighter != null
            ? BuildBreadcrumbText(regionHighlighter.HoveredBreadcrumb)
            : "—";
        string selected = regionHighlighter != null
            ? BuildBreadcrumbText(regionHighlighter.SelectedBreadcrumb)
            : "—";
        GUI.Label(new Rect(regionPanel.x + 12f, regionPanel.y + 7f, regionPanel.width - 24f, 43f),
            $"悬停：{hovered}", regionLabelStyle);
        GUI.Label(new Rect(regionPanel.x + 12f, regionPanel.y + 53f, regionPanel.width - 24f, 43f),
            $"已选择：{selected}", regionLabelStyle);

        Rect panel = GetTimelinePanelRect(guiWidth, guiHeight);
        DrawTimeline(panel);

        GUI.matrix = previousGuiMatrix;
    }

    private void DrawCurrentGeologicBreadcrumb(float guiWidth)
    {
        GeologicPeriod period;
        GeologicEpoch epoch;
        GeologicTimeScale.TryGetCurrent(timeMa, out period, out epoch);
        string text = period.HasEpochs
            ? $"当前：{period.DisplayName} → {epoch.DisplayName}"
            : $"当前：{period.DisplayName}";
        GUI.Label(new Rect(24f, 50f, Mathf.Min(700f, guiWidth - 48f), 32f), text, breadcrumbStyle);
    }

    private void DrawTimeline(Rect panel)
    {
        GUI.Box(panel, GUIContent.none, timelinePanelStyle);
        DrawOutlineRect(panel, new Color(0.38f, 0.62f, 0.82f, 0.85f));
        GUI.Label(new Rect(panel.x + 20f, panel.y + 12f, 180f, 28f), "地质时间", titleStyle);
        DrawScaleModeButtons(panel);

        float maxTimeMa = GetMaximumTimeMa();
        Rect bandRect = new Rect(panel.x + 22f, panel.y + 76f, panel.width - 44f, 28f);
        IReadOnlyList<GeologicPeriod> periods = GeologicTimeScale.Periods;
        for (int index = 0; index < periods.Count; index++)
        {
            GeologicPeriod period = periods[index];
            float start = GeologicTimeScale.TimeToNormalizedPosition(
                period.OlderMa, maxTimeMa, timelineScaleMode);
            float end = GeologicTimeScale.TimeToNormalizedPosition(
                period.YoungerMa, maxTimeMa, timelineScaleMode);
            Rect segment = new Rect(
                bandRect.x + bandRect.width * start,
                bandRect.y,
                Mathf.Max(1f, bandRect.width * (end - start)),
                bandRect.height);
            DrawRect(segment, period.Color);
            DrawRect(new Rect(segment.x, segment.y, segment.width, 1f), new Color(0.45f, 0.78f, 1f, 0.9f));
            DrawRect(new Rect(segment.x, segment.yMax - 1f, segment.width, 1f), new Color(0.08f, 0.2f, 0.34f, 0.9f));
            DrawPeriodLabel(period, index, segment);
        }

        Rect inputRect = new Rect(bandRect.x - 12f, bandRect.y - 32f, bandRect.width + 24f, 76f);
        float normalizedPosition = GeologicTimeScale.TimeToNormalizedPosition(
            timeMa, maxTimeMa, timelineScaleMode);
        Event timelineEvent = Event.current;
        bool timelineEventTarget = inputRect.Contains(timelineEvent.mousePosition);
        bool releaseTimelineDrag = false;
        if (timelineEventTarget && timelineEvent.type == EventType.MouseDown && timelineEvent.button == 0)
        {
            BeginTimelineDrag();
        }
        else if (timelineDragging && timelineEvent.type == EventType.MouseUp && timelineEvent.button == 0)
        {
            releaseTimelineDrag = true;
        }
        float nextNormalizedPosition = GUI.HorizontalSlider(
            inputRect, normalizedPosition, 0f, 1f, timelineInputStyle, timelineInputStyle);
        if (!Mathf.Approximately(nextNormalizedPosition, normalizedPosition))
        {
            normalizedPosition = nextNormalizedPosition;
            RequestTimelineTime(Mathf.Round(GeologicTimeScale.NormalizedPositionToTime(
                nextNormalizedPosition, maxTimeMa, timelineScaleMode)));
        }
        if (releaseTimelineDrag)
        {
            EndTimelineDrag();
            ApplyPendingTimelineTime(true);
        }

        DrawEpochTicks(panel, bandRect, maxTimeMa);
        float playheadX = bandRect.x + bandRect.width * normalizedPosition;
        DrawRect(new Rect(playheadX - 1f, bandRect.y - 16f, 2f, 56f), new Color(0.2f, 0.9f, 1f, 0.9f));
        DrawRect(new Rect(playheadX - 7f, bandRect.y - 22f, 14f, 14f), new Color(0.45f, 0.95f, 1f, 1f));
        DrawRect(new Rect(playheadX - 4f, bandRect.y - 19f, 8f, 8f), new Color(0.05f, 0.2f, 0.35f, 1f));

        Rect currentTimeRect = new Rect(
            Mathf.Clamp(playheadX - 70f, panel.x + 12f, panel.xMax - 152f),
            panel.y + 140f,
            140f,
            28f);
        GUI.Box(currentTimeRect, GUIContent.none, timelinePanelStyle);
        GUI.Label(currentTimeRect, $"当前时间：{timeMa:0} Ma", currentTimeStyle);
    }

    private void DrawScaleModeButtons(Rect panel)
    {
        float buttonWidth = 92f;
        float buttonY = panel.y + 12f;
        float firstX = panel.xMax - buttonWidth * 2f - 28f;
        if (GUI.Button(new Rect(firstX, buttonY, buttonWidth, 26f), "真实比例",
                timelineScaleMode == TimelineScaleMode.RealProportion ? modeActiveStyle : modeInactiveStyle))
        {
            timelineScaleMode = TimelineScaleMode.RealProportion;
        }
        if (GUI.Button(new Rect(firstX + buttonWidth + 4f, buttonY, buttonWidth + 16f, 26f), "年代等比例",
                timelineScaleMode == TimelineScaleMode.EqualPeriod ? modeActiveStyle : modeInactiveStyle))
        {
            timelineScaleMode = TimelineScaleMode.EqualPeriod;
        }
    }

    private void DrawPeriodLabel(GeologicPeriod period, int index, Rect segment)
    {
        if (timelineScaleMode == TimelineScaleMode.EqualPeriod)
        {
            GUI.Label(segment, period.DisplayName, periodLabelStyle);
            return;
        }
        bool placeBelowAxis = index == 11;
        float labelY;
        if (index == 10)
        {
            labelY = segment.y - 34f;
        }
        else if (index == 12)
        {
            labelY = segment.y - 18f;
        }
        else
        {
            labelY = placeBelowAxis
                ? segment.yMax + 18f
                : segment.y - (index % 2 == 0 ? 34f : 18f);
        }
        float labelWidth = 70f;
        float guiWidth = Screen.width / GetGuiScale();
        float labelX = Mathf.Clamp(segment.center.x - labelWidth * 0.5f, 8f, guiWidth - labelWidth - 8f);
        GUI.Label(new Rect(labelX, labelY, labelWidth, 18f), period.DisplayName, narrowPeriodLabelStyle);
        if (placeBelowAxis)
        {
            DrawRect(new Rect(segment.center.x, segment.yMax, 1f, labelY - segment.yMax),
                new Color(0.3f, 0.75f, 0.95f, 0.65f));
        }
        else
        {
            DrawRect(new Rect(segment.center.x, labelY + 18f, 1f, segment.y - labelY - 18f),
                new Color(0.3f, 0.75f, 0.95f, 0.65f));
        }
    }

    private void DrawEpochTicks(Rect panel, Rect bandRect, float maxTimeMa)
    {
        Color tickColor = new Color(0.25f, 0.72f, 0.86f, 0.85f);
        float tickY = bandRect.yMax + 9f;
        foreach (GeologicPeriod period in GeologicTimeScale.Periods)
        {
            foreach (GeologicEpoch epoch in period.Epochs)
            {
                float position = GeologicTimeScale.TimeToNormalizedPosition(
                    epoch.OlderMa, maxTimeMa, timelineScaleMode);
                float x = bandRect.x + bandRect.width * position;
                DrawRect(new Rect(x, tickY, 1f, 7f), tickColor);
            }
        }
    }

    private float GetMaximumTimeMa()
    {
        float maximum = landRenderer != null && landRenderer.MaxTimeMa > 0f ? landRenderer.MaxTimeMa : 1000f;
        if (terrainRenderer != null && terrainRenderer.MaxTimeMa > 0f)
        {
            maximum = Mathf.Min(maximum, terrainRenderer.MaxTimeMa);
        }
        if (regionHighlighter != null && regionHighlighter.MaxTimeMa > 0f)
        {
            maximum = Mathf.Min(maximum, regionHighlighter.MaxTimeMa);
        }
        return maximum;
    }

    private void DrawRect(Rect rect, Color color)
    {
        Color previousColor = GUI.color;
        GUI.color = color;
        GUI.DrawTexture(rect, whiteTexture);
        GUI.color = previousColor;
    }

    private void DrawOutlineRect(Rect rect, Color color)
    {
        DrawRect(new Rect(rect.x, rect.y, rect.width, 1f), color);
        DrawRect(new Rect(rect.x, rect.yMax - 1f, rect.width, 1f), color);
        DrawRect(new Rect(rect.x, rect.y, 1f, rect.height), color);
        DrawRect(new Rect(rect.xMax - 1f, rect.y, 1f, rect.height), color);
    }

    public void SetTimeMa(float value)
    {
        timeMa = ClampAndRoundTime(value);
        pendingTimelineTimeMa = timeMa;
        hasPendingTimelineTime = true;
        ApplyPendingTimelineTime(true);
    }

    private void RequestTimelineTime(float value)
    {
        timeMa = ClampAndRoundTime(value);
        pendingTimelineTimeMa = timeMa;
        hasPendingTimelineTime = true;
        ApplyPendingTimelineTime(false);
    }

    private void ApplyPendingTimelineTime(bool force)
    {
        if (!hasPendingTimelineTime)
        {
            return;
        }

        float now = Time.unscaledTime;
        bool updatePrimary = force || !timelineDragging ||
                             now - lastPrimaryTimelineUpdateTime >= TimelinePrimaryUpdateInterval;
        if (updatePrimary && !Mathf.Approximately(lastPrimaryAppliedTimeMa, pendingTimelineTimeMa))
        {
            landRenderer?.SetTimeMa(pendingTimelineTimeMa);
            terrainRenderer?.SetTimeMa(pendingTimelineTimeMa);
            climateRenderer?.SetTimeMa(pendingTimelineTimeMa);
            lastPrimaryAppliedTimeMa = pendingTimelineTimeMa;
            lastPrimaryTimelineUpdateTime = now;
        }

        // 拖动期间不解析区域帧，避免边界重建抢占游标和预览几何的更新预算。
        bool updateRegion = !timelineDragging && (force ||
                            now - lastRegionTimelineUpdateTime >= TimelineRegionUpdateInterval);
        if (updateRegion && !Mathf.Approximately(lastRegionAppliedTimeMa, pendingTimelineTimeMa))
        {
            regionHighlighter?.SetTimeMa(pendingTimelineTimeMa);
            lastRegionAppliedTimeMa = pendingTimelineTimeMa;
            lastRegionTimelineUpdateTime = now;
        }

        hasPendingTimelineTime = !Mathf.Approximately(lastPrimaryAppliedTimeMa, pendingTimelineTimeMa) ||
                                 !Mathf.Approximately(lastRegionAppliedTimeMa, pendingTimelineTimeMa);
        TimelineStateChanged?.Invoke(CurrentTimelineState);
    }

    public void BeginTimelineDrag()
    {
        if (timelineDragging) return;
        timelineDragging = true;
        regionHighlighter?.ClearHover();
        landRenderer?.SetPreviewMode(true);
        TimelineStateChanged?.Invoke(CurrentTimelineState);
    }

    public void EndTimelineDrag()
    {
        if (!timelineDragging) return;
        timelineDragging = false;
        landRenderer?.SetPreviewMode(false);
        TimelineStateChanged?.Invoke(CurrentTimelineState);
    }

    private float ClampAndRoundTime(float value)
    {
        float maximum = landRenderer != null && landRenderer.MaxTimeMa > 0f ? landRenderer.MaxTimeMa : 1000f;
        if (terrainRenderer != null && terrainRenderer.MaxTimeMa > 0f)
        {
            maximum = Mathf.Min(maximum, terrainRenderer.MaxTimeMa);
        }
        if (regionHighlighter != null && regionHighlighter.MaxTimeMa > 0f)
        {
            maximum = Mathf.Min(maximum, regionHighlighter.MaxTimeMa);
        }
        return Mathf.Round(Mathf.Clamp(value, 0f, maximum));
    }

    public void SetTimelineScaleMode(TimelineScaleMode mode)
    {
        timelineScaleMode = mode;
    }

    public void RotateByScreenDelta(Vector2 delta)
    {
        if (earth == null || demoCamera == null || delta.sqrMagnitude < 0.0001f)
        {
            return;
        }
        Vector3 rotationAxis = -delta.x * demoCamera.transform.up + delta.y * demoCamera.transform.right;
        ViewManipulated?.Invoke();
        float rotationAngle = delta.magnitude * dragSensitivity;
        earth.rotation = Quaternion.AngleAxis(rotationAngle, rotationAxis.normalized) * earth.rotation;
    }

    /// <summary>将地理北极（数据坐标 +Z）对齐到屏幕上方，并恢复默认缩放。</summary>
    public void ResetView()
    {
        ViewManipulated?.Invoke();
        if (earth != null && demoCamera != null)
        {
            earth.rotation = Quaternion.LookRotation(demoCamera.transform.up, -demoCamera.transform.forward);
        }
        if (demoCamera != null && defaultCameraPosition != Vector3.zero)
        {
            demoCamera.transform.position = defaultCameraPosition;
        }
        dragging = false;
        pointerTracking = false;
    }

    private static Rect GetTimelinePanelRect(float screenWidth, float screenHeight)
    {
        float width = Mathf.Max(320f, screenWidth - 8f);
        // 面板只包住标题、纪条、世刻度和当前时间，避免底部出现大块空白。
        const float panelHeight = 172f;
        const float bottomMargin = 18f;
        return new Rect(
            (screenWidth - width) * 0.5f,
            screenHeight - panelHeight - bottomMargin,
            width,
            panelHeight);
    }

    private static Rect GetResetButtonRect(float screenWidth)
    {
        return new Rect(screenWidth - 205f, 18f, 181f, 32f);
    }

    private static Rect GetRegionPanelRect(float screenWidth)
    {
        float width = Mathf.Min(360f, Mathf.Max(240f, screenWidth * 0.30f));
        return new Rect(screenWidth - width - 24f, 60f, width, 104f);
    }

    private static string BuildBreadcrumbText(
        IReadOnlyList<DynamicRegionHighlighter.BreadcrumbItem> items)
    {
        if (items == null || items.Count == 0)
        {
            return "—";
        }
        StringBuilder builder = new StringBuilder();
        for (int index = 0; index < items.Count; index++)
        {
            if (index > 0)
            {
                builder.Append(" › ");
            }
            DynamicRegionHighlighter.BreadcrumbItem item = items[index];
            builder.Append("<color=#");
            builder.Append(ColorUtility.ToHtmlStringRGB(item.Color));
            builder.Append('>');
            builder.Append(item.DisplayName);
            builder.Append("</color>");
        }
        return builder.ToString();
    }

    private bool IsPointerOverUi(Vector3 mousePosition, float guiScale)
    {
        Vector2 screenPoint = new Vector2(mousePosition.x, Screen.height - mousePosition.y);
        foreach (System.Func<Vector2, bool> hitTest in AdditionalUiHitTests)
            if (hitTest(screenPoint)) return true;
        float guiWidth = Screen.width / guiScale;
        float guiHeight = Screen.height / guiScale;
        Vector2 guiPosition = new Vector2(mousePosition.x / guiScale, guiHeight - mousePosition.y / guiScale);
        return GetTimelinePanelRect(guiWidth, guiHeight).Contains(guiPosition) ||
               GetResetButtonRect(guiWidth).Contains(guiPosition) ||
               GetRegionPanelRect(guiWidth).Contains(guiPosition);
    }

    private float GetGuiScale()
    {
        float referenceWidth = Mathf.Max(1f, guiReferenceResolution.x);
        float referenceHeight = Mathf.Max(1f, guiReferenceResolution.y);
        float resolutionScale = Mathf.Min(Screen.width / referenceWidth, Screen.height / referenceHeight);
        return Mathf.Max(0.5f, Mathf.Max(1f, resolutionScale) * GuiScaleMultiplier);
    }

    private void EnsureGuiStyles()
    {
        if (timelinePanelStyle != null)
        {
            return;
        }
        panelTexture = MakeTexture(new Color(0.025f, 0.065f, 0.13f, 0.92f));
        whiteTexture = MakeTexture(Color.white);
        transparentTexture = MakeTexture(new Color(1f, 1f, 1f, 0f));
        timelinePanelStyle = new GUIStyle(GUI.skin.box) { normal = { background = panelTexture } };
        timelineInputStyle = new GUIStyle(GUI.skin.horizontalSlider)
        {
            fixedHeight = 40f,
            normal = { background = transparentTexture },
            hover = { background = transparentTexture },
            active = { background = transparentTexture },
        };
        titleStyle = new GUIStyle(GUI.skin.label)
        {
            fontSize = 17,
            fontStyle = FontStyle.Bold,
            normal = { textColor = Color.white },
        };
        detailStyle = new GUIStyle(GUI.skin.label)
        {
            fontSize = 13,
            alignment = TextAnchor.MiddleRight,
            normal = { textColor = new Color(0.72f, 0.86f, 1f) },
        };
        breadcrumbStyle = new GUIStyle(GUI.skin.label)
        {
            fontSize = 20,
            fontStyle = FontStyle.Bold,
            normal = { textColor = new Color(0.35f, 0.9f, 1f) },
        };
        periodLabelStyle = new GUIStyle(GUI.skin.label)
        {
            fontSize = 14,
            fontStyle = FontStyle.Bold,
            alignment = TextAnchor.MiddleCenter,
            normal = { textColor = Color.white },
        };
        narrowPeriodLabelStyle = new GUIStyle(periodLabelStyle)
        {
            fontSize = 11,
            normal = { textColor = new Color(0.7f, 0.9f, 1f) },
        };
        currentTimeStyle = new GUIStyle(GUI.skin.label)
        {
            fontSize = 12,
            alignment = TextAnchor.MiddleCenter,
            normal = { textColor = new Color(0.35f, 0.92f, 1f) },
        };
        modeActiveTexture = MakeTexture(new Color(0.08f, 0.38f, 0.55f, 0.95f));
        modeInactiveTexture = MakeTexture(new Color(0.04f, 0.12f, 0.2f, 0.9f));
        resetTexture = MakeTexture(new Color(0.04f, 0.23f, 0.36f, 0.95f));
        modeActiveStyle = new GUIStyle(GUI.skin.button)
        {
            fontSize = 11,
            fontStyle = FontStyle.Bold,
            normal = { textColor = Color.white, background = modeActiveTexture },
        };
        modeInactiveStyle = new GUIStyle(GUI.skin.button)
        {
            fontSize = 11,
            normal = { textColor = new Color(0.62f, 0.76f, 0.88f), background = modeInactiveTexture },
        };
        resetButtonStyle = new GUIStyle(GUI.skin.button)
        {
            fontSize = 12,
            fontStyle = FontStyle.Bold,
            normal = { textColor = Color.white, background = resetTexture },
        };
        regionPanelStyle = new GUIStyle(GUI.skin.box) { normal = { background = panelTexture } };
        regionLabelStyle = new GUIStyle(GUI.skin.label)
        {
            fontSize = 13,
            alignment = TextAnchor.UpperLeft,
            clipping = TextClipping.Clip,
            richText = true,
            wordWrap = true,
            normal = { textColor = Color.white },
        };
    }

    private static Texture2D MakeTexture(Color color)
    {
        Texture2D texture = new Texture2D(1, 1, TextureFormat.RGBA32, false)
        {
            hideFlags = HideFlags.HideAndDontSave,
        };
        texture.SetPixel(0, 0, color);
        texture.Apply();
        return texture;
    }

    private void OnDestroy()
    {
        if (panelTexture != null) Destroy(panelTexture);
        if (whiteTexture != null) Destroy(whiteTexture);
        if (transparentTexture != null) Destroy(transparentTexture);
        if (modeActiveTexture != null) Destroy(modeActiveTexture);
        if (modeInactiveTexture != null) Destroy(modeInactiveTexture);
        if (resetTexture != null) Destroy(resetTexture);
    }
}
