"""Shared window sizing and locally scoped scrolling for compact/high-DPI screens."""

import sys
import re
import tkinter as tk
from tkinter import ttk


def _relative_luminance(color):
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    return sum((c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4) * weight
               for c, weight in zip(channels, (0.2126, 0.7152, 0.0722)))


def _contrast(a, b):
    low, high = sorted((_relative_luminance(a), _relative_luminance(b)))
    return (high + 0.05) / (low + 0.05)


def configure_readable_styles(style):
    """Preserve semantic button colors while keeping normal text readable."""
    colors = getattr(style, "colors", None)
    if colors is None:
        return
    disabled_bg = style.lookup("TButton", "background", ("disabled",))
    disabled_fg = style.lookup("TButton", "foreground", ("disabled",))
    for semantic in ("primary", "secondary", "success", "info", "warning", "danger", "light", "dark"):
        background = getattr(colors, semantic)
        foreground = "#111111" if semantic in ("warning", "light") else "#ffffff"
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", background):
            continue
        # Darken bright fills enough to retain familiar white button captions.
        for _ in range(64):
            if _contrast(background, foreground) >= 4.5:
                break
            background = "#" + "".join(f"{int(int(background[i:i+2], 16) * .94):02x}" for i in (1, 3, 5))
        shade = lambda factor: "#" + "".join(f"{int(int(background[i:i+2], 16) * factor):02x}" for i in (1, 3, 5))
        name = semantic + ".TButton"
        style.configure(name, background=background, foreground=foreground)
        style.map(name, background=[("disabled", disabled_bg), ("pressed", shade(.85)), ("active", shade(.94))],
                  foreground=[("disabled", disabled_fg), ("!disabled", foreground)])
    for semantic in ("primary", "success", "info", "warning", "danger"):
        foreground = getattr(colors, semantic)
        for _ in range(64):
            if _contrast(foreground, colors.bg) >= 4.5:
                break
            foreground = "#" + "".join(f"{round(int(foreground[i:i+2], 16) * .85 + int(colors.fg[i:i+2], 16) * .15):02x}"
                                        for i in (1, 3, 5))
        style.configure(semantic + ".TLabel", foreground=foreground, background=colors.bg)
    # Secondary label colors from the stock dark theme are too close to its
    # surface. Use the regular text color for instructions and summaries.
    style.configure("secondary.TLabel", foreground=colors.fg, background=colors.bg)


def theme_native_widget(widget):
    """Explicitly theme classic Tk surfaces, including after a theme switch.

    ttk themes do not consistently recolor Text/Listbox/Canvas widgets across
    ttkbootstrap versions. Keep their selection and caret readable too.
    """
    def apply(_event=None):
        if not widget.winfo_exists():
            return
        style = ttk.Style(widget)
        background = style.lookup("TEntry", "fieldbackground") or style.lookup("TFrame", "background")
        foreground = style.lookup("TLabel", "foreground")
        selection = style.lookup("TEntry", "selectbackground") or "#375a7f"
        selection_fg = style.lookup("TEntry", "selectforeground") or foreground
        options = {"background": style.lookup("TFrame", "background") if widget.winfo_class() in ("Canvas", "Toplevel", "Tk") else background}
        if widget.winfo_class() not in ("Canvas", "Toplevel", "Tk"):
            options.update(foreground=foreground, selectbackground=selection, selectforeground=selection_fg)
        if widget.winfo_class() == "Text":
            options["insertbackground"] = foreground
        widget.configure(**options)
        if widget.winfo_class() == "Text":
            for tag, semantic in (("INFO", "success"), ("WARN", "warning"), ("ERROR", "danger")):
                if tag in widget.tag_names():
                    widget.tag_configure(tag, foreground=style.lookup(semantic + ".TLabel", "foreground"))

    def changed(_event=None):
        # Apply after ttkbootstrap's own theme handlers, not before them.
        widget.after_idle(apply)
    widget.bind("<<ThemeChanged>>", changed, add="+")
    apply()


