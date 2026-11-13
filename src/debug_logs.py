import os
import sys
import subprocess
import threading
import re
import datetime
import json
import zipfile
from collections import deque
from pathlib import Path
from typing import Optional, Union
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter.scrolledtext import ScrolledText

try:
    from .utils_ui import center_window
except ImportError:
    try:
        from utils_ui import center_window
    except ImportError:
        from src.utils_ui import center_window

MAX_LINES = 10000  # max lignes conservÃ©es en mÃ©moire ET dans la vue
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0



def search_log_buffers(buffers, query, ignore_case=True, limit_per_log=500):
    """Search literal text in each received buffer, independently of tab filters.

    Count every matching line, but bound the displayed results per source so a
    common query cannot flood the UI. Rows retain their source log name.
    """
    counts, rows = {}, []
    if not query:
        return counts, rows
    needle = query.casefold() if ignore_case else query
    for name, lines in buffers.items():
        recent = deque(maxlen=limit_per_log)
        count = 0
        for line in lines:
            haystack = line.casefold() if ignore_case else line
            if needle in haystack:
                count += 1
                recent.append((name, line))
        counts[name] = count
        rows.extend(recent)
    return counts, rows


def _detect_plink() -> str:
    """
    Essaie d'utiliser plink.exe local (tools/ ou mÃªme dossier),
    sinon 'plink' depuis le PATH Windows.
    """
    if getattr(sys, "frozen", False):
        project_root = os.path.dirname(sys.executable)
        base_dir = project_root
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        # si on est dans src/, on remonte au projet
        project_root = (
            os.path.dirname(base_dir)
            if os.path.basename(base_dir).lower() == "src"
            else base_dir
        )
    tools_dir = os.path.join(project_root, "tools")

    candidates = [
        os.path.join(tools_dir, "plink.exe"),
        os.path.join(base_dir, "plink.exe"),
        "plink",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return "plink"


PLINK_PATH = _detect_plink()


def _runtime_logs_dir() -> str:
    """Return a writable, launch-directory-independent folder for captures."""
    base_dir = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base_dir, "RemoteBorneManager", "logs")


def _runtime_incidents_dir() -> str:
    """Return the per-user location used for operator incident captures."""
    base_dir = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base_dir, "RemoteBorneManager", "incidents")


