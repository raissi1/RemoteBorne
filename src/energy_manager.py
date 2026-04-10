# ================================================================
# energy_manager.py — PRO VERSION (FULL STABLE)
# ================================================================

import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from tkinter import messagebox, filedialog
import time
import math
import csv
import re

# Import compatible dev + exe
try:
    from .utils_ui import center_window
except ImportError:
    from utils_ui import center_window


ENERGY_TOOL_RESOLVE = (
    'EM_TOOL="$(command -v EnergyManagerTestingTool 2>/dev/null || true)"; '
    'if [ -z "$EM_TOOL" ]; then '
    'for p in /usr/local/bin/EnergyManagerTestingTool /usr/bin/EnergyManagerTestingTool; do '
    '[ -x "$p" ] && EM_TOOL="$p" && break; '
    "done; "
    'fi; '
    'if [ -z "$EM_TOOL" ]; then '
    "echo 'EnergyManagerTestingTool not found' >&2; exit 127; "
    "fi; "
)


class EnergyManagerWindow:
    """Energy Manager PRO - version production"""

    def __init__(self, master, ssh):
        self.master = master
        self.ssh = ssh
        self.history = []

        # ================= WINDOW =================
        self.win = ttk.Toplevel(master)
        self.win.title("Energy Manager PRO")
        self.win.minsize(1100, 700)

        center_window(master, self.win, 1200, 800)

        self.win.transient(master)
        self.win.grab_set()
        self.win.lift()
        self.win.focus_force()
        self.win.protocol("WM_DELETE_WINDOW", self.on_close)

        # ================= VARIABLES =================
        self.p_var = tk.StringVar()
        self.q_var = tk.StringVar()

        self.p_cosphi_var = tk.StringVar()
        self.cosphi_var = tk.StringVar()
        self.q_auto_var = tk.StringVar()

        self.table = None
        self.monitor_text = None

        self.build_ui()

        # Auto update Q
        self.cosphi_var.trace_add("write", lambda *_: self.calculate_q_from_cosphi())

    # ================= POPUPS =================
    def _popup(self, level, title, msg):
        self.win.lift()
        self.win.attributes("-topmost", True)
        try:
            getattr(messagebox, level)(title, msg, parent=self.win)
        finally:
            self.win.attributes("-topmost", False)

    def _popup_info(self, t, m): self._popup("showinfo", t, m)
    def _popup_warning(self, t, m): self._popup("showwarning", t, m)
    def _popup_error(self, t, m): self._popup("showerror", t, m)

    # ================= VALIDATION =================
    def _validate_numeric(self, val):
        return val == "" or re.match(r"^-?\d*(\.\d*)?$", val)

    # ================= UI =================
    def build_ui(self):
        main = ttk.Frame(self.win)
        main.pack(fill="both", expand=True, padx=20, pady=20)

        main.rowconfigure(0, weight=1)
        main.rowconfigure(1, weight=2)
        main.columnconfigure(0, weight=3)
        main.columnconfigure(1, weight=2)

        top = ttk.Frame(main)
        top.grid(row=0, column=0, columnspan=2, sticky="nsew")

        bottom_left = ttk.Frame(main)
        bottom_left.grid(row=1, column=0, sticky="nsew", padx=(0, 10))

        bottom_right = ttk.Frame(main)
        bottom_right.grid(row=1, column=1, sticky="nsew")

        self._build_section_energy(top)
        self._build_section_history(bottom_left)
        self._build_section_monitor(bottom_right)

        footer = ttk.Frame(self.win)
        footer.pack(fill="x", padx=20, pady=10)
        ttk.Button(footer, text="Close", bootstyle="danger", command=self.on_close).pack(side="right")

    # ================= ENERGY =================
    def _build_section_energy(self, parent):
        vcmd = (self.win.register(self._validate_numeric), "%P")

        frm = ttk.Labelframe(parent, text="Energy Control", padding=15)
        frm.pack(fill="both", expand=True)

        # P/Q
        ttk.Label(frm, text="P (W)").grid(row=0, column=0)
        ttk.Entry(frm, textvariable=self.p_var, validate="key", validatecommand=vcmd).grid(row=0, column=1)

        ttk.Label(frm, text="Q (VAR)").grid(row=1, column=0)
        ttk.Entry(frm, textvariable=self.q_var, validate="key", validatecommand=vcmd).grid(row=1, column=1)

        ttk.Button(frm, text="Send P/Q", bootstyle="success", command=self.send_pq).grid(row=2, column=0, columnspan=2)

        # CosPhi
        ttk.Label(frm, text="CosPhi").grid(row=3, column=0)
        ttk.Entry(frm, textvariable=self.cosphi_var, validate="key", validatecommand=vcmd).grid(row=3, column=1)

        ttk.Label(frm, text="Q auto").grid(row=4, column=0)
        ttk.Entry(frm, textvariable=self.q_auto_var, state="readonly").grid(row=4, column=1)

        ttk.Button(frm, text="Calculate Q", command=self.calculate_q_from_cosphi).grid(row=5, column=0)
        ttk.Button(frm, text="Send CosPhi", bootstyle="success", command=self.send_cosphi).grid(row=5, column=1)

    # ================= COMMANDES =================
    def send_pq(self):
        try:
            p = int(float(self.p_var.get()))
            q = int(float(self.q_var.get()))
        except:
            self._popup_warning("Erreur", "Valeurs invalides")
            return

        cmd = (
            f"{ENERGY_TOOL_RESOLVE}"
            f"\"$EM_TOOL\" -S -s ocpp -a --power {p} --reactive-power {q}"
        )
        self.execute_energy_cmd("P/Q", cmd)

    def calculate_q_from_cosphi(self):
        try:
            p = float(self.p_cosphi_var.get())
            cos = float(self.cosphi_var.get())

            if not (-1 < cos <= 1):
                raise ValueError

            if abs(cos) < 0.01:
                self._popup_warning("Danger", "CosPhi trop proche de 0")
                return

            q = abs(p) * math.tan(math.acos(cos))
            self.q_auto_var.set(str(int(round(q))))
        except:
            pass

    def send_cosphi(self):
        try:
            p = int(float(self.p_cosphi_var.get()))
            cos = float(self.cosphi_var.get())
        except:
            self._popup_warning("Erreur", "Valeurs invalides")
            return

        cmd = (
            f"{ENERGY_TOOL_RESOLVE}"
            f"\"$EM_TOOL\" --grid-option \"SetpointCosPhi_Pct={int(cos*100)}\" && "
            f"\"$EM_TOOL\" -S -s ocpp -a --power {p}"
        )

        self.execute_energy_cmd("CosPhi", cmd)

    # ================= EXECUTION =================
    def execute_energy_cmd(self, mode, cmd):
        if not self.ssh or not getattr(self.ssh, "connected", False):
            self._popup_error("SSH", "Non connecté")
            return

        ts = time.strftime("%Y-%m-%d %H:%M:%S")

        def callback(res):
            status = "OK" if res["success"] else f"ERR: {res['err']}"
            self.history.append((ts, mode, cmd, status))
            self.update_history_table()

        self.ssh.execute(cmd, callback=callback)

    # ================= HISTORY =================
    def _build_section_history(self, parent):
        columns = ("timestamp", "mode", "cmd", "status")
        self.table = ttk.Treeview(parent, columns=columns, show="headings")

        for col in columns:
            self.table.heading(col, text=col)

        self.table.pack(fill="both", expand=True)

        ttk.Button(parent, text="Export CSV", command=self.export_csv).pack()

    def update_history_table(self):
        for i in self.table.get_children():
            self.table.delete(i)
        for h in reversed(self.history):
            self.table.insert("", "end", values=h)

    def export_csv(self):
        if not self.history:
            self._popup_warning("Vide", "Aucune donnée")
            return

        path = filedialog.asksaveasfilename(defaultextension=".csv", parent=self.win)
        if not path:
            return

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "mode", "cmd", "status"])
            writer.writerows(self.history)

        self._popup_info("Export", "Export réussi")

    # ================= MONITOR =================
    def _build_section_monitor(self, parent):
        self.monitor_text = tk.Text(parent)
        self.monitor_text.pack(fill="both", expand=True)

        btns = ttk.Frame(parent)
        btns.pack()

        ttk.Button(btns, text="Refresh", command=self.refresh_status).pack(side="left")
        ttk.Button(btns, text="Restart", command=self.restart_energy_service).pack(side="left")

    def refresh_status(self):
        cmd = (
            "/etc/init.d/S91energy-manager status 2>&1; "
            "ps | grep -i energy | grep -v grep"
        )

        def cb(res):
            self.monitor_text.delete("1.0", "end")
            self.monitor_text.insert("end", res["out"] or res["err"])

        self.ssh.execute(cmd, callback=cb)

    def restart_energy_service(self):
        cmd = "/etc/init.d/S91energy-manager restart"

        def cb(res):
            if res["success"]:
                self._popup_info("OK", "Service redémarré")
            else:
                self._popup_error("Erreur", res["err"])

        self.ssh.execute(cmd, callback=cb)

    # ================= CLOSE =================
    def on_close(self):
        try:
            self.win.grab_release()
        except:
            pass
        self.win.destroy()