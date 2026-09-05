using System.Diagnostics;
using System.IO;
using UnityEditor;
using UnityEngine;

namespace EarthEvents.Editor
{
    public static partial class EarthEventValidation
    {
        private static RenderTexture target;
        private static Texture2D readback;
        private static byte[] pixels;
        private static Process encoder;
        private static Camera captureCamera;
        private static RenderTexture previousTarget;
        private static float previousAspect;
        private static int captureFrame;
        private static Stopwatch captureTimer;

        private static void BeginCapture()
        {
            captureCamera = controller.ViewCamera;
            previousTarget = captureCamera.targetTexture; previousAspect = captureCamera.aspect;
            target = new RenderTexture(1920, 1080, 24, RenderTextureFormat.ARGB32);
            target.antiAliasing = 2; target.Create();
            readback = new Texture2D(1920, 1080, TextureFormat.RGBA32, false);
            pixels = new byte[1920 * 1080 * 4];
            captureCamera.targetTexture = target; captureCamera.aspect = 1920f / 1080f;

            Quaternion rotation = controller.EarthTransform.rotation;
            Vector3 position = captureCamera.transform.position;
            player.Evaluate(14f);
            controller.ResetView(); Snapshot("default-14s.png");
            controller.EarthTransform.rotation = rotation; captureCamera.transform.position = position;
            player.Evaluate(22f); Snapshot("focus-22s.png");
            controller.EarthTransform.rotation = Quaternion.AngleAxis(180f, captureCamera.transform.up) * rotation;
            player.Evaluate(14f); Snapshot("back-active.png");
            layer.EventsEnabled = false; Snapshot("back-disabled.png");
            layer.EventsEnabled = true;
            controller.RotateByScreenDelta(new Vector2(0.01f, 0f)); // 取消重新开启触发的自动镜头。
            controller.EarthTransform.rotation = rotation; captureCamera.transform.position = position;
            player.Evaluate(75f); layer.FocusImpact(); layer.AdvanceFocus(2f);
            Snapshot("preview-global-75s.png");
            player.DustVisible = false;
            captureCamera.transform.position = position; Snapshot("preview-crater-75s.png");
            player.DustVisible = true;

            // 已安装的本机编码器；不用 Shell 解释参数，不额外安装依赖。
            string ffmpeg = "/opt/homebrew/bin/ffmpeg";
            if (!File.Exists(ffmpeg)) throw new FileNotFoundException("录制需要已安装的 ffmpeg", ffmpeg);
            ProcessStartInfo info = new ProcessStartInfo(ffmpeg,
                "-y -loglevel error -f rawvideo -pixel_format rgba -video_size 1920x1080 -framerate 30 " +
                "-i pipe:0 -vf vflip -c:v libx264 -preset fast -crf 20 -pix_fmt yuv420p " + Output + "/chicxulub-aftermath.mp4")
            { UseShellExecute = false, RedirectStandardInput = true, RedirectStandardError = true, CreateNoWindow = true };
            encoder = Process.Start(info);
            encoder.ErrorDataReceived += (_, args) => { if (!string.IsNullOrEmpty(args.Data)) UnityEngine.Debug.LogWarning(args.Data); };
            encoder.BeginErrorReadLine();
            layer.ExitCinematicView(); layer.AdvanceFocus(2f);
            layer.Replay();
            layer.AutomaticFocusAdvance = false;
            captureFrame = 0; captureTimer = Stopwatch.StartNew();
        }

        private static void ReadFrame()
        {
            RenderTexture old = RenderTexture.active;
            captureCamera.Render(); RenderTexture.active = target;
            readback.ReadPixels(new Rect(0, 0, 1920, 1080), 0, 0, false);
            readback.Apply(false, false); RenderTexture.active = old;
        }

        private static void Snapshot(string name)
        {
            ReadFrame(); File.WriteAllBytes(Output + "/" + name, readback.EncodeToPNG());
        }

        private static void CaptureFrame()
        {
            int totalFrames = Mathf.RoundToInt(player.Definition.durationSeconds * 30f);
            if (captureFrame >= totalFrames)
            {
                stage = 3;
                captureTimer.Stop();
                player.Advance(player.Definition.durationSeconds);
                layer.AdvanceFocus(2f);
                Snapshot("aftermath-75s.png");
                player.DustVisible = false; Snapshot("aftermath-clear-75s.png");
                // 相同的最终坑体，用前半场近景机位检查不规则坑壁。
                captureCamera.transform.position = positionForCrater;
                Snapshot("persistent-crater-75s.png");
                player.DustVisible = true; layer.AdvanceFocus(2f);
                EndCapture();
                File.WriteAllText(Output + "/capture.txt", "PASS\n1920×1080 / 30 fps / " +
                    player.Definition.durationSeconds + " s / " + totalFrames + " frames\n" +
                    "离线录制耗时秒：" + captureTimer.Elapsed.TotalSeconds.ToString("F2") + "\n");
                SessionState.SetBool(SessionKey, false);
                player.AutomaticAdvance = true;
                ScreenCapture.CaptureScreenshot(Output + "/game-ui.png");
                UnityEngine.Debug.Log("撞击验收与1080p单次演出录像完成：" + Path.GetFullPath(Output));
                return;
            }
            player.Evaluate(captureFrame / 30f);
            layer.AdvanceFocus(1f / 30f);
            if (captureFrame == 450) positionForCrater = captureCamera.transform.position;
            ReadFrame();
            if (captureFrame == 0 || captureFrame == 120 || captureFrame == 183 || captureFrame == 210 ||
                captureFrame == 360 || captureFrame == 450 || captureFrame == 750 || captureFrame == 1200 ||
                captureFrame == 1800 || captureFrame == 2249)
                File.WriteAllBytes(Output + "/frame-" + captureFrame.ToString("D4") + ".png", readback.EncodeToPNG());
            readback.GetRawTextureData<byte>().CopyTo(pixels);
            encoder.StandardInput.BaseStream.Write(pixels, 0, pixels.Length);
            captureFrame++;
        }

        private static Vector3 positionForCrater;

        private static void EndCapture()
        {
            if (layer != null) layer.AutomaticFocusAdvance = true;
            if (captureCamera != null)
            { captureCamera.targetTexture = previousTarget; captureCamera.aspect = previousAspect; }
            if (target != null) { target.Release(); Object.DestroyImmediate(target); target = null; }
            if (readback != null) { Object.DestroyImmediate(readback); readback = null; }
            pixels = null;
            if (encoder != null)
            {
                encoder.StandardInput.Close();
                bool exited = encoder.WaitForExit(10000);
                if (!exited) encoder.Kill();
                int code = exited ? encoder.ExitCode : -1;
                encoder.Dispose(); encoder = null;
                if (code != 0) throw new System.InvalidOperationException("视频编码失败：" + code);
            }
        }
    }
}
