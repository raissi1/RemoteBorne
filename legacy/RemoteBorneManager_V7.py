#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
RemoteBorneManager_V7_pretty.py
---------------------------------------------------------
Version avec interface similaire à la V1 :
- Header avec logos + titre centré
- Navigateur GridCodes à gauche
- Panneau de contrôle (status, Energy Manager, services, boutons) à droite
- Console de logs en bas

Backend :
- SSHManager (plink) pour exécuter des commandes
- Navigation filesystem
- Download / Edit / Print via SCP
- Copy vers GridCodes.properties
- Restart services et reboot
- Debug logs, Network config, Energy Manager PRO, Help
---------------------------------------------------------
"""

import os
import math
import time
import threading
import tempfile
import configparser
import posixpath
import tkinter as tk
from tkinter import messagebox, filedialog
from tkinter.scrolledtext import ScrolledText

import ttkbootstrap as ttk
from ttkbootstrap.constants import *

from ssh_manager import SSHManager
import network_config
import debug_logs
import energy_manager
import open_help


class RemoteBorneApp:
    def __init__(self, config: configparser.ConfigParser):
        # ---------- THEME / WINDOW ----------
        self.current_theme = "flatly"  # thème clair plus proche du screenshot
        self.root = ttk.Window(themename=self.current_theme)
        self.style = self.root.style

        self.root.title("Remote Borne Control Interface - RNA")

        try:
            self.root.state("zoomed")
        except Exception:
            try:
                self.root.attributes("-zoomed", True)
            except Exception:
                self.root.geometry("1200x800")

        # ---------- CONFIG ----------
        self.config = config

        ssh_cfg = config["SSH"]
        self.host = ssh_cfg.get("host", "")
        self.user = ssh_cfg.get("username", "")
        self.password = ssh_cfg.get("password", "")
        self.port = int(ssh_cfg.get("port", "22"))

        paths_cfg = config["PATHS"]
        self.default_path = paths_cfg.get(
            "remote_path", "/etc/iotecha/configs/GridCodes"
        )
        self.remote_file = paths_cfg.get(
            "remote_file", "GridCodes.properties"
        )
        self.local_path_default = paths_cfg.get(
            "local_path", os.getcwd()
        )

        self.current_path = self.default_path

        # ---------- STATE ----------
        self.connected = False
        self._stop_alive = False
        
        # Menus refs
        self.file_menu = None
        self.view_menu = None
        self.tools_menu = None
        self.help_menu = None

        # UI refs
        self.path_var = None
        self.path_entry = None
        self.file_list = None
        self.log_text = None

        self.btn_connect = None
        self.btn_disconnect = None
        self.btn_exit = None
        self.btn_refresh = None
        self.btn_copy = None
        self.btn_edit = None
        self.btn_send_power = None
        self.btn_send_cosphi = None
        self.btn_restart_services = None
        self.btn_copy_panel = None
        self.btn_refresh_panel = None

        # Energy manager entries
        self.use_cosphi_var = tk.BooleanVar(value=False)
        self.active_entry = None
        self.reactive_entry = None
        self.cosphi_active_entry = None
        self.cosphi_entry = None

        # Status
        self.status_var = tk.StringVar(value="Disconnected")
        self.led_canvas = None

        # Logos
        self.logo_left = None   # Renault
        self.logo_right = None  # AVL
        self._load_logos()

        # ---------- SSH MANAGER ----------
        self.ssh = SSHManager(
            host=self.host,
            user=self.user,
            password=self.password,
            port=self.port,
            timeout=10,
        )
        self.ssh.set_ui_callback(self.on_ssh_event)
        self.ssh.set_log_callback(self.log)
        self.ssh.start()

        # Heartbeat
        threading.Thread(target=self._alive_monitor_thread, daemon=True).start()

        # ---------- UI ----------
        self._build_menu()
        self._build_layout()

        self._draw_led(False)
        self.log("Application started. Waiting for SSH events...")

    # ==================================================================
    # LOGOS
    # ==================================================================
    def _load_logos(self):
        """
        Charge les logos dans imgs/ si disponibles.
        - logo_left: renault.png
        - logo_right: avl.png
        """
        try:
            from PIL import Image, ImageTk

            left_path = os.path.join("imgs", "renault.png")
            right_path = os.path.join("imgs", "avl.png")

            if os.path.exists(left_path):
                img = Image.open(left_path).resize((90, 35))
                self.logo_left = ImageTk.PhotoImage(img)

            if os.path.exists(right_path):
                img = Image.open(right_path).resize((90, 35))
                self.logo_right = ImageTk.PhotoImage(img)
        except Exception as e:
            print(f"[LOGO ERROR] {e}")

    # ==================================================================
    # MENU
    # ==================================================================
    def _build_menu(self):
        menubar = tk.Menu(self.root)

        # ----- FILE -----
        self.file_menu = tk.Menu(menubar, tearoff=0)
        self.file_menu.add_command(label="Connect", command=self.force_reconnect)
        self.file_menu.add_command(label="Disconnect", command=self._manual_disconnect)
        self.file_menu.add_separator()
        self.file_menu.add_command(label="Copy to GridCodes", command=self.copy_selected_to_gridcodes)
        self.file_menu.add_command(label="Download", command=self.download_selected)
        self.file_menu.add_command(label="Print", command=self.print_selected)
        self.file_menu.add_command(label="Edit", command=self.edit_selected)
        self.file_menu.add_separator()
        self.file_menu.add_command(label="Restart Services", command=self.restart_initd_services)
        self.file_menu.add_command(label="Reboot", command=self.reboot_device)
        self.file_menu.add_separator()
        self.file_menu.add_command(label="Exit", command=self.on_exit)
        menubar.add_cascade(label="File", menu=self.file_menu)

        # ----- VIEW -----
        self.view_menu = tk.Menu(menubar, tearoff=0)
        self.view_menu.add_command(
            label="Light theme", command=lambda: self.set_theme("flatly")
        )
        self.view_menu.add_command(
            label="Dark theme", command=lambda: self.set_theme("darkly")
        )
        menubar.add_cascade(label="View", menu=self.view_menu)

        # ----- NETWORK -----
        self.network_menu = tk.Menu(menubar, tearoff=0)
        self.network_menu.add_command(
            label="Network config", command=self.open_network_config
        )
        menubar.add_cascade(label="Network", menu=self.network_menu)

        # ----- DEBUG -----
        self.debug_menu = tk.Menu(menubar, tearoff=0)
        self.debug_menu.add_command(
            label="Debug logs", command=self.open_debug_logs_window
        )
        menubar.add_cascade(label="Debug", menu=self.debug_menu)

        # ----- ENERGY -----
        self.energy_menu = tk.Menu(menubar, tearoff=0)
        self.energy_menu.add_command(
            label="Energy Manager PRO", command=self.open_energy_manager
        )
        menubar.add_cascade(label="Energy", menu=self.energy_menu)

        # ----- HELP -----
        self.help_menu = tk.Menu(menubar, tearoff=0)
        self.help_menu.add_command(label="Help", command=self.open_help_window)
        self.help_menu.add_separator()
        self.help_menu.add_command(label="About", command=self.show_about)
        menubar.add_cascade(label="Help", menu=self.help_menu)

        self.root.config(menu=menubar)


    # ==================================================================
    # THEME
    # ==================================================================
    def set_theme(self, theme: str):
        try:
            self.style.theme_use(theme)
            self.current_theme = theme
            self.log(f"[THEME] Switched to {theme}")
        except Exception as e:
            self.log(f"[THEME ERROR] {e}")
            messagebox.showerror("Theme", f"Cannot switch theme:\n{e}")

    # ==================================================================
    # LAYOUT (style V1)
    # ==================================================================
    def _build_layout(self):
        main = ttk.Frame(self.root)
        main.pack(fill="both", expand=True)

        # ---------- HEADER ----------
        header = ttk.Frame(main)
        header.pack(fill="x", padx=10, pady=(5, 0))

        header.grid_columnconfigure(0, weight=1)
        header.grid_columnconfigure(1, weight=3)
        header.grid_columnconfigure(2, weight=1)

        # Left logo
        left_logo_frame = ttk.Frame(header)
        left_logo_frame.grid(row=0, column=0, sticky="w")
        if self.logo_left:
            ttk.Label(left_logo_frame, image=self.logo_left).pack(anchor="w")
        else:
            ttk.Label(left_logo_frame, text="", width=10).pack()

        # Title centered
        center_frame = ttk.Frame(header)
        center_frame.grid(row=0, column=1, sticky="nsew")
        ttk.Label(
            center_frame,
            text="Remote Borne Control Interface",
            font=("Segoe UI", 16, "bold"),
            anchor="center",
        ).pack(fill="x")
        ttk.Label(
            center_frame,
            text="RNA",
            font=("Segoe UI", 8, "italic"),
            anchor="center",
        ).pack(fill="x")

        # Right logo
        right_logo_frame = ttk.Frame(header)
        right_logo_frame.grid(row=0, column=2, sticky="e")
        if self.logo_right:
            ttk.Label(right_logo_frame, image=self.logo_right).pack(anchor="e")
        else:
            ttk.Label(right_logo_frame, text="", width=10).pack()

        # ---------- BODY ----------
        body = ttk.Frame(main)
        body.pack(fill="both", expand=True, padx=10, pady=5)

        body.grid_columnconfigure(0, weight=4)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        # ===== LEFT: GRIDCODES BROWSER =====
        left = ttk.Labelframe(
            body,
            text=f"GridCodes browser ({self.default_path})",
            padding=5,
        )
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 5))

        # Path row
        path_frame = ttk.Frame(left)
        path_frame.pack(fill="x", pady=(0, 3))

        ttk.Label(path_frame, text="Path:").pack(side="left")
        self.path_var = tk.StringVar(value=self.current_path)
        self.path_entry = ttk.Entry(path_frame, textvariable=self.path_var)
        self.path_entry.pack(side="left", fill="x", expand=True, padx=4)

        ttk.Button(path_frame, text="Root", width=5, command=self._go_root).pack(
            side="right", padx=1
        )
        ttk.Button(path_frame, text="Up", width=4, command=self._go_parent).pack(
            side="right", padx=1
        )
        ttk.Button(path_frame, text="Go", width=4, command=self._go_to_path).pack(
            side="right", padx=1
        )

        # File list
        list_frame = ttk.Frame(left)
        list_frame.pack(fill="both", expand=True, pady=(0, 3))

        self.file_list = tk.Listbox(list_frame, activestyle="none")
        self.file_list.pack(side="left", fill="both", expand=True)
        yscroll = ttk.Scrollbar(
            list_frame, orient="vertical", command=self.file_list.yview
        )
        yscroll.pack(side="right", fill="y")
        self.file_list.config(yscrollcommand=yscroll.set)

        self.file_list.bind("<Double-Button-1>", self.on_file_double_click)
        self.file_list.bind("<Button-3>", self.on_file_right_click)

        # Bottom buttons (Refresh / Copy / Edit)
        file_btn_frame = ttk.Frame(left)
        file_btn_frame.pack(fill="x")

        self.btn_refresh = ttk.Button(
            file_btn_frame,
            text="Refresh",
            width=12,
            command=self.refresh_file_list,
        )
        self.btn_refresh.pack(side="left", padx=2, pady=2)

        self.btn_copy = ttk.Button(
            file_btn_frame,
            text="Copy to GridCodes",
            width=18,
            command=self.copy_selected_to_gridcodes,
        )
        self.btn_copy.pack(side="left", padx=2, pady=2)

        self.btn_edit = ttk.Button(
            file_btn_frame,
            text="Edit",
            width=10,
            command=self.edit_selected,
        )
        self.btn_edit.pack(side="left", padx=2, pady=2)

        # ===== RIGHT: CONTROLS PANEL =====
        right = ttk.Frame(body)
        right.grid(row=0, column=1, sticky="nsew")

        # ----- STATUS FRAME -----
        status_frame = ttk.Labelframe(right, text="Status & Controls", padding=5)
        status_frame.pack(fill="x", pady=(0, 5))

        ttk.Label(status_frame, text=f"IP: {self.host}").pack(anchor="w")
        ttk.Label(status_frame, text=f"User: {self.user}").pack(anchor="w")
        ttk.Label(status_frame, textvariable=self.status_var).pack(anchor="w")

        self.led_canvas = tk.Canvas(
            status_frame, width=18, height=18, highlightthickness=0, bd=0
        )
        self.led_canvas.pack(anchor="e", pady=(2, 0))

        # ----- ENERGY MANAGER CONTROLS -----
        energy_frame = ttk.Labelframe(
            right, text="Energy Manager Controls", padding=5
        )
        energy_frame.pack(fill="x", pady=(0, 5))

        # P / Q Setpoint
        power_frame = ttk.Labelframe(energy_frame, text="P / Q Setpoint", padding=5)
        power_frame.pack(fill="x", pady=(0, 5))

        ttk.Label(power_frame, text="Active (P) [W]:").pack(anchor="w")
        self.active_entry = ttk.Entry(power_frame)
        self.active_entry.pack(fill="x", pady=(0, 3))

        ttk.Label(power_frame, text="Reactive (Q) [var]:").pack(anchor="w")
        self.reactive_entry = ttk.Entry(power_frame)
        self.reactive_entry.pack(fill="x", pady=(0, 3))

        self.btn_send_power = ttk.Button(
            power_frame,
            text="Send",
            command=self.send_power_command,
        )
        self.btn_send_power.pack(fill="x", pady=(3, 0))

        # CosPhi Setpoint
        cos_frame = ttk.Labelframe(energy_frame, text="CosPhi Setpoint", padding=5)
        cos_frame.pack(fill="x", pady=(0, 5))

        self.cosphi_mode_label = ttk.Label(
            cos_frame, text="Mode: CosPhi"
        )
        self.cosphi_mode_label.pack(anchor="w", pady=(0, 3))

        self.use_cosphi_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            cos_frame,
            text="Use CosPhi mode",
            variable=self.use_cosphi_var,
            command=self._update_cosphi_ui,
        ).pack(anchor="w", pady=(0, 3))

        ttk.Label(cos_frame, text="Active (P) [W]:").pack(anchor="w")
        self.cosphi_active_entry = ttk.Entry(cos_frame)
        self.cosphi_active_entry.pack(fill="x", pady=(0, 3))

        ttk.Label(cos_frame, text="CosPhi:").pack(anchor="w")
        self.cosphi_entry = ttk.Entry(cos_frame)
        self.cosphi_entry.pack(fill="x", pady=(0, 3))

        self.btn_send_cosphi = ttk.Button(
            cos_frame,
            text="Send",
            command=self.send_cosphi_command,
        )
        self.btn_send_cosphi.pack(fill="x", pady=(3, 0))

        # ----- SERVICES (restart) -----
        svc_frame = ttk.Labelframe(right, text="Services", padding=5)
        svc_frame.pack(fill="x", pady=(0, 5))

        ttk.Label(
            svc_frame, text="Restart critical services:"
        ).pack(anchor="w", pady=(0, 3))

        self.btn_restart_services = ttk.Button(
            svc_frame,
            text="Restart Services",
            command=self.restart_initd_services,
        )
        self.btn_restart_services.pack(fill="x")

        # ----- BIG BUTTONS (Connect / Disconnect / Copy / Refresh / Exit) -----
        btn_panel = ttk.Frame(right)
        btn_panel.pack(fill="x", pady=(10, 0))

        self.btn_connect = ttk.Button(
            btn_panel,
            text="Connect",
            bootstyle=SUCCESS,
            command=self.force_reconnect,
        )
        self.btn_connect.pack(fill="x", pady=1)

        self.btn_disconnect = ttk.Button(
            btn_panel,
            text="Disconnect",
            command=self._manual_disconnect,
        )
        self.btn_disconnect.pack(fill="x", pady=1)

        # Copy direct depuis panneau
        self.btn_copy_panel = ttk.Button(
            btn_panel,
            text="Copy to GridCodes",
            command=self.copy_selected_to_gridcodes,
        )
        self.btn_copy_panel.pack(fill="x", pady=1)

        self.btn_refresh_panel = ttk.Button(
            btn_panel,
            text="Refresh List",
            command=self.refresh_file_list,
        )
        self.btn_refresh_panel.pack(fill="x", pady=1)

        self.btn_exit = ttk.Button(
            btn_panel, text="Exit", bootstyle=DANGER, command=self.on_exit
        )
        self.btn_exit.pack(fill="x", pady=(5, 0))

        # ---------- CONSOLE ----------
        log_frame = ttk.Labelframe(main, text="Logs", padding=3)
        log_frame.pack(fill="both", expand=True, padx=10, pady=(0, 5))

        self.log_text = ScrolledText(log_frame, height=10, wrap="word", font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True)

        # Initial state
        self._update_controls_state()
        self._update_cosphi_ui()

    # ==================================================================
    # LOGGING + LED
    # ==================================================================
    def log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {msg}\n"
        if self.log_text is not None:
            try:
                self.log_text.insert("end", line)
                self.log_text.see("end")
            except Exception:
                pass
        print(line, end="")

    def _draw_led(self, status: bool):
        if not self.led_canvas:
            return
        self.led_canvas.delete("all")
        color = "#28a745" if status else "#dc3545"
        self.led_canvas.create_oval(3, 3, 15, 15, fill=color, outline=color)

    # ==================================================================
    # STATE / COSPHI UI
    # ==================================================================
    def _update_controls_state(self):
        is_conn = self.connected

        # ----- BOUTONS -----
        if self.btn_connect:
            self.btn_connect.config(state=tk.DISABLED if is_conn else tk.NORMAL)
        if self.btn_disconnect:
            self.btn_disconnect.config(state=tk.NORMAL if is_conn else tk.DISABLED)
        if self.btn_exit:
            self.btn_exit.config(state=tk.NORMAL)

        for btn in [
            self.btn_refresh,
            self.btn_copy,
            self.btn_edit,
            self.btn_restart_services,
            self.btn_copy_panel,
            self.btn_refresh_panel,
        ]:
            if btn:
                btn.config(state=tk.NORMAL if is_conn else tk.DISABLED)

        # ----- MENUS -----
        if self.file_menu:
            self.file_menu.entryconfig("Connect", state=tk.DISABLED if is_conn else tk.NORMAL)
            self.file_menu.entryconfig("Disconnect", state=tk.NORMAL if is_conn else tk.DISABLED)
            self.file_menu.entryconfig("Copy to GridCodes", state=tk.NORMAL if is_conn else tk.DISABLED)
            self.file_menu.entryconfig("Download", state=tk.NORMAL if is_conn else tk.DISABLED)
            self.file_menu.entryconfig("Print", state=tk.NORMAL if is_conn else tk.DISABLED)
            self.file_menu.entryconfig("Edit", state=tk.NORMAL if is_conn else tk.DISABLED)
            self.file_menu.entryconfig("Restart Services", state=tk.NORMAL if is_conn else tk.DISABLED)
            self.file_menu.entryconfig("Reboot", state=tk.NORMAL if is_conn else tk.DISABLED)
            self.file_menu.entryconfig("Exit", state=tk.NORMAL)

        # Network : toujours accessible
        if self.network_menu:
            self.network_menu.entryconfig("Network config", state=tk.NORMAL)

        # Debug : seulement connecté
        if self.debug_menu:
            self.debug_menu.entryconfig("Debug logs", state=tk.NORMAL if is_conn else tk.DISABLED)

        # Energy : seulement connecté
        if self.energy_menu:
            self.energy_menu.entryconfig(
                "Energy Manager PRO",
                state=tk.NORMAL if is_conn else tk.DISABLED
            )

        # Help : toujours accessible
        if self.help_menu:
            self.help_menu.entryconfig("Help", state=tk.NORMAL)
            self.help_menu.entryconfig("About", state=tk.NORMAL)

        # Ajuste la partie P/Q / CosPhi
        self._update_cosphi_ui()


    def _update_cosphi_ui(self):
        use = self.use_cosphi_var.get()
        if not self.connected:
            # Tout désactiver si pas connecté
            for entry in (
                self.active_entry,
                self.reactive_entry,
                self.cosphi_active_entry,
                self.cosphi_entry,
            ):
                if entry:
                    entry.config(state="disabled")
            for btn in (self.btn_send_power, self.btn_send_cosphi):
                if btn:
                    btn.config(state="disabled")
            return

        if not use:
            # Mode P/Q
            if self.active_entry:
                self.active_entry.config(state="normal")
            if self.reactive_entry:
                self.reactive_entry.config(state="normal")
            if self.btn_send_power:
                self.btn_send_power.config(state="normal")

            if self.cosphi_active_entry:
                self.cosphi_active_entry.config(state="disabled")
            if self.cosphi_entry:
                self.cosphi_entry.config(state="disabled")
            if self.btn_send_cosphi:
                self.btn_send_cosphi.config(state="disabled")
        else:
            # Mode CosPhi
            if self.active_entry:
                self.active_entry.config(state="disabled")
            if self.reactive_entry:
                self.reactive_entry.config(state="disabled")
            if self.btn_send_power:
                self.btn_send_power.config(state="disabled")

            if self.cosphi_active_entry:
                self.cosphi_active_entry.config(state="normal")
            if self.cosphi_entry:
                self.cosphi_entry.config(state="normal")
            if self.btn_send_cosphi:
                self.btn_send_cosphi.config(state="normal")

    # ==================================================================
    # HEARTBEAT
    # ==================================================================
    def _alive_monitor_thread(self):
        while not self._stop_alive:
            time.sleep(10)
            if not self.ssh or not self.ssh.connected:
                continue

            def cb(res):
                if not res["success"]:
                    self.log("[ALIVE] Heartbeat failed (echo alive).")

            self.ssh.execute("echo alive", callback=cb, auto_retry=False)

    # ==================================================================
    # SSH EVENTS
    # ==================================================================
    def on_ssh_event(self, event_type, data):
        if event_type == "connected":
            self.connected = True
            self._draw_led(True)
            self.status_var.set("Connected")
            self.log("[SSH] Connected.")
            self._init_file_browser()
            self._update_controls_state()
            self._update_cosphi_ui()

        elif event_type == "disconnected":
            self.connected = False
            self._draw_led(False)
            self.status_var.set("Disconnected")
            self.log("[SSH] Disconnected.")
            self._update_controls_state()
            self._update_cosphi_ui()

        elif event_type == "reconnecting":
            self.connected = False
            self._draw_led(False)
            self.status_var.set("Reconnecting...")
            self.log("[SSH] Reconnecting...")
            self._update_controls_state()
            self._update_cosphi_ui()

        elif event_type == "reconnected":
            self.connected = True
            self._draw_led(True)
            self.status_var.set("Connected")
            self.log("[SSH] Reconnected.")
            self.refresh_file_list()
            self._update_controls_state()
            self._update_cosphi_ui()

    # ==================================================================
    # FILE BROWSER
    # ==================================================================
    def _init_file_browser(self):
        self.current_path = self.default_path
        self.refresh_file_list()

    def refresh_file_list(self):
        if not self.connected:
            self.log("[FILES] Not connected.")
            return

        cmd = f"ls -Ap {self.current_path}"

        def cb(res):
            self.file_list.delete(0, "end")
            if not res["success"]:
                self.log(f"[FILES] Error: {res['err']}")
                return

            lines = res["out"].splitlines()
            if self.current_path.rstrip("/") != self.default_path.rstrip("/"):
                self.file_list.insert("end", "[..] (Parent)")
            for e in lines:
                e = e.strip()
                if e:
                    self.file_list.insert("end", e)

            self.path_var.set(self.current_path)
            self.log(f"[FILES] {len(lines)} entries in {self.current_path}")

        self.ssh.execute(cmd, callback=cb)

    def _go_root(self):
        self.current_path = self.default_path
        self.refresh_file_list()

    def _go_to_path(self):
        if not self.connected:
            return
        target = self.path_var.get().strip() or self.current_path

        def cb(res):
            if res["success"]:
                self.current_path = target
                self.refresh_file_list()
            else:
                messagebox.showerror("Path", f"Remote folder not found:\n{target}")

        self.ssh.execute(f'test -d "{target}"', callback=cb)

    def _go_parent(self):
        if self.current_path.rstrip("/") == self.default_path.rstrip("/"):
            return
        self.current_path = posixpath.dirname(self.current_path.rstrip("/")) or "/"
        self.refresh_file_list()

    def on_file_double_click(self, event):
        if not self.connected:
            return
        sel = self.file_list.curselection()
        if not sel:
            return
        item = self.file_list.get(sel[0])

        if item.startswith("[..]"):
            self._go_parent()
            return

        full_path = self._join_remote(self.current_path, item)

        if item.endswith("/"):
            self.current_path = full_path.rstrip("/")
            self.refresh_file_list()
        else:
            self.open_file_editor(full_path)

    def on_file_right_click(self, event):
        if not self.connected:
            return
        sel = self.file_list.curselection()
        if not sel:
            return
        idx = self.file_list.nearest(event.y)
        self.file_list.selection_clear(0, "end")
        self.file_list.selection_set(idx)
        item = self.file_list.get(idx)

        menu = tk.Menu(self.root, tearoff=0)

        if item.startswith("[..]"):
            menu.add_command(label="Parent", command=self._go_parent)
        else:
            full_path = self._join_remote(self.current_path, item)
            if item.endswith("/"):
                menu.add_command(label="Open folder", command=lambda: self._open_dir(full_path))
            else:
                menu.add_command(label="Edit", command=lambda: self.open_file_editor(full_path))
                menu.add_command(label="Download", command=lambda: self.download_file(full_path))
                menu.add_command(label="Print", command=lambda: self.print_file(full_path))
                menu.add_command(label="Copy to GridCodes", command=lambda: self.copy_to_gridcodes(full_path))

        menu.tk_popup(event.x_root, event.y_root)

    def _open_dir(self, path):
        self.current_path = path.rstrip("/")
        self.refresh_file_list()

    def _join_remote(self, *parts):
        cleaned = []
        for p in parts:
            if not p:
                continue
            cleaned.append(str(p).replace("\\", "/"))
        return posixpath.join(*cleaned)

    def _get_selected_path(self):
        sel = self.file_list.curselection()
        if not sel:
            return None
        item = self.file_list.get(sel[0])
        if item.startswith("[..]"):
            return None
        return self._join_remote(self.current_path, item)

    # ==================================================================
    # FILE OPERATIONS
    # ==================================================================
    def copy_selected_to_gridcodes(self):
        path = self._get_selected_path()
        if not path:
            messagebox.showwarning("Copy", "No file selected.")
            return
        self.copy_to_gridcodes(path)

    def download_selected(self):
        path = self._get_selected_path()
        if not path:
            messagebox.showwarning("Download", "No file selected.")
            return
        self.download_file(path)

    def print_selected(self):
        path = self._get_selected_path()
        if not path:
            messagebox.showwarning("Print", "No file selected.")
            return
        self.print_file(path)

    def edit_selected(self):
        path = self._get_selected_path()
        if not path:
            messagebox.showwarning("Edit", "No file selected.")
            return
        self.open_file_editor(path)

    def copy_to_gridcodes(self, src_path):
        dst = self._join_remote(self.default_path, self.remote_file)
        filename = posixpath.basename(src_path)

        if not messagebox.askyesno(
            "Copy",
            f"Overwrite {self.remote_file} with:\n{filename} ?",
        ):
            return

        cmd = f"cp -p '{src_path}' '{dst}'"

        def after_copy(res):
            if not res["success"]:
                self.log(f"[GRID] Copy failed: {res['err']}")
                messagebox.showerror("Copy", "Remote copy failed.")
                return

            self.log(f"[GRID] '{filename}' copied to {self.remote_file}")

            if messagebox.askyesno(
                "Cable",
                "File copied.\nIs the cable already disconnected?",
            ):
                if messagebox.askyesno(
                    "Restart Services",
                    "Configuration changed.\nRestart services now "
                    "(S39ConfigManager, S91energy-manager, S95chargerapp)?",
                ):
                    self.restart_initd_services()

        self.ssh.execute(cmd, callback=after_copy)

    def download_file(self, remote_path):
        initial_dir = (
            self.local_path_default
            if os.path.isdir(self.local_path_default)
            else os.getcwd()
        )
        local_path = filedialog.asksaveasfilename(
            initialdir=initial_dir,
            initialfile=os.path.basename(remote_path),
        )
        if not local_path:
            return

        self.log(f"[DOWNLOAD] {remote_path}")

        def worker():
            ok, out, err = self.ssh.backend.scp_get(
                remote_path, local_path, timeout=60
            )
            if ok:
                self.log(f"[DOWNLOAD] Saved to {local_path}")
            else:
                self.log(f"[DOWNLOAD ERROR] {err or out}")
                messagebox.showerror(
                    "Download", f"Download failed:\n{err or out}"
                )

        threading.Thread(target=worker, daemon=True).start()

    def print_file(self, remote_path):
        try:
            from reportlab.pdfgen import canvas
            from reportlab.lib.pagesizes import A4
        except ImportError:
            messagebox.showerror(
                "Print", "The 'reportlab' module is not installed."
            )
            return

        filename = os.path.basename(remote_path)
        self.log(f"[PRINT] {remote_path}")

        tmp_dir = tempfile.mkdtemp(prefix="rbm_print_")
        local_content_file = os.path.join(tmp_dir, filename)

        def worker():
            try:
                ok, out, err = self.ssh.backend.scp_get(
                    remote_path, local_content_file, timeout=60
                )
                if not ok:
                    self.log(f"[PRINT ERROR] Download failed: {err or out}")
                    messagebox.showerror(
                        "Print", f"Download failed:\n{err or out}"
                    )
                    return

                pdf_path = filedialog.asksaveasfilename(
                    title=f"Save PDF for {filename}",
                    defaultextension=".pdf",
                    initialfile=f"{filename}.pdf",
                )
                if not pdf_path:
                    self.log("[PRINT] Cancelled by user.")
                    return

                from reportlab.pdfgen import canvas
                from reportlab.lib.pagesizes import A4

                c = canvas.Canvas(pdf_path, pagesize=A4)
                width, height = A4
                c.setFont("Helvetica", 10)

                y = height - 40
                line_h = 12

                c.drawString(
                    40,
                    y,
                    f"RemoteBorne Manager - Printout of: {remote_path}",
                )
                y -= 2 * line_h
                c.line(40, y, width - 40, y)
                y -= line_h

                with open(
                    local_content_file,
                    "r",
                    encoding="utf-8",
                    errors="replace",
                ) as f:
                    for line in f:
                        line = line.rstrip("\n")
                        if y < 40:
                            c.showPage()
                            c.setFont("Helvetica", 10)
                            y = height - 40
                        c.drawString(40, y, line[:200])
                        y -= line_h

                c.save()
                self.log(f"[PRINT] PDF saved to {pdf_path}")
                messagebox.showinfo(
                    "Print", f"PDF saved to:\n{pdf_path}"
                )
            except Exception as e:
                self.log(f"[PRINT ERROR] {e}")
                messagebox.showerror("Print", f"Print failed:\n{e}")
            finally:
                try:
                    if os.path.exists(local_content_file):
                        os.remove(local_content_file)
                    if os.path.isdir(tmp_dir):
                        os.rmdir(tmp_dir)
                except Exception:
                    pass

        threading.Thread(target=worker, daemon=True).start()

    def open_file_editor(self, remote_path):
        if not self.connected:
            messagebox.showerror("SSH", "Not connected.")
            return

        editor = ttk.Toplevel(self.root)
        editor.title(f"Edit: {remote_path}")
        editor.geometry("800x600")

        text = tk.Text(editor, wrap="none")
        text.pack(fill="both", expand=True)

        yscroll = ttk.Scrollbar(
            editor, orient="vertical", command=text.yview
        )
        yscroll.pack(side="right", fill="y")
        text.config(yscrollcommand=yscroll.set)

        xscroll = ttk.Scrollbar(
            editor, orient="horizontal", command=text.xview
        )
        xscroll.pack(side="bottom", fill="x")
        text.config(xscrollcommand=xscroll.set)

        btn_frame = ttk.Frame(editor)
        btn_frame.pack(fill="x")
        ttk.Button(
            btn_frame,
            text="Save",
            command=lambda: self._save_editor(editor, text, remote_path),
        ).pack(side="right", padx=5, pady=2)
        ttk.Button(
            btn_frame, text="Close", command=editor.destroy
        ).pack(side="right", padx=5, pady=2)

        tmp_dir = tempfile.mkdtemp(prefix="rbm_edit_")
        local_file = os.path.join(tmp_dir, os.path.basename(remote_path))

        def worker():
            ok, out, err = self.ssh.backend.scp_get(
                remote_path, local_file, timeout=60
            )
            if not ok:
                self.log(f"[EDIT ERROR] Download failed: {err or out}")
                messagebox.showerror(
                    "Edit", f"Download failed:\n{err or out}"
                )
                editor.destroy()
                try:
                    if os.path.exists(local_file):
                        os.remove(local_file)
                    if os.path.isdir(tmp_dir):
                        os.rmdir(tmp_dir)
                except Exception:
                    pass
                return

            with open(
                local_file, "r", encoding="utf-8", errors="replace"
            ) as f:
                content = f.read()

            def fill():
                text.delete("1.0", "end")
                text.insert("1.0", content)

            self.root.after(0, fill)

        threading.Thread(target=worker, daemon=True).start()

    def _save_editor(self, editor, text_widget, remote_path):
        content = text_widget.get("1.0", "end-1c")

        tmp_dir = tempfile.mkdtemp(prefix="rbm_edit_save_")
        local_file = os.path.join(tmp_dir, os.path.basename(remote_path))

        with open(local_file, "w", encoding="utf-8") as f:
            f.write(content)

        def worker():
            ok, out, err = self.ssh.backend.scp_put(
                local_file, remote_path, timeout=60
            )
            try:
                if ok:
                    self.log(f"[EDIT] Saved to {remote_path}")
                    messagebox.showinfo("Edit", "Remote file saved.")
                    editor.destroy()
                else:
                    self.log(
                        f"[EDIT ERROR] Upload failed: {err or out}"
                    )
                    messagebox.showerror(
                        "Edit", f"Upload failed:\n{err or out}"
                    )
            finally:
                try:
                    if os.path.exists(local_file):
                        os.remove(local_file)
                    if os.path.isdir(tmp_dir):
                        os.rmdir(tmp_dir)
                except Exception:
                    pass

        threading.Thread(target=worker, daemon=True).start()

    # ==================================================================
    # ENERGY / SERVICES / REBOOT
    # ==================================================================
    def send_power_command(self):
        if not self.connected:
            messagebox.showwarning(
                "Warning", "Please connect before sending commands."
            )
            return

        if self.use_cosphi_var.get():
            messagebox.showinfo(
                "Mode",
                "CosPhi mode is active.\nDisable 'Use CosPhi' to send simple P/Q.",
            )
            return

        active = self.active_entry.get()
        reactive = self.reactive_entry.get()

        try:
            active_val = int(float(active))
            reactive_val = int(float(reactive))
        except ValueError:
            messagebox.showwarning(
                "Warning", "Active and Reactive must be valid numbers."
            )
            return

        self.log(
            f"Sending setpoint: Active={active_val} W, Reactive={reactive_val} var"
        )

        remote_cmd = (
            "cd /var/aux/EnergyManager && "
            "export LD_LIBRARY_PATH=/usr/local/lib && "
            f"/usr/local/bin/EnergyManagerTestingTool -S -s ocpp -a "
            f"--power {active_val} --reactive-power {reactive_val} "
            "-m CentralSetpoint"
        )

        def cb(res):
            if res["success"]:
                self.log("Power command sent successfully.")
            else:
                err = res["err"] or res["out"] or "unknown error"
                self.log(f"[ERROR] {err}")

        self.ssh.execute(remote_cmd, callback=cb)

    def send_cosphi_command(self):
        if not self.connected:
            messagebox.showwarning(
                "Warning", "Please connect before sending commands."
            )
            return
        if not self.use_cosphi_var.get():
            messagebox.showinfo(
                "Info", "Enable 'Use CosPhi' to send this command."
            )
            return

        active = self.cosphi_active_entry.get()
        cosphi = self.cosphi_entry.get()

        try:
            active_val = int(float(active))
            cosphi_val = float(cosphi)
            if not (-1 < cosphi_val <= 1):
                raise ValueError("CosPhi out of range")
        except ValueError:
            messagebox.showwarning(
                "Warning",
                "Active and CosPhi must be valid numbers; CosPhi in (-1, 1].",
            )
            return

        q_val = int(abs(active_val) * math.tan(math.acos(cosphi_val)))

        self.log("CosPhi calculation:")
        self.log(f"  Active = {active_val} W")
        self.log(f"  CosPhi = {cosphi_val}")
        self.log(
            f"  Reactive (Q) = |{active_val}| * tan(acos({cosphi_val})) = {q_val} var"
        )
        self.log(
            f"Sending CosPhi command: Active={active_val} W, "
            f"CosPhi={cosphi_val}, Reactive={q_val} var"
        )

        remote_cmd = (
            "cd /var/aux/EnergyManager && "
            "export LD_LIBRARY_PATH=/usr/local/lib && "
            f"/usr/local/bin/EnergyManagerTestingTool -S -s ocpp -a "
            f"--power {active_val} --reactive-power {q_val} "
            "-m CentralSetpoint"
        )

        def cb(res):
            if res["success"]:
                self.log("CosPhi command sent successfully.")
            else:
                err = res["err"] or res["out"] or "unknown error"
                self.log(f"[ERROR] {err}")

        self.ssh.execute(remote_cmd, callback=cb)

    def restart_initd_services(self):
        if not self.connected:
            messagebox.showwarning("Services", "Not connected.")
            return

        services = ["S39ConfigManager", "S91energy-manager", "S95chargerapp"]

        cmd_parts = []
        for s in services:
            cmd_parts.append(f'echo "Stopping {s}"')
            cmd_parts.append(
                f"/etc/init.d/{s} stop || echo 'Error stopping {s}'"
            )
            cmd_parts.append(f'echo "Starting {s}"')
            cmd_parts.append(
                f"/etc/init.d/{s} start || echo 'Error starting {s}'"
            )
            cmd_parts.append('echo "--------------------------------"')
        cmd = " ; ".join(cmd_parts)

        self.log("[SERVICES] Restarting services...")

        def cb(res):
            if res["out"]:
                for line in res["out"].splitlines():
                    self.log(line)
            if not res["success"]:
                self.log(f"[SERVICES ERROR] {res['err']}")
                messagebox.showerror("Services", "Restart failed.")
            else:
                self.log("[SERVICES] Restart sequence finished.")
                messagebox.showinfo(
                    "Services", "Restart sequence finished."
                )

        self.ssh.execute(cmd, callback=cb)

    def reboot_device(self):
        if not self.connected:
            messagebox.showwarning("Reboot", "Not connected.")
            return

        if not messagebox.askyesno("Reboot", "Reboot the device now?"):
            return

        self.log("[REBOOT] Sending 'reboot' command...")

        def cb(res):
            if not res["success"]:
                self.log(f"[REBOOT ERROR] {res['err'] or res['out']}")
                messagebox.showerror(
                    "Reboot", "Reboot command failed (maybe no effect)."
                )
            else:
                self.log("[REBOOT] Command sent. Device will reboot.")
                messagebox.showinfo(
                    "Reboot",
                    "Reboot command sent.\nDevice will restart.",
                )

        self.ssh.execute("reboot", callback=cb, auto_retry=False)

    def open_energy_manager(self):
        """Ouvre la fenêtre Energy Manager PRO (une seule fois)."""
        try:
            # On instancie juste la fenêtre, __init__ appelle déjà build_ui()
            self._energy_win = energy_manager.EnergyManagerWindow(self.root, self.ssh)
        except Exception as e:
            self.log(f"[ERROR] Unable to open Energy Manager: {e}")
            messagebox.showerror(
                "Energy Manager",
                f"Unable to open Energy Manager:\n{e}"
            )

    # ==================================================================
    # NETWORK / DEBUG / HELP
    # ==================================================================
    def open_network_config(self):
        try:
            network_config.open_network_config(self.root)
        except Exception as e:
            self.log(f"[ERROR] Unable to open network config: {e}")
            messagebox.showerror("Network", f"Network GUI error:\n{e}")
            return

        # Rechargement de config.ini après fermeture
        try:
            cfg = configparser.ConfigParser()
            cfg.read("config.ini", encoding="utf-8")
            self.config = cfg

            ssh_cfg = cfg["SSH"]
            self.host = ssh_cfg.get("host", "")
            self.user = ssh_cfg.get("username", "")
            self.password = ssh_cfg.get("password", "")
            self.port = int(ssh_cfg.get("port", "22"))

            paths_cfg = cfg["PATHS"]
            self.default_path = paths_cfg.get(
                "remote_path", "/etc/iotecha/configs/GridCodes"
            )
            self.remote_file = paths_cfg.get(
                "remote_file", "GridCodes.properties"
            )
            self.local_path_default = paths_cfg.get(
                "local_path", os.getcwd()
            )

            self.log("[NETWORK] config.ini reloaded.")

            # Nouveau SSHManager
            try:
                self.ssh.stop()
            except Exception:
                pass

            self.ssh = SSHManager(
                host=self.host,
                user=self.user,
                password=self.password,
                port=self.port,
                timeout=10,
            )
            self.ssh.set_ui_callback(self.on_ssh_event)
            self.ssh.set_log_callback(self.log)
            self.ssh.start()
            self.log("[NETWORK] SSHManager restarted with new settings.")
        except Exception as e:
            self.log(f"[ERROR] Failed to reload config.ini: {e}")
            messagebox.showerror(
                "Network", f"Failed to reload config.ini:\n{e}"
            )

    def open_debug_logs_window(self):
        try:
            debug_logs.open_debug_logs_window(
                self.root, self.host, self.user, self.password, self.port
            )
        except Exception as e:
            self.log(f"[ERROR] Unable to open debug logs: {e}")
            messagebox.showerror(
                "Debug Logs", f"Unable to open debug logs:\n{e}"
            )

    def open_help_window(self):
        try:
            open_help.open_help(self.root)
        except Exception as e:
            self.log(f"[ERROR] Unable to open help: {e}")
            messagebox.showerror("Help", f"Unable to open help:\n{e}")

    # ==================================================================
    # MISC / EXIT
    # ==================================================================
    def force_reconnect(self):
        self.ssh.force_reconnect()

    def _manual_disconnect(self):
        self.connected = False
        self._draw_led(False)
        self.status_var.set("Disconnected")
        self._update_controls_state()
        self._update_cosphi_ui()
        self.log("[SSH] Manual disconnect (UI only).")

    def show_about(self):
        messagebox.showinfo(
            "About",
            "Remote Borne Control Interface V7 (pretty)\n"
            "Layout similaire à la V1 (header + browser gauche + panneau droit + logs).\n"
            "Backend: SSHManager + Plink.\n",
        )

    def on_exit(self):
        if messagebox.askokcancel("Exit", "Quit application?"):
            self._stop_alive = True
            try:
                self.ssh.stop()
            except Exception:
                pass
            self.root.destroy()


# ======================================================================
# MAIN
# ======================================================================
def start_app():
    cfg = configparser.ConfigParser()
    if not os.path.exists("config.ini"):
        cfg["SSH"] = {"host": "", "username": "", "password": "", "port": "22"}
        cfg["PATHS"] = {
            "remote_path": "/etc/iotecha/configs/GridCodes",
            "remote_file": "GridCodes.properties",
            "local_path": os.getcwd(),
        }
        with open("config.ini", "w", encoding="utf-8") as f:
            cfg.write(f)
    else:
        cfg.read("config.ini", encoding="utf-8")

    app = RemoteBorneApp(cfg)
    app.root.protocol("WM_DELETE_WINDOW", app.on_exit)
    app.root.mainloop()


if __name__ == "__main__":
    start_app()