def parse_diagnostic_line(log_name: str, line: str) -> dict[str, str]:
    """Extract stable operator metrics from one service-log line.

    The EVSE services have evolved their surrounding log format over time, so
    the parser deliberately detects only the metric tokens.  It returns raw
    values rather than inferring a pass/fail result from different sign
    conventions used by the services.
    """
    updates = {}
    text = line.strip()
    if not text:
        return updates

    if log_name == "EnergyManager.log":
        match = re.search(r"power_W\s*:\s*([-+]?\d+(?:\.\d+)?)", text, re.I)
        if match:
            updates["setpoint_p"] = f"{match.group(1)} W"
        match = re.search(r"(?:reactive|q)[^\n]*?(?:var|power_W)\s*[:=]\s*([-+]?\d+(?:\.\d+)?)", text, re.I)
        if match:
            updates["setpoint_q"] = f"{match.group(1)} var"

    elif log_name == "ChargerApp.log":
        match = re.search(r"PresentSOC[^\d]*(\d+(?:\.\d+)?)", text, re.I)
        if match:
            updates["soc"] = f"{match.group(1)} %"
        for token, key, unit in (
            ("evActivePowerPresent_W", "charger_p", "W"),
            ("evReactivePowerPresent_W", "charger_q", "var"),
            ("ChargePowerLimit", "charge_limit", "W"),
            ("DischargePowerLimit", "discharge_limit", "W"),
        ):
            match = re.search(rf"{re.escape(token)}[^-+\d]*([-+]?\d+(?:\.\d+)?)", text, re.I)
            if match:
                updates[key] = f"{match.group(1)} {unit}"
        match = re.search(r"(?:T1|Relay)[^\n]*(?:T1\s*[:=]\s*[-+]?\d+)", text, re.I)
        if match:
            updates["temperature"] = match.group(0)

    elif log_name == "iotc-meter-dispatcher.log":
        for token, key, unit in (
            ("activePower", "meter_p", "W"),
            ("reactivePower", "meter_q", "var"),
            ("powerFactor", "power_factor", ""),
            ("frequency", "frequency", "Hz"),
        ):
            match = re.search(rf'"?{re.escape(token)}"?\s*[:=]\s*([-+]?\d+(?:\.\d+)?)', text, re.I)
            if match:
                updates[key] = f"{match.group(1)}{(' ' + unit) if unit else ''}"
        # Some dispatcher builds log a JSON object without a conventional
        # prefix.  This validates the payload for future troubleshooting but
        # does not make the live monitor dependent on a fixed JSON schema.
        if "{" in text:
            try:
                json.loads(text[text.index("{"):])
                updates.setdefault("meter_payload", "valid JSON received")
            except (ValueError, TypeError):
                pass

    elif log_name == "ocpp-service.log":
        # OCPP can emit a large volume of raw JSON frames.  Keep the live
        # diagnosis focused on the service state and the latest operator-useful
        # event instead of copying payloads that may contain identifiers.
        match = re.search(r"OCPPStatePublisher:\s*publish state\s+(OCPPState\w+)", text, re.I)
        if match:
            updates["ocpp_connection"] = match.group(1).replace("OCPPState", "")

        if re.search(r"NetConnection:\s*Connected\b", text, re.I):
            updates["ocpp_connection"] = "Connected"
        elif re.search(r"NetConnection:.*(?:Connection is lost|Connection failed|disconnect)", text, re.I):
            updates["ocpp_connection"] = "Disconnected"

        match = re.search(r"BootNotificationResponse received:\s*(\w+)", text, re.I)
        if match:
            updates["ocpp_boot"] = match.group(1).capitalize()
        elif re.search(r"BootNotification.*rejected", text, re.I):
            updates["ocpp_boot"] = "Rejected"

        # StatusNotification payloads are sent both through internal bridges
        # and to the central system.  Their common fields give a reliable view
        # of the last state for the connector mentioned by this log line.
        if "StatusNotification" in text:
            status = re.search(r'"status"\s*:\s*"([^\"]+)"', text, re.I)
            connector = re.search(r'"connectorId"\s*:\s*(\d+)', text, re.I)
            if status:
                connector_id = connector.group(1) if connector else "?"
                updates["ocpp_connector"] = f"Connector {connector_id}: {status.group(1)}"
                updates["ocpp_exchange"] = "StatusNotification"
                if status.group(1).lower() == "faulted":
                    error_code = re.search(r'"errorCode"\s*:\s*"([^\"]+)"', text, re.I)
                    info = re.search(r'"info"\s*:\s*"([^\"]+)"', text, re.I)
                    vendor_code = re.search(r'"vendorErrorCode"\s*:\s*"([^\"]+)"', text, re.I)
                    details = [error_code.group(1) if error_code else "Faulted"]
                    if info:
                        details.append(info.group(1))
                    if vendor_code:
                        details.append(f"code {vendor_code.group(1)}")
                    updates["ocpp_fault"] = " | ".join(details)

        if re.search(r"\bStartTransaction\b", text, re.I):
            updates["ocpp_transaction"] = "Start transaction"
            updates["ocpp_exchange"] = "StartTransaction"
        elif re.search(r"\bStopTransaction\b", text, re.I):
            updates["ocpp_transaction"] = "Stop transaction"
            updates["ocpp_exchange"] = "StopTransaction"
        elif re.search(r"\bAuthorize\b", text, re.I):
            updates["ocpp_exchange"] = "Authorize"
        elif re.search(r"\bHeartbeat\b", text, re.I):
            updates["ocpp_exchange"] = "Heartbeat"
        elif re.search(r"\bMeterValues\b", text, re.I):
            updates["ocpp_exchange"] = "MeterValues"

        # Smart scheduling and the EnergyManager bridge expose the effective
        # V2X settings. They are more actionable than the raw OCPP frame.
        match = re.search(r"v2x\s*mode\s*:\s*([^;\n]+)", text, re.I)
        if match:
            updates["ocpp_v2x_mode"] = match.group(1).strip()
        match = re.search(
            r"activeSetPoint:.*?Power:\s*([-+]?\d+(?:\.\d+)?)\s*\(W\)",
            text,
            re.I,
        )
        if match:
            updates["ocpp_active_setpoint"] = f"{match.group(1)} W"
        match = re.search(
            r"reactiveSetPoint:.*?Power:\s*([-+]?\d+(?:\.\d+)?)\s*\(W\)",
            text,
            re.I,
        )
        if match:
            updates["ocpp_reactive_setpoint"] = f"{match.group(1)} var"

        for reactive, key, unit in (
            (False, "ocpp_active_setpoint", "W"),
            (True, "ocpp_reactive_setpoint", "var"),
        ):
            name = r"SetPoint\s+Reactive" if reactive else r"SetPoint(?!\s+Reactive)"
            match = re.search(
                rf"{name}\s+power_W\s*:\s*([-+]?\d+(?:\.\d+)?)",
                text,
                re.I,
            )
            if match:
                updates[key] = f"{match.group(1)} {unit}"

        for token, key, unit in (
            (r"Charge:\s*\{\s*maxPower_W", "ocpp_charge_limit", "W"),
            (r"Discharge:\s*\{\s*maxPower_W", "ocpp_discharge_limit", "W"),
            (r"New HW limits received,\s*power_W", "ocpp_hw_power_limit", "W"),
            (r"New HW limits received,\s*current_mA", "ocpp_hw_current_limit", "mA"),
        ):
            match = re.search(rf"{token}\s*:\s*([-+]?\d+(?:\.\d+)?)", text, re.I)
            if match:
                updates[key] = f"{match.group(1)} {unit}"

        # MeterValues frames can contain phase values plus aggregate values.
        # Keep a short phase summary and the latest aggregate reading.
        def meter_values(measurand: str):
            return re.findall(
                rf'"measurand"\s*:\s*"{re.escape(measurand)}"'
                r'(?:\s*,\s*"phase"\s*:\s*"([^"]+)")?'
                r'.*?"value"\s*:\s*"([^"]+)"',
                text,
                re.I,
            )

        voltage_values = meter_values("Voltage")
        if voltage_values:
            updates["ocpp_meter_voltage"] = " | ".join(
                f"{phase or 'total'}: {value} V"
                for phase, value in voltage_values[:3]
            )
        for measurand, key, unit in (
            ("Current.Offered", "ocpp_meter_current", "A"),
            ("Power.Offered", "ocpp_meter_offered_power", "W"),
            ("Power.Active.Import", "ocpp_meter_import_power", "W"),
            ("Power.Active.Export", "ocpp_meter_export_power", "W"),
            ("Energy.Active.Import.Register", "ocpp_meter_import_energy", "Wh"),
            ("Energy.Active.Export.Register", "ocpp_meter_export_energy", "Wh"),
            ("SoC", "ocpp_meter_soc", "%"),
        ):
            values = meter_values(measurand)
            if values:
                updates[key] = f"{values[-1][1]} {unit}"
    return updates


