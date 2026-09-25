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

try:
    from .utils_ui import center_window
    from .setpoint_validation import (
        finite_number,
        validate_active_power,
        validate_cosphi,
        validate_reactive_power,
    )
except ImportError:
    try:
        from utils_ui import center_window
        from setpoint_validation import (
            finite_number,
            validate_active_power,
            validate_cosphi,
            validate_reactive_power,
        )
    except ImportError:
        from src.utils_ui import center_window
        from src.setpoint_validation import (
            finite_number,
            validate_active_power,
            validate_cosphi,
            validate_reactive_power,
        )

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

    def __init__(
        self,
        master,
        ssh: "SSHManager",
        ssh_queue=None,
        on_close=None,
        pn_limit_provider=None,
    ):
        self.master = master
        self.ssh = ssh
        self.ssh_queue = ssh_queue
        self._on_close_callback = on_close
        self.pn_limit_provider = pn_limit_provider or (lambda: 11000.0)

        # Historique : liste de tuples (timestamp, mode, cmd, status)
        self.history = []

        # Fenêtre principale de l'Energy Manager
        self.win = ttk.Toplevel(master)
        # Build the dashboard off-screen. Showing it before its geometry is
        # known produces a visible default-size flash on some Windows PCs.
        self.win.withdraw()
        self.win.title("Energy Manager PRO")
        # ------------------------------------------------------------
        # Taille fenêtre principale
        # ------------------------------------------------------------
        # Adapter la taille à la résolution de l'écran
        screen_h = self.win.winfo_screenheight()
        screen_w = self.win.winfo_screenwidth()
        # The operating panels and monitor benefit from additional room while
        # preserving a margin around RBM on compact industrial displays.
        window_height = max(660, min(820, int(screen_h * 0.84)))
        window_width = max(980, min(1200, int(screen_w * 0.84)))

        # taille minimale raisonnable
        self.win.minsize(900, 640)

        # centrage
        center_window(self.master, self.win, window_width, window_height)

        # autorise resize
        self.win.resizable(True, True)

        # Champs P/Q & CosPhi
        self.p_var = tk.StringVar()
        self.q_var = tk.StringVar()
        self.p_cosphi_var = tk.StringVar()
        self.cosphi_var = tk.StringVar()
        self.q_auto_var = tk.StringVar()
        self._command_in_progress = False
        self.btn_send_pq = None
        self.btn_send_cosphi = None

        # Widgets pour historique / monitor
        self.table = None
        self.monitor_text = None

        self.build_ui()
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        try:
            # Keep this dashboard modeless. It remains above RBM when opened,
            # without grabbing the main application or flashing on creation.
            self.win.transient(master)
            self.win.deiconify()
            self.win.lift()
            self.win.focus_force()
        except Exception:
            pass

    # ------------------------------------------------------------
    # Helpers popups : toujours devant et modales
    # ------------------------------------------------------------
    def _show_popup(self, popup, title: str, message: str):
        try:
            was_topmost = bool(int(self.win.attributes("-topmost")))
        except (tk.TclError, TypeError, ValueError):
            was_topmost = False
        try:
            self.win.lift()
            self.win.attributes("-topmost", True)
            popup(title, message, parent=self.win)
        finally:
            try:
                self.win.attributes("-topmost", was_topmost)
                if was_topmost:
                    self.win.lift()
            except tk.TclError:
                pass

    def _popup_info(self, title: str, message: str):
        self._show_popup(messagebox.showinfo, title, message)

    def _popup_warning(self, title: str, message: str):
        self._show_popup(messagebox.showwarning, title, message)

    def _popup_error(self, title: str, message: str):
        self._show_popup(messagebox.showerror, title, message)

    def close(self):
        try:
            self.win.grab_release()
        except Exception:
            pass
        try:
            event_name = getattr(self, "_mousewheel_event", None)
            if event_name:
                self.win.unbind_all(event_name)
        except Exception:
            pass
        callback = getattr(self, "_on_close_callback", None)
        self._on_close_callback = None
        if callable(callback):
            try:
                callback()
            except Exception:
                pass
        try:
            if self.win.winfo_exists():
                self.win.destroy()
        except Exception:
            pass

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
        # Keep the Close action visible independently from the content panels.
        footer = ttk.Frame(self.win, padding=(14, 6, 14, 10))
        footer.pack(side="bottom", fill="x")
        ttk.Button(
            footer,
            text="Close",
            bootstyle="danger",
            command=self.close,
        ).pack(side="right")

        # The dashboard content fits in the compact window. Avoid a global
        # mouse-wheel binding and scrolling canvas, which previously made the
        # layout look oversized and could hide the footer.
        main = ttk.Frame(self.win, padding=(14, 10, 14, 6))
        main.pack(fill="both", expand=True)

        # ==========================================================
        # GRID RESPONSIVE
        # ==========================================================
        # The history and service monitor are complementary views. Keeping
        # them at the same width prevents the command columns being clipped.
        main.columnconfigure(0, weight=1, uniform="energy_lower_panels")
        main.columnconfigure(1, weight=1, uniform="energy_lower_panels")
        main.rowconfigure(0, weight=0)
        main.rowconfigure(1, weight=1)

        top = ttk.Frame(main)
        top.grid(row=0, column=0, columnspan=2, sticky="nsew", pady=(0, 10))
        top.columnconfigure(0, weight=1)

        bottom_left = ttk.Frame(main)
        bottom_left.grid(row=1, column=0, sticky="nsew", padx=(0, 10))

        bottom_right = ttk.Frame(main)
        bottom_right.grid(row=1, column=1, sticky="nsew")

        self._build_section_pq_cosphi(top)
        self._build_section_history(bottom_left)
        self._build_section_monitor(bottom_right)

    # ------------------------------------------------------------
    # SECTION P/Q & COSPHI  — cote a cote, adaptatif
    # ------------------------------------------------------------
    def _build_section_pq_cosphi(self, parent):
        frm = ttk.Frame(parent)
        frm.pack(fill="both", expand=True)

        title = ttk.Label(
            frm,
            text="P/Q and CosPhi Mode",
            font=("Segoe UI", 14, "bold"),
            anchor="center",
        )
        title.pack(pady=(2, 6))

        vcmd = (self.win.register(self._validate_numeric), "%P")

        # Conteneur cote a cote — s’adapte si la fenetre est trop etroite
        side_frame = ttk.Frame(frm)
        side_frame.pack(fill="x", expand=True, pady=(0, 6))
        side_frame.columnconfigure(0, weight=1, minsize=280)
        side_frame.columnconfigure(1, weight=1, minsize=280)

        # --- Mode P/Q (colonne gauche)
        pq_frame = ttk.Labelframe(side_frame, text="Mode P/Q", padding=10)
        pq_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=4)
        pq_frame.columnconfigure(1, weight=1)

        ttk.Label(pq_frame, text="Active Power P (W) :").grid(
            row=0, column=0, sticky="w", pady=5
        )
        ttk.Entry(
            pq_frame,
            textvariable=self.p_var,
            width=14,
            validate="key",
            validatecommand=vcmd,
        ).grid(row=0, column=1, padx=8, sticky="ew")

        ttk.Label(pq_frame, text="Reactive Power Q (VAR) :").grid(
            row=1, column=0, sticky="w", pady=5
        )
        ttk.Entry(
            pq_frame,
            textvariable=self.q_var,
            width=14,
            validate="key",
            validatecommand=vcmd,
        ).grid(row=1, column=1, padx=8, sticky="ew")

        self.btn_send_pq = ttk.Button(
            pq_frame,
            text="Send P/Q",
            bootstyle="success",
            command=self.send_pq,
            width=16,
        )
        self.btn_send_pq.grid(row=2, column=0, columnspan=2, pady=(12, 4))

        # --- Mode CosPhi (colonne droite)
        cos_frame = ttk.Labelframe(side_frame, text="Mode CosPhi", padding=10)
        cos_frame.grid(row=0, column=1, sticky="nsew", padx=(6, 0), pady=4)
        cos_frame.columnconfigure(1, weight=1)

        ttk.Label(cos_frame, text="Active Power P (W) :").grid(
            row=0, column=0, sticky="w", pady=5
        )
        ttk.Entry(
            cos_frame,
            textvariable=self.p_cosphi_var,
            width=14,
            validate="key",
            validatecommand=vcmd,
        ).grid(row=0, column=1, padx=8, sticky="ew")

        ttk.Label(cos_frame, text="CosPhi (-1 → 1] :").grid(
            row=1, column=0, sticky="w", pady=5
        )
        ttk.Entry(
            cos_frame,
            textvariable=self.cosphi_var,
            width=14,
            validate="key",
            validatecommand=vcmd,
        ).grid(row=1, column=1, padx=8, sticky="ew")

        ttk.Label(cos_frame, text="Q auto (VAR) :").grid(
            row=2, column=0, sticky="w", pady=5
        )
        q_auto_entry = ttk.Entry(
            cos_frame,
            textvariable=self.q_auto_var,
            width=14,
            state="readonly",
        )
        q_auto_entry.grid(row=2, column=1, padx=8, sticky="ew")

        btn_row = ttk.Frame(cos_frame)
        btn_row.grid(row=3, column=0, columnspan=2, pady=(12, 4))
        ttk.Button(
            btn_row,
            text="Calculate Q",
            bootstyle="info",
            command=self.calculate_q_from_cosphi,
            width=14,
        ).pack(side="left", padx=4)

        self.btn_send_cosphi = ttk.Button(
            btn_row,
            text="Send CosPhi",
            bootstyle="success",
            command=self.send_cosphi,
            width=14,
        )
        self.btn_send_cosphi.pack(side="left", padx=4)

        # Auto-adaptation : si la fenetre devient trop etroite,
        # basculer en colonne unique
        def _on_resize(event):
            w = frm.winfo_width()
            if w > 0 and w < 600:
                # Colonne unique
                pq_frame.grid(row=0, column=0, columnspan=2, sticky="nsew",
                              padx=0, pady=4)
                cos_frame.grid(row=1, column=0, columnspan=2, sticky="nsew",
                               padx=0, pady=4)
            else:
                # Cote a cote
                pq_frame.grid(row=0, column=0, columnspan=1, sticky="nsew",
                              padx=(0, 6), pady=4)
                cos_frame.grid(row=0, column=1, columnspan=1, sticky="nsew",
                               padx=(6, 0), pady=4)

        frm.bind("<Configure>", _on_resize)


    # ------------------------------------------------------------
    # SECTION HISTORIQUE
    # ------------------------------------------------------------
    def _build_section_history(self, parent):
        frm = ttk.Labelframe(parent, text="Command History", padding=10)
        frm.pack(fill="both", expand=True)
        
        
        columns = ("timestamp", "mode", "cmd", "status")
        self.table = ttk.Treeview(
            frm, columns=columns, show="headings", height=8, bootstyle="info"
        )
        self.table.heading("timestamp", text="Time")
        self.table.heading("mode", text="Mode")
        self.table.heading("cmd", text="Command")
        self.table.heading("status", text="Result")

        # These widths fit in the left half of the companion window and keep
        # the Status column visible instead of clipping it off-screen.
        self.table.column("timestamp", width=105, minwidth=90, anchor="w", stretch=False)
        self.table.column("mode", width=65, minwidth=55, anchor="center", stretch=False)
        self.table.column("cmd", width=220, minwidth=150, anchor="w", stretch=True)
        self.table.column("status", width=85, minwidth=70, anchor="center", stretch=False)

        self.table.pack(fill="both", expand=True, pady=(0, 10))

        btns = ttk.Frame(frm)
        btns.pack(fill="x")

        ttk.Button(
            btns,
            text="Export CSV",
            bootstyle="secondary",
            command=self.export_csv,
        ).pack(side="left", padx=5, pady=5)

    # ------------------------------------------------------------
    # SECTION MONITOR
    # ------------------------------------------------------------
    def _build_section_monitor(self, parent):
        frm = ttk.Labelframe(parent, text="Monitor Energy Manager", padding=10)
        frm.pack(fill="both", expand=True)
        

        self.monitor_text = tk.Text(
            frm,
            height=10,
            font=("Consolas", 10),
            wrap="word",
            background="#f8fafc",
            foreground="#111827",
            insertbackground="#111827",
            relief="solid",
            borderwidth=1,
        )
        self.monitor_text.pack(fill="both", expand=True, pady=(0, 10))

        btns = ttk.Frame(frm)
        btns.pack(fill="x")

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
    def _pn_limit(self):
        try:
            return finite_number(self.pn_limit_provider(), "Pn")
        except ValueError:
            return 0.0

    def send_pq(self):
        try:
            p_val = validate_active_power(self.p_var.get(), self._pn_limit())
            q_val = validate_reactive_power(self.q_var.get(), optional=True)
        except ValueError as exc:
            self._popup_warning("Invalid values", str(exc))
            return

        reactive_option = f" --reactive-power {q_val}" if q_val is not None else ""
        display_text = f"Active Power : {p_val} W"
        if q_val is None:
            display_text += "\nReactive Power : not sent"
        else:
            display_text += f"\nReactive Power : {q_val} VAR"

        cmd = (
            "cd /var/aux/EnergyManager && "
            "export LD_LIBRARY_PATH=/usr/local/lib && "
            f"{ENERGY_TOOL_RESOLVE}"
            f"\"$EM_TOOL\" -S -s ocpp -a "
            f"--power {p_val}{reactive_option} -m CentralSetpoint"
        )
        self.execute_energy_cmd(
            "P/Q",
            cmd,
            display_text=display_text,
        )

    def calculate_q_from_cosphi(self):
        try:
            p_val = validate_active_power(self.p_cosphi_var.get(), self._pn_limit())
            cosphi_val = validate_cosphi(self.cosphi_var.get(), default=1.0)
        except ValueError as exc:
            self._popup_warning("Invalid values", str(exc))
            return None

        self.cosphi_var.set(f"{cosphi_val:g}")

        q_val = abs(p_val) * math.tan(math.acos(cosphi_val))
        q_val_rounded = int(round(q_val))
        self.q_auto_var.set(str(q_val_rounded))
        return p_val, cosphi_val, q_val_rounded

    def send_cosphi(self):
        values = self.calculate_q_from_cosphi()
        if values is None:
            return
        p_val, cosphi_val, q_val = values

        cmd = (
            "cd /var/aux/EnergyManager && "
            "export LD_LIBRARY_PATH=/usr/local/lib && "
            f"{ENERGY_TOOL_RESOLVE}"
            f"(\"$EM_TOOL\" --grid-option "
            f"\"SetpointCosPhi_Pct={int(round(cosphi_val * 100))}\" && "
            f"\"$EM_TOOL\" -S -s ocpp -a "
            f"--power {p_val} -m CentralSetpoint)"
        )
        self.execute_energy_cmd(
            "CosPhi",
            cmd,
            display_text=(
                f"Active Power : {p_val} W\n"
                f"CosPhi : {cosphi_val}\n"
                f"Reactive Power : {q_val} VAR"
            )
        )

    # ------------------------------------------------------------
    # FONCTION COMMUNE D’ENVOI
    # ------------------------------------------------------------
  
    def execute_energy_cmd(
        self,
        mode,
        cmd,
        display_text=None,
    ):
        """
        Envoi commande Energy Manager.
        """

        if not self.ssh or not getattr(self.ssh, "connected", False):

            self._popup_error(
                "SSH Error",
                "Not connected to the charger."
            )

            return

        if self._command_in_progress:
            self._popup_warning(
                "Energy Manager",
                "A command is already running. Wait for its result before sending another one.",
            )
            return

        self._command_in_progress = True
        for button in (self.btn_send_pq, self.btn_send_cosphi):
            if button is not None:
                button.configure(state="disabled")

        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

        # texte affiché utilisateur
        pretty_cmd = display_text or mode

        def callback(res):
            def _ui():
                status = "OK" if res["success"] else "ERR"
                self.history.append(
                    (
                        timestamp,
                        mode,
                        pretty_cmd,
                        status,
                    )
                )

                self.update_history_table()

                self._command_in_progress = False
                for button in (self.btn_send_pq, self.btn_send_cosphi):
                    if button is not None:
                        button.configure(state="normal")

                if res["success"]:
                    self._popup_info(
                        "Energy Manager",
                        (f"Command completed successfully.\n\n{pretty_cmd}")
                    )
                else:
                    err = (
                        res["err"]
                        or res["out"]
                        or "Unknown error"
                    )
                    self._popup_error("Energy Manager Error", err)

            try:
                if self.win.winfo_exists():
                    self.win.after(0, _ui)
            except Exception:
                pass

        if self.ssh_queue is not None:
            queued = self.ssh_queue.execute(
                cmd,
                callback=callback,
                timeout=getattr(self.ssh, "timeout", 30),
                auto_retry=False,
                label=f"Energy {mode}",
                silent=False,
                dedupe_key="energy_manager_command",
            )
            if not queued:
                self._command_in_progress = False
                for button in (self.btn_send_pq, self.btn_send_cosphi):
                    if button is not None:
                        button.configure(state="normal")
                self._popup_warning("Energy Manager", "A command is already queued or running.")
        else:
            self.ssh.execute(
                cmd,
                callback=callback,
            )
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
            self._popup_warning("Empty", "No history entries available.")
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
            self._popup_error("Export", f"CSV export error:\n{e}")
            return

        self._popup_info("Export", "CSV export completed.")

    # ------------------------------------------------------------
    # MONITOR (version sans systemctl, adaptée à /etc/init.d)
    # ------------------------------------------------------------
    def refresh_status(self):
        """Affiche le status du service energy manager (init.d + ps)."""
        if not self.ssh or not getattr(self.ssh, "connected", False):
            self._popup_error("SSH Error", "Not connected to the charger.")
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
            def _ui():
                self.monitor_text.delete("1.0", "end")
                if res["success"]:
                    self.monitor_text.insert("end", res["out"])
                else:
                    err = res["err"] or res["out"] or "Unknown error"
                    self.monitor_text.insert("end", f"ERROR: {err}")

            try:
                if self.win.winfo_exists():
                    self.win.after(0, _ui)
            except Exception:
                pass

        if self.ssh_queue is not None:
            self.ssh_queue.execute(
                cmd,
                callback=callback,
                timeout=getattr(self.ssh, "timeout", 30),
                auto_retry=False,
                label="Energy status",
                silent=False,
            )
        else:
            self.ssh.execute(cmd, callback=callback)

    def restart_energy_service(self):
        if not self.ssh or not getattr(self.ssh, "connected", False):
            self._popup_error("SSH Error", "Not connected to the charger.")
            return

        if not messagebox.askyesno(
            "Services",
            "Before restarting the Energy Manager service, verify that the charging cable is unplugged.\n\nContinue?",
            parent=self.win,
        ):
            return

        cmd = "/etc/init.d/S91energy-manager restart"

        def callback(res):
            def _ui():
                if res["success"]:
                    self._popup_info("Success", "Service S91energy-manager restarted.")
                else:
                    err = res["err"] or res["out"] or "Unknown error"
                    self._popup_error("Error", err)

            try:
                if self.win.winfo_exists():
                    self.win.after(0, _ui)
            except Exception:
                pass

        if self.ssh_queue is not None:
            self.ssh_queue.execute(
                cmd,
                callback=callback,
                timeout=max(30, getattr(self.ssh, "timeout", 30)),
                auto_retry=False,
                label="Restart S91energy-manager",
                silent=False,
                dedupe_key="energy_manager_restart",
            )
        else:
            self.ssh.execute(cmd, callback=callback)
