# ================================================================
# energy_manager.py — VERSION STABLE & PROPRE
# ================================================================

import tkinter as tk
import ttkbootstrap as ttk
from tkinter import messagebox, filedialog
import time
import math
import csv
import re

# Import safe (dev + exe)
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
    "echo 'EnergyManagerTestingTool not found' >&2; "
    "exit 127; "
    "fi; "
)


class EnergyManagerWindow:

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

        # 🔥 auto update Q
        self.cosphi_var.trace_add("write", lambda *args: self.calculate_q_from_cosphi())

    # ================= POPUPS =================
    def _popup(self, level, title, msg):
        self.win.lift()
        self.win.attributes("-topmost", True)
        try:
            getattr(messagebox, level)(title, msg, parent=self.win)
        finally:
            self.win.attributes("-topmost", False)

    # ================= VALIDATION =================
    def _validate_numeric(self, val):
        if val == "":
            return True
        return re.match(r"^-?\d*(\.\d*)?$", val) is not None

    # ================= UI =================
    def build_ui(self):
        main = ttk.Frame(self.win)
        main.pack(fill="both", expand=True, padx=20, pady=20)

        main.columnconfigure(0, weight=3)
        main.columnconfigure(1, weight=2)

        top = ttk.Frame(main)
        top.grid(row=0, column=0, columnspan=2, sticky="nsew")

        bottom_left = ttk.Frame(main)
        bottom_left.grid(row=1, column=0, sticky="nsew")

        bottom_right = ttk.Frame(main)
        bottom_right.grid(row=1, column=1, sticky="nsew")

        self.build_energy_section(top)
        self.build_history(bottom_left)
        self.build_monitor(bottom_right)

    # ================= ENERGY =================
    def build_energy_section(self, parent):
        vcmd = (self.win.register(self._validate_numeric), "%P")

        frame = ttk.Labelframe(parent, text="Energy Control", padding=10)
        frame.pack(fill="x", pady=10)

        ttk.Label(frame, text="P (W)").grid(row=0, column=0)
        ttk.Entry(frame, textvariable=self.p_var, validate="key", validatecommand=vcmd).grid(row=0, column=1)

        ttk.Label(frame, text="Q (VAR)").grid(row=1, column=0)
        ttk.Entry(frame, textvariable=self.q_var, validate="key", validatecommand=vcmd).grid(row=1, column=1)

        ttk.Button(frame, text="Send P/Q", command=self.send_pq).grid(row=2, column=0, columnspan=2)

        ttk.Label(frame, text="CosPhi").grid(row=3, column=0)
        ttk.Entry(frame, textvariable=self.cosphi_var, validate="key", validatecommand=vcmd).grid(row=3, column=1)

        ttk.Label(frame, text="Q auto").grid(row=4, column=0)
        ttk.Entry(frame, textvariable=self.q_auto_var, state="readonly").grid(row=4, column=1)

        ttk.Button(frame, text="Send CosPhi", command=self.send_cosphi).grid(row=5, column=0, columnspan=2)

    # ================= COMMANDES =================
    def send_pq(self):
        try:
            p = int(float(self.p_var.get()))
            q = int(float(self.q_var.get()))
        except:
            self._popup("showwarning", "Erreur", "Valeurs invalides")
            return

        cmd = (
            f"{ENERGY_TOOL_RESOLVE}"
            f"\"$EM_TOOL\" -S -s ocpp -a --power {p} --reactive-power {q}"
        )
        self.exec_cmd("P/Q", cmd)

    def calculate_q_from_cosphi(self):
        try:
            p = float(self.p_cosphi_var.get())
            cos = float(self.cosphi_var.get())

            if abs(cos) < 0.01:
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
            self._popup("showwarning", "Erreur", "Valeurs invalides")
            return

        cmd = (
            f"{ENERGY_TOOL_RESOLVE}"
            f"\"$EM_TOOL\" --grid-option \"SetpointCosPhi_Pct={int(cos*100)}\" && "
            f"\"$EM_TOOL\" -S -s ocpp -a --power {p}"
        )

        self.exec_cmd("CosPhi", cmd)

    # ================= EXEC =================
    def exec_cmd(self, mode, cmd):
        if not self.ssh or not self.ssh.connected:
            self._popup("showerror", "SSH", "Non connecté")
            return

        ts = time.strftime("%H:%M:%S")

        def cb(res):
            status = "OK" if res["success"] else "ERR"
            self.history.append((ts, mode, cmd, status))
            self.update_history()

        self.ssh.execute(cmd, callback=cb)

    # ================= HISTORY =================
    def build_history(self, parent):
        self.table = ttk.Treeview(parent, columns=("t", "m", "c", "s"), show="headings")
        self.table.pack(fill="both", expand=True)

    def update_history(self):
        for i in self.table.get_children():
            self.table.delete(i)
        for h in reversed(self.history):
            self.table.insert("", "end", values=h)

    # ================= MONITOR =================
    def build_monitor(self, parent):
        self.monitor_text = tk.Text(parent)
        self.monitor_text.pack(fill="both", expand=True)

    # ================= CLOSE =================
    def on_close(self):
        try:
            self.win.grab_release()
        except:
            pass
        self.win.destroy()