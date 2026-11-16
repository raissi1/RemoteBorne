#!/usr/bin/env python3
"""Offline UI audit: open each window and verify that actions are visible or scrollable.

Run with a display, for example:
    python scripts/check_window_layout.py --scale 2.6667 --compact
No connection to a charger is started and all edited files are temporary.
"""

import sys
import pathlib
import tempfile
import configparser
import tkinter as tk
from unittest.mock import Mock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import ttkbootstrap as ttk
from src.RemoteBorneManager import RemoteBorneApp
from src.network_config import open_network_config
from src.energy_manager import EnergyManagerWindow
from src.test_sequence import TestSequenceWindow
from src.gridcodes_migration_ui import GridCodesMigrationWindow
from src.debug_logs import DebugLogsWindow
from src.open_help import open_help
from src.utils_ui import ScrollableFrame
import argparse

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--scale",
    type=float,
    default=1.3333,
    help="Tk pixels per typographic point (1.3333=100%%, 2=150%%, 2.6667=200%%)",
)
parser.add_argument(
    "--compact", action="store_true", help="Constrain windows to a 1024x600 work area"
)
args = parser.parse_args()
scale = args.scale
r = ttk.Window(themename="flatly")
r.tk.call("tk", "scaling", scale)
if args.compact:
    import src.utils_ui

    src.utils_ui.screen_work_area = lambda _win: (0, 0, 1024, 600)
errors = []
r.report_callback_exception = lambda kind, value, tb: errors.append(str(value))
cfg = configparser.ConfigParser(interpolation=None)
cfg.read(ROOT / "config" / "config.example.ini")
with patch("src.RemoteBorneManager.ttk.Window", return_value=r), patch(
    "src.RemoteBorneManager.SSHManager.start"
):
    app = RemoteBorneApp(cfg)
app.ssh_queue.stop()
app.ssh_queue = Mock()
app.ssh_queue.execute.return_value = True
app.connected = True
app.ssh.connected = True


def descendants(w):
    for c in w.winfo_children():
        yield c
        yield from descendants(c)


def visible(w):
    if not w.winfo_ismapped() or w.winfo_width() <= 1 or w.winfo_height() <= 1:
        return False
    x, y = w.winfo_rootx(), w.winfo_rooty()
    right = x + w.winfo_width()
    bottom = y + w.winfo_height()
    p = w.master
    while p:
        if (
            x < p.winfo_rootx()
            or y < p.winfo_rooty()
            or right > p.winfo_rootx() + p.winfo_width() + 1
            or bottom > p.winfo_rooty() + p.winfo_height() + 1
        ):
            return False
        if p is w.winfo_toplevel():
            break
        p = p.master
    return True


def audit(name, w):
    r.update()
    bad = []
    scroll_count = 0
    for widget in list(descendants(w)):
        if widget.winfo_class() not in ("TButton", "Button"):
            continue
        # Skip only inactive notebook tabs, not controls that geometry has hidden.
        node = widget
        inactive = False
        while node.master is not None:
            if (
                node.master.winfo_class() == "TNotebook"
                and str(node) != node.master.select()
            ):
                inactive = True
                break
            node = node.master
        if inactive:
            continue
        if not visible(widget):
            p = widget.master
            scroll = None
            while p and p is not w:
                if isinstance(p, ScrollableFrame):
                    scroll = p
                    break
                p = p.master
            if scroll:
                content = scroll.content
                canvas = scroll.canvas
                canvas.xview_moveto(
                    max(
                        0,
                        (widget.winfo_rootx() - content.winfo_rootx() - 8)
                        / content.winfo_width(),
                    )
                )
                canvas.yview_moveto(
                    max(
                        0,
                        (widget.winfo_rooty() - content.winfo_rooty() - 8)
                        / content.winfo_height(),
                    )
                )
                r.update()
                scroll_count += 1
            if not visible(widget) and scroll:
                scroll.canvas.yview_moveto(0)
                r.update()
            if not visible(widget):
                bad.append(str(widget.cget("text")))
                chain = []
                p = widget
                while p:
                    chain.append(
                        (
                            p.winfo_class(),
                            p.winfo_rootx(),
                            p.winfo_rooty(),
                            p.winfo_width(),
                            p.winfo_height(),
                        )
                    )
                    p = p.master
                print("DETAIL", str(widget.cget("text")), chain, flush=True)
    print(
        name,
        "scale",
        scale,
        "size",
        w.winfo_width(),
        w.winfo_height(),
        "bad",
        bad,
        "scrolled",
        scroll_count,
        flush=True,
    )
    return bad


