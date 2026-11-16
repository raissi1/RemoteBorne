"""Small presentation adapters that keep existing RBM command handlers intact."""

import tkinter as tk
from tkinter import ttk


def file_kind(name):
    name = name.strip()
    if name.startswith("[DIR]") or name.startswith("[.]") or name.endswith("/"):
        return "Folder"
    if name.startswith("["):
        return ""
    lower = name.lower()
    if lower.endswith((".py", ".sh")):
        return "Script"
    if lower.endswith((".properties", ".ini", ".migration", ".validityflag")):
        return "Config"
    if name.startswith("GC_"):
        return "GridCode"
    return "File"


class FileTable(ttk.Treeview):
    """A two-column file view with the Listbox API used by existing navigation.

    Keep raw names (including spaces and recursive group labels) separate from
    presentation. Row indices keep matching the recursive search path mapping.
    """

    def __init__(self, parent, **kwargs):
        super().__init__(
            parent,
            columns=("kind",),
            show="tree headings",
            selectmode="browse",
            height=12,
            **kwargs
        )
        self._raw = {}
        self.heading("#0", text="Name")
        self.heading("kind", text="Type")
        self.column("#0", width=260, minwidth=120, stretch=True)
        self.column("kind", width=80, minwidth=65, stretch=False)
        # Guard precedes both application callbacks and native selection. This
        # preserves Listbox's disabled behavior while loading or running tests.
        self._guard_tag = "RBMFileGuard" + str(self).replace(".", "_").replace("!", "_")
        self.bindtags((self._guard_tag,) + self.bindtags())
        for event in ("<Button-1>", "<Button-3>", "<Double-Button-1>", "<KeyPress>"):
            self.bind_class(self._guard_tag, event, self._guard)

    def bind_open_command(self, callback):
        self._open_command = callback
        self.bind("<Double-Button-1>", self._open_row)
        self.bind("<Return>", self._open_row)

    def _open_row(self, event):
        if self.instate(("disabled",)):
            return "break"
        if getattr(event, "keysym", "") != "Return":
            row = self.nearest(event.y)
            if row is None:
                return "break"  # A heading/separator is never an open-file action.
            self.selection_set(row)
        self._open_command(event)
        return "break"

    def _guard(self, _event):
        if self.instate(("disabled",)):
            return "break"

    def configure(self, cnf=None, **kwargs):
        options = dict(cnf or {}) if isinstance(cnf, dict) else {}
        options.update(kwargs)
        if "state" in options:
            self.state(
                ("disabled",) if options.pop("state") == "disabled" else ("!disabled",)
            )
        return (
            super().configure(**options)
            if options
            else (None if kwargs or cnf else super().configure())
        )

    config = configure

    def _index(self, index):
        if str(index) == "end":
            return len(self.get_children()) - 1
        return int(index)

    def insert(self, index, *elements):
        for value in elements:
            position = "end" if str(index) == "end" else int(index)
            iid = super().insert("", position, text=value, values=(file_kind(value),))
            self._raw[iid] = value
            if position != "end":
                index = position + 1

    def delete(self, first, last=None):
        children = self.get_children()
        start = self._index(first)
        stop = start if last is None else self._index(last)
        rows = children[max(0, start) : stop + 1]
        if rows:
            super().delete(*rows)
            for row in rows:
                self._raw.pop(row, None)

    def get(self, first, last=None):
        children = self.get_children()
        start = self._index(first)
        if last is None:
            return self._raw[children[start]]
        return tuple(self._raw[row] for row in children[start : self._index(last) + 1])

    def curselection(self):
        selected = set(super().selection())
        return tuple(i for i, row in enumerate(self.get_children()) if row in selected)

    def selection_clear(self, first, last=None):
        children = self.get_children()
        start = self._index(first)
        stop = start if last is None else self._index(last)
        rows = children[max(0, start) : stop + 1]
        if rows:
            super().selection_remove(*rows)

    def selection_set(self, first, last=None):
        children = self.get_children()
        start = self._index(first)
        stop = start if last is None else self._index(last)
        rows = children[max(0, start) : stop + 1]
        if rows:
            super().selection_set(rows)

    def nearest(self, y):
        row = self.identify_row(y)
        return self.get_children().index(row) if row else None

    def size(self):
        return len(self.get_children())


class MenuCommand:
    """Retain button-like state and progress updates for an Actions menu item."""

    def __init__(self, menu, label, command):
        self.menu = menu
        menu.add_command(label=label, command=command)
        self.index = menu.index("end")

    def configure(self, **options):
        if "text" in options:
            options["label"] = options.pop("text")
        self.menu.entryconfigure(self.index, **options)

    config = configure

    def cget(self, key):
        return self.menu.entrycget(self.index, "label" if key == "text" else key)

    def invoke(self):
        return self.menu.invoke(self.index)
