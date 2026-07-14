import unittest
import sys
from pathlib import Path, PureWindowsPath

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rmdedit.cli import pandoc_path


class PandocPathTests(unittest.TestCase):
    def test_windows_path_uses_forward_slashes(self) -> None:
        path = PureWindowsPath(
            "C:/Users/example/privat/rmdedit-templates-privat/assets/fonts"
        )

        self.assertEqual(
            pandoc_path(path),
            "C:/Users/example/privat/rmdedit-templates-privat/assets/fonts",
        )

    def test_posix_path_is_unchanged(self) -> None:
        path = Path("/home/example/rmdedit/assets/fonts")

        self.assertEqual(pandoc_path(path), "/home/example/rmdedit/assets/fonts")


if __name__ == "__main__":
    unittest.main()