bad = []
with tempfile.TemporaryDirectory() as d:
    open_network_config(r, str(pathlib.Path(d) / "config.ini"))
    r.update()
    w = [w for w in r.winfo_children() if isinstance(w, tk.Toplevel)][-1]
    bad += audit("network", w)
    for widget in descendants(w):
        if widget.winfo_class() == "TEntry":
            row = int(widget.grid_info().get("row", -1))
            if row == 1:
                widget.delete(0, "end")
                widget.insert(0, "127.0.0.1")
            if row == 3:
                widget.delete(0, "end")
                widget.insert(0, "test%password")
            if row == 7:
                widget.delete(0, "end")
                widget.insert(0, str(pathlib.Path(d) / "exports.v17"))
    with patch("src.network_config.messagebox.showinfo"), patch(
        "src.network_config.messagebox.showerror"
    ) as error:
        [
            widget
            for widget in descendants(w)
            if widget.winfo_class() == "TButton" and widget.cget("text") == "Save"
        ][0].invoke()
        assert not error.called, "Network save failed"
    saved = configparser.ConfigParser(interpolation=None)
    saved.read(pathlib.Path(d) / "config.ini")
    assert saved["SSH"]["password"] == "test%password"
    assert saved["PATHS"]["local_path"].endswith("exports.v17")
    energy = EnergyManagerWindow(r, app.ssh, app.ssh_queue)
    bad += audit("energy", energy.win)
    energy.close()
    seq = TestSequenceWindow(r, app.ssh_queue, lambda: True, lambda: 11000)
    seq.win.deiconify()
    bad += audit("sequence", seq.win)
    seq.close(force=True)
    migration = GridCodesMigrationWindow(
        r, d, lambda: False, lambda p: None, lambda p: None
    )
    bad += audit("migration", migration.window)
    migration.close()
    debug = DebugLogsWindow(r, ("127.0.0.1", "root", "test"))
    bad += audit("debug", debug.window)
    for name in debug.log_buffers:
        debug.log_buffers[name] = ["ERROR example"]
    debug.global_find_var.set("ERROR")
    debug.find_in_all_logs()
    bad += audit("results", debug.window)
    debug.on_close()
    open_help(r)
    w = [w for w in r.winfo_children() if isinstance(w, tk.Toplevel)][-1]
    bad += audit("help", w)
    w.destroy()
    (pathlib.Path(d) / "example.txt").write_text("example")
    app._show_file_editor("/tmp/test", str(pathlib.Path(d) / "example.txt"))
    w = app._editor_window
    bad += audit("editor", w)
    find_button = next(
        widget
        for widget in descendants(w)
        if widget.winfo_class() == "TButton" and widget.cget("text") == "Find"
    )
    find_button.invoke()
    bad += audit("editor-find", app._find_dialog)
    app._find_dialog.destroy()
    app._close_editor_window()
    app.open_terminal()
    w = app._terminal_window
    bad += audit("terminal", w)
    app._close_terminal_window(force=True)
    app.open_netlogger_download()
    w = [w for w in r.winfo_children() if isinstance(w, tk.Toplevel)][-1]
    bad += audit("netlogger", w)
    w.destroy()
    app._file_entries = ["test"]
    app._open_file_find_dialog()
    w = app._browser_find_dialog
    bad += audit("find", w)
    w.destroy()
    bad += audit("main", r)
print("Callback errors", errors, flush=True)
r.destroy()
sys.exit(1 if bad or errors else 0)
