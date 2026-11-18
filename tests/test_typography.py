"""Font selection should be readable even when Windows fonts are absent."""
import unittest
from unittest.mock import Mock, patch
from src.utils_ui import ui_font, mono_font


class TestTypography(unittest.TestCase):
    def test_windows_variable_font_is_preferred_and_regular(self):
        with patch('src.utils_ui.tkfont.families', return_value=('Segoe UI', 'Segoe UI Variable Text', 'Arial')):
            self.assertEqual(ui_font(Mock()), ('Segoe UI Variable Text', 10, 'normal'))

    def test_available_sans_font_is_used_without_windows_fonts(self):
        with patch('src.utils_ui.tkfont.families', return_value=('fixed', 'helvetica')):
            self.assertEqual(ui_font(Mock(), 12), ('helvetica', 12, 'normal'))

    def test_code_keeps_an_installed_monospace_font(self):
        with patch('src.utils_ui.tkfont.families', return_value=('Segoe UI', 'Consolas', 'Cascadia Mono')):
            self.assertEqual(mono_font(Mock()), ('Cascadia Mono', 10, 'normal'))

    def test_family_lookup_is_case_insensitive(self):
        with patch('src.utils_ui.tkfont.families', return_value=('segoe ui',)):
            self.assertEqual(ui_font(Mock(), 11), ('segoe ui', 11, 'normal'))
