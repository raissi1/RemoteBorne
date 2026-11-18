"""Explicit secondary-window icons must work in source and portable layouts."""
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from src.utils_ui import apply_window_icon


class TestSecondaryWindowIcons(unittest.TestCase):
    def test_each_window_gets_its_own_icon(self):
        windows = [Mock(), Mock()]
        expected = str(Path(__file__).resolve().parents[1] / 'BorneCommander.ico')
        with patch('src.utils_ui.sys.platform', 'win32'):
            for window in windows:
                self.assertTrue(apply_window_icon(window))
                window.iconbitmap.assert_called_once_with(expected)

    def test_portable_bundle_resource_is_preferred(self):
        with tempfile.TemporaryDirectory() as directory:
            icon = Path(directory) / 'BorneCommander.ico'
            icon.touch()
            window = Mock()
            with patch('src.utils_ui.sys.platform', 'win32'), \
                 patch('src.utils_ui.sys._MEIPASS', directory, create=True):
                self.assertTrue(apply_window_icon(window))
            window.iconbitmap.assert_called_once_with(str(icon))

    def test_missing_icon_does_not_block_window(self):
        window = Mock()
        with patch('src.utils_ui.sys.platform', 'win32'), patch.object(Path, 'is_file', return_value=False):
            self.assertFalse(apply_window_icon(window))
        window.iconbitmap.assert_not_called()

    def test_invalid_icon_does_not_block_window(self):
        window = Mock()
        window.iconbitmap.side_effect = tk.TclError('unsupported icon')
        with patch('src.utils_ui.sys.platform', 'win32'):
            self.assertFalse(apply_window_icon(window))
