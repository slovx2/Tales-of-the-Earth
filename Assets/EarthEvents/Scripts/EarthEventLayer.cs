using UnityEngine;

namespace EarthEvents
{
    /// <summary>把时间轴状态适配为事件生命周期；禁用根节点可卸下整层。</summary>
    public sealed partial class EarthEventLayer : MonoBehaviour
    {
        [SerializeField] private EarthDemoController controller;
        [SerializeField] private ImpactSequencePlayer player;
        [SerializeField] private bool eventsEnabled = true;
        private bool eligible;
        private GUIStyle labelStyle, buttonStyle;

        public bool EventsEnabled
        {
            get => eventsEnabled;
            set
            {
                eventsEnabled = value;
                if (controller != null) HandleTimeline(controller.CurrentTimelineState);
            }
        }
        public ImpactSequencePlayer Player => player;
        public void Configure(EarthDemoController source, ImpactSequencePlayer sequence)
        { controller = source; player = sequence; }

        private void OnEnable()
        {
            if (controller == null || player == null) return;
            controller.TimelineStateChanged += HandleTimeline;
            controller.ViewManipulated += CancelFocus;
            controller.AdditionalUiHitTests.Add(HitTest);
        }

        private void Start()
        {
            if (controller != null) HandleTimeline(controller.CurrentTimelineState);
        }

        private void Update()
        {
            // Inspector 开关和重新激活根节点也使用同一入口；同态不重启。
            if (controller != null) HandleTimeline(controller.CurrentTimelineState);
        }

        private void HandleTimeline(EarthDemoController.TimelineState state)
        {
            bool next = eventsEnabled && player != null && player.Definition != null &&
                state.FormalFrameReady && !state.IsDragging &&
                Mathf.Approximately(state.TimeMa, player.Definition.eventTimeMa);
            if (next == eligible) return;
            eligible = next;
            if (next) { player.Play(); FocusImpact(); }
            else { CancelFocus(); cinematicView = false; player.StopAndReset(); }
        }

        private float UiScale => Mathf.Max(0.75f, Screen.height / 1080f);
        private Rect ControlsRect => new Rect(24f, 108f, 630f, 36f);
        private bool HitTest(Vector2 screenPoint) => ControlsRect.Contains(screenPoint / UiScale);

        private void OnGUI()
        {
            if (player == null) return;
            if (labelStyle == null)
            {
                labelStyle = new GUIStyle(GUI.skin.label) { fontSize = 16,
                    normal = { textColor = new Color(1f, 0.79f, 0.49f) } };
                buttonStyle = new GUIStyle(GUI.skin.button) { fontSize = 15 };
            }
            Matrix4x4 old = GUI.matrix;
            GUI.matrix = Matrix4x4.Scale(Vector3.one * UiScale);
            if (GUI.Button(new Rect(24f, 108f, 140f, 32f),
                eventsEnabled ? "事件动画：开" : "事件动画：关", buttonStyle))
                EventsEnabled = !eventsEnabled;
            GUI.enabled = eligible;
            if (GUI.Button(new Rect(174f, 108f, 170f, 32f),
                cinematicView ? "退出动画视角" : "进入动画视角", buttonStyle))
            { if (cinematicView) ExitCinematicView(); else FocusImpact(); }
            if (GUI.Button(new Rect(354f, 108f, 120f, 32f), "重新播放", buttonStyle)) Replay();
            if (GUI.Button(new Rect(484f, 108f, 150f, 32f),
                player.DustVisible ? "烟尘层：显示" : "烟尘层：隐藏", buttonStyle))
                player.DustVisible = !player.DustVisible;
            GUI.enabled = true;
            if (eligible)
            {
                GUI.Label(new Rect(24f, 150f, 670f, 28f),
                    "希克苏鲁伯撞击 · 约66 Ma｜尺寸与时序经艺术化处理", labelStyle);
                GUI.Label(new Rect(24f, 180f, 420f, 28f), player.StageLabel, labelStyle);
            }
            GUI.matrix = old;
        }

        private void OnDisable()
        {
            if (controller != null)
            {
                controller.TimelineStateChanged -= HandleTimeline;
                controller.ViewManipulated -= CancelFocus;
                controller.AdditionalUiHitTests.Remove(HitTest);
            }
            eligible = false;
            cinematicView = false;
            CancelFocus();
            if (player != null) player.StopAndReset();
        }
    }
}
