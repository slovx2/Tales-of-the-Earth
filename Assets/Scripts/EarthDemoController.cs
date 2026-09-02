using UnityEngine;

public sealed class EarthDemoController : MonoBehaviour
{
    [SerializeField] private Transform earth;
    [SerializeField] private DynamicLandRenderer landRenderer;
    [SerializeField] private DynamicTerrainRenderer terrainRenderer;
    [SerializeField] private DynamicRegionHighlighter regionHighlighter;
    [SerializeField] private float dragSensitivity = 0.35f;
    [SerializeField] private float zoomSensitivity = 1.2f;

    private bool dragging;
    private bool pointerTracking;
    private Vector3 lastMouse;
    private Vector3 pointerDownPosition;
    private Camera demoCamera;
    private float timeMa;
    private GUIStyle timelinePanelStyle;
    private GUIStyle timelineTrackStyle;
    private GUIStyle timelineThumbStyle;
    private GUIStyle titleStyle;
    private GUIStyle detailStyle;
    private GUIStyle tickStyle;
    private GUIStyle resetButtonStyle;
    private GUIStyle regionPanelStyle;
    private GUIStyle regionLabelStyle;
    private Texture2D panelTexture;
    private Texture2D trackTexture;
    private Texture2D thumbTexture;
    private Vector3 defaultCameraPosition;

