from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WindowsSetupScriptTests(unittest.TestCase):
    def test_amd_setup_can_install_python_312_automatically(self):
        text = (ROOT / "setup_amd_gpu.bat").read_text(encoding="utf-8", errors="replace").lower()
        self.assertIn("winget install", text)
        self.assertIn("python.python.3.12", text)
        self.assertIn("--accept-package-agreements", text)

    def test_amd_setup_uses_unpinned_current_torch_directml(self):
        text = (ROOT / "setup_amd_gpu.bat").read_text(encoding="utf-8", errors="replace").lower()
        self.assertIn("pip install --upgrade torch-directml", text)
        self.assertNotIn("torch-directml==", text)


if __name__ == "__main__":
    unittest.main()
