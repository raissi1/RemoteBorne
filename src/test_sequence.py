"""V16 automated P/Q and CosPhi test sequencer.

This module is intentionally plain Python. The V15 delivery embedded the
sequencer as compressed bytecode, which made reviews, maintenance, and
endpoint-security checks unnecessarily difficult. The public API remains
compatible with :mod:`RemoteBorneManager`.
"""

from __future__ import annotations

import csv
import math
import re
import time
import tkinter as tk
from tkinter import filedialog, messagebox

import ttkbootstrap as ttk

try:
    from .energy_manager import ENERGY_TOOL_RESOLVE
    from .setpoint_validation import (
        MAX_REACTIVE_VAR as MAX_REACTIVE_VAR_LIMIT,
        finite_number,
        validate_active_power,
        validate_cosphi,
        validate_reactive_power,
    )
    from .utils_ui import center_window
except ImportError:
    try:
        from energy_manager import ENERGY_TOOL_RESOLVE
        from setpoint_validation import (
            MAX_REACTIVE_VAR as MAX_REACTIVE_VAR_LIMIT,
            finite_number,
            validate_active_power,
            validate_cosphi,
            validate_reactive_power,
        )
        from utils_ui import center_window
    except ImportError:
        from src.energy_manager import ENERGY_TOOL_RESOLVE
        from src.setpoint_validation import (
            MAX_REACTIVE_VAR as MAX_REACTIVE_VAR_LIMIT,
            finite_number,
            validate_active_power,
            validate_cosphi,
            validate_reactive_power,
        )
        from src.utils_ui import center_window