    public float CurrentTimeMa => timeMa;
    public float ActiveFrameTimeMa => landRenderer != null ? landRenderer.ActiveFrameTimeMa : -1f;

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
        if (regionHighlighter == null)
        {
            regionHighlighter = earth.GetComponent<DynamicRegionHighlighter>();
        }
        if (demoCamera != null)
        {
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
        bool pointerOverUi = IsPointerOverUi(Input.mousePosition);
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
                Vector3 position = demoCamera.transform.position;
                position.z = Mathf.Clamp(position.z - scroll * zoomSensitivity, -10f, -3.2f);
                demoCamera.transform.position = position;
            }
        }

        if (dragging || pointerOverUi)
        {
            regionHighlighter?.ClearHover();
        }
        else
        {
            regionHighlighter?.UpdateHover(demoCamera, Input.mousePosition);
        }
    }

    private void OnGUI()
    {
        EnsureGuiStyles();
        GUI.Label(new Rect(24f, 18f, 520f, 30f), "EARTH EVOLUTION · 动态几何原型", titleStyle);
        GUI.Label(new Rect(24f, 48f, 680f, 24f),
            "左键点击选择 · 左键拖动旋转 · 滚轮缩放 · 时间轴精度 1 Ma", detailStyle);
        if (GUI.Button(GetResetButtonRect(), "重置视角（北极朝上）", resetButtonStyle))
        {
            ResetView();
        }

        Rect regionPanel = GetRegionPanelRect();
        GUI.Box(regionPanel, GUIContent.none, regionPanelStyle);
        string hovered = regionHighlighter != null && !string.IsNullOrEmpty(regionHighlighter.HoveredRegionName)
            ? regionHighlighter.HoveredRegionName
            : "—";
        string selected = regionHighlighter != null && !string.IsNullOrEmpty(regionHighlighter.SelectedRegionName)
            ? regionHighlighter.SelectedRegionName
            : "—";
        GUI.Label(new Rect(regionPanel.x + 12f, regionPanel.y + 8f, regionPanel.width - 24f, 28f),
            $"悬停：{hovered}", regionLabelStyle);
        GUI.Label(new Rect(regionPanel.x + 12f, regionPanel.y + 39f, regionPanel.width - 24f, 28f),
            $"已选择：{selected}", regionLabelStyle);

        Rect panel = GetTimelinePanelRect();
        GUI.Box(panel, GUIContent.none, timelinePanelStyle);
        GUI.Label(new Rect(panel.x + 20f, panel.y + 12f, 180f, 24f), "地质时间", titleStyle);
        string statistics = landRenderer == null
            ? "几何数据未加载"
            : $"{timeMa:0} Ma  ·  几何帧 {landRenderer.ActiveFrameTimeMa:0} Ma  ·  " +
              $"{landRenderer.ActiveVertexCount:N0} 顶点  ·  切帧 {landRenderer.LastLoadMilliseconds:0.0} ms";
        GUI.Label(new Rect(panel.x + 180f, panel.y + 14f, panel.width - 200f, 22f), statistics, detailStyle);

        float maxTimeMa = landRenderer != null && landRenderer.MaxTimeMa > 0f ? landRenderer.MaxTimeMa : 1000f;
        if (terrainRenderer != null && terrainRenderer.MaxTimeMa > 0f)
        {
            maxTimeMa = Mathf.Min(maxTimeMa, terrainRenderer.MaxTimeMa);
        }
        Rect sliderRect = new Rect(panel.x + 22f, panel.y + 43f, panel.width - 44f, 22f);
        float timelinePosition = maxTimeMa - timeMa;
        float nextPosition = GUI.HorizontalSlider(
            sliderRect, timelinePosition, 0f, maxTimeMa, timelineTrackStyle, timelineThumbStyle);
        float nextTimeMa = Mathf.Round(maxTimeMa - nextPosition);
        if (!Mathf.Approximately(nextTimeMa, timeMa))
        {
            SetTimeMa(nextTimeMa);
        }

        float tickY = panel.y + 69f;
        GUI.Label(new Rect(panel.x + 18f, tickY, 120f, 20f), $"{maxTimeMa:0} Ma", tickStyle);
        GUI.Label(new Rect(panel.center.x - 55f, tickY, 110f, 20f), $"{maxTimeMa * 0.5f:0} Ma", tickStyle);
        GUI.Label(new Rect(panel.xMax - 138f, tickY, 120f, 20f), "0 Ma · 现在", tickStyle);
    }

    public void SetTimeMa(float value)
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
        timeMa = Mathf.Round(Mathf.Clamp(value, 0f, maximum));
        landRenderer?.SetTimeMa(timeMa);
        terrainRenderer?.SetTimeMa(timeMa);
        regionHighlighter?.SetTimeMa(timeMa);
    }

    public void RotateByScreenDelta(Vector2 delta)
    {
        if (earth == null || demoCamera == null || delta.sqrMagnitude < 0.0001f)
        {
            return;
        }
        Vector3 rotationAxis = -delta.x * demoCamera.transform.up + delta.y * demoCamera.transform.right;
        float rotationAngle = delta.magnitude * dragSensitivity;
        earth.rotation = Quaternion.AngleAxis(rotationAngle, rotationAxis.normalized) * earth.rotation;
    }

    /// <summary>将地理北极（数据坐标 +Z）对齐到屏幕上方，并恢复默认缩放。</summary>
    public void ResetView()
    {
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

    private static Rect GetTimelinePanelRect()
    {
        float width = Mathf.Min(Screen.width - 36f, 860f);
        return new Rect((Screen.width - width) * 0.5f, Screen.height - 108f, width, 92f);
    }

    private static Rect GetResetButtonRect()
    {
        return new Rect(Screen.width - 205f, 18f, 181f, 32f);
    }

    private static Rect GetRegionPanelRect()
    {
        float width = Mathf.Min(360f, Mathf.Max(240f, Screen.width * 0.30f));
        return new Rect(Screen.width - width - 24f, 60f, width, 76f);
    }

    private static bool IsPointerOverUi(Vector3 mousePosition)
    {
        Vector2 guiPosition = new Vector2(mousePosition.x, Screen.height - mousePosition.y);
        return GetTimelinePanelRect().Contains(guiPosition) ||
               GetResetButtonRect().Contains(guiPosition) ||
               GetRegionPanelRect().Contains(guiPosition);
    }

    private void EnsureGuiStyles()
    {
        if (timelinePanelStyle != null)
        {
            return;
        }
        panelTexture = MakeTexture(new Color(0.035f, 0.075f, 0.14f, 0.96f));
        trackTexture = MakeTexture(new Color(0.20f, 0.52f, 0.82f, 1f));
        thumbTexture = MakeTexture(new Color(0.35f, 0.92f, 1f, 1f));
        timelinePanelStyle = new GUIStyle(GUI.skin.box) { normal = { background = panelTexture } };
        timelineTrackStyle = new GUIStyle(GUI.skin.horizontalSlider)
        {
            fixedHeight = 6f,
            normal = { background = trackTexture },
        };
        timelineThumbStyle = new GUIStyle(GUI.skin.horizontalSliderThumb)
        {
            fixedWidth = 16f,
            fixedHeight = 24f,
            normal = { background = thumbTexture },
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
        tickStyle = new GUIStyle(detailStyle) { alignment = TextAnchor.MiddleCenter, fontSize = 12 };
        resetButtonStyle = new GUIStyle(GUI.skin.button)
        {
            fontSize = 12,
            fontStyle = FontStyle.Bold,
            normal = { textColor = Color.white },
        };
        regionPanelStyle = new GUIStyle(GUI.skin.box) { normal = { background = panelTexture } };
        regionLabelStyle = new GUIStyle(GUI.skin.label)
        {
            fontSize = 13,
            alignment = TextAnchor.MiddleLeft,
            clipping = TextClipping.Clip,
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
        if (trackTexture != null) Destroy(trackTexture);
        if (thumbTexture != null) Destroy(thumbTexture);
    }
}
