import inspect
import unittest

from app.services import transcriber, render


class Rx580AccelerationTests(unittest.TestCase):
    def test_transcribe_accepts_progress_callback(self):
        params = inspect.signature(transcriber.transcribe).parameters
        self.assertIn("progress_callback", params)

    def test_auto_backend_prefers_directml_on_windows_when_available(self):
        self.assertEqual(
            transcriber.resolve_backend("auto", platform_name="win32", directml_available=True),
            "directml",
        )

    def test_auto_backend_falls_back_to_faster_whisper(self):
        self.assertEqual(
            transcriber.resolve_backend("auto", platform_name="win32", directml_available=False),
            "faster-whisper",
        )

    def test_amf_encoder_args_use_rx580_hardware_encoder(self):
        args = render.video_encoder_args("h264_amf")
        self.assertIn("h264_amf", args)
        self.assertIn("-quality", args)
        self.assertNotIn("libx264", args)


if __name__ == "__main__":
    unittest.main()
