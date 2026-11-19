"""RBM user interface for safe local GridCodes migrations."""

from __future__ import annotations

import datetime
import threading
from pathlib import Path
from typing import Callable, Optional
import tkinter as tk
from tkinter import filedialog, messagebox

import ttkbootstrap as ttk

try:
    from .gridcodes_migrator import MigrationError, analyze_migration, export_plan
    from .utils_ui import center_window, ScrollableFrame, theme_native_widget, ui_font, mono_font
except ImportError:
    from gridcodes_migrator import MigrationError, analyze_migration, export_plan
    from utils_ui import center_window, ScrollableFrame, theme_native_widget, ui_font, mono_font


class GridCodesMigrationWindow:
    """Guide an operator through local review before any EVSE upload."""

    def __init__(
        self,
        parent,
        exports_dir: str,
        is_connected: Callable[[], bool],
        upload_export: Callable[[str], None],
        log: Callable[[str], None],
    ):
        self.parent = parent
        self.exports_dir = Path(exports_dir)
        self.is_connected = is_connected
        self.upload_export = upload_export
        self.log = log
        self.plan = None
        self.export_dir: Optional[Path] = None

        self.window = ttk.Toplevel(parent)
        self.window.withdraw()
        self.window.title("GridCodes Migration")
        self.window.minsize(1040, 700)
        self.window.geometry("1180x800")
        self.window.transient("")
        center_window(parent, self.window, 1180, 800)
        self.window.protocol("WM_DELETE_WINDOW", self.close)

        self.source_var = tk.StringVar()
        self.template_var = tk.StringVar()
        self.rules_var = tk.StringVar()
        self.vehicle_var = tk.StringVar()
        self.power_1ph_var = tk.StringVar()
        self.power_3ph_var = tk.StringVar()
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.output_var = tk.StringVar(value=str(self.exports_dir / "migrations" / timestamp))
        self.status_var = tk.StringVar(value="Select the source and the target template, then analyze before exporting.")
        self.summary_var = tk.StringVar(value="No analysis yet.")
        self._build_ui()
        self._fit_initial_size()
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()
        # A migration is a review-and-export workflow. Keep the operator in
        # this window until it is closed, while leaving Debug Logs modeless.
        self.window.grab_set()

    def _build_ui(self):
        actions = ttk.Frame(self.window, padding=(12, 8))
        actions.pack(side="bottom", fill="x")
        self._migration_actions = actions
        workspace = ttk.Frame(self.window)
        workspace.pack(fill="both", expand=True)
        workspace.columnconfigure(0, weight=1)
        workspace.rowconfigure(1, weight=1)
        self._migration_workspace = workspace
        scroll = ScrollableFrame(workspace)
        scroll.grid(row=0, column=0, sticky="nsew")
        scroll.grid_propagate(False)
        self._migration_scroll = scroll
        preview = ttk.Frame(workspace, padding=(10, 0, 10, 4))
        preview.grid(row=1, column=0, sticky="nsew")
        preview.columnconfigure(0, weight=1)
        preview.rowconfigure(0, weight=1)
        self._migration_preview = preview
        root = ttk.Frame(scroll.content, padding=12)
        root.pack(fill="both", expand=True)
        root.columnconfigure(1, weight=1)

        ttk.Label(root, text="GridCodes Migration", font=ui_font(self.window, 11)).grid(
            row=0, column=0, columnspan=3, sticky="w"
        )
        ttk.Label(
            root,
            text="The target template defines the final configuration. Analysis is local and never changes source files or the EVSE.",
            bootstyle="secondary",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(2, 10))

        form = ttk.Labelframe(root, text="Migration source and output", padding=8)
        form.grid(row=2, column=0, columnspan=3, sticky="new")
        form.columnconfigure(1, weight=1)
        form.columnconfigure(4, weight=1)
        self._path_fields = []
        self._path_row(
            form, 0, 0, "Source file or folder", self.source_var, self._browse_source
        )
        self._path_row(
            form, 0, 3, "Target template", self.template_var, self._browse_template
        )
        self._path_row(
            form, 1, 0, "Manual rename rules", self.rules_var, self._browse_rules
        )
        self._path_row(
            form, 1, 3, "Export folder", self.output_var, self._browse_output
        )

        profile = ttk.Labelframe(root, text="Project profile (optional)", padding=8)
        profile.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        self._profile_fields = []
        for label, variable, width, justify in (
            ("Vehicle for GC names:", self.vehicle_var, 12, "left"),
            ("PowerMax 1Ph [var]:", self.power_1ph_var, 10, "right"),
            ("PowerMax 3Ph [var]:", self.power_3ph_var, 10, "right"),
        ):
            caption = ttk.Label(profile, text=label)
            entry = ttk.Entry(profile, textvariable=variable, width=width, justify=justify)
            self._profile_fields.append((caption, entry))
        self._profile_hint = ttk.Label(
            profile, text="Leave all fields empty to preserve generic migration behavior. Values are applied only when confirmed in the preview.",
            bootstyle="secondary")
        self._migration_profile = profile

        self.analyze_button = ttk.Button(actions, text="Analyze migration", bootstyle="primary", command=self.analyze)
        self.export_button = ttk.Button(actions, text="Export migrated files", bootstyle="success", state="disabled", command=self.export)
        self.upload_button = ttk.Button(actions, text="Upload exported files to EVSE", bootstyle="warning", state="disabled", command=self.upload)
        close_button = ttk.Button(actions, text="Close", command=self.close)
        action_buttons = (self.analyze_button, self.export_button, self.upload_button, close_button)
        for button in action_buttons:
            button.configure(width=0, padding=(8, 3))
        layout = {"columns": None}
        def layout_actions(_event=None):
            columns = 4 if actions.winfo_width() >= sum(b.winfo_reqwidth() + 8 for b in action_buttons) else 2
            if layout["columns"] == columns:
                return
            layout["columns"] = columns
            for index, button in enumerate(action_buttons):
                button.grid(row=index // columns, column=index % columns, sticky="w", padx=4, pady=3)
        actions.bind("<Configure>", layout_actions, add="+")
        actions.after_idle(layout_actions)

        ttk.Label(root, textvariable=self.status_var, bootstyle="info").grid(
            row=5, column=0, columnspan=3, sticky="w", pady=(0, 6)
        )
        ttk.Label(root, textvariable=self.summary_var, bootstyle="secondary").grid(
            row=6, column=0, columnspan=3, sticky="w", pady=(0, 6)
        )

        results = ttk.Labelframe(preview, text="Analysis preview", padding=6)
        results.grid(row=0, column=0, sticky="nsew")
        results.columnconfigure(0, weight=1)
        results.rowconfigure(0, weight=1)
        columns = ("file", "source", "target", "renamed", "added", "removed", "warnings")
        self.tree = ttk.Treeview(results, columns=columns, show="headings", height=4)
        headings = {
            "file": "File", "source": "Source keys", "target": "Target keys",
            "renamed": "Renamed", "added": "Added", "removed": "Removed", "warnings": "Warnings",
        }
        widths = {"file": 330, "source": 90, "target": 90, "renamed": 85, "added": 75, "removed": 85, "warnings": 75}
        for key in columns:
            self.tree.heading(key, text=headings[key])
            self.tree.column(key, width=widths[key], anchor="center" if key != "file" else "w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(results, orient="vertical", command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(results, orient="horizontal", command=self.tree.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=scrollbar.set, xscrollcommand=horizontal.set)
        self.tree.bind("<<TreeviewSelect>>", self._show_selected_details)

        detail = ttk.Labelframe(preview, text="Selected file details", padding=5)
        detail.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        detail.columnconfigure(0, weight=1)
        detail.rowconfigure(0, weight=1)
        self.details = tk.Text(detail, height=3, wrap="word", state="disabled", font=ui_font(self.window))
        theme_native_widget(self.details)
        self.details.grid(row=0, column=0, sticky="nsew")
        details_scroll = ttk.Scrollbar(detail, orient="vertical", command=self.details.yview)
        details_scroll.grid(row=0, column=1, sticky="ns")
        self.details.configure(yscrollcommand=details_scroll.set)
        self._migration_details_frame = detail
        self._migration_form = form
        workspace.bind("<Configure>", self._layout_workspace, add="+")
        preview.bind("<Configure>", self._layout_workspace, add="+")
        scroll.content.bind("<Configure>", self._layout_workspace, add="+")
        scroll.content.bind("<Configure>", self._layout_form, add="+")
        scroll.canvas.bind("<Configure>", self._layout_form, add="+")
        workspace.after_idle(self._layout_form)
        workspace.after_idle(self._layout_workspace)


    def _layout_form(self, _event=None):
        available = max(200, self._migration_scroll.canvas.winfo_width() - 48)
        pair_width = max(sum(child.winfo_reqwidth() for child in group) + 36 for group in self._path_fields)
        columns = 2 if available >= pair_width * 2 else 1
        for column in range(6):
            self._migration_form.columnconfigure(column, weight=1 if column in ((1, 4) if columns == 2 else (1,)) else 0)
        for index, group in enumerate(self._path_fields):
            row, column = index // columns, (index % columns) * 3
            for offset, widget in enumerate(group):
                widget.grid(row=row, column=column + offset, sticky="ew" if offset == 1 else "w", padx=(0, 6), pady=3)
        profile_width = sum(sum(w.winfo_reqwidth() for w in group) + 24 for group in self._profile_fields)
        wide_profile = available >= profile_width
        for column in range(6):
            self._migration_profile.columnconfigure(column, weight=1 if column in ((1, 3, 5) if wide_profile else (1,)) else 0)
        for index, (label, entry) in enumerate(self._profile_fields):
            row, column = (0, index * 2) if wide_profile else (index, 0)
            label.grid(row=row, column=column, sticky="w", pady=2)
            entry.grid(row=row, column=column+1, sticky="ew", padx=(6, 12), pady=2)
        self._profile_hint.grid(row=1 if wide_profile else 3, column=0, columnspan=6 if wide_profile else 2, sticky="w", pady=(4, 0))
        for parent in (self._migration_scroll.content.winfo_children()[0], self._migration_profile):
            for label in parent.winfo_children():
                if label.winfo_class() == "TLabel" and (len(str(label.cget("text"))) > 70 or str(label.cget("textvariable"))):
                    label.configure(wraplength=available)
        self._layout_workspace()
        self._migration_scroll.request_layout()

    def _layout_workspace(self, _event=None):
        available = self._migration_workspace.winfo_height()
        if available <= 1:
            return
        rows = 1 if self.window.winfo_height() < 720 else 3
        if int(self.details.cget("height")) != rows:
            self.details.configure(height=rows)
        children = self._migration_form.winfo_children()
        control_height = max(child.winfo_reqheight() for child in children)
        horizontal = (self._migration_scroll.horizontal.winfo_reqheight()
                      if self._migration_scroll.content.winfo_reqwidth() > self._migration_scroll.canvas.winfo_width() + 1 else 0)
        height = min(self._migration_scroll.content.winfo_reqheight() + horizontal + 2,
                     max(control_height + 20 + horizontal, available - self._migration_preview.winfo_reqheight()))
        if int(self._migration_scroll.cget("height")) != height:
            self._migration_scroll.configure(height=height)

    def _fit_initial_size(self):
        for _ in range(3):
            self.window.update_idletasks()
            pair_width = max(sum(child.winfo_reqwidth() for child in group) + 36 for group in self._path_fields)
            width = max(1040, pair_width * 2 + 36, self._migration_scroll.content.winfo_reqwidth() + 36,
                        self._migration_actions.winfo_reqwidth() + 20)
            height = max(720, self._migration_scroll.content.winfo_reqheight() +
                         self._migration_preview.winfo_reqheight() + self._migration_actions.winfo_reqheight() + 32)
            center_window(self.parent, self.window, width, height)
            self.window.update_idletasks()
            self._layout_form()
            self._layout_workspace()

    def _path_row(self, parent, row, column, label, variable, command):
        caption = ttk.Label(parent, text=f"{label}:")
        entry = ttk.Entry(parent, textvariable=variable)
        button = ttk.Button(parent, text="Browse", command=command, width=0, padding=(8, 3))
        caption.grid(row=row, column=column, sticky="w", padx=(0, 6), pady=3)
        entry.grid(row=row, column=column+1, sticky="ew", pady=3)
        button.grid(row=row, column=column+2, sticky="w", padx=6, pady=3)
        self._path_fields.append((caption, entry, button))

    def _browse_source(self):
        path = filedialog.askdirectory(parent=self.window, title="Select GridCodes source folder")
        if not path:
            path = filedialog.askopenfilename(parent=self.window, title="Select GridCodes source file")
        if path:
            self.source_var.set(path)

    def _browse_template(self):
        path = filedialog.askopenfilename(parent=self.window, title="Select target GridCodes template")
        if path:
            self.template_var.set(path)

    def _browse_rules(self):
        path = filedialog.askopenfilename(parent=self.window, title="Select optional manual rename rules", filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
        if path:
            self.rules_var.set(path)

    def _browse_output(self):
        path = filedialog.askdirectory(parent=self.window, title="Select migration export folder", initialdir=str(self.exports_dir))
        if path:
            self.output_var.set(path)

    def analyze(self):
        source = self.source_var.get().strip()
        template = self.template_var.get().strip()
        if not source or not template:
            messagebox.showwarning("GridCodes Migration", "Select a source file or folder and a target template.", parent=self.window)
            return
        self.analyze_button.configure(state="disabled")
        self.export_button.configure(state="disabled")
        self.upload_button.configure(state="disabled")
        self.status_var.set("Analyzing locally; source files and EVSE are unchanged...")
        self.export_dir = None
        rules = self.rules_var.get().strip() or None
        vehicle = self.vehicle_var.get()
        power_1ph = self.power_1ph_var.get()
        power_3ph = self.power_3ph_var.get()

        def worker():
            try:
                plan = analyze_migration(
                    source,
                    template,
                    rules,
                    vehicle_name=vehicle,
                    power_max_1ph_var=power_1ph,
                    power_max_3ph_var=power_3ph,
                )
                result = (plan, None)
            except Exception as exc:
                result = (None, exc)
            try:
                self.window.after(0, lambda: self._analysis_finished(*result))
            except (tk.TclError, RuntimeError):
                pass  # The operator closed the window while analysis ran.

        threading.Thread(target=worker, daemon=True).start()

    def _analysis_finished(self, plan, error):
        if not self.window.winfo_exists():
            return
        self.analyze_button.configure(state="normal")
        if error:
            self.plan = None
            self.status_var.set("Analysis failed. No files were changed.")
            messagebox.showerror("GridCodes Migration", str(error), parent=self.window)
            return
        self.plan = plan
        for item in self.tree.get_children():
            self.tree.delete(item)
        for index, item in enumerate(plan.items):
            report = item.report
            self.tree.insert("", "end", iid=str(index), values=(
                item.relative_output, report.source_parameters, report.template_parameters,
                len(report.renamed), len(report.added), len(report.removed), len(report.warnings),
            ))
        self.summary_var.set(
            f"{len(plan.items)} file(s) ready for export | {len(plan.errors)} error(s) | {len(plan.generated_rules)} automatic rename rule(s) proposed"
        )
        self.status_var.set("Analysis complete. Review the details, then export to a new local folder.")
        self.export_button.configure(state="normal" if plan.items else "disabled")
        self.log(f"[MIGRATION] Analysis complete: {len(plan.items)} file(s), {len(plan.errors)} error(s).")
        if plan.items:
            self.tree.selection_set("0")
            self._show_selected_details()
        if plan.errors:
            messagebox.showwarning("GridCodes Migration", f"Analysis completed with {len(plan.errors)} file error(s). Review the preview before export.", parent=self.window)

    def _show_selected_details(self, _event=None):
        selection = self.tree.selection()
        if not selection or self.plan is None:
            return
        report = self.plan.items[int(selection[0])].report
        lines = [
            f"Source: {report.source}", f"Output: {report.output}", "",
            f"Renamed ({len(report.renamed)}): " + (", ".join(report.renamed) or "none"),
            f"Added from template ({len(report.added)}): " + (", ".join(report.added) or "none"),
            f"Removed old keys ({len(report.removed)}): " + (", ".join(report.removed) or "none"),
            f"Unresolved removed ({len(report.unresolved_removed)}): " + (", ".join(report.unresolved_removed) or "none"),
            f"Project overrides ({len(report.profile_overrides)}): " + (", ".join(report.profile_overrides) or "none"),
            f"Warnings ({len(report.warnings)}): " + (" | ".join(report.warnings) or "none"),
        ]
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", "\n".join(lines))
        self.details.configure(state="disabled")

    def export(self):
        if self.plan is None:
            return
        if not messagebox.askyesno("Export migrated files", "Export the reviewed migration to the selected local output folder?\n\nThe original files will remain unchanged.", parent=self.window):
            return
        try:
            target, report = export_plan(self.plan, self.output_var.get().strip())
        except (MigrationError, OSError) as exc:
            messagebox.showerror("GridCodes Migration", str(exc), parent=self.window)
            return
        self.export_dir = target
        self.status_var.set(f"Export complete: {target}")
        self.upload_button.configure(state="normal" if self.is_connected() else "disabled")
        self.log(f"[MIGRATION] Exported {len(self.plan.items)} file(s): {target}; report: {report}")
        messagebox.showinfo("GridCodes Migration", f"Migration export completed.\n\nFiles: {target}\nReport: {report}", parent=self.window)

    def upload(self):
        if self.export_dir is None:
            return
        if not self.is_connected():
            messagebox.showwarning("GridCodes Migration", "Connect to the EVSE before uploading exported files.", parent=self.window)
            return
        if not messagebox.askyesno("Upload migrated files", "Upload only the exported configuration files to the current remote GridCodes folder?\n\nThe migration report will stay local. Existing remote files with the same names can be replaced.", parent=self.window):
            return
        self.upload_export(str(self.export_dir))

    def close(self):
        try:
            self.window.grab_release()
        except tk.TclError:
            pass
        try:
            self.window.destroy()
        except tk.TclError:
            pass


def open_gridcodes_migration_window(*args, **kwargs):
    return GridCodesMigrationWindow(*args, **kwargs)
