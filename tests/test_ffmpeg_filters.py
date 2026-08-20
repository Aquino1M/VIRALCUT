from __future__ import annotations

import shutil
import subprocess
import unittest

from app.services import render


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
class FfmpegFilterTests(unittest.TestCase):
    def test_smart_crop_filter_is_valid_ffmpeg_filtergraph(self):
        vf = render._crop_filter(0.50)
        proc = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=black:s=1920x1080:r=1:d=0.05",
                "-vf", vf,
                "-frames:v", "1", "-f", "null", "-",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_smart_crop_expression_escapes_filtergraph_commas(self):
        vf = render._crop_filter(0.50)
        self.assertIn(r"max(0\,min(iw-1080\,", vf)


if __name__ == "__main__":
    unittest.main()
