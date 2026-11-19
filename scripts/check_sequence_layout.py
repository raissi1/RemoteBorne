"""Offline sequence table visibility at startup and after a compact resize."""
import configparser
import argparse
import pathlib
import sys
from unittest.mock import Mock, patch
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import ttkbootstrap as ttk
from src.RemoteBorneManager import RemoteBorneApp
from src.test_sequence import TestSequenceWindow

cfg = configparser.ConfigParser(interpolation=None)
cfg.read(pathlib.Path(__file__).resolve().parents[1] / 'config/config.example.ini')
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--scale", type=float, default=1.3333)
args = parser.parse_args()
scale = args.scale
root = ttk.Window()
root.tk.call("tk", "scaling", scale)
errors = []
root.report_callback_exception = lambda kind, value, tb: errors.append(str(value))
with patch('src.RemoteBorneManager.ttk.Window', return_value=root), patch('src.RemoteBorneManager.SSHManager.start'):
    app = RemoteBorneApp(cfg)
app.ssh_queue.stop()
app.ssh_queue = Mock()
app.connected = app.ssh.connected = True
root.withdraw()


def assert_rows(seq, minimum):
    root.update()
    seq.tree.yview_moveto(0)
    root.update()
    for row in seq.tree.get_children()[:minimum]:
        bounds = seq.tree.bbox(row)
        assert bounds and bounds[1] + bounds[3] <= seq.tree.winfo_height(), (
            'Sequence rows clipped', minimum, seq.tree.winfo_height(), bounds)
    assert seq.tree.winfo_rooty() + seq.tree.winfo_height() <= seq.progress_bar.winfo_rooty()
    for widget in (seq.progress_bar, seq.log_text, seq.btn_start):
        assert widget.winfo_ismapped()
        assert widget.winfo_rooty() + widget.winfo_height() <= seq.win.winfo_rooty() + seq.win.winfo_height()


for theme in ('flatly', 'darkly'):
    app._apply_theme(theme)
    for width, height in ((1920, 1080), (1024, 600)):
        with patch('src.utils_ui.screen_work_area', return_value=(0, 0, width, height)):
            seq = TestSequenceWindow(root, app.ssh_queue, lambda: True, lambda: 11000)
            app._add_test_sequence_pn_helper(seq)
            app._size_test_sequence_window(seq.win, seq)
            seq.win.deiconify()
            root.update()
            for value in (0, 100, 200, 300, 400, 500):
                seq.active_var.set(str(value))
                seq.add_step()
            assert_rows(seq, 4 if height >= 1000 else 2)
            seq.win.geometry(f'{min(1000, width - 24)}x{min(650, height - 48)}')
            assert_rows(seq, 2)
            print(theme, scale, (width, height), 'startup and resized table/log/progress: OK')
            seq.close(force=True)
assert not errors, errors
root.destroy()
