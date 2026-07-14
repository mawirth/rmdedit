import sys
import tempfile
import unittest
from pathlib import Path, PureWindowsPath
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rmdedit.cli import file_state, pandoc_path, recoverable_windows_r_shutdown


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


class WindowsRShutdownTests(unittest.TestCase):
    def test_accepts_complete_new_pdf_for_signed_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / "output.pdf"
            with patch("rmdedit.cli.sys.platform", "win32"):
                pdf.write_bytes(b"%PDF-1.7\ncontent\n%%EOF\n")

                self.assertTrue(
                    recoverable_windows_r_shutdown(-1073741569, pdf, None)
                )

    def test_accepts_unsigned_windows_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / "output.pdf"
            with patch("rmdedit.cli.sys.platform", "win32"):
                pdf.write_bytes(b"%PDF-1.7\ncontent\n%%EOF\n")

                self.assertTrue(
                    recoverable_windows_r_shutdown(0xC00000FF, pdf, None)
                )

    def test_rejects_unchanged_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / "output.pdf"
            pdf.write_bytes(b"%PDF-1.7\ncontent\n%%EOF\n")
            previous_state = file_state(pdf)
            with patch("rmdedit.cli.sys.platform", "win32"):
                self.assertFalse(
                    recoverable_windows_r_shutdown(
                        -1073741569, pdf, previous_state
                    )
                )

    def test_rejects_incomplete_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pdf = Path(directory) / "output.pdf"
            pdf.write_bytes(b"%PDF-1.7\nincomplete")
            with patch("rmdedit.cli.sys.platform", "win32"):
                self.assertFalse(
                    recoverable_windows_r_shutdown(-1073741569, pdf, None)
                )


if __name__ == "__main__":
    unittest.main()
