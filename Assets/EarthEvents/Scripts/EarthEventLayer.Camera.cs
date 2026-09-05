using UnityEngine;

namespace EarthEvents
{
    public sealed partial class EarthEventLayer
    {
        private bool focusing, cinematicView, trackSequence;
        private float focusTime;
        private Quaternion startRotation, targetRotation, returnRotation;
        private Vector3 startCamera, targetCamera, returnCamera, closeCamera, wideCamera;
        public bool IsFocusing => focusing;
        public bool IsCinematicView => cinematicView;
        public bool AutomaticFocusAdvance { get; set; } = true;

        public void Replay()
        {
            if (!eligible) return;
            player.Replay();
            player.DustVisible = true;
            FocusImpact();
        }

        public void FocusImpact()
        {
            if (!eligible || controller.ViewCamera == null) return;
            Transform earth = controller.EarthTransform;
            Camera camera = controller.ViewCamera;
            if (!cinematicView)
            {
                returnRotation = earth.rotation;
                returnCamera = camera.transform.position;
            }
            cinematicView = true; trackSequence = true;
            Vector3 north = Vector3.ProjectOnPlane(Vector3.forward, player.Definition.SiteDirection).normalized;
            // 参考图中的右上球缘位置；平移相机后使撞击点居中，保留斜视曲率。
            Vector3 normal = (-camera.transform.forward * 0.57f + camera.transform.right * 0.36f +
                camera.transform.up * 0.74f).normalized;
            targetRotation = Quaternion.LookRotation(normal, camera.transform.up) *
                Quaternion.Inverse(Quaternion.LookRotation(player.Definition.SiteDirection, north));
            float radius = earth.lossyScale.x * 0.5f;
            Vector3 siteWorld = earth.position + normal * radius;
            closeCamera = siteWorld - camera.transform.forward * (radius * 1.25f) + camera.transform.up * radius * 0.04f;
            // 后半场逐渐拉远，呈现烟尘覆盖全球；玩家操作后立即停止镜头编排。
            float wideDistance = radius * 1.28f / Mathf.Tan(camera.fieldOfView * 0.5f * Mathf.Deg2Rad);
            wideCamera = earth.position - camera.transform.forward * wideDistance - camera.transform.up * radius * 0.10f;
            targetCamera = SequenceCameraPosition();
            BeginFocus();
        }

        public void ExitCinematicView()
        {
            if (!cinematicView) return;
            cinematicView = false; trackSequence = false;
            targetRotation = returnRotation; targetCamera = returnCamera;
            BeginFocus();
        }

        private void BeginFocus()
        {
            startRotation = controller.EarthTransform.rotation;
            startCamera = controller.ViewCamera.transform.position;
            focusTime = 0f; focusing = true;
        }

        private Vector3 SequenceCameraPosition()
        {
            float pullback = Mathf.SmoothStep(0f, 1f, Mathf.InverseLerp(32f, 60f, player.PlaybackSeconds));
            return Vector3.Lerp(closeCamera, wideCamera, pullback);
        }

        private void LateUpdate()
        { if (AutomaticFocusAdvance) AdvanceFocus(Time.unscaledDeltaTime); }

        public void AdvanceFocus(float seconds)
        {
            if (cinematicView && trackSequence) targetCamera = SequenceCameraPosition();
            if (!focusing)
            {
                if (cinematicView && trackSequence) controller.ViewCamera.transform.position = targetCamera;
                return;
            }
            focusTime += Mathf.Max(0f, seconds);
            float blend = Mathf.SmoothStep(0f, 1f, focusTime / 2f);
            controller.EarthTransform.rotation = Quaternion.Slerp(startRotation, targetRotation, blend);
            controller.ViewCamera.transform.position = Vector3.Lerp(startCamera, targetCamera, blend);
            if (focusTime >= 2f) focusing = false;
        }

        private void CancelFocus() { focusing = false; trackSequence = false; }
    }
}
