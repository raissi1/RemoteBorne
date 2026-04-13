# ================================================================
# energy_manager.py — ENERGY MANAGER PRO (Ultimate)
# ================================================================

import tkinter as tk
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from tkinter import messagebox, filedialog
import time
import math
import csv
import re

ENERGY_TOOL_RESOLVE = (
    'EM_TOOL="$(command -v EnergyManagerTestingTool 2>/dev/null || true)"; '
    'if [ -z "$EM_TOOL" ]; then '
    'for p in /usr/local/bin/EnergyManagerTestingTool /usr/bin/EnergyManagerTestingTool; do '
    '[ -x "$p" ] && EM_TOOL="$p" && break; '
    "done; "
    'fi; '
    'if [ -z "$EM_TOOL" ]; then '
    "echo 'EnergyManagerTestingTool not found on target (checked PATH, /usr/local/bin, /usr/bin)' >&2; "
    "exit 127; "
    "fi; "
)


class EnergyManagerWindow:
    """Fenêtre Energy Manager PRO (plein écran, une seule vue)."""

    def __init__(self, master, ssh: "SSHManager"):
        self.master = master
        self.ssh = ssh

        # Historique : liste de tuples (timestamp, mode, cmd, status)
        self.history = []

        # Fenêtre principale de l'Energy Manager
        self.win = ttk.Toplevel(master)
        self.win.title("Energy Manager PRO")
        try:
            self.win.transient(master)
            self.win.grab_set()
            self.win.focus_force()
        except Exception:
            pass
        self.win.geometry("1000x680")
        self.win.minsize(900, 580)
        self._center_on_parent(1000, 680)

        # Champs P/Q & CosPhi
        self.p_var = tk.StringVar()
        self.q_var = tk.StringVar()
        self.p_cosphi_var = tk.StringVar()
        self.cosphi_var = tk.StringVar()
        self.q_auto_var = tk.StringVar()

        # Widgets pour historique / monitor
        self.table = None
        self.monitor_text = None

        self.build_ui()

    def _center_on_parent(self, width: int, height: int):
        try:
            self.master.update_idletasks()
            px, py = self.master.winfo_rootx(), self.master.winfo_rooty()
            pw, ph = self.master.winfo_width(), self.master.winfo_height()
            if pw > 1 and ph > 1:
                x = px + max(0, (pw - width) // 2)
                y = py + max(0, (ph - height) // 2)
                self.win.geometry(f"{width}x{height}+{x}+{y}")
                return
        except Exception:
            pass
        self.win.update_idletasks()
        x = (self.win.winfo_screenwidth() - width) // 2
        y = (self.win.winfo_screenheight() - height) // 2
        self.win.geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")

    # ------------------------------------------------------------
    # Helpers popups : toujours devant et modales
    # ------------------------------------------------------------
    def _popup_info(self, title: str, message: str):
        self.win.lift()
        self.win.attributes("-topmost", True)
        try:
            messagebox.showinfo(title, message, parent=self.win)
        finally:
            self.win.attributes("-topmost", False)

    def _popup_warning(self, title: str, message: str):
        self.win.lift()
        self.win.attributes("-topmost", True)
        try:
            messagebox.showwarning(title, message, parent=self.win)
        finally:
            self.win.attributes("-topmost", False)

    def _popup_error(self, title: str, message: str):
        self.win.lift()
        self.win.attributes("-topmost", True)
        try:
            messagebox.showerror(title, message, parent=self.win)
        finally:
            self.win.attributes("-topmost", False)

    # ------------------------------------------------------------
    # Validation saisie numérique (float / int)
    # ------------------------------------------------------------
    def _validate_numeric(self, new_value: str) -> bool:
        """
        Validation pour les champs P/Q/CosPhi :
         - autorise vide (pendant la saisie)
         - autorise -123, 3.14, -0.5, etc.
         - refuse les lettres et caractères spéciaux
        """
        if new_value == "":
            return True
        pattern = r"^-?\d*(\.\d*)?$"
        return re.match(pattern, new_value) is not None

    # ------------------------------------------------------------
    # UI principale : une seule vue structurée
    # ------------------------------------------------------------
    def build_ui(self):
        main = ttk.Frame(self.win)
        main.pack(fill="both", expand=True, padx=14, pady=14)

        # Layout général : zone top + zone bas (history/monitor) + footer
        main.rowconfigure(1, weight=1)
        main.columnconfigure(0, weight=3)
        main.columnconfigure(1, weight=2)

        top = ttk.Frame(main)
        top.grid(row=0, column=0, columnspan=2, sticky="nsew", pady=(0, 10))

        bottom_left = ttk.Frame(main)
        bottom_left.grid(row=1, column=0, sticky="nsew", padx=(0, 10))

        bottom_right = ttk.Frame(main)
        bottom_right.grid(row=1, column=1, sticky="nsew")

        self._build_section_pq_cosphi(top)
        self._build_section_history(bottom_left)
        self._build_section_monitor(bottom_right)

        footer = ttk.Frame(main)
        footer.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Button(
            footer,
            text="Close",
            bootstyle="danger",
            command=self.win.destroy,
        ).pack(side="right")

    # ------------------------------------------------------------
    # SECTION P/Q & COSPHI
    # ------------------------------------------------------------
    def _build_section_pq_cosphi(self, parent):
        frm = ttk.Frame(parent)
        frm.pack(fill="both", expand=True)

        title = ttk.Label(
            frm,
            text="Mode P/Q et CosPhi",
            font=("Segoe UI", 22, "bold"),
            anchor="center",
        )
        title.pack(pady=10)

        vcmd = (self.win.register(self._validate_numeric), "%P")

        # --- Mode P/Q
        pq_frame = ttk.Labelframe(frm, text="Mode P/Q", padding=15)
        pq_frame.pack(fill="x", pady=10)

        ttk.Label(pq_frame, text="Active Power P (W) :").grid(
            row=0, column=0, sticky="w", pady=5
        )
        ttk.Entry(
            pq_frame,
            textvariable=self.p_var,
            width=20,
            validate="key",
            validatecommand=vcmd,
        ).grid(row=0, column=1, padx=10, sticky="w")

        ttk.Label(pq_frame, text="Reactive Power Q (VAR) :").grid(
            row=1, column=0, sticky="w", pady=5
        )
        ttk.Entry(
            pq_frame,
            textvariable=self.q_var,
            width=20,
            validate="key",
            validatecommand=vcmd,
        ).grid(row=1, column=1, padx=10, sticky="w")

        ttk.Button(
            pq_frame,
            text="Send P/Q",
            bootstyle="success",
            command=self.send_pq,
        ).grid(row=2, column=0, columnspan=2, pady=10)

        pq_frame.grid_columnconfigure(2, weight=1)

        # --- Mode CosPhi
        cos_frame = ttk.Labelframe(frm, text="Mode CosPhi", padding=15)
        cos_frame.pack(fill="x", pady=10)

        ttk.Label(cos_frame, text="Active Power P (W) :").grid(
            row=0, column=0, sticky="w", pady=5
        )
        ttk.Entry(
            cos_frame,
            textvariable=self.p_cosphi_var,
            width=20,
            validate="key",
            validatecommand=vcmd,
        ).grid(row=0, column=1, padx=10, sticky="w")

        ttk.Label(cos_frame, text="CosPhi (-1 → 1] :").grid(
            row=1, column=0, sticky="w", pady=5
        )
        ttk.Entry(
            cos_frame,
            textvariable=self.cosphi_var,
            width=20,
            validate="key",
            validatecommand=vcmd,
        ).grid(row=1, column=1, padx=10, sticky="w")

        ttk.Label(cos_frame, text="Reactive Power Q (auto) :").grid(
            row=2, column=0, sticky="w", pady=5
        )
        q_auto_entry = ttk.Entry(
            cos_frame,
            textvariable=self.q_auto_var,
            width=20,
            state="readonly",
        )
        q_auto_entry.grid(row=2, column=1, padx=10, sticky="w")

        ttk.Button(
            cos_frame,
            text="Calculate Q",
            bootstyle="info",
            command=self.calculate_q_from_cosphi,
        ).grid(row=3, column=0, pady=10, sticky="e")

        ttk.Button(
            cos_frame,
            text="Send CosPhi",
            bootstyle="success",
            command=self.send_cosphi,
        ).grid(row=3, column=1, pady=10, sticky="w")

        cos_frame.grid_columnconfigure(2, weight=1)

    # ------------------------------------------------------------
    # SECTION HISTORIQUE
    # ------------------------------------------------------------
    def _build_section_history(self, parent):
        frm = ttk.Labelframe(parent, text="Historique des commandes", padding=10)
        frm.pack(fill="both", expand=True)

        columns = ("timestamp", "mode", "cmd", "status")
        self.table = ttk.Treeview(
            frm, columns=columns, show="headings", bootstyle="info"
        )
        self.table.heading("timestamp", text="Timestamp")
        self.table.heading("mode", text="Mode")
        self.table.heading("cmd", text="Commande")
        self.table.heading("status", text="Statut")

        self.table.column("timestamp", width=150, anchor="w")
        self.table.column("mode", width=80, anchor="center")
        self.table.column("cmd", width=400, anchor="w")
        self.table.column("status", width=120, anchor="center")

        self.table.pack(fill="both", expand=True, pady=(0, 10))

        btns = ttk.Frame(frm)
        btns.pack(anchor="w")

        ttk.Button(
            btns,
            text="Exporter CSV",
            bootstyle="secondary",
            command=self.export_csv,
        ).pack(side="left", padx=5, pady=5)

    # ------------------------------------------------------------
    # SECTION MONITOR
    # ------------------------------------------------------------
    def _build_section_monitor(self, parent):
        frm = ttk.Labelframe(parent, text="Monitor Energy Manager", padding=10)
        frm.pack(fill="both", expand=True)

        self.monitor_text = tk.Text(frm, height=12, font=("Consolas", 10))
        self.monitor_text.pack(fill="both", expand=True, pady=(0, 10))

        btns = ttk.Frame(frm)
        btns.pack(anchor="w")

        ttk.Button(
            btns,
            text="Refresh status",
            bootstyle="info",
            command=self.refresh_status,
        ).pack(side="left", padx=5, pady=5)

        ttk.Button(
            btns,
            text="Restart S91energy-manager",
            bootstyle="warning",
            command=self.restart_energy_service,
        ).pack(side="left", padx=5, pady=5)

    # ------------------------------------------------------------
    # LOGIQUE P/Q & COSPHI
    # ------------------------------------------------------------
    def send_pq(self):
        p_str = self.p_var.get().strip()
        q_str = self.q_var.get().strip()

        try:
            p_val = int(float(p_str))
            q_val = int(float(q_str))
        except ValueError:
            self._popup_warning("Valeurs invalides", "P et Q doivent être numériques.")
            return

        cmd = (
            "cd /var/aux/EnergyManager && "
            "export LD_LIBRARY_PATH=/usr/local/lib && "
            f"{ENERGY_TOOL_RESOLVE}"
            f"\"$EM_TOOL\" -S -s ocpp -a "
            f"--power {p_val} --reactive-power {q_val} -m CentralSetpoint"
        )
        self.execute_energy_cmd("P/Q", cmd)

    def calculate_q_from_cosphi(self):
        p_str = self.p_cosphi_var.get().strip()
        cosphi_str = self.cosphi_var.get().strip()

        try:
            p_val = float(p_str)
            cosphi_val = float(cosphi_str)
            if not (-1.0 < cosphi_val <= 1.0):
                raise ValueError("CosPhi hors plage")
        except ValueError:
            self._popup_warning(
                "Valeurs invalides",
                "P doit être numérique et CosPhi dans l'intervalle (-1, 1].",
            )
            return

        q_val = abs(p_val) * math.tan(math.acos(cosphi_val))
        q_val_rounded = int(round(q_val))
        self.q_auto_var.set(str(q_val_rounded))

    def send_cosphi(self):
        p_str = self.p_cosphi_var.get().strip()
        cosphi_str = self.cosphi_var.get().strip()
        q_str = self.q_auto_var.get().strip()

        try:
            p_val = int(float(p_str))
            cosphi_val = float(cosphi_str)
            q_val = int(float(q_str))
        except ValueError:
            self._popup_warning(
                "Valeurs invalides",
                "P, CosPhi et Q auto doivent être remplis et numériques "
                "(pensez à cliquer sur 'Calculate Q').",
            )
            return

        cmd = (
            "cd /var/aux/EnergyManager && "
            "export LD_LIBRARY_PATH=/usr/local/lib && "
            f"{ENERGY_TOOL_RESOLVE}"
            f"(\"$EM_TOOL\" --grid-option "
            f"\"SetpointCosPhi_Pct={int(round(cosphi_val * 100))}\" && "
            f"\"$EM_TOOL\" -S -s ocpp -a "
            f"--power {p_val} -m CentralSetpoint) >/dev/null 2>&1 &"
        )
        self.execute_energy_cmd("CosPhi", cmd)

    # ------------------------------------------------------------
    # FONCTION COMMUNE D’ENVOI
    # ------------------------------------------------------------
    def execute_energy_cmd(self, mode, cmd):
        if not self.ssh or not getattr(self.ssh, "connected", False):
            self._popup_error("Erreur SSH", "Non connecté à la borne.")
            return

        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

        def callback(res):
            status = "OK" if res["success"] else f"ERR: {res['err']}"
            self.history.append((timestamp, mode, cmd, status))
            self.update_history_table()
            if res["success"]:
                self._popup_info("Succès", f"Commande envoyée :\n{cmd}")
            else:
                err = res["err"] or res["out"] or "Erreur inconnue"
                self._popup_error("Erreur", f"Erreur lors de l’envoi.\n{err}")

        self.ssh.execute(cmd, callback=callback)

    # ------------------------------------------------------------
    # HISTORIQUE
    # ------------------------------------------------------------
    def update_history_table(self):
        if not self.table:
            return
        for item in self.table.get_children():
            self.table.delete(item)
        for h in self.history:
            self.table.insert("", "end", values=h)

    def export_csv(self):
        if not self.history:
            self._popup_warning("Vide", "Aucune entrée dans l’historique.")
            return

        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            parent=self.win,
        )
        if not path:
            return

        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["timestamp", "mode", "command", "status"])
                writer.writerows(self.history)
        except Exception as e:
            self._popup_error("Export", f"Erreur lors de l'export CSV :\n{e}")
            return

        self._popup_info("Export", "Export CSV effectué.")

    # ------------------------------------------------------------
    # MONITOR (version sans systemctl, adaptée à /etc/init.d)
    # ------------------------------------------------------------
    def refresh_status(self):
        """Affiche le status du service energy manager (init.d + ps)."""
        if not self.ssh or not getattr(self.ssh, "connected", False):
            self._popup_error("Erreur SSH", "Non connecté à la borne.")
            return

        # Ici on évite systemctl, on utilise /etc/init.d + ps
        cmd = (
            'echo "=== /etc/init.d/S91energy-manager status ==="; '
            "/etc/init.d/S91energy-manager status 2>&1 || "
            'echo "No /etc/init.d/S91energy-manager script"; '
            'echo ""; echo "=== ps | grep -i energy ==="; '
            "ps | grep -i energy | grep -v grep || "
            'echo "No energy-related process found"'
        )

        def callback(res):
            self.monitor_text.delete("1.0", "end")
            if res["success"]:
                self.monitor_text.insert("end", res["out"])
            else:
                err = res["err"] or res["out"] or "Erreur inconnue"
                # On écrit quand même le message dans la zone
                self.monitor_text.insert("end", f"ERROR: {err}")

        self.ssh.execute(cmd, callback=callback)

    def restart_energy_service(self):
        if not self.ssh or not getattr(self.ssh, "connected", False):
            self._popup_error("Erreur SSH", "Non connecté à la borne.")
            return

        cmd = "/etc/init.d/S91energy-manager restart"

        def callback(res):
            if res["success"]:
                self._popup_info("OK", "Service S91energy-manager redémarré.")
            else:
                err = res["err"] or res["out"] or "Erreur inconnue"
                self._popup_error("Erreur", err)

        self.ssh.execute(cmd, callback=callback)
