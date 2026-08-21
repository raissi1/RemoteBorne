#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RemoteBorneManager.py

Interface Windows pour contrôle de borne IOTECHA :
- Connexion SSH robuste via plink.exe (ssh_manager.py / plink_backend.py)
- Navigation des GridCodes
- Copie vers GridCodes.properties
- Download / Print PDF / Edition distante
- Commandes EnergyManagerTestingTool (P/Q et CosPhi)
- Restart services + reboot borne
- Debug logs (via debug_logs.py)
- Network config (config.ini modifiable)
- Thèmes : flatly (clair) & darkly (sombre)
"""
import sys, os
import subprocess


BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)


import math
import time
import tempfile
import threading
import configparser
import posixpath
import re

import tkinter as tk
from tkinter import messagebox, filedialog, simpledialog

import ttkbootstrap as ttk
from ttkbootstrap.constants import *


# ----------------------------------------------------------------------
# Imports projet (compat mode script + mode package "src")
# ----------------------------------------------------------------------
try:
    from .ssh_manager import SSHManager
    from .ssh_queue import SSHQueue
    from .network_config import open_network_config
    from .open_help import open_help
    from . import energy_manager
    from . import debug_logs
except ImportError:
    try:
        from ssh_manager import SSHManager
        from ssh_queue import SSHQueue
        from network_config import open_network_config
        from open_help import open_help
        import energy_manager
        import debug_logs
    except ImportError:
        from src.ssh_manager import SSHManager
        from src.ssh_queue import SSHQueue
        from src.network_config import open_network_config
        from src.open_help import open_help
        from src import energy_manager
        from src import debug_logs

APP_VERSION = "2026.03.31.1"

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

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas as pdf_canvas
    from reportlab.pdfbase import pdfmetrics

    HAVE_REPORTLAB = True
except Exception:
    HAVE_REPORTLAB = False


# ----------------------------------------------------------------------
# Chemins de base (support .py + exe PyInstaller)
# ----------------------------------------------------------------------

def _base_dir():
    """
    - En mode script (.py) : retourne la racine du projet
      (parent de src/)
    - En mode exe (PyInstaller) : retourne le dossier contenant le .exe
    """
    if getattr(sys, "frozen", False):
        # exe : on veut le dossier où se trouve l'exe
        return os.path.dirname(sys.executable)

    # mode développement : fichier dans src/
    base = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(base)  # parent de src/ -> racine


BASE_DIR = _base_dir()

# Dossiers principaux
CONFIG_DIR  = os.path.join(BASE_DIR, "config")
DOCS_DIR    = os.path.join(BASE_DIR, "documents")
TOOLS_DIR   = os.path.join(BASE_DIR, "tools")
EXPORTS_DIR = os.path.join(BASE_DIR, "exports")
LOGS_DIR    = os.path.join(BASE_DIR, "logs")

# Création des dossiers si absents
for d in (CONFIG_DIR, DOCS_DIR, TOOLS_DIR, EXPORTS_DIR, LOGS_DIR):
    os.makedirs(d, exist_ok=True)

# Fichier de config unique (dans config/)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.ini")

# Dossiers images (on garde les mêmes noms qu'avant)
IMG_DIR_1 = os.path.join(BASE_DIR, "imgs")
IMG_DIR_2  = os.path.join(BASE_DIR, "imgs")


# ----------------------------------------------------------------------
# Lecture config.ini
# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
# Lecture config.ini
# ----------------------------------------------------------------------
def load_config() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()

    if not os.path.isfile(CONFIG_PATH):
        # Premier lancement : on crée un fichier config.ini par défaut
        cfg["SSH"] = {
            "host": "192.168.1.100",
            "username": "root",
            "password": "CHANGE_ME",
            "port": "22",
            "timeout": "30",
            "retry_base_delay": "2",
            "retry_max_delay": "10",
            "alive_interval": "10",
        }
        cfg["PATHS"] = {
            "remote_path": "/etc/iotecha/configs/GridCodes",
            "remote_file": "GridCodes.properties",
            # par défaut on pointe vers EXPORTS_DIR ou documents
            "local_path": os.path.join(EXPORTS_DIR, "GridCodes.properties"),
        }

        # On écrit dans config/config.ini
        os.makedirs(CONFIG_DIR, exist_ok=True)
        cfg["SECURITY"] = {"edit_password": ""}
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            cfg.write(f)

        print(f"[CONFIG] Fichier créé : {CONFIG_PATH}")
    else:
        # Fichier déjà présent : on le lit
        cfg.read(CONFIG_PATH, encoding="utf-8")
        needs_writeback = False
        print(f"[CONFIG] Fichier chargé : {CONFIG_PATH}")

        # Sécurité : on vérifie que les sections existent
        if "SSH" not in cfg:
            cfg["SSH"] = {
                "host": "",
                "username": "",
                "password": "",
                "port": "22",
                "timeout": "30",
                "retry_base_delay": "2",
                "retry_max_delay": "10",
                "alive_interval": "10",
            }
            needs_writeback = True
        elif "timeout" not in cfg["SSH"]:
            cfg["SSH"]["timeout"] = "30"
            needs_writeback = True
        if "retry_base_delay" not in cfg["SSH"]:
            cfg["SSH"]["retry_base_delay"] = "2"
            needs_writeback = True
        if "retry_max_delay" not in cfg["SSH"]:
            cfg["SSH"]["retry_max_delay"] = "10"
            needs_writeback = True
        if "alive_interval" not in cfg["SSH"]:
            cfg["SSH"]["alive_interval"] = "10"
            needs_writeback = True
        if "PATHS" not in cfg:
            cfg["PATHS"] = {
                "remote_path": "/etc/iotecha/configs/GridCodes",
                "remote_file": "GridCodes.properties",
                "local_path": os.path.join(EXPORTS_DIR, "GridCodes.properties"),
            }
            needs_writeback = True
        if "SECURITY" not in cfg:
            cfg["SECURITY"] = {"edit_password": ""}
            needs_writeback = True
        elif "edit_password" not in cfg["SECURITY"]:
            cfg["SECURITY"]["edit_password"] = ""
            needs_writeback = True
        if needs_writeback:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                cfg.write(f)

    return cfg

# ----------------------------------------------------------------------
# Application principale
# ----------------------------------------------------------------------
class RemoteBorneApp:
    def __init__(self, config: configparser.ConfigParser):
        # ---------- CONFIG ----------
        self.config = config
        ssh_cfg = config["SSH"]
        paths_cfg = config["PATHS"]
        security_cfg = config["SECURITY"]

        self.host = ssh_cfg.get("host", "")
        self.user = ssh_cfg.get("username", "")
        self.password = ssh_cfg.get("password", "")
        self.port = int(ssh_cfg.get("port", "22"))
        self.ssh_timeout = max(30, int(ssh_cfg.get("timeout", "30")))
        self.retry_base_delay = max(0.5, float(ssh_cfg.get("retry_base_delay", "2")))
        self.retry_max_delay = max(
            self.retry_base_delay, float(ssh_cfg.get("retry_max_delay", "10"))
        )
        self.alive_interval = max(5, int(ssh_cfg.get("alive_interval", "10")))

        self.default_path = paths_cfg.get(
            "remote_path", "/etc/iotecha/configs/GridCodes"
        )
        self.remote_file = paths_cfg.get("remote_file", "GridCodes.properties")
        self.local_default_path = paths_cfg.get(
            "local_path", os.path.join(EXPORTS_DIR, "GridCodes.properties")
        )
        self.edit_password = security_cfg.get("edit_password", "").strip()
        _local_dir = os.path.dirname(self.local_default_path) or self.local_default_path
        if not self.local_default_path or not os.path.exists(_local_dir):
            self.local_default_path = os.path.join(
                os.path.expanduser("~"),
                "Documents",
                "remote_borne_manager",
                self.remote_file,
            )
            os.makedirs(os.path.dirname(self.local_default_path), exist_ok=True)

        self.current_path = self.default_path

        # ---------- ETAT ----------
        self.connected = False
        self._alive_stop = False
        self._manual_disconnect_mode = False
        self.current_theme = "flatly"

        # ---------- ROOT / STYLE ----------
        # Fenêtre ttkbootstrap, thème "flatly" comme V7
        self.root = ttk.Window(themename=self.current_theme)
        self.root.title("Remote Borne Control Interface")
        self._set_app_icon()

        try:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            w = int(sw * 0.90)
            h = int(sh * 0.90)
            x = max(0, (sw - w) // 2)
            y = max(0, (sh - h) // 2)
            self.root.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            try:
                self.root.state("zoomed")
            except Exception:
                self.root.geometry("1200x800")

        self.root.minsize(1000, 700)

        # style ttkbootstrap
        self.style = self.root.style

        self.temp_var = tk.StringVar(value="Temp: --")
        self.soc_var = tk.StringVar(value="SoC: --")
        # ---------- VARIABLES ----------
        self.status_var = tk.StringVar(value="Disconnected")
        self.use_cosphi_var = tk.BooleanVar(value=False)
        

        # Références widgets (pour enable/disable)
        self.btn_connect = None
        self.btn_disconnect = None
        self.btn_exit = None

        self.btn_refresh = None
        self.btn_copy = None
        self.btn_edit = None
        self.btn_download = None
        self.btn_upload = None
        self.btn_print = None

        self.btn_send_power = None
        self.btn_send_cosphi = None
        self.btn_restart_services = None
        self.btn_reboot = None
        self.btn_copy_panel = None
        self.btn_refresh_panel = None
        self.btn_monitor = None
        self.terminal_menu = None

        self.active_entry = None
        self.reactive_entry = None
        self.cosphi_active_entry = None
        self.cosphi_entry = None
        
        self.log_text = None 
        self.file_list = None
        self.path_entry = None
        self._file_refresh_seq = 0
        self._editor_window = None
        self._editor_remote_path = None
        self._close_editor_window = None
        self._terminal_window = None
        self._close_terminal_window = None
        self._energy_win = None
        self._debug_logs_window = None
        self._find_dialog = None
        self.temp_label_var = tk.StringVar(value="Relay: -- °C")
        self.soc_label_var = tk.StringVar(value="SoC Batterie: --")
        self._monitor_stop = False
        self._monitor_thread_started = False
        self._last_user_command_ts = time.time()
        self._last_monitor_poll_ts = 0.0
        self._refresh_running = False
        self._refresh_pending = False
        self._closing = False
        self._scp_lock = threading.Lock()

        self.led_canvas = None
        self.ip_label = None
        self.user_label = None

        # Logos
        self.logo_left = None   # Renault
        self.logo_right = None  # AVL
        self._load_logos()

        # ---------- SSH ----------
        # Nouvelle façon (comme en V7) : on donne un timeout numérique
        # puis on enregistre les callbacks UI + logs.
        self.ssh = SSHManager(
            host=self.host,
            user=self.user,
            password=self.password,
            port=self.port,
            timeout=self.ssh_timeout,
            retry_base_delay=self.retry_base_delay,
            retry_max_delay=self.retry_max_delay,
        )

        # Callbacks pour que ssh_manager remonte les événements à l’UI
        self.ssh.set_ui_callback(self.on_ssh_event)
        self.ssh.set_log_callback(self.log)
        self.ssh_queue = SSHQueue(self.ssh, self.root, log=self.log)

        # On démarre le thread interne de SSHManager
        self.ssh.start()



        # ---------- UI ----------
        self._build_menu()
        self._build_layout()
        self._set_led(False)
        self._update_controls_state()
        self._start_ui_connection_guard()


        self.log(f"[INFO] RemoteBorne version: {APP_VERSION} ({os.path.basename(__file__)})")
        self.log("[INFO] Application started. Waiting for SSH events...")
        self.log(
            f"[SSH] Timeout={self.ssh_timeout}s | retry_base={self.retry_base_delay}s | retry_max={self.retry_max_delay}s | alive={self.alive_interval}s"
        )

        self.root.protocol("WM_DELETE_WINDOW", self.on_exit)

    def _set_app_icon(self):
        icon_path = os.path.join(BASE_DIR, "BorneCommander.ico")
        if not os.path.isfile(icon_path):
            return
        try:
            self.root.iconbitmap(icon_path)
        except Exception:
            pass

    # ==================================================================
    # THEMES (flatly / darkly)
    # ==================================================================
    def _init_themes(self):
        """Avec ttkbootstrap, on n'a plus besoin de simuler les palettes."""
        # rien à faire ici, mais on garde la fonction pour compatibilité
        pass

    def _apply_theme(self, theme_name: str):
        """Applique un thème ttkbootstrap (flatly / darkly)."""
        self.current_theme = theme_name
        try:
            self.style.theme_use(theme_name)
            # MAJ du style du log en fonction du nouveau thème
            if self.log_text is not None:
                self._style_logs()
        except Exception as e:
            print(f"[THEME ERROR] {e}")
            self._popup_error("Theme", f"Cannot switch theme:\n{e}")

    def _center_toplevel(self, win: tk.Toplevel, width: int, height: int, parent=None):
        """Centre une fenêtre fille par rapport à la fenêtre parente (fallback écran)."""
        parent = parent or self.root
        try:
            parent.update_idletasks()
            px, py = parent.winfo_rootx(), parent.winfo_rooty()
            pw, ph = parent.winfo_width(), parent.winfo_height()
            if pw > 1 and ph > 1:
                x = px + max(0, (pw - width) // 2)
                y = py + max(0, (ph - height) // 2)
                win.geometry(f"{width}x{height}+{x}+{y}")
                return
        except Exception:
            pass

        # fallback : centre écran
        win.update_idletasks()
        x = (win.winfo_screenwidth() - width) // 2
        y = (win.winfo_screenheight() - height) // 2
        win.geometry(f"{width}x{height}+{x}+{y}")
            
    # ==========================================================
    # Validation clavier pour les champs numériques (float + signe)
    # ==========================================================
    def _validate_float_key(self, new_value: str) -> bool:
        """
        Autorise uniquement :
          - vide (pendant la saisie)
          - -12
          - 3.14
          - -0.5
          - 12.
        Interdit tout le reste (lettres, virgule, etc).
        """
        if new_value == "":
            return True
        pattern = r"^-?\d*(\.\d*)?$"
        return re.match(pattern, new_value) is not None

    # ==================================================================
    # LOGOS
    # ==================================================================
    def _load_logos(self):
        renault_path = None
        avl_path = None

        for base in (IMG_DIR_1, IMG_DIR_2):
            if not os.path.isdir(base):
                continue

            # Cherche n'importe quel .png contenant "renault" ou "avl"
            try:
                for fname in os.listdir(base):
                    low = fname.lower()
                    full = os.path.join(base, fname)
                    if not os.path.isfile(full):
                        continue
                    if low.endswith(".png"):
                        if "renault" in low and not renault_path:
                            renault_path = full
                        if "avl" in low and not avl_path:
                            avl_path = full
            except Exception as e:
                print(f"[LOGO SCAN ERROR] {base}: {e}")

        try:
            if renault_path:
                img = tk.PhotoImage(file=renault_path)
                max_h = 40
                h = img.height()
                if h > max_h:
                    factor = max(1, int(math.ceil(h / max_h)))
                    img = img.subsample(factor, factor)
                self.logo_left = img

            if avl_path:
                img = tk.PhotoImage(file=avl_path)
                max_h = 40
                h = img.height()
                if h > max_h:
                    factor = max(1, int(math.ceil(h / max_h)))
                    img = img.subsample(factor, factor)
                self.logo_right = img

        except Exception as e:
            self.logo_left = None
            self.logo_right = None
            print(f"[LOGO ERROR] {e}")

    # ==================================================================
    # MENU
    # ==================================================================
    def _build_menu(self):
        menubar = tk.Menu(self.root)

        # FILE
        self.file_menu = tk.Menu(menubar, tearoff=0)
        self.file_menu.add_command(label="Connect", command=self.force_reconnect)
        self.file_menu.add_command(label="Disconnect", command=self._manual_disconnect)
        self.file_menu.add_separator()
        self.file_menu.add_command(
            label="Download", command=self._menu_download
        )
        self.file_menu.add_command(label="Print", command=self._menu_print)
        self.file_menu.add_command(label="Edit", command=self._menu_edit)
        self.file_menu.add_separator()
        self.file_menu.add_command(
            label="Restart services", command=self.restart_initd_services
        )
        self.file_menu.add_command(label="Reboot device", command=self.reboot_device)
        self.file_menu.add_separator()
        self.file_menu.add_command(label="Exit", command=self.on_exit)
        menubar.add_cascade(label="File", menu=self.file_menu)

        # VIEW
        view_menu = tk.Menu(menubar, tearoff=0)
        theme_menu = tk.Menu(view_menu, tearoff=0)
        theme_menu.add_command(
            label="Flatly (Light)", command=lambda: self._apply_theme("flatly")
        )
        theme_menu.add_command(
            label="Darkly (Dark)", command=lambda: self._apply_theme("darkly")
        )
        view_menu.add_cascade(label="Theme", menu=theme_menu)
        menubar.add_cascade(label="View", menu=view_menu)

        # DEBUG
        self.debug_menu = tk.Menu(menubar, tearoff=0)
        self.debug_menu.add_command(label="Debug logs", command=self.open_debug_logs)
        menubar.add_cascade(label="Debug", menu=self.debug_menu)

        # ENERGY (nouveau)
        self.energy_menu = tk.Menu(menubar, tearoff=0)
        self.energy_menu.add_command(
            label="Energy Manager PRO",
            command=self.open_energy_manager,
        )
        menubar.add_cascade(label="Energy", menu=self.energy_menu)


        # NETWORK
        net_menu = tk.Menu(menubar, tearoff=0)
        net_menu.add_command(label="Network config", command=self.open_network_config)
        menubar.add_cascade(label="Network", menu=net_menu)

        # TERMINAL
        self.terminal_menu = tk.Menu(menubar, tearoff=0)
        self.terminal_menu.add_command(
            label="Open Terminal", command=self.open_terminal
        )
        menubar.add_cascade(label="Terminal", menu=self.terminal_menu)


        # HELP
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Help", command=lambda: open_help(self.root))
        help_menu.add_command(label="About", command=self._show_about)
        menubar.add_cascade(label="Help", menu=help_menu)


        self.root.config(menu=menubar)

    def _style_logs(self):
        if self.current_theme == "darkly":
            self.log_text.configure(
                background="#1e1e1e",
                foreground="#dcdcdc",
                insertbackground="#ffffff",
                borderwidth=0,
                relief="flat"
            )
        else:
            self.log_text.configure(
                background="#f0f0f0",
                foreground="black",
                insertbackground="black",
                borderwidth=1,
                relief="sunken"
            )

    # ==================================================================
    # LAYOUT (proche V2, plus clean)
    # ==================================================================
    def _build_layout(self):
        # ----- MAIN -----
        main = ttk.Frame(self.root)
        main.pack(fill="both", expand=True)

        # 🔥 IMPORTANT (responsive)
        main.grid_columnconfigure(0, weight=3)
        main.grid_columnconfigure(1, weight=2)

        main.grid_rowconfigure(0, weight=0)
        main.grid_rowconfigure(1, weight=3)
        main.grid_rowconfigure(2, weight=2)
        main.grid_rowconfigure(3, weight=2)

        # ----- HEADER (logos + titre + status) -----
        header = ttk.Frame(main)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=(5, 0))
        header.grid_columnconfigure(0, weight=1)
        header.grid_columnconfigure(1, weight=3)
        header.grid_columnconfigure(2, weight=1)

        left_logo_fr = ttk.Frame(header)
        left_logo_fr.grid(row=0, column=0, sticky="w")
        if self.logo_left:
            ttk.Label(left_logo_fr, image=self.logo_left).pack(anchor="w")

        center_fr = ttk.Frame(header)
        center_fr.grid(row=0, column=1, sticky="nsew")
        ttk.Label(
            center_fr,
            text="Remote Borne Control Interface",
            font=("Segoe UI", 16, "bold"),
            anchor="center",
        ).pack(fill="x")
        ttk.Label(
            center_fr,
            text="RBM",
            font=("Segoe UI", 8, "italic"),
            anchor="center",
        ).pack(fill="x")

        right_logo_fr = ttk.Frame(header)
        right_logo_fr.grid(row=0, column=2, sticky="e")
        if self.logo_right:
            ttk.Label(right_logo_fr, image=self.logo_right).pack(anchor="e")

        # ----- LEFT : FILE BROWSER -----
        left = ttk.Labelframe(
            main,
            text=f"EVSE Local Grid Code Configuration Files",
            padding=5,
        )
        left.grid(row=1, column=0, rowspan=2, sticky="nsew", padx=(10, 5), pady=5)

        # 🔥 IMPORTANT (responsive)
        left.grid_rowconfigure(0, weight=0)   # barre de path
        left.grid_rowconfigure(1, weight=1)   # liste fichiers
        left.grid_columnconfigure(0, weight=1)

        # Path bar
        path_row = ttk.Frame(left)
        path_row.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        path_row.grid_columnconfigure(1, weight=1)

        ttk.Label(path_row, text="Path:").grid(row=0, column=0, sticky="w")
        self.path_entry = ttk.Entry(path_row)
        self.path_entry.grid(row=0, column=1, sticky="ew", padx=2)
        self.path_entry.insert(0, self.current_path)

        ttk.Button(path_row, text="Go", width=6, command=self._go_to_path).grid(
            row=0, column=2, padx=2
        )
        ttk.Button(path_row, text="Up", width=6, command=self._go_parent).grid(
            row=0, column=3, padx=2
        )
        ttk.Button(path_row, text="Root", width=6, command=self._go_root).grid(
            row=0, column=4, padx=2
        )

        # File list
        list_frame = ttk.Frame(left)
        list_frame.grid(row=1, column=0, sticky="nsew")
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(1, weight=1)     # <--- AJOUT NECESSAIRE
        left.grid_columnconfigure(0, weight=1)  # <--- AJOUT NECESSAIRE


        self.file_list = tk.Listbox(
            list_frame,
            activestyle="none",
            font=("Segoe UI", 10),
        )
        self.file_list.grid(row=0, column=0, sticky="nsew")

        vs = ttk.Scrollbar(
            list_frame, orient="vertical", command=self.file_list.yview
        )
        vs.grid(row=0, column=1, sticky="ns")
        hs = ttk.Scrollbar(
            list_frame, orient="horizontal", command=self.file_list.xview
        )
        hs.grid(row=1, column=0, sticky="ew")

        self.file_list.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)

        self.file_list.bind("<Double-Button-1>", self.on_file_double_click)
        self.file_list.bind("<Button-3>", self._on_file_menu)

        # ----- RIGHT TOP : STATUS + CONTROLS -----
        right_top = ttk.Labelframe(main, text="Status & Controls", padding=5)
        right_top.grid(row=1, column=1, sticky="nsew", padx=(5, 10), pady=(5, 2))
        right_top.grid_columnconfigure(0, weight=1)

        # Status row
        status_row = ttk.Frame(right_top)
        status_row.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        status_row.grid_columnconfigure(1, weight=1)

        self.ip_label = ttk.Label(
            status_row, text=f"IP: {self.host or '-'}", anchor="w"
        )
        self.ip_label.grid(row=0, column=0, sticky="w")

        self.user_label = ttk.Label(
            status_row, text=f"User: {self.user or '-'}", anchor="w"
        )
        self.user_label.grid(row=1, column=0, sticky="w")
        
        #ttk.Label(status_row, textvariable=self.temp_var).grid(row=2, column=0, sticky="w")
        #ttk.Label(status_row, textvariable=self.soc_var).grid(row=3, column=0, sticky="w")
        
        self.led_canvas = tk.Canvas(
            status_row, width=20, height=20, highlightthickness=0
        )
        self.led_canvas.grid(row=0, column=1, rowspan=2, sticky="e", padx=8)

        ttk.Label(
            status_row,
            textvariable=self.status_var,
        ).grid(row=0, column=2, rowspan=2, sticky="e")

        # Connection buttons
        btn_row = ttk.Frame(right_top)
        btn_row.grid(row=1, column=0, sticky="ew")
        btn_row.grid_columnconfigure(0, weight=1)
        btn_row.grid_columnconfigure(1, weight=1)
        btn_row.grid_columnconfigure(2, weight=1)

        self.btn_connect = ttk.Button(
            btn_row,
            text="Connect",
            style="Accent.TButton",
            command=self.force_reconnect,
        )
        self.btn_connect.grid(row=0, column=0, padx=2, pady=2, sticky="ew")

        self.btn_disconnect = ttk.Button(
            btn_row,
            text="Disconnect",
            style="Danger.TButton",
            command=self._manual_disconnect,
        )
        self.btn_disconnect.grid(row=0, column=1, padx=2, pady=2, sticky="ew")

        self.btn_exit = ttk.Button(
            btn_row, text="Exit", style="Danger.TButton", command=self.on_exit
        )
        self.btn_exit.grid(row=0, column=2, padx=2, pady=2, sticky="ew")

        # File actions
        file_actions = ttk.Labelframe(right_top, text="Test Configuration", padding=5)
        file_actions.grid(row=2, column=0, sticky="nsew", pady=(4, 0))

        # Layout tuned for long labels: short actions on first row,
        # long actions on a second row with wider buttons.
        file_actions.grid_columnconfigure(0, weight=1)
        file_actions.grid_columnconfigure(1, weight=1)
        file_actions.grid_columnconfigure(2, weight=1)
        file_actions.grid_columnconfigure(3, weight=1)
        file_actions.grid_rowconfigure(0, weight=0)
        file_actions.grid_rowconfigure(1, weight=0)

        style = ttk.Style()
        style.configure("Wide.TButton", padding=(8, 6))
        style.configure("Monitor.TButton", padding=(8, 2))

        # Row 1: short actions
        self.btn_refresh = ttk.Button(
            file_actions, text="Refresh", command=self.refresh_file_list
        )
        self.btn_refresh.grid(row=0, column=0, padx=3, pady=3, sticky="ew")

        self.btn_download = ttk.Button(
            file_actions, text="Download", command=self._menu_download
        )
        self.btn_download.grid(row=0, column=1, padx=3, pady=3, sticky="ew")

        self.btn_edit = ttk.Button(
            file_actions, text="Edit", command=self._menu_edit
        )
        self.btn_edit.grid(row=0, column=2, padx=3, pady=3, sticky="ew")

        self.btn_print = ttk.Button(
            file_actions, text="Print", command=self._menu_print
        )
        self.btn_print.grid(row=0, column=3, padx=3, pady=3, sticky="ew")

        # Row 2: long actions
        self.btn_upload = ttk.Button(
            file_actions,
            text="Upload Configuration\nFile from PC",
            style="Wide.TButton",
            command=self.upload_files_to_current_path,
        )
        self.btn_upload.grid(
            row=1, column=0, columnspan=2, padx=3, pady=3, sticky="ew"
        )

        self.btn_copy_panel = ttk.Button(
            file_actions,
            text="Load Grid Code\nConfiguration",
            style="Wide.TButton",
            command=self.copy_selected_to_gridcodes,
        )
        self.btn_copy_panel.grid(
            row=1, column=2, columnspan=2, padx=3, pady=3, sticky="ew"
        )

        # ----- RIGHT MIDDLE : ENERGY MANAGER -----
        em_frame = ttk.Labelframe(main, text="Energy Manager Controls", padding=5)
        em_frame.grid(row=2, column=1, sticky="ew", padx=(5, 10), pady=(2, 5))
        em_frame.grid_columnconfigure(0, weight=1)
        em_frame.grid_columnconfigure(1, weight=1)

        # Validateur float commun à tous les champs P/Q/CosPhi
        vcmd_float = (self.root.register(self._validate_float_key), "%P")

        # P/Q
        pq_frame = ttk.Labelframe(em_frame, text="P / Q Setpoint", padding=5)
        pq_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        pq_frame.grid_columnconfigure(1, weight=1)

        ttk.Label(pq_frame, text="Active (P) [W]:").grid(row=0, column=0, sticky="w")
        self.active_entry = ttk.Entry(
            pq_frame,
            validate="key",
            validatecommand=vcmd_float,
        )
        self.active_entry.grid(row=0, column=1, sticky="ew", pady=2)
        # Default value for active
        self.active_entry.insert(0, "0")

        ttk.Label(pq_frame, text="Reactive (Q) [var]:").grid(
            row=1, column=0, sticky="w"
        )
        self.reactive_entry = ttk.Entry(
            pq_frame,
            validate="key",
            validatecommand=vcmd_float,
        )
        self.reactive_entry.grid(row=1, column=1, sticky="ew", pady=2)
        # Default value for reactive
        self.reactive_entry.insert(0, "0")

        self.btn_send_power = ttk.Button(
            pq_frame,
            text="Send",
            style="Accent.TButton",
            command=self.send_power_command,
        )
        self.btn_send_power.grid(
            row=2, column=0, columnspan=2, pady=(6, 0), sticky="ew"
        )

        # CosPhi
        cosphi_frame = ttk.Labelframe(em_frame, text="CosPhi Setpoint", padding=5)
        cosphi_frame.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        cosphi_frame.grid_columnconfigure(1, weight=1)

        ttk.Checkbutton(
            cosphi_frame,
            text="Use CosPhi mode",
            variable=self.use_cosphi_var,
            command=self._on_cosphi_toggle,
        ).grid(row=0, column=0, columnspan=2, sticky="w")

        ttk.Label(cosphi_frame, text="Active (P) [W]:").grid(
            row=1, column=0, sticky="w"
        )
        self.cosphi_active_entry = ttk.Entry(
            cosphi_frame,
            validate="key",
            validatecommand=vcmd_float,
        )
        self.cosphi_active_entry.grid(row=1, column=1, sticky="ew", pady=2)
        # Default value for active
        self.cosphi_active_entry.insert(0, "0")

        ttk.Label(cosphi_frame, text="CosPhi:").grid(row=2, column=0, sticky="w")
        self.cosphi_entry = ttk.Entry(
            cosphi_frame,
            validate="key",
            validatecommand=vcmd_float,
        )
        self.cosphi_entry.grid(row=2, column=1, sticky="ew", pady=2)
        # PAS de valeur par défaut : CosPhi doit être saisi par l'utilisateur

        self.btn_send_cosphi = ttk.Button(
            cosphi_frame,
            text="Send",
            style="Accent.TButton",
            command=self.send_cosphi_command,
        )
        self.btn_send_cosphi.grid(
            row=3, column=0, columnspan=2, pady=(6, 0), sticky="ew"
        )

        # Services
        srv_frame = ttk.Labelframe(em_frame, text="Services", padding=5)
        srv_frame.grid(row=1, column=0, sticky="nsew", padx=(0, 4), pady=(4, 0))
        srv_frame.grid_columnconfigure(0, weight=1)
        srv_frame.grid_columnconfigure(1, weight=1)
        srv_frame.grid_rowconfigure(1, weight=0)

        self.btn_restart_services = ttk.Button(
            srv_frame,
            text="Restart services",
            style="Success.TButton",
            command=self.restart_initd_services,
        )
        self.btn_restart_services.grid(
            row=0, column=0, padx=3, pady=3, sticky="ew"
        )

        self.btn_reboot = ttk.Button(
            srv_frame,
            text="Reboot device",
            style="Danger.TButton",
            command=self.reboot_device,
        )
        self.btn_reboot.grid(row=0, column=1, padx=3, pady=3, sticky="ew")

        # ttk.Label(
            # srv_frame,
            # text="Run after each configuration change.",
            # anchor="w",
            # justify="left",
        # ).grid(row=1, column=0, columnspan=2, sticky="w", padx=2, pady=(4, 0))

        # --- ADDED ---
        derate_frame = ttk.Labelframe(
            em_frame, text="Temperature / Derating", padding=5
        )
        derate_frame.grid(
            row=1, column=1, sticky="nsew", padx=(4, 0), pady=(4, 0)
        )

        derate_frame.grid_columnconfigure(0, weight=1)
        derate_frame.grid_columnconfigure(1, weight=0)
        derate_frame.grid_rowconfigure(0, weight=0)
        derate_frame.grid_rowconfigure(1, weight=0)

        # Relay temperatures - full width on row 0
        self.temp_label = ttk.Label(
            derate_frame,
            textvariable=self.temp_label_var,
            anchor="w",
            justify="left",
        )
        self.temp_label.grid(row=0, column=0, columnspan=2, sticky="ew", padx=2, pady=2)

        # SoC + refresh button on row 1
        self.soc_label = ttk.Label(
            derate_frame,
            textvariable=self.soc_label_var,
            anchor="w",
            justify="left",
        )
        self.soc_label.grid(row=1, column=0, sticky="ew", padx=2, pady=2)

        self.btn_monitor = ttk.Button(
            derate_frame,
            text="Refresh",
            style="Monitor.TButton",
            width=9,
            command=self.update_monitor,
        )
        self.btn_monitor.grid(row=1, column=1, sticky="e", padx=(8, 2), pady=2)


        # ----- BOTTOM : LOGS -----
        log_frame = ttk.Labelframe(main, text="Logs", padding=5)
        log_frame.grid(
            row=3, column=0, columnspan=2, sticky="nsew", padx=10, pady=(0, 10)
        )

        # 🔥 IMPORTANT : moins de priorité verticale
        main.grid_rowconfigure(3, weight=1)

        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(0, weight=1)

        self.log_text = tk.Text(
            log_frame,
            height=6,
            wrap="word",
            state="disabled",
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")

        log_scroll = ttk.Scrollbar(
            log_frame, orient="vertical", command=self.log_text.yview
        )
        log_scroll.grid(row=0, column=1, sticky="ns")

        self.log_text.configure(yscrollcommand=log_scroll.set)

        # style du log en fonction du thème
        self._style_logs()

    # ==================================================================
    # LOG & LED
    # ==================================================================
    def log(self, msg: str):
        """
        Log dans la console + zone de logs Tkinter, en étant thread-safe.
        Si appelé depuis un thread secondaire, on reposte dans le thread UI.
        """
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {msg}\n"
        print(line, end="")

        if self.log_text is None:
            return

        # Si on est déjà dans le thread principal Tk → on peut écrire direct
        if threading.current_thread() is threading.main_thread():
            self._append_log_line(line)
        else:
            # Sinon, on reposte dans le thread Tk
            try:
                self.root.after(0, self._append_log_line, line)
            except Exception:
                # En dernier recours : on laisse juste la console
                pass

    def _append_log_line(self, line: str):
        """
        Implémentation réelle d'ajout dans le widget Text (à appeler
        uniquement depuis le thread principal Tk).
        """
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line)

        # Limite du nombre de lignes pour éviter de ralentir l'UI
        try:
            max_lines = 2000
            lines = int(self.log_text.index("end-1c").split(".")[0])
            if lines > max_lines:
                self.log_text.delete("1.0", f"{lines - max_lines}.0")
        except Exception:
            pass

        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    # ============================================================
    # LED connection indicator (green/red dot)
    # ============================================================
    def _set_led(self, state: bool):
        """
        Affiche un point vert (connected) ou rouge (disconnected)
        dans le canvas de statut (status_led ou led_canvas).
        """

        # Cas 1 : tu as un canvas self.status_led (comme dans une de tes versions)
        if hasattr(self, "status_led") and self.status_led is not None:
            try:
                self.status_led.delete("all")
                color = "#27AE60" if state else "#E74C3C"  # vert / rouge
                self.status_led.create_oval(2, 2, 18, 18, fill=color, outline=color)
            except Exception:
                pass
            return

        # Cas 2 : fallback sur self.led_canvas si c'est lui que tu utilises
        if hasattr(self, "led_canvas") and self.led_canvas is not None:
            try:
                self.led_canvas.delete("all")
                color = "#27AE60" if state else "#E74C3C"
                self.led_canvas.create_oval(2, 2, 18, 18, fill=color, outline=color)
            except Exception:
                pass
            return

        # Sinon on ne fait rien (pas de canvas défini)
        return

    # ==================================================================
    # SSH EVENTS & CONNECT/DISCONNECT
    # ==================================================================
    def force_reconnect(self):
        self._manual_disconnect_mode = False
        self.log("[SSH] Reconnecting...")
        try:
            self.ssh.restart()
        except Exception as e:
            self.log(f"[SSH ERROR] {e}")

    def _manual_disconnect(self):
        self._manual_disconnect_mode = True
        self._refresh_running = False
        self._refresh_pending = False
        self._close_aux_windows("manual disconnect")
        try:
            self.ssh.close()
        except Exception:
            pass
        self.connected = False
        self.status_var.set("Disconnected")
        self._set_led(False)
        self._clear_file_list_ui()
        self._update_controls_state()

    def _clear_file_list_ui(self):
        if self.file_list is None:
            return
        try:
            self.file_list.delete(0, "end")
            self.file_list.selection_clear(0, "end")
        except Exception:
            pass

    def _join_remote(self, *parts):
        cleaned = []
        for p in parts:
            if not p:
                continue
            cleaned.append(str(p).replace("\\", "/"))
        return posixpath.join(*cleaned)
  
    def _close_aux_windows(self, reason: str = "disconnect", force: bool = False):
        if self._closing and not force:
            return

        closed_any = False

        def _safe_destroy(win):
            nonlocal closed_any
            if win is None:
                return
            try:
                if not win.winfo_exists():
                    return
            except Exception:
                return
            try:
                win.grab_release()
            except Exception:
                pass
            try:
                win.destroy()
                closed_any = True
            except Exception:
                pass

        close_editor = getattr(self, "_close_editor_window", None)
        if callable(close_editor):
            try:
                close_editor()
                closed_any = True
            except Exception:
                _safe_destroy(getattr(self, "_editor_window", None))
        else:
            _safe_destroy(getattr(self, "_editor_window", None))
        self._editor_window = None
        self._editor_remote_path = None
        self._close_editor_window = None

        _safe_destroy(getattr(self, "_find_dialog", None))
        self._find_dialog = None

        close_terminal = getattr(self, "_close_terminal_window", None)
        if callable(close_terminal):
            try:
                close_terminal()
                closed_any = True
            except Exception:
                _safe_destroy(getattr(self, "_terminal_window", None))
        else:
            _safe_destroy(getattr(self, "_terminal_window", None))
        self._terminal_window = None
        self._close_terminal_window = None

        debug_window = getattr(self, "_debug_logs_window", None)
        if debug_window is not None:
            try:
                debug_window.on_close()
                closed_any = True
            except Exception:
                _safe_destroy(getattr(debug_window, "window", None))
        self._debug_logs_window = None

        energy_win = getattr(self, "_energy_win", None)
        if energy_win is not None:
            try:
                close_energy = getattr(energy_win, "close", None)
                if callable(close_energy):
                    close_energy()
                    closed_any = True
                else:
                    _safe_destroy(getattr(energy_win, "win", None))
            except Exception:
                _safe_destroy(getattr(energy_win, "win", None))
        self._energy_win = None

        if force:
            try:
                tracked = {
                    getattr(self, "_editor_window", None),
                    getattr(self, "_find_dialog", None),
                    getattr(self, "_terminal_window", None),
                    getattr(getattr(self, "_energy_win", None), "win", None),
                    getattr(getattr(self, "_debug_logs_window", None), "window", None),
                }
                for child in list(self.root.winfo_children()):
                    if (
                        isinstance(child, tk.Toplevel)
                        and child not in tracked
                        and child.winfo_exists()
                    ):
                        _safe_destroy(child)
            except Exception:
                pass

        if closed_any:
            self.log(f"[UI] Secondary windows closed after {reason}.")

    def _has_aux_windows_open(self) -> bool:
        tracked_windows = [
            getattr(self, "_editor_window", None),
            getattr(self, "_find_dialog", None),
            getattr(self, "_terminal_window", None),
            getattr(getattr(self, "_energy_win", None), "win", None),
            getattr(getattr(self, "_debug_logs_window", None), "window", None),
        ]
        for win in tracked_windows:
            if win is None:
                continue
            try:
                if win.winfo_exists():
                    return True
            except Exception:
                continue
        return False

    def _start_ui_connection_guard(self):
        def guard():
            if self._closing:
                return
            try:
                disconnected = (
                    not self.connected
                    or not getattr(self.ssh, "connected", False)
                    or getattr(self.ssh, "_reconnect_in_progress", False)
                    or str(self.status_var.get()).startswith("Reconnecting")
                )
                if disconnected and self._has_aux_windows_open():
                    self._close_aux_windows("UI guard disconnect")
            except Exception:
                pass
            try:
                self.root.after(750, guard)
            except Exception:
                pass

        try:
            self.root.after(750, guard)
        except Exception:
            pass

    # ==================================================================
    # ALIVE MONITOR (heartbeat echo alive)
    # ==================================================================
    def _start_alive_monitor(self):
        """
        Lance un thread qui envoie 'echo alive' toutes les 10 s.

        - Ne spam pas self.ssh.execute (auto_retry=False)
        - En cas d’échec, on log et on lance une reconnexion propre.
        """
        if hasattr(self, "_alive_thread_started") and self._alive_thread_started:
            return
        self._alive_thread_started = True

        def worker():
            last_reconnect_try = 0.0
            heartbeat_failures = 0
            monitor_interval = max(10, self.alive_interval)
            while not self._alive_stop:
                time.sleep(monitor_interval)
                # Si l’app est fermée, on sort
                if not hasattr(self, "ssh"):
                    break
                if getattr(self.ssh, "_reconnect_in_progress", False):
                    heartbeat_failures = 0
                    continue
                # Si pas connecté -> on tente une reconnexion périodique
                if not self.ssh.connected:
                    heartbeat_failures = 0
                    if self._manual_disconnect_mode:
                        continue
                    if self.status_var.get().startswith("Reconnecting"):
                        continue
                    now = time.time()
                    # évite de spammer plusieurs tentatives/logs toutes les 10s
                    if now - last_reconnect_try >= 30:
                        self.log("[ALIVE] Disconnected, attempting reconnect.")
                        self.ssh.restart()
                        last_reconnect_try = now
                    continue

                def cb(res):
                    nonlocal heartbeat_failures, last_reconnect_try
                    if not res["success"]:
                        if getattr(self.ssh, "_reconnect_in_progress", False):
                            heartbeat_failures = 0
                            return
                        heartbeat_failures += 1
                        self.log(
                            f"[ALIVE] Heartbeat failed ({heartbeat_failures}/3)."
                        )
                        if heartbeat_failures < 3:
                            return
                        now = time.time()
                        if now - last_reconnect_try >= 30:
                            self.log(
                                "[ALIVE] 3 heartbeat failures in a row, forcing reconnect."
                            )
                            self.ssh.force_reconnect(force_if_connected=True)
                            last_reconnect_try = now
                        heartbeat_failures = 0
                    else:
                        heartbeat_failures = 0

                # IMPORTANT : pas d’auto_retry ici, sinon double gestion
                self.ssh_queue.execute(
                    "echo alive",
                    callback=cb,
                    timeout=8,
                    auto_retry=False,
                    log_errors=False,
                    command_type="heartbeat",
                    silent=True,
                    label="Heartbeat",
                )

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    # --- ADDED ---
    def _start_monitor(self):
        if self._monitor_thread_started:
            return
        self._monitor_thread_started = True

        def worker():
            while not self._monitor_stop:
                idle_seconds = time.time() - self._last_user_command_ts
                if (
                    self.ssh.connected
                    and not self._manual_disconnect_mode
                    and not getattr(self.ssh, "_reconnect_in_progress", False)
                    and not getattr(self.ssh_queue, "pause_monitoring", False)
                    and idle_seconds >= 180
                    and (time.time() - self._last_monitor_poll_ts) >= 180
                ):
                    self.update_temp_and_soc()
                    self._last_monitor_poll_ts = time.time()
                time.sleep(5)

        threading.Thread(target=worker, daemon=True).start()

    def _mark_user_command(self):
        self._last_user_command_ts = time.time()

    def _safe_mark_user_command(self):
        try:
            self._mark_user_command()
        except Exception:
            self._last_user_command_ts = time.time()

    # --- ADDED ---
    def update_temperature(self):
        """Compatibility alias: refresh Temp and SoC together."""
        self.update_temp_and_soc()

    def update_soc(self):
        """Compatibility alias kept for older call sites."""
        pass

    def update_monitor(self):
        """Manual refresh button: Temp and SoC in one SSH command."""
        if not self.connected:
            self.log("[MONITOR] Refresh: not connected.")
            return
        self.log("[MONITOR] Manual refresh requested...")
        self.update_temp_and_soc(manual=True)

    def update_temp_and_soc(self, manual=False):
        """Fetch Temp and SoC with a single SSH command."""

        if getattr(self.ssh_queue, "pause_monitoring", False):
            if manual:
                self.log("[MONITOR] Refresh skipped: file operation in progress.")
            return

        cmd = (
            'echo "===TEMP==="; '
            'grep -oiE "DerateDetails:.*" /var/aux/ChargerApp/derate.log 2>/dev/null | tail -1; '
            'echo "===SOC==="; '
            'grep -oE "evPresentSo[Cc]: [0-9]+" /var/aux/ChargerApp/ChargerApp.log 2>/dev/null | tail -1 | grep -oE "[0-9]+"'
        )

        def cb(res):
            stdout = (res.get("stdout") or res.get("out") or "").strip()

            if not res.get("success") or not stdout:
                err = (res.get("stderr") or res.get("err") or "").strip()
                self.log(f"[MONITOR] SSH error - {err or 'no response'}")
                return

            parts = stdout.split("===SOC===")
            temp_raw = parts[0].replace("===TEMP===", "").strip()
            soc_raw = parts[1].strip() if len(parts) > 1 else ""

            relays = re.findall(
                r"PowerBoard Relay T(\d+)\s*:\s*(\d+)", temp_raw, re.IGNORECASE
            )
            m_pb = re.search(r"(?<!Relay )PowerBoard T1\s*:\s*(\d+)", temp_raw, re.IGNORECASE)
            m_mb = re.search(r"MainBoard T1\s*:\s*(\d+)", temp_raw, re.IGNORECASE)

            if relays:
                relay_dict = {int(n): int(v) for n, v in relays}
                relay_str = " | ".join(f"T{n}:{relay_dict[n]}" for n in sorted(relay_dict))
                temp_display = f"Relay: {relay_str} °C"
                max_temp = max(relay_dict.values())
            elif m_pb:
                val = int(m_pb.group(1))
                temp_display = f"PowerBoard T1: {val} °C"
                max_temp = val
            elif m_mb:
                val = int(m_mb.group(1))
                temp_display = f"MainBoard T1: {val} °C"
                max_temp = val
            else:
                temp_display = None
                max_temp = None

            if temp_display:
                self.log(f"[MONITOR] Temp - {temp_display}")
            else:
                self.log(
                    "[MONITOR] Temp: no match in derate.log"
                    + (f" - raw: {temp_raw[:80]}" if temp_raw else " - empty")
                )

            soc_match = re.search(r"(\d+)", soc_raw)
            soc_value = soc_match.group(1) if soc_match else None

            if soc_value is not None:
                self.log(f"[MONITOR] SoC: {soc_value} %")
            else:
                self.log(
                    "[MONITOR] SoC: no match in ChargerApp.log"
                    + (f" - raw: {soc_raw[:80]}" if soc_raw else " - empty")
                )

            def apply_ui():
                if temp_display is None:
                    self.temp_label_var.set("Relay: -- °C")
                    self.temp_label.configure(foreground="")
                else:
                    self.temp_label_var.set(temp_display)
                    self.temp_label.configure(
                        foreground=("red" if (max_temp or 0) > 80 else "green")
                    )
                self.soc_label_var.set(
                    f"SoC Batterie (last known): {soc_value}"
                    if soc_value is not None
                    else "SoC Batterie: --"
                )

            try:
                if not self._closing and self.root.winfo_exists():
                    self.root.after(0, apply_ui)
            except Exception:
                pass

        self.ssh_queue.execute(
            cmd,
            callback=cb,
            timeout=min(self.ssh_timeout, 5),
            command_type="monitor_temp_soc",
            label="Monitor Temp + SoC",
            silent=False,
            auto_retry=False,
            log_errors=False,
        )

    # ==================================================================
    # SSH EVENTS (connect / disconnect / reconnect)
    # ==================================================================
    def on_ssh_event(self, event_type, data):
        """
        Callback appelé par SSHManager (ssh_manager.py).

        event_type ∈ {"connected","disconnected","reconnecting","reconnected"}
        On s'assure que tout se fait dans le thread Tkinter via root.after.
        """

        def _handle(ev_type, ev_data):
            if ev_type == "connected":
                self._manual_disconnect_mode = False
                self.connected = True
                self.status_var.set("Connected")
                self.log("[SSH] Connected")
                self._set_led(True)
                self._update_controls_state()
                # Initialize remote file browser
                self.current_path = self.default_path
                self.refresh_file_list()
                # démarre le heartbeat et le monitor
                # Délai 3 s : laisse le refresh se terminer avant le premier poll
                self._start_alive_monitor()
                self._start_monitor()
                self.root.after(3000, self.update_monitor)

            elif ev_type == "disconnected":
                self.connected = False
                self._refresh_running = False
                self._refresh_pending = False
                self.status_var.set("Disconnected")
                self.log("[SSH] Disconnected")
                self._close_aux_windows("SSH disconnect")
                self._set_led(False)
                self._clear_file_list_ui()
                self.temp_label_var.set("Relay: -- °C")
                self.temp_label.configure(foreground="")
                self.soc_label_var.set("SoC Batterie: --")
                self._update_controls_state()

            elif ev_type == "reconnecting":
                self.connected = False
                self.status_var.set("Reconnecting…")
                self.log("[SSH] Reconnecting…")
                self._set_led(False)
                self.temp_label_var.set("Relay: -- °C")
                self.temp_label.configure(foreground="")
                self.soc_label_var.set("SoC Batterie: --")
                self._update_controls_state()

            elif ev_type == "reconnected":
                self._manual_disconnect_mode = False
                self.connected = True
                self.status_var.set("Connected")
                self.log("[SSH] Reconnected")
                self._set_led(True)
                self._update_controls_state()
                self.refresh_file_list()
                self.root.after(3000, self.update_monitor)

        # On reposte dans le thread principal Tk
        try:
            self.root.after(0, _handle, event_type, data)
        except Exception:
            # Si la fenêtre est déjà fermée, on ignore
            pass

    # ==================================================================
    # ENABLE / DISABLE WIDGETS
    # ==================================================================
    def _update_controls_state(self):
        # boutons qui doivent fonctionner même déconnecté
        always = [self.btn_exit]

        # boutons nécessitant connexion
        needs_conn = [
            self.btn_disconnect,
            self.btn_refresh,
            self.btn_copy_panel,
            self.btn_download,
            self.btn_upload,
            self.btn_print,
            self.btn_edit,
            self.btn_upload,
            self.btn_send_power,
            self.btn_send_cosphi,
            self.btn_restart_services,
            self.btn_reboot,
            self.btn_monitor,
        ]

        # ----- Bouton Connect -----
        if self.btn_connect:
            self.btn_connect.configure(
                state="disabled" if self.connected else "normal"
            )

        # ----- Boutons toujours actifs -----
        for b in always:
            if b:
                b.configure(state="normal")

        # ----- Boutons qui nécessitent une connexion -----
        for b in needs_conn:
            if b:
                b.configure(state="normal" if self.connected else "disabled")

        # ----- Menus -----
        try:
            state_conn = tk.NORMAL if self.connected else tk.DISABLED
            state_not_conn = tk.NORMAL if not self.connected else tk.DISABLED

            if self.file_menu:
                # Connect only when disconnected
                self.file_menu.entryconfig("Connect", state=state_not_conn)
                # Disconnect only when connected
                self.file_menu.entryconfig("Disconnect", state=state_conn)
                # Actions needing connection
                self.file_menu.entryconfig("Download", state=state_conn)
                self.file_menu.entryconfig("Print", state=state_conn)
                self.file_menu.entryconfig("Edit", state=state_conn)
                self.file_menu.entryconfig("Restart services", state=state_conn)
                self.file_menu.entryconfig("Reboot device", state=state_conn)

            state_conn = tk.NORMAL if self.connected else tk.DISABLED
            if hasattr(self, "debug_menu"):
                self.debug_menu.entryconfig("Debug logs", state=state_conn)
            if hasattr(self, "energy_menu") and self.energy_menu:
                self.energy_menu.entryconfig("Energy Manager PRO", state=state_conn)
            if hasattr(self, "terminal_menu") and self.terminal_menu:
                self.terminal_menu.entryconfig("Open Terminal", state=state_conn)

        except Exception:
            pass

        # ----- Liste de fichiers (GridCodes browser) -----
        if hasattr(self, "file_list") and self.file_list:
            if self.connected:
                self.file_list.configure(state="normal")
            else:
                self.file_list.configure(state="disabled")
                try:
                    self.file_list.selection_clear(0, "end")
                except Exception:
                    pass

        # CosPhi exclusif vs P/Q
        self._on_cosphi_toggle(update_only=True)

    # ==================================================================
    # FILE ACTION LOCK — désactive les boutons fichier pendant une action
    # ==================================================================
    def _lock_file_actions(self, reason: str = ""):
        """Désactive Edit, Download, Print, Copy tant qu'une action est en cours."""
        for b in [self.btn_edit, self.btn_download, self.btn_print, self.btn_copy_panel]:
            try:
                if b:
                    b.configure(state="disabled")
            except Exception:
                pass
        if reason:
            self.log(f"[FILES] Locked: {reason}")

    def _unlock_file_actions(self):
        """Réactive les boutons fichier si connecté."""
        if not self.connected:
            return
        for b in [self.btn_edit, self.btn_download, self.btn_print, self.btn_copy_panel]:
            try:
                if b:
                    b.configure(state="normal")
            except Exception:
                pass

    # ==================================================================
    # NAVIGATION FICHIERS — VERSION ASYNC AVEC SSHManager.execute
    # ==================================================================
    def refresh_file_list(self):
        """Refresh the remote file list."""

        if not self.connected:
            self.log("[FILES] Please connect before refreshing list.")
            return

        if getattr(self, "_refresh_running", False):
            if not getattr(self, "_refresh_pending", False):
                self.log("[FILES] Refresh already in progress, queued.")
            self._refresh_pending = True
            return

        self._refresh_running = True
        self._refresh_pending = False

        if not getattr(self, "current_path", None):
            self.current_path = self.default_path

        requested_path = self.current_path
        cmd = f'ls -Ap "{requested_path}"'
        self.log(f"[FILES] Listing {requested_path}")

        self._file_refresh_seq += 1
        req_id = self._file_refresh_seq

        def cb(res):
            def apply_ui():
                self._refresh_running = False
                rerun_needed = bool(getattr(self, "_refresh_pending", False))
                self._refresh_pending = False

                try:
                    if req_id != self._file_refresh_seq:
                        return

                    if self.current_path != requested_path:
                        rerun_needed = True
                        return

                    self.file_list.delete(0, "end")

                    if not res.get("success"):
                        msg = (
                            res.get("stderr")
                            or res.get("err")
                            or res.get("stdout")
                            or res.get("out")
                            or ""
                        ).strip()
                        self.log(f"[FILES] Error: {msg}")
                        return

                    lines = (res.get("stdout") or res.get("out") or "").splitlines()

                    if requested_path.rstrip("/") != self.default_path.rstrip("/"):
                        self.file_list.insert("end", "[.] (Parent)")

                    count = 0
                    for e in lines:
                        e = e.strip()
                        if e:
                            self.file_list.insert("end", e)
                            count += 1

                    if hasattr(self, "path_entry"):
                        self.path_entry.delete(0, "end")
                        self.path_entry.insert(0, requested_path)

                    self.log(f"[FILES] {count} entries in {requested_path}")

                except Exception as ex:
                    self.log(f"[FILES ERROR] {ex}")
                finally:
                    if rerun_needed and self.connected and not self._closing:
                        try:
                            self.root.after(0, self.refresh_file_list)
                        except Exception:
                            pass

            try:
                if not self._closing and self.root.winfo_exists():
                    self.root.after(0, apply_ui)
                else:
                    self._refresh_running = False
                    self._refresh_pending = False
            except Exception:
                self._refresh_running = False
                self._refresh_pending = False

        self.ssh_queue.execute(
            cmd,
            callback=cb,
            timeout=self.ssh_timeout,
            command_type="refresh",
            label="Refresh file list",
            silent=False,
        )

    def _go_root(self):
        if not self.connected:
            return
        self.current_path = self.default_path
        self.refresh_file_list()

    def _go_to_path(self):
        if not self.connected:
            return
        target = (
            self.path_entry.get().strip()
            if hasattr(self, "path_entry")
            else self.current_path
        )
        if not target:
            target = self.current_path

        def cb(res):
            if res["success"]:
                self.current_path = target
                self.refresh_file_list()
            else:
                self._popup_error("Path", f"Remote folder not found:\n{target}")

        self.ssh_queue.execute(
            f'test -d "{target}"',
            callback=cb,
            timeout=self.ssh_timeout,
            auto_retry=False,
            log_errors=False,
            command_type="path_check",
            silent=True,
            label="Validate remote path",
        )

    def _go_parent(self):
        if self.current_path.rstrip("/") == self.default_path.rstrip("/"):
            return
        import posixpath
        self.current_path = posixpath.dirname(self.current_path.rstrip("/")) or "/"
        self.refresh_file_list()
    
    def _remote_join(self, base: str, name: str) -> str:
        """
        Joint proprement un chemin distant (style Linux).

        Exemple:
            base = "/etc/iotecha/configs/GridCodes"
            name = "GridCodes.properties"
            -> "/etc/iotecha/configs/GridCodes/GridCodes.properties"
        """
        import posixpath

        if not base:
            base = "/"

        base = base.rstrip("/")
        name = name.lstrip("/")

        if not base:
            return "/" + name
        return posixpath.join(base, name)
   
    def on_file_double_click(self, event):
        if not self.connected:
            return

        # Anti-spam : un seul download à la fois
        if getattr(self, "_edit_in_progress", False):
            return

        sel = self.file_list.curselection()
        if not sel:
            return

        item = self.file_list.get(sel[0]).strip()
        if not item:
            return

        # Parent : ta ligne est "[.] (Parent)"
        if item.startswith("[.]"):
            self._go_parent()
            return

        # Construit le chemin complet
        full_path = self._join_remote(self.current_path, item)

        # Dossier (ls -Ap met un "/" à la fin)
        if item.endswith("/"):
            self.current_path = full_path.rstrip("/")
            self.refresh_file_list()
            return

        # Fichier → ouvre l’éditeur
        self._edit_in_progress = True
        try:
            self.open_file_editor(full_path)
        finally:
            self._edit_in_progress = False

    def _on_file_menu(self, event):
        # menu contextuel (clic droit)
        if not self.connected:
            return
        try:
            index = self.file_list.nearest(event.y)
            self.file_list.selection_clear(0, "end")
            self.file_list.selection_set(index)
        except Exception:
            return

        item = self._get_selected_item()
        if not item or item.startswith("[.]"):
            return
        is_dir = item.endswith("/")

        menu = tk.Menu(self.root, tearoff=0)
        if not is_dir:
            menu.add_command(
                label="Edit", command=lambda: self._edit_file_from_context()
            )
            menu.add_command(
                label="Download", command=lambda: self._download_from_context()
            )
            menu.add_command(
                label="Print", command=lambda: self._print_from_context()
            )
            menu.add_separator()
            menu.add_command(
                label="Copy to GridCodes.properties",
                command=lambda: self.copy_selected_to_gridcodes(),
            )
            menu.add_separator()

        menu.add_command(
            label="Delete",
            command=lambda: self.delete_selected_remote()
        )
        menu.post(event.x_root, event.y_root)

    def _get_selected_item(self):
        """
        Retourne l'élément sélectionné dans la liste (ou None si rien).
        Utilisé par :
          - _open_file_from_context
          - _edit_file_from_context
          - _download_from_context
          - _print_from_context
          - _selected_remote_file
        """
        try:
            sel = self.file_list.curselection()
        except Exception:
            return None

        if not sel:
            return None

        return self.file_list.get(sel[0])

    def _edit_file_from_context(self):
        item = self._get_selected_item()
        if not item or item.startswith("[.]"):
            return
        full_path = posixpath.join(self.current_path, item)
        self.open_file_editor(full_path)


    def _download_from_context(self):
        item = self._get_selected_item()
        if not item or item.startswith("[.]"):
            return
        full_path = posixpath.join(self.current_path, item)
        self.download_file(full_path)

    def _print_from_context(self):
        item = self._get_selected_item()
        if not item or item.startswith("[.]"):
            return
        full_path = posixpath.join(self.current_path, item)
        self.print_file(full_path)

    # ==================================================================
    # COPY / DOWNLOAD / PRINT / EDIT
    # ==================================================================
    def _selected_remote_file(self):
        item = self._get_selected_item()
        if not item or item.startswith("[.]"):
            self._popup_warning("GridCodes", "Please select a file.")
            return None
        return posixpath.join(self.current_path, item)

    def delete_selected_remote(self):
        if self._closing:
            return
        if not self.connected:
            self._popup_warning("Delete", "Please connect first.")
            return

        item = self._get_selected_item()
        if not item or item.startswith("[.]"):
            return

        remote_path = self._join_remote(self.current_path, item.rstrip("/"))
        is_dir = item.endswith("/")
        target_type = "directory" if is_dir else "file"

        confirm = messagebox.askyesno(
            "Confirm Delete",
            (
                f"Delete this {target_type}?\n\n"
                f"{remote_path}\n\n"
                "This action cannot be undone."
            ),
            parent=self.root,
        )
        if not confirm:
            return

        cmd = f'rm -rf "{remote_path}"' if is_dir else f'rm -f "{remote_path}"'
        self.log(f"[DELETE] {remote_path}")

        def cb(res):
            if self._closing:
                return
            if res.get("success"):
                self.log(f"[DELETE] Success: {remote_path}")
                try:
                    self.root.after(0, self.refresh_file_list)
                except Exception:
                    pass
                return

            err = res.get("err") or res.get("out") or "Unknown error"
            self.log(f"[DELETE ERROR] {err}")
            self._popup_error("Delete Error", err)

        self.ssh_queue.execute(
            cmd,
            callback=cb,
            timeout=self.ssh_timeout,
            command_type="delete",
            label="Delete remote item",
            silent=False,
        )

    def copy_selected_to_gridcodes(self):
        if not self.connected:
            self._popup_warning("GridCodes", "Please connect first.")
            return
        src = self._selected_remote_file()
        if not src:
            return
        dst = posixpath.join(self.default_path, self.remote_file)
        self.log(f"[GRID] Copying {src} -> {dst}")

        if src == dst:
            self.log("[GRID] Source and destination are identical; nothing to do.")
            self._popup_info(
                "GridCodes",
                "Selected file is already GridCodes.properties.\nNo copy needed.",
            )
            return

        cmd = f"cp '{src}' '{dst}'"
        def _copy_cb(res):
            self.ssh_queue.pause_monitoring = False
            if not res["success"]:
                err = (res["err"] or res["out"] or "").strip()
                self.log(f"[GRID ERROR] {err}")
                self._popup_error("GridCodes", f"Copy failed:\n{err}")
                return

            self.log("[GRID] Copy done.")
            if messagebox.askyesno(
                "Services",
                "GridCodes.properties updated.\nRestart services now?",
            ):
                self.restart_initd_services()

        self.ssh_queue.execute(
            cmd,
            callback=_copy_cb,
            timeout=self.ssh_timeout,
            critical=True,
            label="Copy GridCodes.properties",
            silent=False,
        )

    def _menu_download(self):
        self._safe_mark_user_command()
        remote = self._selected_remote_file()
        if not remote:
            return
        self.download_file(remote)


    def download_file(self, remote_path: str):
        if not self.connected:
            self._popup_warning("Download", "Please connect first.")
            return

        # Lock immédiat — avant le dialog, pour empêcher toute autre action
        self._lock_file_actions("Download in progress")

        filename = posixpath.basename(remote_path)

        # Dossier de sauvegarde : dossier du local_default_path s'il existe,
        # sinon dossier du fichier local par défaut
        save_dir = self.local_default_path
        if os.path.isfile(save_dir):
            save_dir = os.path.dirname(save_dir)
        elif not os.path.isdir(save_dir):
            save_dir = os.path.dirname(save_dir)
        if not os.path.isdir(save_dir):
            save_dir = os.path.expanduser("~")

        local = filedialog.asksaveasfilename(
            parent=self.root,
            title="Save file as",
            initialfile=filename,
            initialdir=save_dir,
            filetypes=[
                ("Properties files", "*.properties"),
                ("All files", "*.*"),
            ],
            defaultextension="",
        )
        if not local:
            # Annulé — on déverrouille immédiatement
            self._unlock_file_actions()
            return

        self.log(f"[DOWNLOAD] {remote_path} -> {local}")
        if self.btn_download:
            self.btn_download.configure(text="Downloading…")

        def worker():
            try:
                with self._scp_lock:
                    res = self.ssh.scp_get(
                        remote_path,
                        local,
                        timeout=self.ssh_timeout,
                    )
            except Exception as e:
                res = {"success": False, "out": "", "err": str(e)}

            def done():
                self._unlock_file_actions()
                if self.btn_download:
                    self.btn_download.configure(text="Download")
                if not res["success"]:
                    err = (res["err"] or res["out"] or "").strip()
                    self.log(f"[DOWNLOAD ERROR] {err}")
                    self._popup_error("Download", f"Download failed:\n{err}")
                    return
                self.log("[DOWNLOAD] Done.")
                self._popup_info("Download", f"File saved:\n{local}")

            try:
                if not self._closing and self.root.winfo_exists():
                    self.root.after(0, done)
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _menu_print(self):
        self._safe_mark_user_command()
        remote = self._selected_remote_file()
        if not remote:
            return
        self.print_file(remote)

    def print_file(self, remote_path: str):
        if not HAVE_REPORTLAB:
            self._popup_error(
                "Print",
                "reportlab is not installed.\nRun: pip install reportlab",
            )
            return
        if not self.connected:
            self._popup_warning("Print", "Please connect first.")
            return

        # Lock immédiat — avant le dialog, pour empêcher toute autre action
        self._lock_file_actions("Print in progress")

        remote_name = posixpath.basename(remote_path)
        default_pdf_name = f"{os.path.splitext(remote_name)[0]}.pdf"

        # Dossier de sauvegarde propre
        save_dir = EXPORTS_DIR if os.path.isdir(EXPORTS_DIR) else os.path.expanduser("~")

        pdf_path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Save PDF as",
            defaultextension=".pdf",
            initialfile=default_pdf_name,
            initialdir=save_dir,
            filetypes=[
                ("PDF files", "*.pdf"),
                ("All files", "*.*"),
            ],
        )
        if not pdf_path:
            # Annulé par l'utilisateur — on déverrouille immédiatement
            self._unlock_file_actions()
            return

        self.log(f"[PRINT] Downloading {remote_path} for PDF...")
        if self.btn_print:
            self.btn_print.configure(text="Printing…")

        def worker():
            with tempfile.NamedTemporaryFile(delete=False, suffix=".properties") as tmp:
                tmp_local = tmp.name
            try:
                with self._scp_lock:
                    res = self.ssh.scp_get(
                        remote_path,
                        tmp_local,
                        timeout=self.ssh_timeout,
                    )
                if not res["success"]:
                    raise RuntimeError((res["err"] or res["out"] or "").strip())

                with open(tmp_local, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()

                c = pdf_canvas.Canvas(pdf_path, pagesize=A4)
                width, height = A4
                x_margin = 40
                y = height - 40
                font_name = "Courier"
                font_size = 9
                max_text_width = width - (x_margin * 2)
                c.setFont(font_name, font_size)

                def _wrap_line_for_pdf(raw_line: str):
                    expanded = raw_line.expandtabs(4)
                    if expanded == "":
                        return [""]

                    wrapped = []
                    current = ""
                    for word in expanded.split(" "):
                        candidate = word if not current else f"{current} {word}"
                        if (
                            pdfmetrics.stringWidth(candidate, font_name, font_size)
                            <= max_text_width
                        ):
                            current = candidate
                            continue

                        if current:
                            wrapped.append(current)
                            current = ""

                        chunk = ""
                        for ch in word:
                            cnd = chunk + ch
                            if (
                                pdfmetrics.stringWidth(cnd, font_name, font_size)
                                <= max_text_width
                            ):
                                chunk = cnd
                            else:
                                if chunk:
                                    wrapped.append(chunk)
                                chunk = ch
                        current = chunk

                    wrapped.append(current)
                    return wrapped

                for line in content.splitlines():
                    wrapped_lines = _wrap_line_for_pdf(line)
                    for wrapped in wrapped_lines:
                        c.drawString(x_margin, y, wrapped)
                        y -= 12
                        if y < 40:
                            c.showPage()
                            c.setFont(font_name, font_size)
                            y = height - 40

                c.save()
                outcome = {"success": True, "err": ""}
            except Exception as e:
                outcome = {"success": False, "err": str(e)}
            finally:
                try:
                    os.remove(tmp_local)
                except Exception:
                    pass

            def done():
                self._unlock_file_actions()
                if self.btn_print:
                    self.btn_print.configure(text="Print")
                if not outcome["success"]:
                    self.log(f"[PRINT ERROR] {outcome['err']}")
                    self._popup_error("Print", outcome["err"])
                    return
                self.log(f"[PRINT] PDF saved to {pdf_path}")
                self._popup_info("Print", f"PDF saved:\n{pdf_path}")

            try:
                if not self._closing and self.root.winfo_exists():
                    self.root.after(0, done)
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()
                
    def upload_files_to_current_path(self):
        self._safe_mark_user_command()
        if not self.connected:
            self._popup_warning("Upload", "Not connected.")
            return

        local_files = filedialog.askopenfilenames(
            parent=self.root,
            title="Select file(s) to upload",
        )
        if not local_files:
            return

        target_dir = (self.current_path or self.default_path).rstrip("/")
        self.log(f"[UPLOAD] Preparing {len(local_files)} file(s) to {target_dir}")

        def worker():
            ok_count = 0
            fail_count = 0
            ensure_res = self.ssh.ensure_remote_dir(target_dir)
            if not ensure_res["success"]:
                self.log(
                    f"[UPLOAD ERROR] Remote path unavailable: {target_dir} ({ensure_res['err'] or ensure_res['out']})"
                )
                try:
                    self.root.after(
                        0,
                        lambda: self._popup_error(
                            "Upload",
                            f"Cannot prepare remote path:\n{target_dir}\n\n{(ensure_res['err'] or ensure_res['out']).strip()}",
                        ),
                    )
                except Exception:
                    pass
                return

            for local_path in local_files:
                filename = os.path.basename(local_path)
                remote_path = self._join_remote(target_dir, filename)
                attempt_success = False
                last_err = ""
                for attempt in range(1, 4):
                    self.log(f"[UPLOAD] {filename} attempt {attempt}/3...")
                    res = self.ssh.scp_put(
                        local_path,
                        remote_path,
                        timeout=self.ssh_timeout,
                    )
                    if res["success"]:
                        attempt_success = True
                        ok_count += 1
                        self.log(f"[UPLOAD] OK: {filename} -> {remote_path}")
                        break
                    last_err = (res["err"] or res["out"] or "").strip()
                    self.log(f"[UPLOAD WARN] {filename} attempt {attempt} failed: {last_err}")
                    time.sleep(0.5 * attempt)
                if not attempt_success:
                    fail_count += 1
                    self.log(f"[UPLOAD ERROR] {filename}: failed after 3 attempts ({last_err})")
                else:
                    check_cmd = f'test -f "{remote_path}" && wc -c < "{remote_path}"'
                    size_res = self.ssh.execute_sync(
                        check_cmd,
                        timeout=self.ssh_timeout,
                        auto_retry=False,
                        log_errors=False,
                    )
                    local_size = os.path.getsize(local_path)
                    remote_size = (
                        int((size_res.get("out") or "0").strip() or 0)
                        if size_res.get("success")
                        else -1
                    )
                    if (not size_res.get("success")) or remote_size != local_size:
                        fail_count += 1
                        ok_count -= 1
                        self.log(
                            f"[UPLOAD ERROR] size mismatch {filename}: local={local_size}, remote={remote_size}, err={size_res.get('err')}"
                        )

            self.log(f"[UPLOAD] Completed: {ok_count} success, {fail_count} failed.")
            try:
                self.root.after(0, self.refresh_file_list)
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()
    def _menu_edit(self):
        remote = self._selected_remote_file()
        if not remote:
            return
        self.open_file_editor(remote)

    def _ensure_edit_authorized(self) -> bool:
        password = getattr(self, "edit_password", "").strip()
        if not password:
            return True

        entered = simpledialog.askstring(
            "Edit authentication",
            "Enter the edit password to modify this file:",
            show="*",
            parent=self.root,
        )
        if entered is None:
            self.log("[AUTH] Edit authentication cancelled.")
            return False
        if entered != password:
            self.log("[AUTH] Edit authentication failed.")
            self._popup_error(
                "Edit authentication",
                "Invalid password.\nEdit access denied.",
            )
            return False

        self.log("[AUTH] Edit authentication granted.")
        return True

    def open_file_editor(self, remote_path: str):
        self._safe_mark_user_command()
        if not self.connected:
            self._popup_warning("Edit", "Not connected.")
            return
        if self._editor_window is not None:
            try:
                if self._editor_window.winfo_exists():
                    self._editor_window.deiconify()
                    self._editor_window.lift()
                    self._editor_window.focus_force()
                    already_open = self._editor_remote_path or "unknown"
                    self.log(f"[INFO] Editor already open ({already_open})")
                    self._popup_info(
                        "Editor already open",
                        f"An editor is already open:\n{already_open}\n\n"
                        "Close it first to open another file.",
                    )
                    return
            except Exception:
                # Référence stale (fenêtre détruite côté Tk/OS) -> reset et ouverture propre
                pass
            self._editor_window = None
            self._editor_remote_path = None

        if not self._ensure_edit_authorized():
            return

        self.log(f"[EDIT] Downloading {remote_path}...")
        self._lock_file_actions("Editor opening")
        if self.btn_edit:
            self.btn_edit.configure(text="Opening…")
        def worker():
            with tempfile.NamedTemporaryFile(delete=False, suffix=".conf") as tmp:
                tmp_local = tmp.name
            try:
                with self._scp_lock:
                    res = self.ssh.scp_get(
                        remote_path,
                        tmp_local,
                        timeout=self.ssh_timeout,
                    )
                if not res["success"]:
                    err = (res["err"] or res["out"] or "").strip()
                    self.log(f"[EDIT ERROR] Download failed: {err}")
                    try:
                        os.remove(tmp_local)
                    except Exception:
                        pass
                    try:
                        if not self._closing and self.root.winfo_exists():
                            self.root.after(
                                0,
                                lambda: self._popup_error("Edit", f"Download failed:\n{err}"),
                            )
                    except Exception:
                        pass
                    return
                try:
                    if not self._closing and self.root.winfo_exists():
                        self.root.after(
                            0,
                            lambda: self._show_file_editor(remote_path, tmp_local),
                        )
                except Exception:
                    try:
                        os.remove(tmp_local)
                    except Exception:
                        pass
            except Exception as e:
                err = str(e)
                self.log(f"[EDIT ERROR] {err}")
                try:
                    os.remove(tmp_local)
                except Exception:
                    pass
                try:
                    if not self._closing and self.root.winfo_exists():
                        self.root.after(
                            0,
                            lambda: self._popup_error("Edit", f"Download failed:\n{err}"),
                        )
                except Exception:
                    pass
            finally:
                try:
                    if not self._closing and self.root.winfo_exists():
                        # N'unlock que si l'éditeur n'a PAS été ouvert (échec SCP)
                        if self._editor_window is None:
                            self.root.after(0, self._unlock_file_actions)
                            self.root.after(
                                0,
                                lambda: self.btn_edit.configure(text="Edit")
                                if self.btn_edit else None,
                            )
                except Exception:
                    pass

        threading.Thread(target=worker, daemon=True).start()

    def _show_file_editor(self, remote_path: str, tmp_local: str):
        # Les boutons restent verrouillés tant que l'éditeur est ouvert
        # Ils seront réactivés par close_editor()
        if self.btn_edit:
            self.btn_edit.configure(text="Edit")
        # ----- Fenêtre d’édition -----
        win = tk.Toplevel(self.root)
        win.title(f"Edit: {remote_path}")
        self._center_toplevel(win, 960, 680, parent=self.root)
        win.minsize(820, 560)
        win.transient(self.root)   # attachée à la fenêtre principale
        win.grab_set()             # bloque la fenêtre principale
        win.focus_force()
        self._editor_window = win
        self._editor_remote_path = remote_path

        editor_frame = ttk.Frame(win)
        editor_frame.pack(fill="both", expand=True)
        editor_frame.grid_rowconfigure(0, weight=1)
        editor_frame.grid_columnconfigure(0, weight=1)

        txt = tk.Text(editor_frame, wrap="none")
        txt.grid(row=0, column=0, sticky="nsew")

        vs = ttk.Scrollbar(editor_frame, orient="vertical", command=txt.yview)
        vs.grid(row=0, column=1, sticky="ns")
        hs = ttk.Scrollbar(editor_frame, orient="horizontal", command=txt.xview)
        hs.grid(row=1, column=0, sticky="ew")
        txt.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)

        try:
            with open(tmp_local, "r", encoding="utf-8", errors="ignore") as f:
                txt.insert("1.0", f.read())
        except Exception as e:
            self.log(f"[EDIT ERROR] {e}")

        btn_bar = ttk.Frame(win)
        btn_bar.pack(fill="x", side="bottom")

        status_bar = ttk.Label(win, text="")
        status_bar.pack(fill="x", side="bottom", padx=6, pady=(0, 4))

        def clear_find_highlight():
            txt.tag_remove("find_match", "1.0", "end")
            status_bar.configure(text="")

        def close_editor():
            if getattr(self, "_find_dialog", None) and self._find_dialog.winfo_exists():
                try:
                    self._find_dialog.destroy()
                except Exception:
                    pass
                self._find_dialog = None
            try:
                if os.path.exists(tmp_local):
                    os.remove(tmp_local)
            except Exception:
                pass
            self._editor_window = None
            self._editor_remote_path = None
            # Réactiver les boutons fichier à la fermeture de l'éditeur
            self._unlock_file_actions()
            try:
                win.destroy()
            except Exception:
                pass

        # Alias de compatibilité: certains builds/appels réfèrent encore "on_close"
        on_close = close_editor
        win.protocol("WM_DELETE_WINDOW", close_editor)

        def open_find_dialog():
            if hasattr(self, "_find_dialog") and self._find_dialog and self._find_dialog.winfo_exists():
                self._find_dialog.lift()
                self._find_dialog.focus_force()
                return

            dialog = tk.Toplevel(win)
            self._find_dialog = dialog
            dialog.title("Find (Ctrl+F)")
            dialog.transient(win)
            dialog.grab_set()
            dialog.resizable(False, False)
            self._center_toplevel(dialog, 520, 170, parent=win)
            dialog.grid_columnconfigure(0, weight=0)
            dialog.grid_columnconfigure(1, weight=1)
            dialog.grid_rowconfigure(0, weight=0)
            dialog.grid_rowconfigure(1, weight=0)
            dialog.protocol("WM_DELETE_WINDOW", lambda: (setattr(self, "_find_dialog", None), dialog.destroy()))

            ttk.Label(dialog, text="Search text:").grid(row=0, column=0, padx=10, pady=(12, 8), sticky="w")
            q_var = tk.StringVar()
            q_entry = ttk.Entry(dialog, textvariable=q_var, width=42)
            q_entry.grid(row=0, column=1, padx=(0, 10), pady=(12, 8), sticky="ew")
            q_entry.focus_set()

            txt.tag_configure("find_match", background="#ffe082", foreground="#000000")
            find_state = {"ranges": [], "pos": -1}

            def _focus_match(i: int):
                if not find_state["ranges"]:
                    return
                i = i % len(find_state["ranges"])
                find_state["pos"] = i
                start, end = find_state["ranges"][i]
                txt.mark_set("insert", start)
                txt.see(start)
                txt.tag_remove("sel", "1.0", "end")
                txt.tag_add("sel", start, end)
                status_bar.configure(
                    text=f"Find: {len(find_state['ranges'])} match(es) | {i + 1}/{len(find_state['ranges'])}"
                )

            def run_find(*_):
                needle = q_var.get()
                txt.tag_remove("find_match", "1.0", "end")
                find_state["ranges"] = []
                find_state["pos"] = -1
                if not needle:
                    status_bar.configure(text="Find: empty query")
                    return

                start = "1.0"
                while True:
                    idx = txt.search(needle, start, stopindex="end", nocase=True)
                    if not idx:
                        break
                    end = f"{idx}+{len(needle)}c"
                    txt.tag_add("find_match", idx, end)
                    find_state["ranges"].append((idx, end))
                    start = end

                if find_state["ranges"]:
                    _focus_match(0)
                else:
                    status_bar.configure(text="Find: no match")

            def next_match(*_):
                if find_state["ranges"]:
                    _focus_match(find_state["pos"] + 1)

            def prev_match(*_):
                if find_state["ranges"]:
                    _focus_match(find_state["pos"] - 1)

            btns = ttk.Frame(dialog)
            btns.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 10))
            btns.grid_columnconfigure(0, weight=1)
            btns.grid_columnconfigure(1, weight=0)
            btns.grid_columnconfigure(2, weight=0)
            btns.grid_columnconfigure(3, weight=0)
            ttk.Button(btns, text="Find", command=run_find, width=10).grid(row=0, column=1, padx=(0, 6))
            ttk.Button(btns, text="Previous", command=prev_match, width=10).grid(row=0, column=2, padx=6)
            ttk.Button(btns, text="Next", command=next_match, width=10).grid(row=0, column=3, padx=(6, 0))
            q_entry.bind("<Return>", run_find)
            dialog.bind("<F3>", next_match)
            dialog.bind("<Shift-F3>", prev_match)
            dialog.bind(
                "<Escape>",
                lambda _e: (setattr(self, "_find_dialog", None), dialog.destroy()),
            )

        def _write_local_and_upload(target_remote: str, check_existing: bool = True):
            content = txt.get("1.0", "end-1c")
            content = content.replace("\r\n", "\n").replace("\r", "\n")
            try:
                with open(tmp_local, "w", encoding="utf-8", newline="\n") as f:
                    f.write(content)
            except Exception as e:
                self._popup_error("Save", f"Local save error:\n{e}")
                return

            def do_upload():
                if target_remote == remote_path:
                    self.log(f"[EDIT] Save overwrite -> {target_remote}")
                else:
                    self.log(f"[EDIT] Save As -> {target_remote}")

                def upload_worker():
                    with self._scp_lock:
                        res2 = self.ssh.scp_put(
                            tmp_local,
                            target_remote,
                            timeout=self.ssh_timeout,
                        )

                    def done():
                        if not res2["success"]:
                            err2 = (res2["err"] or res2["out"] or "").strip()
                            self.log(f"[EDIT ERROR] Save upload failed: {err2}")
                            self._popup_error("Save", f"Upload failed:\n{err2}")
                            return

                        self.log("[EDIT] Save upload done.")
                        self.refresh_file_list()

                        if (
                            posixpath.basename(target_remote) == self.remote_file
                            and messagebox.askyesno(
                                "Services",
                                "GridCodes.properties modified.\nRestart services now?",
                            )
                        ):
                            self.restart_initd_services()

                    try:
                        if not self._closing and self.root.winfo_exists():
                            self.root.after(0, done)
                    except Exception:
                        pass

                threading.Thread(target=upload_worker, daemon=True).start()

            def on_exists_check(res):
                if res.get("success"):
                    if not messagebox.askyesno(
                        "Confirm overwrite",
                        f"File already exists:\n{target_remote}\n\nOverwrite?",
                        parent=win,
                    ):
                        return
                do_upload()

            if not check_existing:
                do_upload()
                return

            self.ssh_queue.execute(
                f'test -e "{target_remote}"',
                callback=on_exists_check,
                timeout=self.ssh_timeout,
                auto_retry=False,
                log_errors=False,
                command_type="remote_exists_check",
                silent=True,
                label="Check remote file",
            )

        def save_direct():
            if not messagebox.askyesno(
                "Save",
                "Do you want to save the updates made to this file?",
                parent=win,
            ):
                return
            _write_local_and_upload(remote_path, check_existing=False)

        def save_and_upload():
            user_name = simpledialog.askstring(
                "Save As",
                "Remote filename (or full remote path):",
                initialvalue=posixpath.basename(remote_path),
                parent=win,
            )
            if user_name is None:
                return

            user_name = user_name.strip()
            if not user_name:
                self._popup_warning("Save", "Filename cannot be empty.")
                return

            if "/" in user_name:
                target_remote = user_name
            else:
                target_remote = self._join_remote(posixpath.dirname(remote_path), user_name)
            _write_local_and_upload(target_remote)

        # Compat safety: older UI variants may still reference save_as_upload
        # during local merges/conflicts. Keep alias to avoid runtime NameError.
        save_as_upload = save_and_upload

        ttk.Button(btn_bar, text="Find", command=open_find_dialog).pack(
            side="left", padx=5, pady=5
        )
        ttk.Button(btn_bar, text="Save", command=save_direct).pack(
            side="right", padx=5, pady=5
        )
        ttk.Button(btn_bar, text="Save As", command=save_as_upload).pack(
            side="right", padx=5, pady=5
        )
        ttk.Button(
            btn_bar, text="Close", command=on_close, style="Danger.TButton"
        ).pack(side="right", padx=5, pady=5)
        txt.bind("<Control-f>", lambda e: (open_find_dialog(), "break"))
        txt.bind("<Escape>", lambda e: (clear_find_highlight(), "break"))
        txt.bind("<Control-w>", lambda e: (close_editor(), "break"))

    # ==================================================================
    # ENERGY MANAGER – P/Q (ULTIMATE)
    # ==================================================================
    def send_power_command(self):
        self._safe_mark_user_command()
        if not self.connected:
            messagebox.showwarning(
                "Energy Manager", "Please connect before sending commands."
            )
            return

        # Si CosPhi mode actif, on bloque P/Q
        if self.use_cosphi_var.get():
            messagebox.showinfo(
                "Energy Manager",
                "CosPhi mode is active.\nDisable 'Use CosPhi mode' to send simple P/Q.",
            )
            return

        active = self.active_entry.get().strip()
        reactive = self.reactive_entry.get().strip()

        # Valeur par défaut = 0 si vide
        if active == "":
            active = "0"
        if reactive == "":
            reactive = "0"

        try:
            active_val = float(active)
            reactive_val = float(reactive)
        except ValueError:
            messagebox.showwarning(
                "Energy Manager", "Active and Reactive must be valid numeric values."
            )
            return

        # Plage [-11000 ; 11000]
        for label, value in (("Active (P)", active_val), ("Reactive (Q)", reactive_val)):
            if value < -11000 or value > 11000:
                messagebox.showwarning(
                    "Energy Manager",
                    f"{label} must be between -11000 and 11000.",
                )
                return

        # On envoie des entiers
        active_int = int(round(active_val))
        reactive_int = int(round(reactive_val))

        self.log(
            f"Sending setpoint: Active={active_int} W, Reactive={reactive_int} var"
        )

        remote_cmd = (
            "cd /var/aux/EnergyManager && "
            "export LD_LIBRARY_PATH=/usr/local/lib && "
            f"{ENERGY_TOOL_RESOLVE}"
            f"\"$EM_TOOL\" -S -s ocpp -a "
            f"--power {active_int} --reactive-power {reactive_int} "
            "-m CentralSetpoint"
        )

        def cb(res):
            if res["success"]:
                self.log("Power command sent successfully.")
            else:
                err = res["err"] or res["out"] or "unknown error"
                self.log(f"[ERROR] {err}")

        self.ssh_queue.execute(
            remote_cmd,
            callback=cb,
            timeout=self.ssh_timeout,
            label="Power setpoint",
            silent=False,
        )

    # ==================================================================
    # ENERGY MANAGER – CosPhi (ULTIMATE)
    # ==================================================================
    def send_cosphi_command(self):
        self._safe_mark_user_command()
        if not self.connected:
            messagebox.showwarning(
                "Energy Manager", "Please connect before sending commands."
            )
            return
        if not self.use_cosphi_var.get():
            messagebox.showinfo(
                "Energy Manager", "Enable 'Use CosPhi mode' to send this command."
            )
            return

        active = self.cosphi_active_entry.get().strip()
        cosphi = self.cosphi_entry.get().strip()

        # P : valeur par défaut 0 si vide
        if active == "":
            active = "0"

        # CosPhi : obligatoire
        if cosphi == "":
            messagebox.showwarning(
                "Energy Manager",
                "CosPhi must not be empty.\nPlease enter a value in (-1, 0) or (0, 1].",
            )
            return

        try:
            active_val = float(active)
            cosphi_val = float(cosphi)
        except ValueError:
            messagebox.showwarning(
                "Energy Manager",
                "Active and CosPhi must be valid numeric values.",
            )
            return

        # P dans la plage [-11000 ; 11000]
        if active_val < -11000 or active_val > 11000:
            messagebox.showwarning(
                "Energy Manager",
                "Active (P) must be between -11000 and 11000.",
            )
            return

        # CosPhi dans (-1, 1] et ≠ 0
        if not (-1.0 < cosphi_val <= 1.0) or abs(cosphi_val) < 1e-9:
            messagebox.showwarning(
                "Energy Manager",
                "CosPhi must be in (-1, 0) or (0, 1].\n"
                "Value 0 is not allowed.",
            )
            return

        # Calcul Q conservé pour information opérateur
        q_val = int(round(abs(active_val) * math.tan(math.acos(cosphi_val))))
        cosphi_pct = int(round(cosphi_val * 100))
        active_int = int(round(active_val))

        self.log("CosPhi calculation:")
        self.log(f"  Active = {active_val} W")
        self.log(f"  CosPhi = {cosphi_val}")
        self.log(
            f"  Reactive (Q) = |{active_val}| * tan(acos({cosphi_val})) = {q_val} var"
        )
        self.log(
            f"Sending CosPhi command: Active={active_val} W, "
            f"CosPhi={cosphi_val} ({cosphi_pct}%), Reactive={q_val} var"
        )

        grid_opt_cmd = (
            f"\"$EM_TOOL\" --grid-option "
            f"\"SetpointCosPhi_Pct={cosphi_pct}\""
        )
        setpoint_cmd = (
            f"\"$EM_TOOL\" -S -s ocpp -a "
            f"--power {active_int} -m CentralSetpoint"
        )
        remote_cmd = (
            "cd /var/aux/EnergyManager && "
            "export LD_LIBRARY_PATH=/usr/local/lib && "
            f"{ENERGY_TOOL_RESOLVE}"
            f"({grid_opt_cmd} && {setpoint_cmd}) >/dev/null 2>&1 &"
        )

        def cb(res):
            if res["success"]:
                self.log("CosPhi command sent successfully.")
            else:
                err = res["err"] or res["out"] or "unknown error"
                self.log(f"[ERROR] {err}")

        self.ssh_queue.execute(
            remote_cmd,
            callback=cb,
            timeout=self.ssh_timeout,
            label="CosPhi setpoint",
            silent=False,
        )


    def _on_cosphi_toggle(self, update_only: bool = False):
        use_cosphi = self.use_cosphi_var.get()

        # P/Q widgets
        pq_state = "disabled" if use_cosphi else "normal"
        if self.active_entry:
            self.active_entry.configure(state=pq_state)
        if self.reactive_entry:
            self.reactive_entry.configure(state=pq_state)
        if self.btn_send_power:
            self.btn_send_power.configure(state=pq_state if self.connected else "disabled")

        # CosPhi widgets
        cos_state = "normal" if use_cosphi else "disabled"
        if self.cosphi_active_entry:
            self.cosphi_active_entry.configure(state=cos_state)
        if self.cosphi_entry:
            self.cosphi_entry.configure(state=cos_state)
        if self.btn_send_cosphi:
            self.btn_send_cosphi.configure(state=cos_state if self.connected else "disabled")

    # ==================================================================
    # SERVICES / REBOOT
    # ==================================================================
    def restart_initd_services(self):
        if not self.connected:
            self._popup_warning("Services", "Please connect first.")
            return

        if not messagebox.askyesno(
            "Services",
            "Before restarting services, verify that the charging cable is unplugged.\n\nContinue?",
            parent=self.root,
        ):
            return

        services = ["S39ConfigManager", "S91energy-manager", "S95chargerapp"]

        cmd_parts = []
        for s in services:
            cmd_parts.append(f'echo "Stopping {s}"')
            cmd_parts.append(f"/etc/init.d/{s} stop || echo 'Error stopping {s}'")
            cmd_parts.append(f'echo \"Starting {s}\"')
            cmd_parts.append(f"/etc/init.d/{s} start || echo 'Error starting {s}'")
            cmd_parts.append('echo "--------------------------------"')

        cmd = " ; ".join(cmd_parts)
        self.log("[SERVICES] Restarting services.")

        def cb(res):
            if res["out"]:
                for line in res["out"].splitlines():
                    self.log(line)
            if not res["success"]:
                self.log(f"[SERVICES ERROR] {res['err'] or res['out']}")
                self._popup_error("Services", "Restart failed.")
            else:
                self.log("[SERVICES] Restart sequence finished.")
                self._popup_info("Services", "Restart sequence finished.")

        self.ssh_queue.execute(
            cmd,
            callback=cb,
            timeout=max(60, self.ssh_timeout),
            label="Restart services",
            silent=False,
        )

    def reboot_device(self):
        if not self.connected:
            self._popup_warning("Reboot", "Please connect first.")
            return

        if not messagebox.askyesno(
            "Reboot",
            "Before rebooting the device, verify that the charging cable is unplugged.\n\nContinue?",
            parent=self.root,
        ):
            return

        if not messagebox.askyesno(
            "Reboot",
            "Reboot the device now?",
            parent=self.root,
        ):
            return

        self.log("[REBOOT] Sending 'reboot' command...")

        def cb(res):
            if not res["success"]:
                self.log(f"[REBOOT ERROR] {res['err'] or res['out']}")
                self._popup_error("Reboot", "Reboot command failed.")
            else:
                self.log("[REBOOT] Command sent. Device will reboot.")
                self._popup_info("Reboot", "Reboot command sent.")

        self.ssh_queue.execute(
            "reboot",
            callback=cb,
            timeout=15,
            auto_retry=False,
            label="Reboot device",
            silent=False,
        )

    def open_energy_manager(self):
        if not self.connected:
            self._popup_warning(
                "Energy Manager",
                "Please connect before opening Energy Manager PRO.",
            )
            return
        try:
            if self._energy_win is not None:
                win = getattr(self._energy_win, "win", self._energy_win)
                if win is not None and win.winfo_exists():
                    win.deiconify()
                    win.lift()
                    win.focus_force()
                    return

            self._energy_win = energy_manager.EnergyManagerWindow(
                self.root,
                self.ssh,
                ssh_queue=self.ssh_queue,
                on_close=lambda: setattr(self, "_energy_win", None),
            )
            try:
                win = getattr(self._energy_win, "win", self._energy_win)
                win.transient(self.root)
                win.grab_set()
                win.focus_force()
                win.update_idletasks()
            except Exception:
                pass
        except Exception as e:
            self.log(f"[ERROR] Unable to open Energy Manager: {e}")
            self._popup_error(
                "Energy Manager",
                f"Unable to open Energy Manager:\n{e}",
            )

    def open_terminal(self):
        if self._closing:
            return
        if not self.connected:
            self._popup_warning("Terminal", "Please connect first.")
            return

        if hasattr(self, "_terminal_window"):
            try:
                if (
                    self._terminal_window is not None
                    and self._terminal_window.winfo_exists()
                ):
                    self._terminal_window.deiconify()
                    self._terminal_window.lift()
                    self._terminal_window.focus_force()
                    return
            except Exception:
                pass

        current_dir = self.current_path or self.default_path

        win = tk.Toplevel(self.root)
        self._terminal_window = win
        win.title("RBM SSH Terminal")
        self._center_toplevel(win, 1100, 700, parent=self.root)
        win.minsize(900, 500)

        try:
            win.transient(self.root)
            win.lift()
            win.focus_force()
        except Exception:
            pass

        frame = ttk.Frame(win, padding=5)
        frame.pack(fill="both", expand=True)
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        output = tk.Text(
            frame,
            bg="#0d1117",
            fg="#c9d1d9",
            insertbackground="white",
            font=("Consolas", 10),
            wrap="word",
            state="disabled",
        )
        output.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=output.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        output.configure(yscrollcommand=scrollbar.set)

        entry = ttk.Entry(frame, font=("Consolas", 10))
        entry.grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="ew",
            padx=5,
            pady=5,
        )

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=2, column=0, columnspan=2, sticky="ew")

        def append(text):
            try:
                output.configure(state="normal")
                output.insert("end", text)
                output.see("end")
                output.configure(state="disabled")
            except Exception:
                pass

        def clear():
            output.configure(state="normal")
            output.delete("1.0", "end")
            output.configure(state="disabled")

        ttk.Button(btn_frame, text="Clear", command=clear).pack(
            side="left", padx=5, pady=5
        )
        ttk.Button(
            btn_frame,
            text="Close",
            style="Danger.TButton",
            command=win.destroy,
        ).pack(side="right", padx=5, pady=5)

        history = []
        history_index = [-1]

        def show_help():
            append(
                "\n"
                "Available commands:\n\n"
                "Navigation:\n"
                "  ls\n"
                "  cd <dir>\n"
                "  pwd\n\n"
                "Files:\n"
                "  cat <file>\n"
                "  cp <src> <dst>\n"
                "  mv <src> <dst>\n"
                "  rm <file>\n\n"
                "Scripts:\n"
                "  python3 script.py\n"
                "  sh script.sh\n\n"
                "Logs:\n"
                "  grep\n"
                "  tail\n"
                "  journalctl\n\n"
                "Built-in:\n"
                "  clear\n"
                "  help\n\n"
                "Unsupported interactive commands:\n"
                "  vim, nano, top, htop\n\n"
            )

        def run_command(cmd):
            nonlocal current_dir

            if cmd.startswith("cd"):
                parts = cmd.split(maxsplit=1)
                if len(parts) == 1:
                    new_dir = self.default_path
                else:
                    new_dir = parts[1].strip()

                if not new_dir.startswith("/"):
                    new_dir = current_dir.rstrip("/") + "/" + new_dir

                test_cmd = f'test -d "{new_dir}"'

                def cb(res):
                    def _ui():
                        nonlocal current_dir
                        if res["success"]:
                            current_dir = new_dir
                            append(f"[DIR] {current_dir}\n")
                        else:
                            append("[ERROR] Directory not found\n")

                    try:
                        if not self._closing and self.root.winfo_exists():
                            self.root.after(0, _ui)
                    except Exception:
                        pass

                self.ssh_queue.execute(
                    test_cmd,
                    callback=cb,
                    timeout=self.ssh_timeout,
                    auto_retry=False,
                    log_errors=False,
                    command_type="terminal_cd",
                    silent=True,
                    label="Terminal cd",
                )
                return

            if cmd.startswith("rm "):
                cmd = "rm -f " + cmd[3:]
            elif cmd.startswith("mv "):
                cmd = "mv -f " + cmd[3:]
            elif cmd.startswith("cp "):
                cmd = "cp -f " + cmd[3:]

            interactive_cmds = ["vim", "vi", "nano", "top", "htop", "less", "more"]
            base_cmd = cmd.split()[0] if cmd.split() else ""
            if base_cmd in interactive_cmds:
                append(
                    f"[INFO] '{base_cmd}' is an interactive command and cannot run "
                    f"in this terminal.\n"
                    f"       Use a system terminal for interactive editors or tools.\n"
                )
                return

            full_cmd = f'cd "{current_dir}" && {cmd}'
            append(f"\n{current_dir} $ {cmd}\n")

            def cb(res):
                try:
                    stdout = (res.get("out") or "").strip()
                    stderr = (res.get("err") or "").strip()
                    success = res.get("success", False)

                    def _ui():
                        if stdout:
                            append(stdout + "\n")
                        if stderr:
                            append("[ERROR] " + stderr + "\n")
                        if success and not stdout and not stderr:
                            append("[OK]\n")

                    try:
                        if not self._closing and self.root.winfo_exists():
                            self.root.after(0, _ui)
                    except Exception:
                        pass
                except Exception as e:
                    try:
                        self.root.after(0, lambda: append(f"[ERROR] {e}\n"))
                    except Exception:
                        pass

            self.ssh_queue.execute(
                full_cmd,
                callback=cb,
                timeout=self.ssh_timeout,
                auto_retry=False,
                log_errors=False,
                command_type="terminal_cmd",
                silent=False,
                label=f"Terminal: {cmd[:60]}",
            )

        def on_enter(event=None):
            cmd = entry.get().strip()
            if not cmd:
                return
            if cmd == "clear":
                clear()
                entry.delete(0, "end")
                return
            if cmd == "help":
                show_help()
                entry.delete(0, "end")
                return

            history.append(cmd)
            history_index[0] = len(history)
            run_command(cmd)
            entry.delete(0, "end")

        def history_up(event):
            if history:
                history_index[0] = max(0, history_index[0] - 1)
                entry.delete(0, "end")
                entry.insert(0, history[history_index[0]])

        def history_down(event):
            if history:
                history_index[0] = min(len(history), history_index[0] + 1)
                entry.delete(0, "end")
                if history_index[0] < len(history):
                    entry.insert(0, history[history_index[0]])

        entry.bind("<Return>", on_enter)
        entry.bind("<Up>", history_up)
        entry.bind("<Down>", history_down)
        entry.focus_force()

        append(
            "RBM SSH Terminal ready.\n"
            f"Connected to {self.host}\n"
            "Type 'help' for commands.\n"
        )

        def _on_close():
            try:
                self._close_terminal_window = None
                self._terminal_window = None
            except Exception:
                pass
            try:
                win.destroy()
            except Exception:
                pass

        self._close_terminal_window = _on_close
        win.protocol("WM_DELETE_WINDOW", _on_close)

    
    def open_network_config(self):
        """
        Ouvre la fenêtre Network config (network_config.py) en éditant CONFIG_PATH,
        puis recharge self.config / self.host / self.user / self.port après Save.
        """
        def on_saved():
            try:
                previous_ssh = (self.host, self.user, self.password, self.port)
                self.config.read(CONFIG_PATH, encoding="utf-8")
                ssh_cfg = self.config["SSH"]
                paths_cfg = self.config["PATHS"]
                security_cfg = self.config["SECURITY"]

                self.host = ssh_cfg.get("host", "")
                self.user = ssh_cfg.get("username", "")
                self.password = ssh_cfg.get("password", "")
                self.port = int(ssh_cfg.get("port", "22"))
                self.default_path = paths_cfg.get(
                    "remote_path", "/etc/iotecha/configs/GridCodes"
                )
                self.remote_file = paths_cfg.get("remote_file", "GridCodes.properties")
                self.local_default_path = paths_cfg.get(
                    "local_path", os.path.join(EXPORTS_DIR, "GridCodes.properties")
                )
                local_dir = (
                    os.path.dirname(self.local_default_path)
                    or self.local_default_path
                )
                if not self.local_default_path or not os.path.exists(local_dir):
                    self.local_default_path = os.path.join(
                        os.path.expanduser("~"),
                        "Documents",
                        "remote_borne_manager",
                        self.remote_file,
                    )
                    os.makedirs(os.path.dirname(self.local_default_path), exist_ok=True)
                self.edit_password = security_cfg.get("edit_password", "").strip()
                self.current_path = self.default_path

                # Mise à jour des labels
                if self.ip_label is not None:
                    self.ip_label.configure(text=f"IP: {self.host or '-'}")
                if self.user_label is not None:
                    self.user_label.configure(text=f"User: {self.user or '-'}")
                if self.path_entry is not None:
                    self.path_entry.delete(0, "end")
                    self.path_entry.insert(0, self.current_path)

                ssh_changed = previous_ssh != (
                    self.host,
                    self.user,
                    self.password,
                    self.port,
                )

                if ssh_changed:
                    self.log("[NETWORK] SSH target changed, restarting application.")
                    self._popup_info(
                        "Network",
                        "Network configuration updated.\nThe application will restart now."
                    )
                    self.root.after(150, self._restart_application)
                    return

                if self.connected:
                    self.refresh_file_list()

                self.log("[NETWORK] config.ini reloaded.")
                self._popup_info(
                    "Network",
                    "Network configuration updated successfully."
                )
            except Exception as e:
                self.log(f"[NETWORK ERROR] {e}")
                self._popup_error(
                    "Network",
                    f"Failed to reload config.ini:\n{e}",
                )

        # Appel explicite avec CONFIG_PATH + callback
        open_network_config(self.root, CONFIG_PATH, on_saved)

    def _restart_application(self):
        try:
            if getattr(sys, "frozen", False):
                cmd = [sys.executable]
                cwd = os.path.dirname(sys.executable)
            else:
                cmd = [sys.executable, os.path.abspath(__file__)]
                cwd = os.path.dirname(os.path.abspath(__file__))
            subprocess.Popen(cmd, cwd=cwd)
        except Exception as e:
            self.log(f"[RESTART ERROR] {e}")
            self._popup_error(
                "Restart",
                f"Unable to restart application automatically:\n{e}",
            )
            return

        self.on_exit()

       
    def open_debug_logs(self):
        """Ouvre la fenÃªtre Debug Logs seulement si SSH connectÃ©."""
        if not self.connected:
            self._popup_warning(
                "Debug logs",
                "Please connect before opening Debug logs.",
            )
            return

        try:
            if self._debug_logs_window is not None:
                debug_win = getattr(self._debug_logs_window, "window", None)
                if debug_win is not None and debug_win.winfo_exists():
                    debug_win.deiconify()
                    debug_win.lift()
                    debug_win.focus_force()
                    return
            self._debug_logs_window = None

            self._debug_logs_window = debug_logs.open_debug_logs_window(
                self.root,
                self.ssh.host,
                self.ssh.user,
                self.ssh.password,
                self.ssh.port
            )
        except Exception as e:
            self._debug_logs_window = None
            self._popup_error("Debug logs", f"Unable to open the Debug logs window:\n{e}")

    def _show_about(self):
        self._popup_info(
            "About",
            "Remote Borne Control Interface (RBM)\n"
            "Author: Nabil RAISSI\n"
            "Backend: plink.exe / pscp.exe\n"
            "SSH queue, SCP protection and integrated terminal included.",
        )

    # ==================================================================
    # EXIT
    # ==================================================================
    def on_exit(self):
        self._closing = True
        self._alive_stop = True
        self._monitor_stop = True
        try:
            self._close_aux_windows("application exit", force=True)
        except Exception:
            pass
        try:
            self.ssh_queue.stop()
        except Exception:
            pass
        try:
            self.ssh.close()
        except Exception:
            pass
        self.root.after(150, self.root.destroy)

    # --------------------------------------------------------------
    # Helpers pour popups MODALES et toujours au premier plan
    # --------------------------------------------------------------
    def _popup_info(self, title: str, message: str, parent=None):
        # parent = fenêtre parente (Toplevel) si fournie, sinon root
        win = parent or self.root
        win.lift()
        win.attributes("-topmost", True)
        try:
            messagebox.showinfo(title, message, parent=win)
        finally:
            win.attributes("-topmost", False)

    def _popup_warning(self, title: str, message: str, parent=None):
        win = parent or self.root
        win.lift()
        win.attributes("-topmost", True)
        try:
            messagebox.showwarning(title, message, parent=win)
        finally:
            win.attributes("-topmost", False)

    def _popup_error(self, title: str, message: str, parent=None):
        win = parent or self.root
        win.lift()
        win.attributes("-topmost", True)
        try:
            messagebox.showerror(title, message, parent=win)
        finally:
            win.attributes("-topmost", False)

# ----------------------------------------------------------------------
# ENTRY POINT
# ----------------------------------------------------------------------
def start_app():
    cfg = load_config()
    app = RemoteBorneApp(cfg)
    try:
        app.root.mainloop()
    except KeyboardInterrupt:
        print("[INFO] KeyboardInterrupt received, closing application...")
        try:
            app.on_exit()
        except Exception:
            try:
                app.root.destroy()
            except Exception:
                pass


if __name__ == "__main__":
    print("[INFO] Starting RemoteBorne Manager...")
    start_app()
