"""Font selection should be readable even when Windows fonts are absent."""
import unittest
from unittest.mock import Mock, patch
from src.utils_ui import ui_font, mono_font, use_application_theme


class TestTypography(unittest.TestCase):
    def test_classic_windows_font_is_preferred_and_regular(self):
        with patch('src.utils_ui.tkfont.families', return_value=('Segoe UI', 'Segoe UI Variable Text', 'Arial')):
            self.assertEqual(ui_font(Mock()), ('Segoe UI', 10, 'normal'))

    def test_available_sans_font_is_used_without_windows_fonts(self):
        with patch('src.utils_ui.tkfont.families', return_value=('fixed', 'helvetica')):
            self.assertEqual(ui_font(Mock(), 12), ('helvetica', 12, 'normal'))

    def test_code_keeps_an_installed_monospace_font(self):
        with patch('src.utils_ui.tkfont.families', return_value=('Segoe UI', 'Consolas', 'Cascadia Mono')):
            self.assertEqual(mono_font(Mock()), ('Consolas', 10, 'normal'))

    def test_family_lookup_is_case_insensitive(self):
        with patch('src.utils_ui.tkfont.families', return_value=('segoe ui',)):
            self.assertEqual(ui_font(Mock(), 11), ('segoe ui', 11, 'normal'))


    def test_variable_font_remains_a_fallback_when_classic_is_absent(self):
        with patch('src.utils_ui.tkfont.families', return_value=('Segoe UI Variable Text',)):
            self.assertEqual(ui_font(Mock()), ('Segoe UI Variable Text', 10, 'normal'))

    def test_selected_classic_theme_is_not_remapped(self):
        for name in ('flatly', 'darkly'):
            with self.subTest(theme=name):
                style = Mock()
                use_application_theme(style, name)
                style.theme_use.assert_called_once_with(name)
                style.register_theme.assert_not_called()
