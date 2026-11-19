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
import tkinter.font as tkfont
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
from src.utils_ui import ScrollableFrame, _contrast
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
parser.add_argument("--theme", choices=("flatly", "darkly"), default="flatly")
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
app._apply_theme(args.theme)
app.ssh_queue.stop()
app.ssh_queue = Mock()
app.ssh_queue.execute.return_value = True
app.connected = True
app.ssh.connected = True
app._update_controls_state()


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
    # Check actual rendered styles, not merely whether controls exist.
    for item in descendants(w):
        if item.winfo_class() not in ("TLabel", "TButton") or not item.winfo_ismapped():
            continue
        if "disabled" in item.state() or not str(item.cget("text")):
            continue
        style = str(item.cget("style")) or item.winfo_class()
        foreground = (item.cget("foreground") if "foreground" in item.keys() else "") or app.style.lookup(style, "foreground")
        background = (item.cget("background") if "background" in item.keys() else "") or app.style.lookup(style, "background") or app.style.lookup("TFrame", "background")
        if foreground and background and _contrast(str(foreground), str(background)) < 4.5:
            bad.append("Low contrast: " + str(item.cget("text")))
    scroll_count = 0
    for widget in list(descendants(w)):
        if widget.winfo_class() not in ("TButton", "Button", "TCheckbutton", "TRadiobutton", "TMenubutton"):
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
        style_name = str(widget.cget("style")) if "style" in widget.keys() else ""
        label = str(widget.cget("text"))
        font = app.style.lookup(style_name or widget.winfo_class(), "font") or "TkDefaultFont"
        if label and widget.winfo_width() < tkfont.Font(font=font).measure(label) + 8:
            bad.append("Clipped caption: " + label)
        if not visible(widget):
            p = widget.master
            scrolls = []
            while p and p is not w:
                if isinstance(p, ScrollableFrame):
                    scrolls.append(p)
                p = p.master
            # Responsive panes can change their scrollregion while a resize
            # settles. Retry against the settled region; a truly clipped
            # control still fails after these attempts.
            for _attempt in range(3):
                r.update_idletasks()
                for scroll in scrolls:
                    content = scroll.content
                    canvas = scroll.canvas
                    region = [float(value) for value in canvas.tk.splitlist(canvas.cget("scrollregion"))]
                    region_width = max(1, region[2] - region[0])
                    region_height = max(1, region[3] - region[1])
                    canvas.xview_moveto(max(0, (widget.winfo_rootx() - content.winfo_rootx() - 8) / region_width))
                    canvas.yview_moveto(max(0, (widget.winfo_rooty() - content.winfo_rooty() - 8) / region_height))
                    r.update_idletasks()
                    scroll_count += 1
                r.update()
                if visible(widget):
                    break
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
    for width in (900, min(1280, r.winfo_width())):
        energy.win.geometry(f"{width}x{energy.win.winfo_height()}")
        r.update()
        assert (
            not energy._energy_scroll.horizontal.winfo_ismapped()
        ), "Energy Manager requires horizontal scrolling"
        assert energy._energy_scroll.canvas.xview() == (0.0, 1.0)
        bad += audit(f"energy-width-{width}", energy.win)
    energy.close()
    seq = TestSequenceWindow(r, app.ssh_queue, lambda: True, lambda: 11000)
    app._add_test_sequence_file_actions(seq)
    app._add_test_sequence_pn_helper(seq)
    app._size_test_sequence_window(seq.win, seq)
    seq.win.deiconify()
    bad += audit("sequence", seq.win)
    assert seq.btn_start.winfo_width() < seq.win.winfo_width() / 2, "Start button must stay compact"
    for active in (0, 100, 200):
        seq.active_var.set(str(active))
        seq.add_step()
    seq.tree.yview_moveto(0)
    r.update()
    assert visible(seq.tree), "Sequence table must stay outside the settings viewport"
    rows = seq.tree.get_children()
    for row in rows[:2]:
        bounds = seq.tree.bbox(row)
        assert bounds and bounds[1] + bounds[3] <= seq.tree.winfo_height(), ("At least two complete sequence rows must remain visible", bounds, seq.tree.winfo_height(), seq._sequence_workspace.winfo_height(), seq._sequence_scroll.winfo_height(), seq._sequence_footer.winfo_height(), seq.sequence_log_frame.winfo_height())
    assert visible(seq.progress_bar), "Sequence progress bar is hidden"
    assert seq.progress_bar.winfo_rooty() < seq.btn_start.winfo_rooty(), "Progress must precede the command row"
    assert seq.sequence_log_frame.winfo_rooty() > seq.btn_start.winfo_rooty(), "Sequence log must be below commands"
    seq.progress_var.set(50)
    r.update()
    assert float(seq.progress_bar.cget("value")) == 50
    seq.progress_var.set(0)
    assert visible(seq.log_text), "Sequence log is hidden or outside the viewport"
    seq._log("Sequence journal visibility check")
    assert "Sequence journal visibility check" in seq.log_text.get("1.0", "end")
    assert str(seq.log_text.cget("state")) == "disabled", "Sequence log must stay read-only"
    seq.close(force=True)
    migration = GridCodesMigrationWindow(
        r, d, lambda: False, lambda p: None, lambda p: None
    )
    bad += audit("migration", migration.window)
    migration.close()
    debug = DebugLogsWindow(r, ("127.0.0.1", "root", "test"))
    bad += audit("debug", debug.window)
    for tab in debug.notebook.tabs():
        debug.notebook.select(tab)
        bad += audit("debug-tab-" + debug.notebook.tab(tab, "text"), debug.window)
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
    app._file_list_path = app.current_path
    app._open_file_find_dialog()
    w = app._browser_find_dialog
    bad += audit("find", w)
    w.destroy()
    bad += audit("main", r)
print("Callback errors", errors, flush=True)
r.destroy()
sys.exit(1 if bad or errors else 0)
