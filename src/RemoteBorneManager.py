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

import math
import time
import tempfile
import threading
import configparser
import posixpath
import re
import textwrap

import tkinter as tk
from tkinter import messagebox, filedialog, simpledialog

import ttkbootstrap as ttk
from ttkbootstrap.constants import *

try:
    from .utils_ui import center_window
except ImportError:
    from utils_ui import center_window

# ----------------------------------------------------------------------
# Imports projet (compat mode script + mode package "src")
# ----------------------------------------------------------------------
try:
    from .ssh_manager import SSHManager
    from .network_config import open_network_config
    from .open_help import open_help
    from . import energy_manager
    from . import debug_logs
except ImportError:
    try:
        from ssh_manager import SSHManager
        from network_config import open_network_config
        from open_help import open_help
        import energy_manager
        import debug_logs
    except ImportError:
        from src.ssh_manager import SSHManager
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
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            cfg.write(f)

        print(f"[CONFIG] Fichier créé : {CONFIG_PATH}")
    else:
        # Fichier déjà présent : on le lit
        cfg.read(CONFIG_PATH, encoding="utf-8")
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
        elif "timeout" not in cfg["SSH"]:
            cfg["SSH"]["timeout"] = "30"
        if "retry_base_delay" not in cfg["SSH"]:
            cfg["SSH"]["retry_base_delay"] = "2"
        if "retry_max_delay" not in cfg["SSH"]:
            cfg["SSH"]["retry_max_delay"] = "10"
        if "alive_interval" not in cfg["SSH"]:
            cfg["SSH"]["alive_interval"] = "10"
        if "PATHS" not in cfg:
            cfg["PATHS"] = {
                "remote_path": "/etc/iotecha/configs/GridCodes",
                "remote_file": "GridCodes.properties",
                "local_path": os.path.join(EXPORTS_DIR, "GridCodes.properties"),
            }

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

        self.current_path = self.default_path

        # ---------- ETAT ----------
        self.connected = False
        self._alive_stop = False
        self._manual_disconnect_mode = False
        self.current_theme = "flatly"

        # ---------- ROOT / STYLE ----------
        # Fenêtre ttkbootstrap, thème "flatly" comme V7
        self.root = ttk.Window(themename=self.current_theme)
        self.root.title("Remote Borne Control Interface - RNA")
        self._set_app_icon()

        try:
            # plein écran si possible
            self.root.state("zoomed")
        except Exception:
            try:
                self.root.attributes("-zoomed", True)
            except Exception:
                self.root.geometry("1200x800")

        self.root.minsize(1000, 700)

        # style ttkbootstrap
        self.style = self.root.style


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

        self.active_entry = None
        self.reactive_entry = None
        self.cosphi_active_entry = None
        self.cosphi_entry = None
        
        self.log_text = None 
        self.file_list = None
        self.path_entry = None
        self._editor_window = None
        self._editor_remote_path = None
        # --- ADDED ---
        self.temp_label_var = tk.StringVar(value="Temp: --")
        self.soc_label_var = tk.StringVar(value="SoC Batterie: --")
        self._monitor_stop = False
        self._monitor_thread_started = False
        self._temp_update_inflight = False
        self._soc_update_inflight = False

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

        # On démarre le thread interne de SSHManager
        self.ssh.start()



        # ---------- UI ----------
        self._build_menu()
        self._build_layout()
        self._set_led(False)
        self._update_controls_state()


        self.log(f"[INFO] RemoteBorne version: {APP_VERSION} ({os.path.basename(__file__)})")
        self.log("[INFO] Application started. Waiting for SSH events...")
        self.log(
            f"[SSH] Timeout={self.ssh_timeout}s | retry_base={self.retry_base_delay}s | retry_max={self.retry_max_delay}s | alive={self.alive_interval}s"
        )
        self.root.after(200, self.force_reconnect)

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
        terminal_menu = tk.Menu(menubar, tearoff=0)
        terminal_menu.add_command(label="Open Terminal", command=self.open_terminal)
        menubar.add_cascade(label="Terminal", menu=terminal_menu)
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
        main.grid_columnconfigure(0, weight=3)
        main.grid_columnconfigure(1, weight=2)
        main.grid_rowconfigure(1, weight=1)
        main.grid_rowconfigure(2, weight=1)
        main.grid_rowconfigure(3, weight=1)

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
            text="RNA",
            font=("Segoe UI", 8, "italic"),
            anchor="center",
        ).pack(fill="x")

        right_logo_fr = ttk.Frame(header)
        right_logo_fr.grid(row=0, column=2, sticky="e")
        if self.logo_right:
            ttk.Label(right_logo_fr, image=self.logo_right).pack(anchor="e")

        # ----- LEFT : FILE BROWSER -----
        left = ttk.Labelframe(
            main, text=f"GridCodes browser ({self.default_path})", padding=5
        )
        left.grid(row=1, column=0, rowspan=2, sticky="nsew", padx=(10, 5), pady=5)
        left.grid_rowconfigure(1, weight=1)

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
        file_actions = ttk.Labelframe(right_top, text="GridCodes", padding=5)
        file_actions.grid(row=2, column=0, sticky="ew", pady=(4, 0))
        file_actions.grid_columnconfigure(0, weight=1)
        file_actions.grid_columnconfigure(1, weight=1)

        self.btn_refresh = ttk.Button(
            file_actions, text="Refresh", command=self.refresh_file_list
        )
        self.btn_refresh.grid(row=0, column=0, padx=2, pady=2, sticky="ew")

        self.btn_copy_panel = ttk.Button(
            file_actions,
            text="Copy to GridCodes.properties",
            command=self.copy_selected_to_gridcodes,
        )
        self.btn_copy_panel.grid(row=0, column=1, padx=2, pady=2, sticky="ew")

        self.btn_download = ttk.Button(
            file_actions, text="Download", command=self._menu_download
        )
        self.btn_download.grid(row=1, column=0, padx=2, pady=2, sticky="ew")

        self.btn_print = ttk.Button(
            file_actions, text="Print", command=self._menu_print
        )
        self.btn_print.grid(row=1, column=1, padx=2, pady=2, sticky="ew")

        self.btn_upload = ttk.Button(
            file_actions, text="Upload", command=self.upload_files_to_current_path
        )
        self.btn_upload.grid(row=2, column=0, padx=2, pady=2, sticky="ew")

        self.btn_edit = ttk.Button(
            file_actions, text="Edit", command=self._menu_edit
        )
        self.btn_edit.grid(row=2, column=1, padx=2, pady=2, sticky="ew")

        # ----- RIGHT MIDDLE : ENERGY MANAGER -----
        em_frame = ttk.Labelframe(main, text="Energy Manager Controls", padding=5)
        em_frame.grid(row=2, column=1, sticky="nsew", padx=(5, 10), pady=(2, 5))
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
            row=2, column=0, columnspan=2, pady=(4, 0), sticky="ew"
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
            row=3, column=0, columnspan=2, pady=(4, 0), sticky="ew"
        )

        # Services
        srv_frame = ttk.Labelframe(em_frame, text="Services", padding=5)
        srv_frame.grid(row=1, column=0, sticky="nsew", padx=(0, 4), pady=(4, 0))
        srv_frame.grid_columnconfigure(0, weight=1)
        srv_frame.grid_columnconfigure(1, weight=1)

        self.btn_restart_services = ttk.Button(
            srv_frame,
            text="Restart services",
            style="Success.TButton",
            command=self.restart_initd_services,
        )
        self.btn_restart_services.grid(
            row=0, column=0, padx=2, pady=2, sticky="ew"
        )

        self.btn_reboot = ttk.Button(
            srv_frame,
            text="Reboot device",
            style="Danger.TButton",
            command=self.reboot_device,
        )
        self.btn_reboot.grid(row=0, column=1, padx=2, pady=2, sticky="ew")

        # --- ADDED ---
        derate_frame = ttk.Labelframe(
            em_frame, text="Temperature / Derating", padding=5
        )
        derate_frame.grid(
            row=1, column=1, sticky="nsew", padx=(4, 0), pady=(4, 0)
        )
        derate_frame.grid_columnconfigure(0, weight=1)
        derate_frame.grid_columnconfigure(1, weight=1)

        self.temp_label = ttk.Label(derate_frame, textvariable=self.temp_label_var)
        self.temp_label.grid(row=0, column=0, sticky="w", padx=2, pady=2)
        self.soc_label = ttk.Label(derate_frame, textvariable=self.soc_label_var)
        self.soc_label.grid(row=0, column=1, sticky="w", padx=2, pady=2)

        # ----- BOTTOM : LOGS -----
        log_frame = ttk.Labelframe(main, text="Logs", padding=5)
        log_frame.grid(
            row=4, column=0, columnspan=2, sticky="nsew", padx=10, pady=(0, 10)
        )
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
            while not self._alive_stop:
                time.sleep(self.alive_interval)
                # Si l’app est fermée, on sort
                if not hasattr(self, "ssh"):
                    break
                # Si pas connecté -> on tente une reconnexion périodique
                if not self.ssh.connected:
                    heartbeat_failures = 0
                    if self._manual_disconnect_mode:
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
                self.ssh.execute(
                    "echo alive",
                    callback=cb,
                    timeout=self.ssh_timeout,
                    auto_retry=False,
                    log_errors=False,
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
                if self.ssh.connected and not self._manual_disconnect_mode:
                    self.update_temperature()
                    self.update_soc()
                time.sleep(5)

        threading.Thread(target=worker, daemon=True).start()

    # --- ADDED ---
    def update_temperature(self):
        if self._temp_update_inflight:
            return
        self._temp_update_inflight = True
        cmd = "tail -n 20 /var/aux/ChargerApp/derate.log"

        def cb(res):
            try:
                if not res.get("success"):
                    return
                output = (res.get("stdout") or "") + "\n" + (res.get("stderr") or "")
                match = re.search(r"Temp\s*[:=]\s*(-?\d+)", output, flags=re.IGNORECASE)
                if not match:
                    return
                temp = int(match.group(1))

                def apply_ui():
                    self.temp_label_var.set(f"Temp: {temp}")
                    self.temp_label.configure(foreground=("red" if temp > 80 else "green"))

                try:
                    self.root.after(0, apply_ui)
                except Exception:
                    pass
            finally:
                self._temp_update_inflight = False

        self.ssh.execute(
            cmd,
            callback=cb,
            timeout=self.ssh_timeout,
            auto_retry=False,
            log_errors=False,
        )

    # --- ADDED ---
    def update_soc(self):
        if self._soc_update_inflight:
            return
        self._soc_update_inflight = True
        cmd = "tail -n 50 /var/aux/ChargerApp/ChargerApp.log"

        def cb(res):
            try:
                if not res.get("success"):
                    return
                output = (res.get("stdout") or "") + "\n" + (res.get("stderr") or "")
                matches = re.findall(r"evPresentSoc\s*[:=]\s*(\d+)", output, flags=re.IGNORECASE)
                if not matches:
                    return

                def apply_ui():
                    self.soc_label_var.set(f"SoC Batterie: {matches[-1]}")

                try:
                    self.root.after(0, apply_ui)
                except Exception:
                    pass
            finally:
                self._soc_update_inflight = False

        self.ssh.execute(
            cmd,
            callback=cb,
            timeout=self.ssh_timeout,
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
                # init navigateur fichiers
                self.current_path = self.default_path
                self.refresh_file_list()
                # démarre le heartbeat
                self._start_alive_monitor()
                self._start_monitor()

            elif ev_type == "disconnected":
                self.connected = False
                self.status_var.set("Disconnected")
                self.log("[SSH] Disconnected")
                self._set_led(False)
                self._clear_file_list_ui()
                self._update_controls_state()

            elif ev_type == "reconnecting":
                self.connected = False
                self.status_var.set("Reconnecting…")
                self.log("[SSH] Reconnecting…")
                self._set_led(False)
                self._update_controls_state()

            elif ev_type == "reconnected":
                self._manual_disconnect_mode = False
                self.connected = True
                self.status_var.set("Connected")
                self.log("[SSH] Reconnected")
                self._set_led(True)
                self._update_controls_state()
                self.refresh_file_list()

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
            self.btn_send_power,
            self.btn_send_cosphi,
            self.btn_restart_services,
            self.btn_reboot,
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
                self.file_menu.entryconfig("Reboot", state=state_conn)

            state_conn = tk.NORMAL if self.connected else tk.DISABLED
            if hasattr(self, "debug_menu"):
                self.debug_menu.entryconfig("Debug logs", state=state_conn)
            if hasattr(self, "energy_menu") and self.energy_menu:
                self.energy_menu.entryconfig("Energy Manager PRO", state=state_conn)

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
    # NAVIGATION FICHIERS — VERSION ASYNC AVEC SSHManager.execute
    # ==================================================================
       # ==================================================================
    # NAVIGATION FICHIERS — VERSION ASYNC AVEC SSHManager.execute
    # ==================================================================
    def refresh_file_list(self):
        """Rafraîchit la liste distante (ls -Ap) de façon SYNCHRONE."""
        if not self.connected:
            self.log("[FILES] Please connect before refreshing list.")
            return

        # Sécurité : chemin courant
        if not getattr(self, "current_path", None):
            self.current_path = self.default_path

        # On quote le path pour éviter les soucis d'espaces, etc.
        cmd = f'ls -Ap "{self.current_path}"'
        self.log(f"[FILES] Listing {self.current_path}")

        # Appel direct au backend plink (synchrone)
        try:
            rc, out, err = self.ssh.backend.exec(cmd, timeout=self.ssh.timeout)
        except Exception as e:
            self.log(f"[FILES] Exception during ls: {e}")
            self._popup_error("Files", f"Error listing directory:\n{e}")
            return

        # On vide la liste avant de remplir
        self.file_list.delete(0, "end")

        if rc != 0:
            msg = (err or out or "").strip()
            self.log(f"[FILES] Error: {msg}")
            self._popup_error("Files", f"Error listing directory:\n{msg}")
            return

        lines = out.splitlines()

        # Ajout de l’entrée [.] (Parent) sauf si on est au path par défaut
        if self.current_path.rstrip("/") != self.default_path.rstrip("/"):
            self.file_list.insert("end", "[.] (Parent)")

        # Ajout des fichiers / dossiers
        for e in lines:
            e = e.strip()
            if e:
                self.file_list.insert("end", e)

        # Mise à jour du champ Path si présent
        if hasattr(self, "path_entry"):
            self.path_entry.delete(0, "end")
            self.path_entry.insert(0, self.current_path)

        self.log(f"[FILES] {len(lines)} entries in {self.current_path}")

    def _go_root(self):
        if not self.connected:
            return
        self.current_path = self.default_path
        self.refresh_file_list()

    def _go_to_path(self):
        if not self.connected:
            return
        target = self.path_entry.get().strip() if hasattr(self, "path_entry") else self.current_path
        if not target:
            target = self.current_path

        def cb(res):
            if res["success"]:
                self.current_path = target
                self.refresh_file_list()
            else:
                self._popup_error("Path", f"Remote folder not found:\n{target}")

        self.ssh.execute(f'test -d "{target}"', callback=cb)

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

        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(
            label="Edit", command=lambda: self._edit_file_from_context()
        )
        menu.add_command(
            label="Download", command=lambda: self._download_from_context()
        )
        menu.add_command(
            label="Print", command=lambda: self._print_from_context()
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

    def copy_selected_to_gridcodes(self):
        if not self.connected:
            self._popup_warning("GridCodes", "Not connected.")
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

        self.ssh.execute(cmd, callback=_copy_cb)



    def _menu_download(self):
        remote = self._selected_remote_file()
        if not remote:
            return
        self.download_file(remote)

    def download_file(self, remote_path: str):
        if not self.connected:
            self._popup_warning("Download", "Not connected.")
            return

        filename = posixpath.basename(remote_path)
        local = filedialog.asksaveasfilename(
            title="Save file as",
            defaultextension="",
            initialfile=filename,
            initialdir=os.path.dirname(self.local_default_path),
        )
        if not local:
            return

        self.log(f"[DOWNLOAD] {remote_path} -> {local}")

        res = self.ssh.scp_get(remote_path, local)
        if not res["success"]:
            err = (res["err"] or res["out"] or "").strip()
            self.log(f"[DOWNLOAD ERROR] {err}")
            self._popup_error("Download", f"Download failed:\n{err}")
            return

        self.log("[DOWNLOAD] Done.")
        self._popup_info("Download", f"File saved:\n{local}")


    def _menu_print(self):
        remote = self._selected_remote_file()
        if not remote:
            return
        self.print_file(remote)

    def upload_files_to_current_path(self):
        if not self.connected:
            self._popup_warning("Upload", "Not connected.")
            return

        local_files = filedialog.askopenfilenames(
            title="Select file(s) to upload",
            parent=self.root,
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
                    res = self.ssh.scp_put(local_path, remote_path)
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
                    rc, out, err = self.ssh.backend.exec(check_cmd, timeout=self.ssh_timeout)
                    local_size = os.path.getsize(local_path)
                    remote_size = int((out or "0").strip() or 0) if rc == 0 else -1
                    if rc != 0 or remote_size != local_size:
                        fail_count += 1
                        ok_count -= 1
                        self.log(
                            f"[UPLOAD ERROR] size mismatch {filename}: local={local_size}, remote={remote_size}, err={err}"
                        )

            self.log(f"[UPLOAD] Completed: {ok_count} success, {fail_count} failed.")
            try:
                self.root.after(0, self.refresh_file_list)
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def print_file(self, remote_path: str):
        if not HAVE_REPORTLAB:
            self._popup_error(
                "Print",
                "reportlab is not installed.\nRun: pip install reportlab",
            )
            return
        if not self.connected:
            self._popup_warning("Print", "Not connected.")
            return

        self.log(f"[PRINT] Downloading {remote_path} for PDF...")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".properties") as tmp:
            tmp_local = tmp.name

        res = self.ssh.scp_get(remote_path, tmp_local)
        if not res["success"]:
            err = (res["err"] or res["out"] or "").strip()
            self.log(f"[PRINT ERROR] {err}")
            self._popup_error("Print", f"Download failed:\n{err}")
            try:
                os.remove(tmp_local)
            except Exception:
                pass
            return

        remote_name = posixpath.basename(remote_path)
        default_pdf_name = f"{os.path.splitext(remote_name)[0]}.pdf"

        pdf_path = filedialog.asksaveasfilename(
            title="Save PDF as",
            defaultextension=".pdf",
            initialfile=default_pdf_name,
            initialdir=EXPORTS_DIR,
        )
        if not pdf_path:
            try:
                os.remove(tmp_local)
            except Exception:
                pass
            return

        try:
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

                    # mot très long sans espace: coupe au caractère
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
            self.log(f"[PRINT] PDF saved to {pdf_path}")
            self._popup_info("Print", f"PDF saved:\n{pdf_path}")
        except Exception as e:
            self.log(f"[PRINT ERROR] {e}")
            self._popup_error("Print", str(e))
        finally:
            try:
                os.remove(tmp_local)
            except Exception:
                pass

    def _menu_edit(self):
        remote = self._selected_remote_file()
        if not remote:
            return
        self.open_file_editor(remote)

    def open_file_editor(self, remote_path: str):
        # 🔒 bloque multi ouverture
        if getattr(self, "editor_open", False):
            self.log("[INFO] Editor already open")
            return

        if not self.connected:
            self._popup_warning("Edit", "Not connected.")
            return
        if self._editor_window is not None:
            try:
                if self._editor_window.winfo_exists():
                    self._editor_window.deiconify()
                    self._editor_window.lift()
                    self._editor_window.focus_force()
                    if self._editor_remote_path:
                        self.log(f"[INFO] Editor already open ({self._editor_remote_path})")
                    else:
                        self.log("[INFO] Editor already open")
                    return
            except Exception:
                # Référence stale (fenêtre détruite côté Tk/OS) -> reset et ouverture propre
                pass
            self._editor_window = None
            self._editor_remote_path = None

        self.log(f"[EDIT] Downloading {remote_path}...")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".conf") as tmp:
            tmp_local = tmp.name

        res = self.ssh.scp_get(remote_path, tmp_local)
        if not res["success"]:
            err = (res["err"] or res["out"] or "").strip()
            self.log(f"[EDIT ERROR] Download failed: {err}")
            self._popup_error("Edit", f"Download failed:\n{err}")

            try:
                os.remove(tmp_local)
            except Exception:
                pass

            self.editor_open = False
            return

        # ----- Fenêtre d’édition -----
        win = tk.Toplevel(self.root)
        win.title(f"Edit: {remote_path}")
        self._center_toplevel(win, 960, 680, parent=self.root)
        win.minsize(820, 560)
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
            self._center_toplevel(dialog, 420, 120, parent=win)
            dialog.protocol("WM_DELETE_WINDOW", lambda: (setattr(self, "_find_dialog", None), dialog.destroy()))

            ttk.Label(dialog, text="Search text:").grid(row=0, column=0, padx=8, pady=8, sticky="w")
            q_var = tk.StringVar()
            q_entry = ttk.Entry(dialog, textvariable=q_var, width=35)
            q_entry.grid(row=0, column=1, padx=8, pady=8)
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
            btns.grid(row=1, column=0, columnspan=2, sticky="e", padx=8, pady=(0, 8))
            ttk.Button(btns, text="Previous", command=prev_match).pack(side="right", padx=4)
            ttk.Button(btns, text="Next", command=next_match).pack(side="right", padx=4)
            ttk.Button(btns, text="Find", command=run_find).pack(side="right", padx=4)
            q_entry.bind("<Return>", run_find)
            dialog.bind("<F3>", next_match)
            dialog.bind("<Shift-F3>", prev_match)
            dialog.bind(
                "<Escape>",
                lambda _e: (setattr(self, "_find_dialog", None), dialog.destroy()),
            )

        def save_and_upload():
            content = txt.get("1.0", "end-1c")
            # Normalise explicitement en LF pour éviter les ^M sous vi/MobaXterm
            content = content.replace("\r\n", "\n").replace("\r", "\n")
            try:
                with open(tmp_local, "w", encoding="utf-8", newline="\n") as f:
                    f.write(content)
            except Exception as e:
                self._popup_error("Edit", f"Local save error:\n{e}")
                return

            self.log(f"[EDIT] Uploading {tmp_local} -> {remote_path}")
            res2 = self.ssh.scp_put(tmp_local, remote_path)

            if not res2["success"]:
                err2 = (res2["err"] or res2["out"] or "").strip()
                self.log(f"[EDIT ERROR] Upload failed: {err2}")
                self._popup_error("Edit", f"Upload failed:\n{err2}")
                return

            self.log("[EDIT] Upload done.")

            if (
                posixpath.basename(remote_path) == self.remote_file
                and messagebox.askyesno(
                    "Services",
                    "GridCodes.properties modified.\nRestart services now?",
                )
            ):
                self.restart_initd_services()

        ttk.Button(btn_bar, text="Find", command=open_find_dialog).pack(side="left", padx=5, pady=5)
        ttk.Button(btn_bar, text="Save", command=save_and_upload).pack(side="right", padx=5, pady=5)
        ttk.Button(btn_bar, text="Close", command=on_close, style="Danger.TButton").pack(side="right", padx=5, pady=5)

        def save_as_upload():
            new_name = simpledialog.askstring(
                "Save As",
                "New remote filename (or full remote path):",
                initialvalue=posixpath.basename(remote_path),
                parent=win,
            )
            if not new_name:
                return

            new_name = new_name.strip()
            if not new_name:
                self._popup_warning("Save As", "Filename cannot be empty.")
                return

            if "/" in new_name:
                target_remote = new_name
            else:
                target_remote = self._join_remote(
                    posixpath.dirname(remote_path), new_name
                )

            content = txt.get("1.0", "end-1c")
            content = content.replace("\r\n", "\n").replace("\r", "\n")
            try:
                with open(tmp_local, "w", encoding="utf-8", newline="\n") as f:
                    f.write(content)
            except Exception as e:
                self._popup_error("Save As", f"Local save error:\n{e}")
                return

        def save_as_upload():
            new_name = simpledialog.askstring(
                "Save As",
                "New remote filename (or full remote path):",
                initialvalue=posixpath.basename(remote_path),
                parent=win,
            )
            if not new_name:
                return

            new_name = new_name.strip()
            if not new_name:
                self._popup_warning("Save As", "Filename cannot be empty.")
                return

            if "/" in new_name:
                target_remote = new_name
            else:
                target_remote = self._join_remote(
                    posixpath.dirname(remote_path), new_name
                )

            content = txt.get("1.0", "end-1c")
            content = content.replace("\r\n", "\n").replace("\r", "\n")
            try:
                with open(tmp_local, "w", encoding="utf-8", newline="\n") as f:
                    f.write(content)
            except Exception as e:
                self._popup_error("Save As", f"Local save error:\n{e}")
                return

            self.log(f"[EDIT] Uploading (Save As) {tmp_local} -> {target_remote}")
            res3 = self.ssh.scp_put(tmp_local, target_remote)
            if not res3["success"]:
                err3 = (res3["err"] or res3["out"] or "").strip()
                self.log(f"[EDIT ERROR] Save As upload failed: {err3}")
                self._popup_error("Save As", f"Upload failed:\n{err3}")
                return

            self.log(f"[EDIT] Save As done -> {target_remote}")
            self.refresh_file_list()

        ttk.Button(btn_bar, text="Find", command=open_find_dialog).pack(
            side="left", padx=5, pady=5
        )
        ttk.Button(btn_bar, text="Save", command=save_and_upload).pack(
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
        if not self.connected:
            messagebox.showwarning(
                "Warning", "Please connect before sending commands."
            )
            return

        # Si CosPhi mode actif, on bloque P/Q
        if self.use_cosphi_var.get():
            messagebox.showinfo(
                "Mode",
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
                "Warning", "Active and Reactive must be valid numeric values."
            )
            return

        # Plage [-11000 ; 11000]
        for label, value in (("Active (P)", active_val), ("Reactive (Q)", reactive_val)):
            if value < -11000 or value > 11000:
                messagebox.showwarning(
                    "Warning",
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

        self.ssh.execute(remote_cmd, callback=cb)

    # ==================================================================
    # ENERGY MANAGER – CosPhi (ULTIMATE)
    # ==================================================================
    def send_cosphi_command(self):
        if not self.connected:
            messagebox.showwarning(
                "Warning", "Please connect before sending commands."
            )
            return
        if not self.use_cosphi_var.get():
            messagebox.showinfo(
                "Info", "Enable 'Use CosPhi mode' to send this command."
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
                "Warning",
                "CosPhi must not be empty.\nPlease enter a value in (-1, 0) or (0, 1].",
            )
            return

        try:
            active_val = float(active)
            cosphi_val = float(cosphi)
        except ValueError:
            messagebox.showwarning(
                "Warning",
                "Active and CosPhi must be valid numeric values.",
            )
            return

        # P dans la plage [-11000 ; 11000]
        if active_val < -11000 or active_val > 11000:
            messagebox.showwarning(
                "Warning",
                "Active (P) must be between -11000 and 11000.",
            )
            return

        # CosPhi dans (-1, 1] et ≠ 0
        if not (-1.0 < cosphi_val <= 1.0) or abs(cosphi_val) < 1e-9:
            messagebox.showwarning(
                "Warning",
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

        self.ssh.execute(remote_cmd, callback=cb)


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
            self._popup_warning("Services", "Not connected.")
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

        self.ssh.execute(cmd, callback=cb)

    def reboot_device(self):
        if not self.connected:
            self._popup_warning("Reboot", "Not connected.")
            return
        if not messagebox.askyesno("Reboot", "Reboot the device now?"):
            return

        self.log("[REBOOT] Sending 'reboot' command...")

        def cb(res):
            if not res["success"]:
                self.log(f"[REBOOT ERROR] {res['err'] or res['out']}")
                self._popup_error("Reboot", "Reboot command failed.")
            else:
                self.log("[REBOOT] Command sent. Device will reboot.")
                self._popup_info("Reboot", "Reboot command sent.")

        # IMPORTANT : pas d’auto_retry, la borne s’éteint juste après
        self.ssh.execute("reboot", callback=cb, auto_retry=False)

    # ==================================================================
    # NETWORK CONFIG / DEBUG / HELP
    # ==================================================================
    def open_energy_manager(self):
        if not self.connected:
            self._popup_warning(
                "Energy Manager",
                "Please connect before opening Energy Manager PRO.",
            )
            return
        try:
            # même principe que V7 / RemoteBorneManager.py
            self._energy_win = energy_manager.EnergyManagerWindow(self.root, self.ssh)
            try:
                win = getattr(self._energy_win, "win", self._energy_win)
                win.transient(self.root)
                win.grab_set()
                win.focus_force()
                self._center_toplevel(win, 900, 600, parent=self.root)
            except Exception:
                pass
        except Exception as e:
            self.log(f"[ERROR] Unable to open Energy Manager: {e}")
            self._popup_error(
                "Energy Manager",
                f"Unable to open Energy Manager:\n{e}",
            )

    
    def open_network_config(self):
        """
        Ouvre la fenêtre Network config (network_config.py) en éditant CONFIG_PATH,
        puis recharge self.config / self.host / self.user / self.port après Save.
        """
        def on_saved():
            try:
                self.config.read(CONFIG_PATH, encoding="utf-8")
                ssh_cfg = self.config["SSH"]

                self.host = ssh_cfg.get("host", "")
                self.user = ssh_cfg.get("username", "")
                self.password = ssh_cfg.get("password", "")
                self.port = int(ssh_cfg.get("port", "22"))

                # Mise à jour des labels
                if self.ip_label is not None:
                    self.ip_label.configure(text=f"IP: {self.host or '-'}")
                if self.user_label is not None:
                    self.user_label.configure(text=f"User: {self.user or '-'}")

                if self.connected:
                    try:
                        self.ssh.close()
                    except Exception:
                        pass
                    self.connected = False
                    self._set_led(False)
                    self.status_var.set("Reconnecting…")
                    self._update_controls_state()
                # Mise à jour de la cible SSH puis reconnexion unique
                self.ssh.update_target(
                    self.host,
                    self.user,
                    self.password,
                    self.port,
                    auto_reconnect=False,
                )
                self._manual_disconnect_mode = False
                self.force_reconnect()

                self.log("[NETWORK] config.ini reloaded.")
                self._popup_info(
                    "Network",
                    "Network configuration updated.\nReconnecting..."
                )
            except Exception as e:
                self.log(f"[NETWORK ERROR] {e}")
                self._popup_error(
                    "Network",
                    f"Failed to reload config.ini:\n{e}",
                )

        # Appel explicite avec CONFIG_PATH + callback
        open_network_config(self.root, CONFIG_PATH, on_saved)

       
    def open_debug_logs(self):
        """Ouvre la fenêtre Debug Logs seulement si SSH connecté."""
        if not self.connected:
            self._popup_warning(
                "SSH non connecté",
                "Veuillez vous connecter à la borne avant d’ouvrir les logs de debug."
            )
            return

        try:
            debug_logs.open_debug_logs_window(
                self.root,
                self.ssh.host,
                self.ssh.user,        # ← correct
                self.ssh.password,    # ← correct
                self.ssh.port         # ← correct
            )
        except Exception as e:
            self._popup_error("Debug logs", f"Impossible d’ouvrir la fenêtre de debug :\n{e}")

    def _show_about(self):
        self._popup_info(
            "About",
            "Remote Borne Control Interface\n"
            "Author: Nabil (RNA)\n"
            "Backend: plink.exe / pscp.exe\n"
            "No WSL, no paramiko.",
        )

# ==================================================================
# TERMINAL PRO
# ==================================================================
    def open_terminal(self):
        if not self.connected:
            self._popup_warning("Terminal", "Please connect first.")
            return

        current_dir = self.current_path

        win = tk.Toplevel(self.root)
        win.title("SSH Terminal PRO")
        center_window(self.root, win, 900, 600)

        frame = ttk.Frame(win)
        frame.pack(fill="both", expand=True)

        # ===== GRID LAYOUT (FIX UI) =====
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        # ===== OUTPUT =====
        output = tk.Text(
            frame,
            bg="#0d1117",
            fg="#c9d1d9",
            insertbackground="white",
            font=("Consolas", 10),
            wrap="word",
            state="disabled"
        )
        output.grid(row=0, column=0, sticky="nsew")

        # ===== ENTRY =====
        entry = ttk.Entry(frame)
        entry.grid(row=1, column=0, sticky="ew", padx=5, pady=5)

        # ===== BUTTONS =====
        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=2, column=0, sticky="ew")

        # ===== HELPERS =====
        def append(text):
            output.configure(state="normal")
            output.insert("end", text)
            output.see("end")
            output.configure(state="disabled")

        def clear():
            output.configure(state="normal")
            output.delete("1.0", "end")
            output.configure(state="disabled")

        ttk.Button(btn_frame, text="Clear", command=clear).pack(side="left", padx=5, pady=5)
        ttk.Button(btn_frame, text="Close", command=win.destroy).pack(side="right", padx=5, pady=5)

        # ===== HISTORY =====
        history = []
        history_index = -1

        def show_help():
            append(
                "\nAvailable commands:\n"
                "- ls, cd, pwd\n"
                "- python3 script.py\n"
                "- sh script.sh\n"
                "- clear\n\n"
            )

        # ===== COMMAND EXECUTION =====
        def run_command(cmd):
            nonlocal current_dir

            # ===== CD MANAGEMENT =====
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
                    nonlocal current_dir
                    if res["success"]:
                        current_dir = new_dir
                        append(f"[DIR] {current_dir}\n")
                    else:
                        append("[ERROR] Directory not found\n")

                self.ssh.execute(test_cmd, callback=cb)
                return

            # ===== NORMAL COMMAND =====
            full_cmd = f'cd "{current_dir}" && {cmd}'

            append(f"\n{current_dir} $ {cmd}\n")

            def cb(res):
                if res["out"]:
                    append(res["out"] + "\n")
                if res["err"]:
                    append("[ERROR] " + res["err"] + "\n")

            self.ssh.execute(full_cmd, callback=cb)

        # ===== ENTER =====
        def on_enter(event=None):
            nonlocal history_index

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
            history_index = len(history)

            run_command(cmd)
            entry.delete(0, "end")

        # ===== HISTORY NAV =====
        def history_up(event):
            nonlocal history_index
            if history:
                history_index = max(0, history_index - 1)
                entry.delete(0, "end")
                entry.insert(0, history[history_index])

        def history_down(event):
            nonlocal history_index
            if history:
                history_index = min(len(history), history_index + 1)
                entry.delete(0, "end")
                if history_index < len(history):
                    entry.insert(0, history[history_index])

        # ===== BINDINGS =====
        entry.bind("<Return>", on_enter)
        entry.bind("<Up>", history_up)
        entry.bind("<Down>", history_down)

        append("Connected to remote shell\nType 'help' for commands\n")
    # ==================================================================
    # EXIT
    # ==================================================================
    def on_exit(self):
        self._alive_stop = True
        self._monitor_stop = True
        try:
            self.ssh.close()
        except Exception:
            pass
        self.root.destroy()

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
