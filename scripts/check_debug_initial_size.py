"""Check diagnosis startup sizing at realistic DPI and compact work areas.

Requires a Tk display. No EVSE connection or log process is started.
"""
import pathlib
import sys
import re
from unittest.mock import patch
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import ttkbootstrap as ttk
from src.debug_logs import DebugLogsWindow
from src.utils_ui import use_application_theme, configure_readable_styles, configure_application_fonts

root = ttk.Window()
root.withdraw()
errors = []
root.report_callback_exception = lambda kind, value, tb: errors.append(str(value))
for theme in ('flatly', 'darkly'):
    use_application_theme(root.style, theme)
    for scale in (1.3333, 2, 2.6667):
        root.tk.call('tk', 'scaling', scale)
        configure_application_fonts(root)
        configure_readable_styles(root.style)
        for width, height in ((1920, 1080), (1024, 600)):
            with patch('src.utils_ui.screen_work_area', return_value=(0, 0, width, height)):
                debug = DebugLogsWindow(root, ('127.0.0.1', 'test', 'test', 2222))
                root.update()
                content = debug._diagnosis_scroll.content
                canvas = debug._diagnosis_scroll.canvas
                notebook = debug.notebook
                pages = [notebook.nametowidget(tab) for tab in notebook.tabs()]
                tab_height = notebook.winfo_reqheight() - max(page.winfo_reqheight() for page in pages)
                required = content.winfo_reqheight() + debug._diagnosis_footer.winfo_reqheight() + tab_height + 12
                position = re.search(r"([+-]\d+)([+-]\d+)$", debug.window.geometry())
                decoration = max(0, debug.window.winfo_rooty() - int(position.group(2))) if position else 0
                usable_height = height - max(48, decoration + 48)
                if required <= usable_height:
                    assert content.winfo_reqheight() <= canvas.winfo_height(), (
                        theme, scale, width, height, 'unnecessary vertical clipping at startup',
                        content.winfo_reqheight(), canvas.winfo_height())
                    assert debug._diagnosis_scroll.canvas.yview() == (0.0, 1.0)
                else:
                    assert debug._diagnosis_scroll.vertical.winfo_ismapped(), 'small screen has no scroll access'
                for button in (debug.capture_button, debug.capture_options):
                    assert button.winfo_ismapped()
                    assert button.winfo_rooty() + button.winfo_height() <= debug.window.winfo_rooty() + debug.window.winfo_height()
                assert debug.window.winfo_height() <= usable_height
                print(theme, scale, (width, height), 'window', debug.window.winfo_width(), debug.window.winfo_height(),
                      'content/viewport', content.winfo_reqheight(), canvas.winfo_height(), 'OK')
                debug.on_close()
assert not errors, errors
root.destroy()