class DebugLogsWindow:
    """
    Ultimate debug tool :
      - tail -f distant via plink
      - filtre type "grep -i" en temps rÃ©el
      - filtres par niveau (ERROR / WARN / INFO)
      - pause du flux temps rÃ©el
      - auto-scroll optionnel
      - sauvegarde de la vue filtrÃ©e
    """

    def __init__(self, parent, ssh_info, host_key=None):
        """
        ssh_info:
            - (host, user, password)
            - ou (host, user, password, port)
        host_key:
            Fingerprint already approved by the main RBM SSH session.  It is
            passed to this independent Plink process so batch mode remains
            secure and does not fail for a newly approved EVSE.
        """
        self.parent = parent
        if len(ssh_info) == 4:
            self.host, self.user, self.password, self.port = ssh_info
        elif len(ssh_info) == 3:
            self.host, self.user, self.password = ssh_info
            self.port = 22
        else:
            raise ValueError("ssh_info must be (host, user, password[, port])")
        self.host_key = (host_key or "").strip()

        # Processus & Ã©tats
        self.processes = {}        # log_name -> subprocess.Popen
        self.running = {}          # log_name -> bool

        # Widgets & options
        self.text_widgets = {}     # log_name -> Text
        self.autoscroll = {}       # log_name -> BooleanVar
        self.pause_live = {}       # log_name -> BooleanVar
        self.saved_files = {}      # log_name -> chemin fichier local

        # Buffers & filtres (pour chaque log)
        self.log_buffers = {}            # log_name -> [str]
        self.filter_text = {}            # log_name -> StringVar
        self.filter_ignore_case = {}     # log_name -> BooleanVar
        self.filter_error = {}           # log_name -> BooleanVar
        self.filter_warn = {}            # log_name -> BooleanVar
        self.filter_info = {}            # log_name -> BooleanVar
        self.diagnosis_values = {}
        self.diagnosis_last_update = tk.StringVar(value="No live service data received yet.")

        # Keep logs visible while the operator continues working in RBM.
        self.window = tk.Toplevel(parent)
        self.window.withdraw()
        self.window.title("Debug Logs - Service Monitor")
        self.window.geometry("1180x760")
        self.window.transient("")
        self.window.minsize(980, 620)

        # Centrage sur la fenÃªtre parente
        center_window(parent, self.window, 1180, 760)

        # Search controls belong only to the Live diagnosis action area.
        self._global_query = ""
        self._global_ignore_case = True
        self._global_search_after = None

        # Notebook
        self.notebook = ttk.Notebook(self.window)
        self.notebook.pack(fill="both", expand=True)

        self._create_diagnosis_tab()

        # Main EVSE service logs.  Every entry gets the same independent
        # live-follow, filtering, local capture, and incident-snapshot flow.
        self.logs_paths = {
            "EnergyManager.log": "/var/aux/EnergyManager/EnergyManager.log",
            "ChargerApp.log": "/var/aux/ChargerApp/ChargerApp.log",
            "iotc-meter-dispatcher.log": "/var/aux/iotc-meter-dispatcher/iotc-meter-dispatcher.log",
            "ocpp-service.log": "/var/aux/ocpp-framework/ocpp-service.log",
        }

        for name, path in self.logs_paths.items():
            self._create_tab(name, path)

        self._create_global_results_tab()
        self.window.bind("<Control-f>", self._focus_global_find)
        self.window.protocol("WM_DELETE_WINDOW", self.on_close)
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()

    def _create_global_find_bar(self, parent):
        bar = ttk.Frame(parent)
        bar.pack(side="left", fill="x", expand=True, padx=(16, 0))
        ttk.Label(bar, text="Find:").pack(side="left")
        self.global_find_var = tk.StringVar(master=self.window)
        self.global_ignore_case_var = tk.BooleanVar(master=self.window, value=True)
        self.global_follow_var = tk.BooleanVar(master=self.window, value=True)
        self.global_find_entry = ttk.Entry(bar, textvariable=self.global_find_var)
        self.global_find_entry.pack(side="left", fill="x", expand=True, padx=6)
        self.global_find_entry.bind("<Return>", self.find_in_all_logs)
        ttk.Button(bar, text="Find", command=self.find_in_all_logs).pack(side="left", padx=3)
        ttk.Button(bar, text="Clear", command=self.clear_global_find).pack(side="left", padx=3)

    def _create_global_results_tab(self):
        self.global_results_tab = ttk.Frame(self.notebook, padding=6)
        self.notebook.add(self.global_results_tab, text="Find - all logs")
        self.global_results_status = tk.StringVar(
            master=self.window,
            value="Search received lines from every log. Start all to receive live data.",
        )
        ttk.Label(
            self.global_results_tab, textvariable=self.global_results_status,
            wraplength=900,
        ).pack(fill="x", pady=(0, 6))
        self.global_results_text = ScrolledText(
            self.global_results_tab, wrap="word", state="disabled",
        )
        self.global_results_text.pack(fill="both", expand=True)
        self.global_results_text.tag_configure("match", background="#ffe082", foreground="#000000")

    def _focus_global_find(self, _event=None):
        self.notebook.select(self.diagnosis_tab)
        self.global_find_entry.focus_set()
        self.global_find_entry.selection_range(0, "end")
        return "break"

    def _cancel_global_search(self):
        if self._global_search_after is not None:
            self.window.after_cancel(self._global_search_after)
            self._global_search_after = None

    def find_in_all_logs(self, _event=None):
        self._cancel_global_search()
        self._global_query = self.global_find_var.get()
        self._global_ignore_case = self.global_ignore_case_var.get()
        self._refresh_global_results()
        self.notebook.select(self.global_results_tab)
        return "break"

    def clear_global_find(self):
        self._cancel_global_search()
        self.global_find_var.set("")
        self._global_query = ""
        self._refresh_global_results()
        self.global_find_entry.focus_set()

    def _schedule_global_search(self):
        # Coalesce incoming streams instead of scanning 40,000 buffered lines
        # for every received line. No remote commands or extra SSH connections.
        if getattr(self, "_global_query", "") and self._global_search_after is None:
            self._global_search_after = self.window.after(500, self._refresh_global_results)

    def _refresh_global_results(self):
        self._global_search_after = None
        query = self._global_query
        counts, rows = search_log_buffers(self.log_buffers, query, self._global_ignore_case)
        widget = self.global_results_text
        position = widget.yview()[0]
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        rendered = [f"[{name}] {line}" for name, line in rows]
        if rendered:
            widget.insert("end", "\n".join(rendered) + "\n")
        if query:
            # Highlight the first occurrence in each result with one Tk call,
            # avoiding thousands of Tcl searches on high-volume streams.
            pattern = re.compile(re.escape(query), re.IGNORECASE if self._global_ignore_case else 0)
            ranges = []
            for number, (name, line) in enumerate(rows, 1):
                match = pattern.search(line)
                if match:
                    offset = len(name) + 3  # [source] prefix
                    ranges.extend((f"{number}.{offset + match.start()}", f"{number}.{offset + match.end()}"))
            if ranges:
                widget.tag_add("match", *ranges)
            total = sum(counts.values())
            detail = " | ".join(f"{name}: {count}" for name, count in counts.items())
            self.global_results_status.set(
                f"{total} matching line(s), {len(rows)} shown (latest 500 per log). "
                f"Received buffers only; updates live.\n{detail}"
            )
        else:
            self.global_results_status.set(
                "Enter text and click Find. Searches received buffers from all logs; "
                "start the streams with Start all."
            )
        widget.configure(state="disabled")
        if self.global_follow_var.get():
            widget.see("end")
        else:
            widget.yview_moveto(position)

    def _create_diagnosis_tab(self):
        """Create a concise, read-only view across the monitored service logs."""
        frame = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(frame, text="Live diagnosis")
        self.diagnosis_tab = frame
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(3, weight=1)

        ttk.Label(
            frame,
            text="Live service diagnosis",
            font=("Segoe UI", 15, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(
            frame,
            text="Values are read from the incoming logs. Only values present in the service logs are shown; power signs are kept raw.",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 10))

        groups = (
            ("Energy Manager", (("setpoint_p", "Last setpoint P"), ("setpoint_q", "Last setpoint Q"))),
            ("Charger", (("soc", "Battery SoC"), ("charger_p", "EV active power"), ("charger_q", "EV reactive power"), ("charge_limit", "Charge limit"), ("discharge_limit", "Discharge limit"), ("temperature", "Temperature"))),
            ("Meter dispatcher", (("meter_p", "Meter active power"), ("meter_q", "Meter reactive power"), ("power_factor", "Power factor"), ("frequency", "Frequency"), ("meter_payload", "Last payload"))),
            (
                "OCPP service",
                (
                    ("ocpp_connection", "Connection"),
                    ("ocpp_boot", "Boot notification"),
                    ("ocpp_connector", "Last connector state"),
                    ("ocpp_fault", "Last reported fault"),
                    ("ocpp_transaction", "Last transaction"),
                    ("ocpp_exchange", "Last OCPP exchange"),
                    ("ocpp_v2x_mode", "V2X mode"),
                    ("ocpp_active_setpoint", "Active setpoint"),
                    ("ocpp_reactive_setpoint", "Reactive setpoint"),
                    ("ocpp_charge_limit", "Charge limit"),
                    ("ocpp_discharge_limit", "Discharge limit"),
                    ("ocpp_hw_power_limit", "HW power limit"),
                    ("ocpp_hw_current_limit", "HW current limit"),
                    ("ocpp_meter_soc", "Meter SoC"),
                    ("ocpp_meter_voltage", "Meter voltage"),
                    ("ocpp_meter_current", "Current offered"),
                    ("ocpp_meter_offered_power", "Power offered"),
                    ("ocpp_meter_import_power", "Active import"),
                    ("ocpp_meter_export_power", "Active export"),
                    ("ocpp_meter_import_energy", "Energy import"),
                    ("ocpp_meter_export_energy", "Energy export"),
                ),
            ),
        )
        for index, (title, metrics) in enumerate(groups):
            row, column = divmod(index, 2)
            group = ttk.Labelframe(frame, text=title, padding=8)
            group.grid(row=row + 2, column=column, sticky="nsew", padx=(0, 8) if column == 0 else (0, 0), pady=(0, 8))
            group.columnconfigure(1, weight=1)
            group.columnconfigure(3, weight=1)
            for metric_index, (key, label) in enumerate(metrics):
                metric_row, metric_column = divmod(metric_index, 2)
                label_column = metric_column * 2
                self.diagnosis_values[key] = tk.StringVar(value="--")
                ttk.Label(group, text=f"{label}:").grid(row=metric_row, column=label_column, sticky="w", padx=(0, 6), pady=2)
                ttk.Label(group, textvariable=self.diagnosis_values[key]).grid(
                    row=metric_row, column=label_column + 1, sticky="w", padx=(0, 12), pady=2
                )

        actions = ttk.Frame(frame)
        actions.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(actions, text="Start all", command=self.start_all_logs).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="Stop all", command=self.stop_all_logs).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="Capture incident", command=self.capture_incident).pack(side="left")
        self._create_global_find_bar(actions)

        # Keep optional search settings and the update status out of the
        # main button row, leaving the query entry room on narrow windows.
        options = ttk.Frame(frame)
        options.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        ttk.Checkbutton(
            options, text="Ignore case", variable=self.global_ignore_case_var,
            command=self.find_in_all_logs,
        ).pack(side="left", padx=(0, 8))
        ttk.Checkbutton(
            options, text="Follow results", variable=self.global_follow_var,
        ).pack(side="left")
        ttk.Label(options, textvariable=self.diagnosis_last_update).pack(side="right")

    def _update_diagnosis(self, log_name: str, line: str):
        updates = parse_diagnostic_line(log_name, line)
        if not updates:
            return
        for key, value in updates.items():
            variable = self.diagnosis_values.get(key)
            if variable is not None:
                variable.set(value)
        self.diagnosis_last_update.set(
            f"Updated {datetime.datetime.now().strftime('%H:%M:%S')} from {log_name}"
        )

    def start_all_logs(self):
        for name in self.logs_paths:
            self.start_log(name)

    def stop_all_logs(self):
        for name in list(self.processes):
            self.stop_log(name, silent=True)
        self._popup_info("Live diagnosis", "All live log streams were stopped.")

    def _incident_summary(self) -> str:
        lines = [
            "RBM Debug incident capture",
            f"Captured: {datetime.datetime.now().isoformat(timespec='seconds')}",
            "",
            "Live diagnosis:",
        ]
        for key in sorted(self.diagnosis_values):
            lines.append(f"- {key}: {self.diagnosis_values[key].get()}")
        lines.extend(("", "Buffered lines:"))
        for name, buffer in self.log_buffers.items():
            lines.append(f"- {name}: {len(buffer)} line(s)")
        return "\n".join(lines) + "\n"

    def _write_incident_capture(
        self, target_dir: Optional[Union[str, Path]] = None
    ) -> Path:
        """Persist a self-contained diagnostic snapshot without credentials."""
        stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        target = Path(target_dir or _runtime_incidents_dir()) / f"incident_{stamp}"
        target.mkdir(parents=True, exist_ok=False)
        (target / "summary.txt").write_text(self._incident_summary(), encoding="utf-8")
        for name, buffer in self.log_buffers.items():
            (target / name).write_text("\n".join(buffer) + ("\n" if buffer else ""), encoding="utf-8")
        archive = target.with_suffix(".zip")
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            for item in target.iterdir():
                bundle.write(item, arcname=item.name)
        return archive

    def capture_incident(self):
        try:
            archive = self._write_incident_capture()
        except OSError as exc:
            self._popup_error("Capture incident", f"Unable to save the incident capture:\n{exc}")
            return
        self._popup_info("Capture incident", f"Diagnostic snapshot saved:\n{archive}")

    def _show_popup(self, popup, title: str, message: str):
        """Keep native dialogs above the Debug Logs window that triggered them."""
        try:
            self.window.lift()
            self.window.attributes("-topmost", True)
            popup(title, message, parent=self.window)
        finally:
            try:
                self.window.attributes("-topmost", False)
                self.window.lift()
            except tk.TclError:
                pass

    def _popup_info(self, title: str, message: str):
        self._show_popup(messagebox.showinfo, title, message)

    def _popup_warning(self, title: str, message: str):
        self._show_popup(messagebox.showwarning, title, message)

    def _popup_error(self, title: str, message: str):
        self._show_popup(messagebox.showerror, title, message)

    # ------------------------------------------------------------------
    # CrÃ©ation d'un onglet complet (zone texte + barre grep + boutons)
    # ------------------------------------------------------------------
    def _create_tab(self, name: str, remote_path: str):
        frame = ttk.Frame(self.notebook)
        self.notebook.add(frame, text=name)

        # layout
        frame.rowconfigure(0, weight=1)  # zone texte
        frame.rowconfigure(1, weight=0)  # barre filtre grep
        frame.rowconfigure(2, weight=0)  # boutons
        frame.columnconfigure(0, weight=1)

        # Zone de texte scrollable
        text_area = ScrolledText(frame, wrap="word", height=20)
        text_area.grid(row=0, column=0, sticky="nsew", padx=2, pady=(2, 0))
        text_area.tag_configure("ERROR", foreground="red")
        text_area.tag_configure("WARN", foreground="orange")
        text_area.tag_configure("INFO", foreground="green")
        self.text_widgets[name] = text_area

        # --- Filtres (grep -i + niveaux) ---
        self.log_buffers[name] = []

        self.filter_text[name] = tk.StringVar()
        self.filter_ignore_case[name] = tk.BooleanVar(value=True)
        self.filter_error[name] = tk.BooleanVar(value=False)
        self.filter_warn[name] = tk.BooleanVar(value=False)
        self.filter_info[name] = tk.BooleanVar(value=False)

        filter_frame = ttk.Frame(frame)
        filter_frame.grid(row=1, column=0, sticky="ew", padx=4, pady=3)
        filter_frame.columnconfigure(1, weight=1)

        ttk.Label(filter_frame, text="grep:").grid(row=0, column=0, padx=4, sticky="w")
        entry = ttk.Entry(filter_frame, textvariable=self.filter_text[name])
        entry.grid(row=0, column=1, sticky="ew", padx=4)
        entry.bind("<Return>", lambda e, n=name: self.apply_filter(n))

        ttk.Checkbutton(
            filter_frame,
            text="-i (ignore case)",
            variable=self.filter_ignore_case[name],
            command=lambda n=name: self.apply_filter(n),
        ).grid(row=0, column=2, padx=4)

        # Filtres par niveau
        ttk.Checkbutton(
            filter_frame,
            text="ERROR",
            variable=self.filter_error[name],
            command=lambda n=name: self.apply_filter(n),
        ).grid(row=1, column=0, padx=4, sticky="w")

        ttk.Checkbutton(
            filter_frame,
            text="WARN",
            variable=self.filter_warn[name],
            command=lambda n=name: self.apply_filter(n),
        ).grid(row=1, column=1, padx=4, sticky="w")

        ttk.Checkbutton(
            filter_frame,
            text="INFO",
            variable=self.filter_info[name],
            command=lambda n=name: self.apply_filter(n),
        ).grid(row=1, column=2, padx=4, sticky="w")

        ttk.Button(
            filter_frame,
            text="Apply",
            command=lambda n=name: self.apply_filter(n),
        ).grid(row=0, column=3, padx=4)

        ttk.Button(
            filter_frame,
            text="Clear",
            command=lambda n=name: self.clear_filter(n),
        ).grid(row=0, column=4, padx=4)

        # Barre de boutons en bas
        self.autoscroll[name] = tk.BooleanVar(value=True)
        self.pause_live[name] = tk.BooleanVar(value=False)

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=2, column=0, sticky="ew", padx=4, pady=(2, 4))
        for col in range(7):
            btn_frame.columnconfigure(col, weight=0)
        btn_frame.columnconfigure(6, weight=1)

        ttk.Button(
            btn_frame, text="Start",
            command=lambda n=name: self.start_log(n)
        ).grid(row=0, column=0, padx=5, pady=5, sticky="w")

        ttk.Button(
            btn_frame, text="Stop",
            command=lambda n=name: self.stop_log(n)
        ).grid(row=0, column=1, padx=5, pady=5, sticky="w")

        ttk.Button(
            btn_frame, text="Clear view",
            command=lambda n=name: self.clear_log(n)
        ).grid(row=0, column=2, padx=5, pady=5, sticky="w")

        ttk.Button(
            btn_frame, text="Save view",
            command=lambda n=name: self.save_log(n)
        ).grid(row=0, column=3, padx=5, pady=5, sticky="w")

        ttk.Button(
            btn_frame, text="Close",
            command=lambda n=name: self.exit_log(n)
        ).grid(row=1, column=6, padx=5, pady=2, sticky="e")

        ttk.Checkbutton(
            btn_frame,
            text="Pause live",
            variable=self.pause_live[name],
            command=lambda n=name: self.on_pause_toggle(n),
        ).grid(row=1, column=0, padx=5, pady=2, sticky="w")

        ttk.Checkbutton(
            btn_frame,
            text="Auto-scroll",
            variable=self.autoscroll[name],
        ).grid(row=1, column=1, padx=5, pady=2, sticky="w")

    # ------------------------------------------------------------------
    # Construction de la commande plink
    # ------------------------------------------------------------------
    def _build_plink_tail_cmd(self, remote_path: str):
        """
        Construit la commande plink pour faire un tail -f sur un fichier de log.
        """
        command = [
            PLINK_PATH,
            "-ssh",
            "-batch",
        ]
        if self.host_key:
            command.extend(["-hostkey", self.host_key])
        command.extend([
            "-P", str(self.port),
            "-l", self.user,
            "-pw", self.password,
            self.host,
            f"tail -f {remote_path}",
        ])
        return command

    # ------------------------------------------------------------------
    # Start / Stop / reader thread
    # ------------------------------------------------------------------
    def start_log(self, log_name: str):
        if log_name in self.processes:
            self._popup_info("Info", f"{log_name} is already being followed.")
            return

        remote_log = self.logs_paths.get(log_name)
        if not remote_log:
            self._popup_error("Error", f"No remote path defined for {log_name}.")
            return

        # Use a per-user folder, not os.getcwd(), so a shortcut or protected
        # installation folder cannot redirect or prevent log capture.
        logs_dir = _runtime_logs_dir()
        date_str = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        file_path = os.path.join(logs_dir, f"{log_name.split('.')[0]}_{date_str}.log")

        try:
            os.makedirs(logs_dir, exist_ok=True)
            log_file = open(file_path, "w", encoding="utf-8")
        except Exception as e:
            self._popup_error("Error", f"Cannot open local log file:\n{e}")
            return

        cmd = self._build_plink_tail_cmd(remote_log)

        try:
            popen_kwargs = {}
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                popen_kwargs["startupinfo"] = startupinfo
                popen_kwargs["creationflags"] = CREATE_NO_WINDOW

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                **popen_kwargs,
            )
        except FileNotFoundError:
            self._popup_error(
                "Error",
                "Unable to start plink.\n"
                "Check that plink.exe is available in the project folder\n"
                "or in the Windows PATH."
            )
            log_file.close()
            return
        except Exception as e:
            self._popup_error("Error", f"Could not start log for {log_name}:\n{e}")
            log_file.close()
            return

        self.processes[log_name] = proc
        self.running[log_name] = True

        self.insert_line(log_name, f"[INFO] Started following {log_name}")
        self.insert_line(log_name, f"[INFO] Local file: {file_path}")

        def reader():
            stopped_by_operator = False
            try:
                while self.running.get(log_name, False):
                    line = proc.stdout.readline()
                    if not line:
                        break
                    try:
                        if self.parent.winfo_exists():
                            self.parent.after(0, self.insert_line, log_name, line)
                        else:
                            break
                    except Exception:
                        break
                    # Ã‰crit dans le fichier local complet
                    log_file.write(line)
                    log_file.flush()
            finally:
                stopped_by_operator = not self.running.get(log_name, False)
                try:
                    if proc.poll() is None:
                        proc.kill()
                except Exception:
                    pass
                try:
                    log_file.close()
                except Exception:
                    pass

                # A failed Plink process must not leave the tab permanently
                # marked as running.  The operator can immediately press Start
                # again after a transient SSH or host-key error.
                if self.processes.get(log_name) is proc:
                    self.processes.pop(log_name, None)
                self.running.pop(log_name, None)

                if not stopped_by_operator:
                    returncode = proc.poll()

                    def report_stream_end():
                        try:
                            if self.window.winfo_exists():
                                self.insert_line(
                                    log_name,
                                    "[ERROR] Log stream stopped "
                                    f"(exit code {returncode}). Press Start to retry.",
                                )
                        except tk.TclError:
                            pass

                    try:
                        if self.parent.winfo_exists():
                            self.parent.after(0, report_stream_end)
                    except Exception:
                        pass

        threading.Thread(target=reader, daemon=True).start()

    # ------------------------------------------------------------------
    # Filtrage type "tail -f | grep -i"
    # ------------------------------------------------------------------
    def _matches_filter(self, log_name: str, line: str) -> bool:
        # grep text
        pattern = (self.filter_text[log_name].get() or "").strip()
        if pattern:
            if self.filter_ignore_case[log_name].get():
                if pattern.lower() not in line.lower():
                    return False
            else:
                if pattern not in line:
                    return False

        # filtres par niveau
        use_error = self.filter_error[log_name].get()
        use_warn = self.filter_warn[log_name].get()
        use_info = self.filter_info[log_name].get()

        if use_error or use_warn or use_info:
            up = line.upper()
            is_err = "ERROR" in up
            is_warn = "WARN" in up
            is_info = "INFO" in up

            if use_error and is_err:
                return True
            if use_warn and is_warn:
                return True
            if use_info and is_info:
                return True
            # au moins un filtre actif mais aucun match
            return False

        return True

    def _append_line_to_widget(self, log_name: str, line: str):
        text_widget = self.text_widgets.get(log_name)
        if text_widget is None:
            return

        # Tag en fonction du niveau
        tag = None
        if re.search(r"\bERROR\b", line, re.IGNORECASE):
            tag = "ERROR"
        elif re.search(r"\bWARN\b", line, re.IGNORECASE):
            tag = "WARN"
        elif re.search(r"\bINFO\b", line, re.IGNORECASE):
            tag = "INFO"

        text_widget.insert(tk.END, line + "\n", tag)

        # Limiter le nombre de lignes affichÃ©es
        try:
            lines = int(text_widget.index("end-1c").split(".")[0])
            if lines > MAX_LINES:
                text_widget.delete("1.0", f"{lines - MAX_LINES}.0")
        except Exception:
            pass

        if self.autoscroll[log_name].get() and not self.pause_live[log_name].get():
            text_widget.see(tk.END)

    def insert_line(self, log_name: str, line: str):
        """
        AppelÃ© Ã  chaque nouvelle ligne reÃ§ue (comme tail -f).
        On stocke dans le buffer + on affiche seulement si Ã§a matche le filtre,
        et si le flux live n'est pas en pause.
        """
        line = line.rstrip("\n")

        # Diagnosis continues updating even when a tab is paused or filtered:
        # the pause is a display preference, not a loss of live telemetry.
        self._update_diagnosis(log_name, line)

        # buffer mÃ©moire
        buf = self.log_buffers.get(log_name)
        if buf is not None:
            buf.append(line)
            if len(buf) > MAX_LINES:
                buf.pop(0)

        # Global Find also receives lines from paused or individually filtered tabs.
        self._schedule_global_search()

        # si pause live : on n'affiche rien, mais on garde dans le buffer
        if self.pause_live[log_name].get():
            return

        if not self._matches_filter(log_name, line):
            return

        self._append_line_to_widget(log_name, line)

    def apply_filter(self, log_name: str):
        """
        RÃ©applique le filtre sur le buffer complet (comme si on faisait
        tail -f | grep ... mais sur l'historique).
        """
        text_widget = self.text_widgets.get(log_name)
        buf = self.log_buffers.get(log_name)
        if text_widget is None or buf is None:
            return

        text_widget.delete("1.0", tk.END)

        for line in buf:
            if self._matches_filter(log_name, line):
                self._append_line_to_widget(log_name, line)

        text_widget.see("end")

    def clear_filter(self, log_name: str):
        self.filter_text[log_name].set("")
        self.filter_ignore_case[log_name].set(True)
        self.filter_error[log_name].set(False)
        self.filter_warn[log_name].set(False)
        self.filter_info[log_name].set(False)
        self.apply_filter(log_name)

    def on_pause_toggle(self, log_name: str):
        """
        Quand on enlÃ¨ve la pause, on rÃ©applique le filtre pour afficher
        l'historique complet Ã  jour.
        """
        if not self.pause_live[log_name].get():
            # on vient de REPRENDRE le flux => on resynchronise la vue
            self.apply_filter(log_name)

    # ------------------------------------------------------------------
    # Boutons
    # ------------------------------------------------------------------
    def stop_log(self, log_name: str, silent: bool = False):
        if log_name in self.processes:
            self.running[log_name] = False
            try:
                self.processes[log_name].kill()
            except Exception:
                pass
            del self.processes[log_name]
        self.running.pop(log_name, None)
        if not silent:
            self._popup_info("Info", f"Stopped following {log_name}.")

    def clear_log(self, log_name: str):
        # efface la vue + le buffer
        if log_name in self.log_buffers:
            self.log_buffers[log_name] = []
        if log_name in self.text_widgets:
            self.text_widgets[log_name].delete("1.0", tk.END)
        self._schedule_global_search()

    def save_log(self, log_name: str):
        """
        Sauvegarde la VUE COURANTE (filtrÃ©e), comme un grep redirigÃ©
        vers un fichier.
        """
        text_widget = self.text_widgets.get(log_name)
        if text_widget is None:
            return

        content = text_widget.get("1.0", tk.END)
        if not content.strip():
            self._popup_warning("Warning", "No content to save.")
            return

        logs_dir = _runtime_logs_dir()
        try:
            os.makedirs(logs_dir, exist_ok=True)
        except Exception as e:
            self._popup_error("Error", f"Cannot create local log folder:\n{e}")
            return

        file_path = filedialog.asksaveasfilename(
            parent=self.window,
            title=f"Save view of {log_name}",
            defaultextension=".log",
            initialfile=f"view_{log_name}",
            initialdir=logs_dir,
        )
        if not file_path:
            return

        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            self._popup_error("Error", f"Could not save log:\n{e}")
            return

        self.saved_files[log_name] = file_path
        self._popup_info("Success", f"Log successfully saved:\n{file_path}")

    def exit_log(self, log_name: str):
        # The Close button closes the shared window, therefore stop every
        # active tail process rather than only the current tab's process.
        self.on_close()

    def on_close(self):
        self._cancel_global_search()
        for log_name in list(self.processes.keys()):
            self.stop_log(log_name, silent=True)
        self.window.destroy()

# ---------- Wrapper utilisation par RemoteBorneManager.py ----------
def open_debug_logs_window(
    parent,
    host: str,
    user: str,
    password: str,
    port: int = 22,
    host_key: str = None,
):
    """
    Appel simple depuis RemoteBorneManager:
        debug_logs.open_debug_logs_window(
            self.root, self.host, self.user, self.password, self.port, host_key
        )
    """
    ssh_info = (host, user, password, port)
    return DebugLogsWindow(parent, ssh_info, host_key=host_key)

