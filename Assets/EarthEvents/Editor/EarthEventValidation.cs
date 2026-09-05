using System;
using System.IO;
using UnityEditor;
using UnityEngine;

namespace EarthEvents.Editor
{
    [InitializeOnLoad]
    public static partial class EarthEventValidation
    {
        private const string SessionKey = "EarthEvents.Validation";
        private const string Output = ".local/validation/impact";
        private const string Request = ".local/validation/impact-request.txt";
        private static int stage, frames;
        private static double nextPoll, focusDeadline;
        private static EarthDemoController controller;
        private static EarthEventLayer layer;
        private static ImpactSequencePlayer player;

        static EarthEventValidation()
        {
            EditorApplication.update += Update;
            EditorApplication.playModeStateChanged += state =>
            {
                if (state == PlayModeStateChange.ExitingPlayMode)
                { SessionState.SetBool(SessionKey, false); EndCapture(); }
            };
            AssemblyReloadEvents.beforeAssemblyReload += () =>
            {
                if (encoder == null) return;
                SessionState.SetBool(SessionKey, false); EndCapture();
            };
        }

        [MenuItem("Earth Demo/Events/Validate and Record Impact")]
        public static void Run()
        {
            Directory.CreateDirectory(Output);
            if (File.Exists(Output + "/failure.txt")) File.Delete(Output + "/failure.txt");
            SessionState.SetBool(SessionKey, true);
            stage = 0; frames = 0;
            EditorApplication.isPaused = false;
            if (!EditorApplication.isPlaying) EditorApplication.EnterPlaymode();
        }

        private static void Update()
        {
            // 文件入口供本地验收自动化调用；只接受固定命令，不执行任意代码。
            if (EditorApplication.timeSinceStartup > nextPoll && !EditorApplication.isCompiling)
            {
                nextPoll = EditorApplication.timeSinceStartup + 1;
                if (File.Exists(Request))
                {
                    string command = File.ReadAllText(Request).Trim(); File.Delete(Request);
                    try
                    {
                        if (command == "install") EarthEventBuilder.InstallIntoOpenScene();
                        else if (command == "validate") Run();
                        else if (command == "regression") EarthDemoPlayValidation.Run();
                        else if (command == "stop") EditorApplication.isPlaying = false;
                        else throw new InvalidOperationException("未知验收命令：" + command);
                    }
                    catch (Exception exception) { Fail(exception); }
                }
            }
            if (!SessionState.GetBool(SessionKey, false) || !EditorApplication.isPlaying || ++frames < 15) return;
            try
            {
                if (stage == 0)
                {
                    controller = UnityEngine.Object.FindObjectOfType<EarthDemoController>();
                    layer = UnityEngine.Object.FindObjectOfType<EarthEventLayer>();
                    Require(controller != null && layer != null, "场景已安装事件层");
                    player = layer.Player;
                    player.AutomaticAdvance = false;
                    ValidateBehavior();
                    controller.ResetView(); controller.SetTimeMa(66f); layer.FocusImpact();
                    layer.AdvanceFocus(2f);
                    Require(!layer.IsFocusing, "两秒定位完成");
                    focusDeadline = EditorApplication.timeSinceStartup + 2.5;
                    stage = 1;
                }
                else if (stage == 1 && EditorApplication.timeSinceStartup > focusDeadline)
                {
                    BeginCapture(); stage = 2;
                }
                else if (stage == 2)
                    for (int i = 0; i < 8 && stage == 2; i++) CaptureFrame();
            }
            catch (Exception exception) { Fail(exception); }
        }

        private static void Require(bool condition, string message)
        {
            if (!condition) throw new InvalidOperationException("验收失败：" + message);
        }