def screen_work_area(win):
    """Return the usable desktop rectangle, excluding the Windows taskbar."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            rect = wintypes.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(rect), 0):
                return rect.left, rect.top, rect.right, rect.bottom
        except (AttributeError, OSError):
            pass
    return 0, 0, win.winfo_screenwidth(), max(200, win.winfo_screenheight() - 60)


def center_window(parent, win, width=900, height=600):
    """Center within usable screen space; never force an oversized minimum."""
    if not getattr(win, "_rbm_surface_themed", False):
        theme_native_widget(win)
        win._rbm_surface_themed = True
    win.update_idletasks()
    left, top, right, bottom = screen_work_area(win)
    decoration_height = 0
    try:
        position = re.search(r"([+-]\d+)([+-]\d+)$", win.geometry())
        if position:
            decoration_height = max(0, win.winfo_rooty() - int(position.group(2)))
    except (tk.TclError, TypeError, ValueError):
        pass
    width = min(int(width), max(200, right - left - 24))
    height = min(int(height), max(150, bottom - top - max(48, decoration_height + 48)))
    old_min = win.minsize()
    win.minsize(min(old_min[0], width), min(old_min[1], height))
    x, y = left + (right - left - width) // 2, top + (bottom - top - height) // 2
    try:
        if parent and parent.winfo_exists():
            parent.update_idletasks()
            if parent.winfo_width() > 1:
                x = parent.winfo_rootx() + (parent.winfo_width() - width) // 2
                y = parent.winfo_rooty() + (parent.winfo_height() - height) // 2
    except tk.TclError:
        pass
    x = max(left + 12, min(x, right - width - 12))
    y = max(top + 12, min(y, bottom - height - decoration_height - 36))
    win.geometry(f"{width}x{height}+{x}+{y}")


class ScrollableFrame(ttk.Frame):
    """Content grows naturally, with scrollbars only when the viewport is smaller.

    Set horizontal=False when children reflow to fit the canvas viewport.

    Wheel handling is scoped to this content's toplevel and descendants. Native
    Text/Listbox/Treeview scrolling is left alone; no bind_all is installed.
    """

    def __init__(self, parent, horizontal=True, **kwargs):
        super().__init__(parent, **kwargs)
        self.allow_horizontal = horizontal
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, highlightthickness=0, width=400, height=300)
        theme_native_widget(self.canvas)
        self.vertical = ttk.Scrollbar(
            self, orient="vertical", command=self.canvas.yview
        )
        self.horizontal = ttk.Scrollbar(
            self, orient="horizontal", command=self.canvas.xview
        )
        self.canvas.configure(
            yscrollcommand=self.vertical.set, xscrollcommand=self.horizontal.set
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.content = ttk.Frame(self.canvas)
        self._item = self.canvas.create_window(0, 0, window=self.content, anchor="nw")
        self.canvas.bind("<Configure>", self._layout)
        self.content.bind("<Configure>", self._layout)
        self._top = self.winfo_toplevel()
        self._bindings = []
        for event in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self._bindings.append((event, self._top.bind(event, self._wheel, add="+")))
        self._bindings.append(
            ("<FocusIn>", self._top.bind("<FocusIn>", self._focus, add="+"))
        )
        self.bind("<Destroy>", self._cleanup, add="+")

    def _layout(self, _event=None):
        if not self.winfo_exists():
            return
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        requested_w, requested_h = (
            self.content.winfo_reqwidth(),
            self.content.winfo_reqheight(),
        )
        content_width = max(width, requested_w) if self.allow_horizontal else width
        self.canvas.itemconfigure(
            self._item, width=content_width, height=max(height, requested_h)
        )
        self.canvas.configure(
            scrollregion=(0, 0, content_width, max(height, requested_h))
        )
        if requested_h > height + 1:
            self.vertical.grid(row=0, column=1, sticky="ns")
        else:
            self.vertical.grid_remove()
        if self.allow_horizontal and requested_w > width + 1:
            self.horizontal.grid(row=1, column=0, sticky="ew")
        else:
            self.horizontal.grid_remove()

    def _wheel(self, event):
        widget = event.widget
        native = {"Text", "Listbox", "Treeview", "TScrollbar", "Scrollbar"}
        if widget.winfo_class() in native:
            return
        while widget is not None and widget is not self.content:
            widget = getattr(widget, "master", None)
        if (
            widget is None
            or self.content.winfo_reqheight() <= self.canvas.winfo_height()
        ):
            return
        delta = getattr(event, "delta", 0)
        steps = (-1 if delta > 0 else 1) if delta else (-1 if event.num == 4 else 1)
        self.canvas.yview_scroll(steps * 3, "units")
        return "break"

    def _focus(self, event):
        widget = event.widget
        ancestor = widget
        while ancestor is not None and ancestor is not self.content:
            ancestor = getattr(ancestor, "master", None)
        if ancestor is None:
            return
        x = widget.winfo_rootx() - self.content.winfo_rootx()
        y = widget.winfo_rooty() - self.content.winfo_rooty()
        left, top = self.canvas.canvasx(0), self.canvas.canvasy(0)
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        if x < left or x + widget.winfo_width() > left + width:
            destination = x - 8 if x < left else x + widget.winfo_width() - width + 8
            self.canvas.xview_moveto(
                max(0, destination / max(1, self.content.winfo_width()))
            )
        if y < top or y + widget.winfo_height() > top + height:
            destination = y - 8 if y < top else y + widget.winfo_height() - height + 8
            self.canvas.yview_moveto(
                max(0, destination / max(1, self.content.winfo_height()))
            )

    def _cleanup(self, event):
        if event.widget is self:
            for sequence, binding in self._bindings:
                self._top.unbind(sequence, binding)
