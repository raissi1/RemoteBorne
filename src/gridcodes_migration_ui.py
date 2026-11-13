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
    from .utils_ui import center_window
except ImportError:
    from gridcodes_migrator import MigrationError, analyze_migration, export_plan
    from utils_ui import center_window


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
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()
        # A migration is a review-and-export workflow. Keep the operator in
        # this window until it is closed, while leaving Debug Logs modeless.
        self.window.grab_set()

    def _build_ui(self):
        root = ttk.Frame(self.window, padding=12)
        root.pack(fill="both", expand=True)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(7, weight=3)
        root.rowconfigure(8, weight=1)

        ttk.Label(root, text="GridCodes Migration", font=("Segoe UI", 16, "bold")).grid(
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
        ttk.Label(profile, text="Vehicle name for GC filenames:").grid(row=0, column=0, sticky="w")
        ttk.Entry(profile, textvariable=self.vehicle_var, width=12).grid(row=0, column=1, sticky="w", padx=(6, 18))
        ttk.Label(profile, text="PowerMax 1Ph [var]:").grid(row=0, column=2, sticky="w")
        ttk.Entry(profile, textvariable=self.power_1ph_var, width=10, justify="right").grid(row=0, column=3, sticky="w", padx=(6, 18))
        ttk.Label(profile, text="PowerMax 3Ph [var]:").grid(row=0, column=4, sticky="w")
        ttk.Entry(profile, textvariable=self.power_3ph_var, width=10, justify="right").grid(row=0, column=5, sticky="w", padx=(6, 0))
        ttk.Label(
            profile,
            text="Leave all fields empty to preserve generic migration behavior. Values are applied only when confirmed in the preview.",
            bootstyle="secondary",
        ).grid(row=1, column=0, columnspan=6, sticky="w", pady=(4, 0))

        actions = ttk.Frame(root)
        actions.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(10, 8))
        self.analyze_button = ttk.Button(actions, text="Analyze migration", bootstyle="primary", command=self.analyze)
        self.analyze_button.pack(side="left", padx=(0, 6))
        self.export_button = ttk.Button(actions, text="Export migrated files", bootstyle="success", state="disabled", command=self.export)
        self.export_button.pack(side="left", padx=(0, 6))
        self.upload_button = ttk.Button(actions, text="Upload exported files to EVSE", bootstyle="warning", state="disabled", command=self.upload)
        self.upload_button.pack(side="left")
        ttk.Button(actions, text="Close", bootstyle="secondary", command=self.close).pack(side="right")

        ttk.Label(root, textvariable=self.status_var, bootstyle="info").grid(
            row=5, column=0, columnspan=3, sticky="w", pady=(0, 6)
        )
        ttk.Label(root, textvariable=self.summary_var, bootstyle="secondary").grid(
            row=6, column=0, columnspan=3, sticky="w", pady=(0, 6)
        )

        results = ttk.Labelframe(root, text="Analysis preview", padding=6)
        results.grid(row=7, column=0, columnspan=3, sticky="nsew")
        results.columnconfigure(0, weight=1)
        results.rowconfigure(0, weight=1)
        columns = ("file", "source", "target", "renamed", "added", "removed", "warnings")
        self.tree = ttk.Treeview(results, columns=columns, show="headings", height=13)
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
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind("<<TreeviewSelect>>", self._show_selected_details)

        detail = ttk.Labelframe(root, text="Selected file details", padding=5)
        detail.grid(row=8, column=0, columnspan=3, sticky="nsew", pady=(8, 0))
        detail.columnconfigure(0, weight=1)
        detail.rowconfigure(0, weight=1)
        self.details = tk.Text(detail, height=8, wrap="word", state="disabled")
        self.details.grid(row=0, column=0, sticky="nsew")

    def _path_row(self, parent, row, column, label, variable, command):
        ttk.Label(parent, text=f"{label}:").grid(
            row=row, column=column, sticky="w", padx=(0, 6), pady=3
        )
        ttk.Entry(parent, textvariable=variable).grid(
            row=row, column=column + 1, sticky="ew", pady=3
        )
        ttk.Button(parent, text="Browse", command=command).grid(
            row=row,
            column=column + 2,
            sticky="e",
            padx=(6, 12 if column == 0 else 0),
            pady=3,
        )

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

        def worker():
            try:
                plan = analyze_migration(
                    source,
                    template,
                    self.rules_var.get().strip() or None,
                    vehicle_name=self.vehicle_var.get(),
                    power_max_1ph_var=self.power_1ph_var.get(),
                    power_max_3ph_var=self.power_3ph_var.get(),
                )
                result = (plan, None)
            except Exception as exc:
                result = (None, exc)
            self.window.after(0, lambda: self._analysis_finished(*result))

        threading.Thread(target=worker, daemon=True).start()

    def _analysis_finished(self, plan, error):
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
        except MigrationError as exc:
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