        private static void ValidateBehavior()
        {
            controller.SetTimeMa(65f); Require(!player.IsPlaying, "65 Ma 不触发");
            controller.SetTimeMa(67f); Require(!player.IsPlaying, "67 Ma 不触发");
            controller.BeginTimelineDrag(); controller.SetTimeMa(66f);
            Require(!player.IsPlaying, "拖动经过66 Ma 不触发");
            controller.EndTimelineDrag(); controller.SetTimeMa(66f);
            Require(player.IsPlaying, "正式66 Ma帧停留后触发");
            player.Advance(4f); controller.SetTimeMa(66f);
            Require(Mathf.Approximately(player.PlaybackSeconds, 4f), "重复年代不重启");
            Require(Vector3.Distance(player.Definition.SiteDirection,
                new Vector3(0.42317491f, 0.80178574f, 0.42197467f)) < 0.00001f, "重建坐标和 Y 反射");
            layer.FocusImpact(); controller.RotateByScreenDelta(new Vector2(4f, 2f));
            Require(!layer.IsFocusing, "手动旋转中止自动镜头");
            layer.FocusImpact(); controller.ResetView(); Require(!layer.IsFocusing, "重置中止自动镜头");
            layer.ExitCinematicView(); layer.AdvanceFocus(2f);
            Vector3 returnPosition = controller.ViewCamera.transform.position;
            Quaternion returnRotation = controller.EarthTransform.rotation;
            layer.FocusImpact(); layer.AdvanceFocus(2f);
            Vector3 siteWorld = controller.EarthTransform.TransformPoint(player.Definition.SiteDirection * 0.5f);
            Vector3 viewport = controller.ViewCamera.WorldToViewportPoint(siteWorld);
            Require(Mathf.Abs(viewport.x - 0.5f) < 0.05f && Mathf.Abs(viewport.y - 0.5f) < 0.08f,
                "近景撞击点保持画面中心");
            layer.ExitCinematicView(); layer.AdvanceFocus(2f);
            Require(Vector3.Distance(returnPosition, controller.ViewCamera.transform.position) < 0.001f &&
                Quaternion.Angle(returnRotation, controller.EarthTransform.rotation) < 0.01f, "退出动画视角恢复进入前视角");
            Renderer ocean = controller.GetComponent<Renderer>();
            MaterialPropertyBlock block = new MaterialPropertyBlock();
            ocean.GetPropertyBlock(block); block.SetFloat("_ValidationSentinel", 17f); ocean.SetPropertyBlock(block);
            foreach (float second in new[] { 4f, 6.4f, 14f, 23f, 45f, 75f })
            {
                player.Evaluate(second); layer.EventsEnabled = false;
                Require(!player.IsPlaying && player.VisibleParticleCount == 0, "任意阶段关闭后清空粒子");
                Require(!player.HasPersistentCrater && player.GlobalDustCoverage == 0f, "关闭后清空坑体和全球烟尘");
                ocean.GetPropertyBlock(block);
                Require(block.GetFloat("_SurfacePatchVisibility") == 0f, "关闭后还原海洋遮罩");
                Require(block.GetFloat("_ValidationSentinel") == 17f, "保留其他系统的材质属性");
                layer.EventsEnabled = true;
                Require(player.IsPlaying && player.PlaybackSeconds == 0f, "重新开启从零播放");
            }
            player.Evaluate(14f); layer.gameObject.SetActive(false);
            Require(!player.IsPlaying, "关闭根节点会停止动画");
            ocean.GetPropertyBlock(block); Require(block.GetFloat("_SurfacePatchVisibility") == 0f, "关闭根节点清理遮罩");
            controller.SetTimeMa(67f); Require(controller.ActiveFrameTimeMa == 67f, "禁用模块后地球仍可切年代");
            layer.gameObject.SetActive(true); controller.SetTimeMa(66f);
            Require(player.IsPlaying, "重新激活根节点后恢复订阅");
            int objects = UnityEngine.Object.FindObjectsOfType<Transform>(true).Length;
            int materials = Resources.FindObjectsOfTypeAll<Material>().Length;
            player.StopAndReset(); player.Play();
            long memoryBefore = GC.GetTotalMemory(true);
            long allocatedBefore = GC.GetAllocatedBytesForCurrentThread();
            var timer = System.Diagnostics.Stopwatch.StartNew();
            for (int frame = 0; frame < 2250; frame++) player.Advance(1f / 30f);
            timer.Stop();
            long allocated = GC.GetAllocatedBytesForCurrentThread() - allocatedBefore;
            long retained = GC.GetTotalMemory(true) - memoryBefore;
            File.WriteAllText(Output + "/performance.txt", "2250 frames / 75 seconds / single playback\n" +
                "平均动画求值CPU毫秒：" + (timer.Elapsed.TotalMilliseconds / 2250).ToString("F4") + "\n" +
                "托管分配字节：" + allocated + "\n托管保留增量字节：" + retained + "\n" +
                "场景Transform数量：" + objects + "\nMaterial数量：" + materials + "\n");
            Require(retained < 1024 * 1024, "单次完整演出无持续托管内存增长");
            player.Advance(150f); player.Play(); controller.SetTimeMa(66f);
            Require(player.IsCompleted && !player.IsPlaying && player.PlaybackSeconds == 75f,
                "结束后停在75秒，不自动循环，同年代和Play不重播");
            Require(player.HasPersistentCrater && player.GlobalDustCoverage == 1f, "完成态保留坑体和全球烟尘");
            player.DustVisible = false;
            Require(player.HasPersistentCrater && player.PlaybackSeconds == 75f, "隐藏烟尘不影响保留坑和时钟");
            layer.Replay();
            Require(player.IsPlaying && !player.IsCompleted && player.PlaybackSeconds == 0f &&
                !player.HasPersistentCrater && player.GlobalDustCoverage == 0f && player.DustVisible,
                "重新播放先清空灾后画面并恢复烟尘可见性");
            Require(objects == UnityEngine.Object.FindObjectsOfType<Transform>(true).Length, "重新播放复用对象");
            Require(materials == Resources.FindObjectsOfTypeAll<Material>().Length, "重新播放复用材质");
            player.Evaluate(14f); int particleCount = player.VisibleParticleCount;
            player.Evaluate(23f); player.Evaluate(14f);
            Require(player.VisibleParticleCount == particleCount, "随机访问阶段具有确定性");
            controller.SetTimeMa(65f); Require(!player.IsPlaying, "离开年代清空事件");
            foreach (string name in new[] { "EarthEvents/ImpactRock", "EarthEvents/ImpactParticle",
                "EarthEvents/ImpactWave", "EarthEvents/ImpactDust", "Earth/DynamicOcean", "Earth/DynamicLand" })
            {
                Shader shader = Shader.Find(name);
                Require(shader != null && !ShaderUtil.ShaderHasError(shader), "Shader 编译：" + name);
            }
            File.WriteAllText(Output + "/behavior.txt", "PASS\n触发、拖动、同年代幂等、75秒单次结束保持、重播清理、全球烟尘开关、近景居中、视角恢复、根节点禁用、属性还原、资源复用、确定性、坐标、Shader 检查通过。\n");
            Debug.Log("撞击行为专项验收通过，开始录制。");
        }

        private static void Fail(Exception exception)
        {
            SessionState.SetBool(SessionKey, false);
            EndCapture(); Directory.CreateDirectory(Output);
            File.WriteAllText(Output + "/failure.txt", exception.ToString());
            Debug.LogException(exception);
        }
    }
}