class TestSequenceWindow:
    """Create and execute an ordered list of EVSE power plateaus."""

    MAX_REACTIVE_VAR = MAX_REACTIVE_VAR_LIMIT
    MIN_HOLD_SECONDS = 1
    MAX_HOLD_SECONDS = 86400

    def __init__(
        self,
        master,
        ssh_queue,
        is_connected,
        pn_limit_provider,
        on_close=None,
        on_steps_changed=None,
    ):
        self.master = master
        self.ssh_queue = ssh_queue
        self.is_connected = is_connected
        self.pn_limit_provider = pn_limit_provider
        self._on_close_callback = on_close
        self._on_steps_changed = on_steps_changed
        self._extra_editable_widgets = []
        self.steps = []
        self.run_id = 0
        self._active_queue_token = None
        self.current_index = 0
        self.running = False
        self.paused = False
        self.stop_requested = False
        self._hold_deadline = None
        self._pause_started_at = None

        # RBM applies its final adaptive geometry before this dialog is mapped.
        self.win = ttk.Toplevel(master)
        self.win.withdraw()
        self.win.title("Test Sequence")
        self.win.minsize(900, 650)
        self.win.resizable(True, True)
        center_window(master, self.win, 980, 700)
        self.win.transient(master)
        self.win.protocol("WM_DELETE_WINDOW", self.close)

        self.mode_var = tk.StringVar(value="P/Q")
        self.active_var = tk.StringVar(value="0")
        self.reactive_var = tk.StringVar(value="")
        self.cosphi_var = tk.StringVar(value="1")
        self.hold_var = tk.StringVar(value="10")
        self.status_var = tk.StringVar(
            value="Ready - build and validate a sequence before starting."
        )
        self.tree = self.log_text = self.q_entry = self.cosphi_entry = None
        self.btn_add = self.btn_update = self.btn_remove = self.btn_clear = None
        self.btn_up = self.btn_down = self.btn_start = None
        self.btn_pause = self.btn_stop = self.btn_import = None

        self._build_ui()
        self._install_numeric_validation()
        self._on_mode_changed()

    def _build_ui(self):
        root = ttk.Frame(self.win, padding=10)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=1)
        root.rowconfigure(4, weight=1)

        header = ttk.Frame(root)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        header.columnconfigure(0, weight=1)
        ttk.Label(
            header, text="Automated Test Sequence", font=("Segoe UI", 16, "bold")
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(header, textvariable=self.status_var, bootstyle="info").grid(
            row=0, column=1, sticky="e"
        )
        ttk.Label(
            header,
            text="Each plateau is sent only after the previous command and hold time complete.",
            bootstyle="secondary",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))

        editor = ttk.Labelframe(root, text="Plateau editor", padding=8)
        editor.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        for column in (1, 3, 5, 7, 9):
            editor.columnconfigure(column, weight=1)

        ttk.Label(editor, text="Mode").grid(row=0, column=0, sticky="w")
        mode = ttk.Combobox(
            editor,
            textvariable=self.mode_var,
            values=("P/Q", "CosPhi"),
            width=10,
            state="readonly",
        )
        mode.grid(row=0, column=1, sticky="ew", padx=(5, 10))
        mode.bind("<<ComboboxSelected>>", lambda _event: self._on_mode_changed())
        ttk.Label(editor, text="Active P [W]").grid(row=0, column=2, sticky="w")
        ttk.Entry(editor, textvariable=self.active_var, width=12, justify="right").grid(
            row=0, column=3, sticky="ew", padx=(5, 10)
        )
        ttk.Label(editor, text="Reactive Q [var]").grid(row=0, column=4, sticky="w")
        self.q_entry = ttk.Entry(
            editor, textvariable=self.reactive_var, width=12, justify="right"
        )
        self.q_entry.grid(row=0, column=5, sticky="ew", padx=(5, 10))
        ttk.Label(editor, text="CosPhi").grid(row=0, column=6, sticky="w")
        self.cosphi_entry = ttk.Entry(
            editor, textvariable=self.cosphi_var, width=9, justify="right"
        )
        self.cosphi_entry.grid(row=0, column=7, sticky="ew", padx=(5, 10))
        ttk.Label(editor, text="Hold [s]").grid(row=0, column=8, sticky="w")
        ttk.Entry(editor, textvariable=self.hold_var, width=8, justify="right").grid(
            row=0, column=9, sticky="ew", padx=(5, 0)
        )
        ttk.Label(
            editor,
            text="Leave Q empty to send active power only. An empty CosPhi defaults to 1.",
            bootstyle="secondary",
        ).grid(row=1, column=0, columnspan=10, sticky="w", pady=(5, 2))

        edits = ttk.Frame(editor)
        edits.grid(row=2, column=0, columnspan=10, sticky="w")
        self.btn_add = ttk.Button(edits, text="Add plateau", command=self.add_step)
        self.btn_add.pack(side="left", padx=(0, 6))
        self.btn_update = ttk.Button(
            edits, text="Update selected", command=self.update_selected
        )
        self.btn_update.pack(side="left", padx=(0, 6))
        self.btn_remove = ttk.Button(
            edits, text="Remove", bootstyle="danger", command=self.remove_selected
        )
        self.btn_remove.pack(side="left", padx=(0, 6))
        self.btn_up = ttk.Button(
            edits, text="Move up", command=lambda: self.move_selected(-1)
        )
        self.btn_up.pack(side="left", padx=(0, 6))
        self.btn_down = ttk.Button(
            edits, text="Move down", command=lambda: self.move_selected(1)
        )
        self.btn_down.pack(side="left", padx=(0, 6))
        self.btn_clear = ttk.Button(
            edits, text="Clear", bootstyle="secondary", command=self.clear_steps
        )
        self.btn_clear.pack(
            side="left"
        )

        sequence = ttk.Labelframe(root, text="Sequence", padding=6)
        sequence.grid(row=2, column=0, sticky="nsew", pady=(0, 6))
        sequence.columnconfigure(0, weight=1)
        sequence.rowconfigure(0, weight=1)
        columns = ("step", "mode", "active", "detail", "hold", "status")
        self.tree = ttk.Treeview(sequence, columns=columns, show="headings", height=8)
        headers = {
            "step": "#",
            "mode": "Mode",
            "active": "Active P [W]",
            "detail": "Q [var] / CosPhi",
            "hold": "Hold [s]",
            "status": "Status",
        }
        widths = {"step": 45, "mode": 90, "active": 130, "detail": 170, "hold": 90, "status": 180}
        for name in columns:
            self.tree.heading(name, text=headers[name])
            self.tree.column(name, width=widths[name], anchor="center", stretch=True)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(sequence, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<<TreeviewSelect>>", self._load_selected)

        controls = ttk.Frame(root)
        controls.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        self.btn_start = ttk.Button(
            controls, text="Start sequence", bootstyle="success", command=self.start
        )
        self.btn_start.pack(side="left", padx=(0, 6))
        self.btn_pause = ttk.Button(
            controls, text="Pause", command=self.toggle_pause, state="disabled"
        )
        self.btn_pause.pack(side="left", padx=(0, 6))
        self.btn_stop = ttk.Button(
            controls,
            text="Stop after current command",
            bootstyle="secondary",
            command=self.stop,
            state="disabled",
        )
        self.btn_stop.pack(side="left")
        ttk.Button(controls, text="Close", bootstyle="danger", command=self.close).pack(
            side="right"
        )
        self.btn_import = ttk.Button(
            controls, text="Import sequence", command=self.import_csv
        )
        self.btn_import.pack(
            side="right", padx=(0, 6)
        )
        ttk.Button(controls, text="Save as CSV", command=self.export_csv).pack(
            side="right", padx=(0, 6)
        )

        log_frame = ttk.Labelframe(root, text="Sequence log", padding=5)
        log_frame.grid(row=4, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_text = tk.Text(log_frame, height=6, wrap="word", state="disabled")
        self.log_text.grid(row=0, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=log_scroll.set)

    def _on_mode_changed(self):
        is_pq = self.mode_var.get() == "P/Q"
        self.q_entry.configure(state="normal" if is_pq else "disabled")
        self.cosphi_entry.configure(state="disabled" if is_pq else "normal")
        if not is_pq and not self.cosphi_var.get().strip():
            self.cosphi_var.set("1")

    def _log(self, message):
        try:
            self.log_text.configure(state="normal")
            self.log_text.insert("end", f"[{time.strftime('%H:%M:%S')}] {message}\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        except tk.TclError:
            pass

    def _popup(self, kind, title, message):
        self.win.lift()
        return getattr(messagebox, kind)(title, message, parent=self.win)

    @staticmethod
    def _number(value, field):
        return finite_number(value, field)

    @staticmethod
    def _is_partial_number(value):
        """Allow normal typing states while rejecting non-numeric pasted text."""
        raw = str(value).strip()
        return raw in ("", "-", ".", "-.") or bool(
            re.fullmatch(r"-?(?:\d+(?:\.\d*)?|\.\d+)", raw)
        )

    def _install_numeric_validation(self):
        """Reject non-numeric text for all setpoint fields, including paste."""
        for variable in (
            self.active_var,
            self.reactive_var,
            self.cosphi_var,
            self.hold_var,
        ):
            last_valid = [variable.get()]
            changing = [False]

            def validate(*_args, _variable=variable, _last_valid=last_valid, _changing=changing):
                if _changing[0]:
                    return
                proposed = _variable.get()
                if self._is_partial_number(proposed):
                    _last_valid[0] = proposed
                    return
                _changing[0] = True
                try:
                    _variable.set(_last_valid[0])
                finally:
                    _changing[0] = False

            variable.trace_add("write", validate)

    def register_editable_widgets(self, *widgets):
        """Register optional host controls that must lock during execution."""
        self._extra_editable_widgets.extend(
            widget for widget in widgets if widget is not None
        )

    def _notify_steps_changed(self):
        """Let the host retain the session after a successful user edit."""
        if callable(self._on_steps_changed):
            self._on_steps_changed(self)

    def _pn_limit(self):
        try:
            return max(0.0, float(self.pn_limit_provider()))
        except Exception:
            return 0.0

    def _form_step(self):
        return self._build_step(
            self.mode_var.get(),
            self.active_var.get(),
            self.reactive_var.get(),
            self.cosphi_var.get(),
            self.hold_var.get(),
        )

    def _build_step(self, mode, active_value, reactive_value, cosphi_value, hold_value):
        """Build one validated plateau from UI or imported CSV values."""
        mode = str(mode).strip()
        if mode not in ("P/Q", "CosPhi"):
            raise ValueError("Select either P/Q or CosPhi mode.")
        active = validate_active_power(active_value, self._pn_limit())
        hold = self._number(hold_value, "Hold time")
        if not self.MIN_HOLD_SECONDS <= hold <= self.MAX_HOLD_SECONDS:
            raise ValueError(
                f"Hold time must be between {self.MIN_HOLD_SECONDS} and {self.MAX_HOLD_SECONDS} seconds."
            )
        step = {"mode": mode, "active": active, "hold": int(round(hold)), "status": "Ready"}
        if mode == "P/Q":
            step["reactive"] = validate_reactive_power(reactive_value, optional=True)
        else:
            step["cosphi"] = validate_cosphi(cosphi_value, default=1.0)
        return step

    def _selected_index(self):
        selection = self.tree.selection()
        if not selection:
            return None
        try:
            return int(self.tree.item(selection[0], "values")[0]) - 1
        except (IndexError, TypeError, ValueError):
            return None

    def _render_steps(self, select_index=None):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for index, step in enumerate(self.steps):
            if step["mode"] == "P/Q":
                detail = "Q omitted" if step.get("reactive") is None else f"Q = {step['reactive']} var"
            else:
                detail = f"CosPhi = {step.get('cosphi', 1):g}"
            item = self.tree.insert(
                "", "end", values=(index + 1, step["mode"], step["active"], detail, step["hold"], step.get("status", "Ready"))
            )
            if select_index == index:
                self.tree.selection_set(item)
                self.tree.focus(item)

    def _set_editing_enabled(self, enabled):
        state = "normal" if enabled else "disabled"
        for button in (
            self.btn_add,
            self.btn_update,
            self.btn_remove,
            self.btn_clear,
            self.btn_up,
            self.btn_down,
            self.btn_import,
            *self._extra_editable_widgets,
        ):
            button.configure(state=state)

    def add_step(self):
        if self.running:
            return
        try:
            self.steps.append(self._form_step())
        except ValueError as exc:
            self._popup("showwarning", "Test Sequence", str(exc))
            return
        self._render_steps(select_index=len(self.steps) - 1)
        self._log(f"Added plateau {len(self.steps)}.")
        self._notify_steps_changed()

    def update_selected(self):
        if self.running:
            return
        index = self._selected_index()
        if index is None:
            self._popup("showinfo", "Test Sequence", "Select a plateau to update.")
            return
        try:
            self.steps[index] = self._form_step()
        except ValueError as exc:
            self._popup("showwarning", "Test Sequence", str(exc))
            return
        self._render_steps(select_index=index)
        self._log(f"Updated plateau {index + 1}.")
        self._notify_steps_changed()

    def remove_selected(self):
        if self.running:
            return
        index = self._selected_index()
        if index is None:
            self._popup("showinfo", "Test Sequence", "Select a plateau to remove.")
            return
        self.steps.pop(index)
        self._render_steps(select_index=min(index, len(self.steps) - 1))
        self._log(f"Removed plateau {index + 1}.")
        self._notify_steps_changed()

    def move_selected(self, direction):
        if self.running:
            return
        index = self._selected_index()
        if index is None:
            self._popup("showinfo", "Test Sequence", "Select a plateau to move.")
            return
        target = index + direction
        if not 0 <= target < len(self.steps):
            return
        self.steps[index], self.steps[target] = self.steps[target], self.steps[index]
        self._render_steps(select_index=target)
        self._notify_steps_changed()

    def clear_steps(self):
        if self.running or not self.steps:
            return
        if not self._popup("askyesno", "Test Sequence", "Clear every plateau in this sequence?"):
            return
        self.steps.clear()
        self._render_steps()
        self._log("Sequence cleared.")
        self._notify_steps_changed()

    def _load_selected(self, _event=None):
        if self.running:
            return
        index = self._selected_index()
        if index is None or index >= len(self.steps):
            return
        step = self.steps[index]
        self.mode_var.set(step["mode"])
        self.active_var.set(str(step["active"]))
        self.reactive_var.set("" if step.get("reactive") is None else str(step.get("reactive")))
        self.cosphi_var.set(str(step.get("cosphi", 1)))
        self.hold_var.set(str(step["hold"]))
        self._on_mode_changed()

    def _command_for(self, step):
        if step["mode"] == "P/Q":
            reactive = step.get("reactive")
            q_option = "" if reactive is None else f" --reactive-power {reactive}"
            detail = "Q omitted" if reactive is None else f"Q={reactive} var"
            command = (
                "cd /var/aux/EnergyManager && export LD_LIBRARY_PATH=/usr/local/lib && "
                f"{ENERGY_TOOL_RESOLVE}"
                f'"$EM_TOOL" -S -s ocpp -a --power {step["active"]}{q_option} -m CentralSetpoint'
            )
            return command, f"P={step['active']} W, {detail}"
        cosphi = step["cosphi"]
        q_auto = int(round(abs(step["active"]) * math.tan(math.acos(cosphi))))
        command = (
            "cd /var/aux/EnergyManager && export LD_LIBRARY_PATH=/usr/local/lib && "
            f"{ENERGY_TOOL_RESOLVE}"
            f'"$EM_TOOL" --grid-option "SetpointCosPhi_Pct={int(round(cosphi * 100))}" '
            f'&& "$EM_TOOL" -S -s ocpp -a --power {step["active"]} -m CentralSetpoint'
        )
        return command, f"P={step['active']} W, CosPhi={cosphi:g}, Q auto={q_auto} var"

    def _validate_sequence(self):
        if not self.steps:
            raise ValueError("Add at least one plateau before starting.")
        validated = []
        for step in self.steps:
            self.mode_var.set(step["mode"])
            self.active_var.set(str(step["active"]))
            self.reactive_var.set("" if step.get("reactive") is None else str(step.get("reactive")))
            self.cosphi_var.set(str(step.get("cosphi", 1)))
            self.hold_var.set(str(step["hold"]))
            validated.append(self._form_step())
        self.steps = validated

    def start(self):
        if self.running:
            return
        if not self.is_connected():
            self._popup("showwarning", "Test Sequence", "SSH is not connected.")
            return
        try:
            self._validate_sequence()
        except ValueError as exc:
            self._popup("showwarning", "Test Sequence", str(exc))
            return
        self.run_id += 1
        self._active_queue_token = f"test-sequence:{self.run_id}"
        self.current_index = 0
        self.running = True
        self.paused = self.stop_requested = False
        self._render_steps(select_index=0)
        self._set_editing_enabled(False)
        self.btn_start.configure(state="disabled")
        self.btn_pause.configure(state="normal", text="Pause")
        self.btn_stop.configure(state="normal")
        self.status_var.set(f"Running 0 of {len(self.steps)} plateaus")
        self._log(f"Sequence started with {len(self.steps)} plateau(s).")
        self._run_next(self.run_id)

    def _run_next(self, run_id):
        if run_id != self.run_id or not self.running:
            return
        if self.stop_requested:
            self._finish("Stopped by operator")
            return
        if self.paused:
            self.win.after(250, lambda: self._run_next(run_id))
            return
        if not self.is_connected():
            self._abort("SSH connection lost. Remaining plateaus were not sent.")
            return
        if self.current_index >= len(self.steps):
            self._finish("Sequence completed")
            return
        step = self.steps[self.current_index]
        step["status"] = "Sending command"
        self._render_steps(select_index=self.current_index)
        self.status_var.set(f"Sending plateau {self.current_index + 1} of {len(self.steps)}")
        command, description = self._command_for(step)
        self._log(f"Plateau {self.current_index + 1}: {description}")
        index = self.current_index
        queued = self.ssh_queue.execute(
            command,
            callback=lambda result: self._command_finished(run_id, index, result),
            timeout=30,
            auto_retry=False,
            label=f"Sequence plateau {index + 1}",
            silent=False,
            cancel_token=self._active_queue_token,
        )
        if not queued:
            self._abort("The command queue rejected this plateau. Sequence stopped safely.")

    def _command_finished(self, run_id, index, result):
        if run_id != self.run_id or not self.running or index >= len(self.steps):
            return
        step = self.steps[index]
        if not result.get("success"):
            step["status"] = "Error"
            self._render_steps(select_index=index)
            detail = (result.get("err") or result.get("out") or "Unknown error").strip()
            self._abort(f"Plateau {index + 1} failed: {detail}")
            return
        if self.stop_requested:
            step["status"] = "Sent - stop requested"
            self._render_steps(select_index=index)
            self._finish("Stopped after current command")
            return
        step["status"] = f"Holding {step['hold']} s"
        self._render_steps(select_index=index)
        self._hold_deadline = time.monotonic() + step["hold"]
        self._wait_hold(run_id, index)

    def _wait_hold(self, run_id, index):
        if run_id != self.run_id or not self.running:
            return
        if self.stop_requested:
            self._finish("Stopped by operator")
            return
        if self.paused:
            self.win.after(250, lambda: self._wait_hold(run_id, index))
            return
        remaining = max(0, int(math.ceil(self._hold_deadline - time.monotonic())))
        if remaining:
            self.status_var.set(f"Holding plateau {index + 1}: {remaining} s remaining")
            self.win.after(250, lambda: self._wait_hold(run_id, index))
            return
        self.steps[index]["status"] = "Completed"
        self.current_index = index + 1
        self._render_steps(select_index=min(self.current_index, len(self.steps) - 1))
        self._run_next(run_id)

    def toggle_pause(self):
        if not self.running:
            return
        if not self.paused:
            self.paused = True
            self._pause_started_at = time.monotonic()
            self.btn_pause.configure(text="Resume")
            self.status_var.set("Sequence paused")
            self._log("Sequence paused.")
            return
        self.paused = False
        if self._hold_deadline is not None and self._pause_started_at is not None:
            self._hold_deadline += time.monotonic() - self._pause_started_at
        self._pause_started_at = None
        self.btn_pause.configure(text="Pause")
        self._log("Sequence resumed.")
        self._run_next(self.run_id)

    def stop(self):
        if not self.running:
            return
        self.stop_requested = True
        self.paused = False
        self.btn_pause.configure(state="disabled", text="Pause")
        self.btn_stop.configure(state="disabled")
        cancelled = self.ssh_queue.cancel_pending(self._active_queue_token)
        if cancelled:
            self.status_var.set("Stopped before the next queued command")
            self._log("Stop requested: queued plateau cancelled before sending.")
            self._finish("Stopped by operator")
            return
        self.status_var.set("Stopping after the current command")
        self._log("Stop requested after the current command.")

    def _abort(self, reason):
        self._log(reason)
        self._finish("Sequence aborted")
        self._popup("showerror", "Test Sequence", reason)

    def _finish(self, status):
        self.running = self.paused = self.stop_requested = False
        self._active_queue_token = None
        self._hold_deadline = self._pause_started_at = None
        self.status_var.set(status)
        self._set_editing_enabled(True)
        self.btn_start.configure(state="normal")
        self.btn_pause.configure(state="disabled", text="Pause")
        self.btn_stop.configure(state="disabled")
        self._render_steps(select_index=min(self.current_index, len(self.steps) - 1))
        self._log(status)

    def export_csv(self):
        path = filedialog.asksaveasfilename(
            parent=self.win,
            title="Export Test Sequence",
            defaultextension=".csv",
            filetypes=[("RBM Test Sequence CSV", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(("step", "mode", "active_w", "reactive_var", "cosphi", "hold_seconds", "status"))
                for index, step in enumerate(self.steps, start=1):
                    writer.writerow((index, step["mode"], step["active"], step.get("reactive", ""), step.get("cosphi", ""), step["hold"], step.get("status", "")))
        except OSError as exc:
            self._popup("showerror", "Test Sequence", f"Unable to export sequence:\n{exc}")
            return
        self._log(f"Sequence exported: {path}")

    def _read_csv_sequence(self, path):
        """Read a saved sequence atomically; no partial import is possible."""
        required_columns = {"mode", "active_w", "reactive_var", "cosphi", "hold_seconds"}
        with open(path, "r", newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or not required_columns.issubset(reader.fieldnames):
                raise ValueError("This file is not a valid RBM Test Sequence CSV.")
            steps = []
            for row_number, row in enumerate(reader, start=2):
                if not any(str(value or "").strip() for value in row.values()):
                    continue
                try:
                    steps.append(
                        self._build_step(
                            row.get("mode", ""),
                            row.get("active_w", ""),
                            row.get("reactive_var", ""),
                            row.get("cosphi", ""),
                            row.get("hold_seconds", ""),
                        )
                    )
                except ValueError as exc:
                    raise ValueError(f"CSV row {row_number}: {exc}") from exc
        if not steps:
            raise ValueError("The selected CSV does not contain any sequence step.")
        return steps

    def import_csv(self):
        if self.running:
            self._popup("showwarning", "Test Sequence", "Stop the sequence before importing another one.")
            return
        path = filedialog.askopenfilename(
            parent=self.win,
            title="Import Test Sequence",
            filetypes=[("RBM Test Sequence CSV", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            steps = self._read_csv_sequence(path)
        except (OSError, ValueError) as exc:
            self._popup("showerror", "Test Sequence", f"Unable to import sequence:\n{exc}")
            return
        self.steps = steps
        self.current_index = 0
        self._render_steps(select_index=0)
        self._notify_steps_changed()
        self.status_var.set(f"Imported {len(steps)} plateau(s) - validate before starting.")
        self._log(f"Sequence imported: {path} ({len(steps)} plateau(s)).")

    def close(self, force=False):
        if self.running and not force:
            self._popup("showwarning", "Test Sequence", "Stop the sequence before closing this window.")
            return
        if self.running:
            self.run_id += 1
            self.stop()
        callback = self._on_close_callback
        self._on_close_callback = None
        if callable(callback):
            callback()
        try:
            self.win.destroy()
        except tk.TclError:
            pass
