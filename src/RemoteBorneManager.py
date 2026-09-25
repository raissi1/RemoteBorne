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
- Sequences automatisees de paliers P/Q et CosPhi
- Restart services + reboot borne
- Debug logs (via debug_logs.py)
- Network config (config.ini modifiable)
- Thèmes : flatly (clair) & darkly (sombre)
"""
import sys, os
import importlib.util
import shutil
import subprocess


BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)


import math
import time
import tempfile
import threading
import configparser
import csv
import fnmatch
import posixpath
import re
import shlex

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
    from . import test_sequence
except ImportError:
    try:
        from ssh_manager import SSHManager
        from ssh_queue import SSHQueue
        from network_config import open_network_config
        from open_help import open_help
        import energy_manager
        import debug_logs
        import test_sequence
    except ImportError:
        from src.ssh_manager import SSHManager
        from src.ssh_queue import SSHQueue
        from src.network_config import open_network_config
        from src.open_help import open_help
        from src import energy_manager
        from src import debug_logs
        from src import test_sequence

APP_VERSION = "16.1.0"

# Operational limits used by the main P/Q and CosPhi panels.  The target still
# validates commands; Pn is an operator-side guard that can be read from the
# active GridCodes.properties file.
DEFAULT_PN_LIMIT_W = 11000.0
MAX_PN_LIMIT_W = 100000.0
NETLOGGER_DEFAULT_PATH = "/var/aux/netlogger"
# Restarting the three EVSE services can legitimately take longer than a
# normal SSH command, especially while ChargerApp initializes.
SERVICE_RESTART_TIMEOUT = 120
SIMULATOR_HOST = "127.0.0.1"
SIMULATOR_PORT = 2222
SIMULATOR_USER = "root"
SIMULATOR_PASSWORD = "rbm-simulator"
SIMULATOR_GRID_CODES_PATH = "/etc/iotecha/configs/GridCodes"

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
CONFIG_TEMPLATE_PATH = os.path.join(CONFIG_DIR, "config.example.ini")

# Dossiers images (on garde les mêmes noms qu'avant)
IMG_DIR_1 = os.path.join(BASE_DIR, "imgs")
IMG_DIR_2  = os.path.join(BASE_DIR, "imgs")


def _local_export_dir(value: str) -> str:
    """Return a usable export directory and migrate legacy file paths."""
    candidate = os.path.normpath(os.path.expanduser((value or "").strip()))
    if candidate and os.path.splitext(os.path.basename(candidate))[1]:
        candidate = os.path.dirname(candidate)
    if candidate and not os.path.isabs(candidate):
        candidate = os.path.join(BASE_DIR, candidate)
    return os.path.abspath(candidate) if candidate else EXPORTS_DIR


def _ensure_local_export_dir(value: str) -> str:
    """Create the configured folder, with the portable exports folder as fallback."""
    requested_dir = _local_export_dir(value)
    for candidate in (requested_dir, EXPORTS_DIR):
        try:
            os.makedirs(candidate, exist_ok=True)
            return candidate
        except OSError as exc:
            print(f"[CONFIG] Local export path unavailable: {candidate} ({exc})")
    return EXPORTS_DIR


# ----------------------------------------------------------------------
# Lecture config.ini
# ----------------------------------------------------------------------
# ----------------------------------------------------------------------
# Lecture config.ini
# ----------------------------------------------------------------------
def load_config() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()

    if not os.path.isfile(CONFIG_PATH):
        # Portable builds ship a template only; each installation creates its
        # own local configuration on first start.
        if os.path.isfile(CONFIG_TEMPLATE_PATH):
            shutil.copyfile(CONFIG_TEMPLATE_PATH, CONFIG_PATH)

    if not os.path.isfile(CONFIG_PATH):
        # Fallback for development runs without a template.
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
            "local_path": EXPORTS_DIR,
            "netlogger_path": NETLOGGER_DEFAULT_PATH,
        }

        # On écrit dans config/config.ini
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            cfg.write(f)

        print(f"[CONFIG] Created: {CONFIG_PATH}")
    else:
        # Fichier déjà présent : on le lit
        cfg.read(CONFIG_PATH, encoding="utf-8")
        needs_writeback = False
        print(f"[CONFIG] Loaded: {CONFIG_PATH}")

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
                "local_path": EXPORTS_DIR,
                "netlogger_path": NETLOGGER_DEFAULT_PATH,
            }
            needs_writeback = True
        elif "netlogger_path" not in cfg["PATHS"]:
            cfg["PATHS"]["netlogger_path"] = NETLOGGER_DEFAULT_PATH
            needs_writeback = True
        elif cfg["PATHS"].get("netlogger_path", "") == "/var/aux/NetLogger":
            # Linux paths are case-sensitive. Migrate the former placeholder
            # to the actual EVSE NetLogger directory used by RBM.
            cfg["PATHS"]["netlogger_path"] = NETLOGGER_DEFAULT_PATH
            needs_writeback = True
        normalized_local_path = _ensure_local_export_dir(
            cfg["PATHS"].get("local_path", "")
        )
        if cfg["PATHS"].get("local_path", "") != normalized_local_path:
            cfg["PATHS"]["local_path"] = normalized_local_path
            needs_writeback = True
        # The editor is no longer password protected. Clean up the obsolete
        # setting left in configurations created by earlier RBM versions.
        if "SECURITY" in cfg and cfg.has_option("SECURITY", "edit_password"):
            cfg.remove_option("SECURITY", "edit_password")
            if not cfg["SECURITY"]:
                cfg.remove_section("SECURITY")
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
        self.local_default_path = _ensure_local_export_dir(
            paths_cfg.get("local_path", EXPORTS_DIR)
        )
        self.netlogger_path = paths_cfg.get(
            "netlogger_path", NETLOGGER_DEFAULT_PATH
        ).strip() or NETLOGGER_DEFAULT_PATH
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

        try:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            # Keep the full operating panel visible on 1080p laptops while
            # retaining a small desktop margin instead of forcing maximized.
            w = int(sw * 0.95)
            h = int(sh * 0.96)
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
        self.simulation_var = tk.StringVar(value="")
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
        self.btn_edit_current_properties = None
        self.btn_netlogger = None
        self.btn_go = None
        self.btn_up = None
        self.btn_root = None

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
        self.pn_entry = None
        self.pn_scale = None
        self.pn_percent_entry = None
        self.btn_read_pn = None
        self.btn_read_last_active_power = None
        self.pn_value_var = tk.StringVar(value=str(int(DEFAULT_PN_LIMIT_W)))
        self.pn_slider_var = tk.DoubleVar(value=0.0)
        self.pn_percent_var = tk.StringVar(value="0")
        self.last_active_power_var = tk.StringVar(value="--")
        self.pn_limit_w = DEFAULT_PN_LIMIT_W
        
        self.log_text = None 
        self.file_list = None
        self.path_entry = None
        self.find_entry = None
        self.btn_find = None
        self.btn_clear_find = None
        self._file_find_var = tk.StringVar(value="")
        self._file_entries = []
        self._file_filter_query = ""
        self._recursive_search_active = False
        self._recursive_search_running = False
        self._recursive_search_after_id = None
        self._recursive_search_pending_query = None
        self._recursive_search_rows = {}
        self._browser_find_dialog = None
        self._file_refresh_seq = 0
        self._file_list_path = None
        self._navigation_pending_logged = False
        self._editor_window = None
        self._editor_remote_path = None
        self._close_editor_window = None
        self._terminal_window = None
        self._close_terminal_window = None
        self._terminal_prefill_command = None
        self._energy_win = None
        self._sequence_win = None
        self._sequence_modal_open = False
        self._sequence_running = False
        self._simulation_mode = False
        self._simulator_module = None
        self._local_simulator_evse = None
        self._local_simulator_server = None
        # Steps survive closing/reopening Test Sequence in this RBM session,
        # but are deliberately discarded when the application exits.
        self._test_sequence_session_steps = []
        self._debug_logs_window = None
        self._find_dialog = None
        self.temp_label_var = tk.StringVar(value="Relay: -- °C")
        self.soc_label_var = tk.StringVar(value="Battery SoC: --")
        self._monitor_stop = False
        self._monitor_thread_started = False
        self._last_user_command_ts = time.time()
        self._last_monitor_poll_ts = 0.0
        self._refresh_running = False
        self._refresh_pending = False
        self._refresh_pending_navigation = False
        self._navigation_locked = False
        self._navigation_in_progress = False
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
        self.ssh.set_host_key_confirmation_callback(self._confirm_new_host_key)
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

    def _confirm_new_host_key(self, host: str, details: str) -> bool:
        """Ask in Tk's thread before trusting a new or replaced EVSE key."""
        answer = {"approved": False}
        done = threading.Event()

        fingerprint = re.search(r"fingerprint is:\s*(.+)", details or "", re.IGNORECASE)
        fingerprint_text = fingerprint.group(1).strip() if fingerprint else "Fingerprint unavailable"
        is_replacement = bool(re.search(
            r"potential security breach|does not match", details or "", re.IGNORECASE
        ))
        title = "SSH host key changed" if is_replacement else "SSH host key verification"
        action = (
            "The cached key for this IP will be replaced."
            if is_replacement
            else "This key will be cached for this IP."
        )

        def ask_operator():
            try:
                answer["approved"] = messagebox.askyesno(
                    title,
                    "An SSH host key was received for:\n"
                    f"{host}\n\nFingerprint:\n{fingerprint_text}\n\n"
                    f"{action}\n\n"
                    "Verify this fingerprint with the EVSE owner before accepting it.",
                    parent=self.root,
                )
            finally:
                done.set()

        try:
            self.root.after(0, ask_operator)
            done.wait(timeout=60)
        except Exception:
            return False
        return bool(answer["approved"])

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
            # Re-apply the RBM visual language after ttkbootstrap changes theme.
            self._configure_ui_styles()
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
        return re.fullmatch(r"-?\d*(?:\.\d*)?", new_value) is not None

    @staticmethod
    def _is_valid_cosphi(value) -> bool:
        """CosPhi operates from -0.99 to 1.00, excluding zero."""
        try:
            cosphi = float(value)
        except (TypeError, ValueError):
            return False
        return math.isfinite(cosphi) and -0.99 <= cosphi <= 1.0 and abs(cosphi) >= 1e-9

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

        # LOCAL SIMULATOR
        self.simulator_menu = tk.Menu(menubar, tearoff=0)
        self.simulator_menu.add_command(
            label="Start local simulator and connect",
            command=self.start_local_simulator_and_connect,
        )
        self.simulator_menu.add_command(
            label="Connect to local simulator",
            command=self.connect_to_local_simulator,
        )
        self.simulator_menu.add_command(
            label="Reset local simulator",
            command=self.reset_local_simulator,
        )
        self.simulator_menu.add_separator()
        self.simulator_menu.add_command(
            label="Return to configured charger",
            command=self.return_to_configured_charger,
        )
        self.simulator_menu.add_command(
            label="Stop local simulator",
            command=self.stop_local_simulator,
        )
        menubar.add_cascade(label="Tools", menu=self.simulator_menu)

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

        # TESTS
        self.tests_menu = tk.Menu(menubar, tearoff=0)
        self.tests_menu.add_command(
            label="Test Sequence", command=self.open_test_sequence
        )
        menubar.add_cascade(label="Tests", menu=self.tests_menu)


        # HELP
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Help", command=lambda: open_help(self.root))
        help_menu.add_command(label="About", command=self._show_about)
        menubar.add_cascade(label="Help", menu=help_menu)


        self.root.config(menu=menubar)

    def _style_logs(self):
        # A fixed high-contrast terminal surface stays readable in both RBM
        # themes and visually separates operational evidence from controls.
        self.log_text.configure(
            background="#18232f",
            foreground="#e7edf2",
            insertbackground="#ffffff",
            selectbackground="#3c6388",
            selectforeground="#ffffff",
            font=("Consolas", 10),
            borderwidth=0,
            relief="flat",
        )

    # ==================================================================
    # LAYOUT (proche V2, plus clean)
    # ==================================================================
    def _configure_ui_styles(self):
        """Keep the main workspace visually consistent across screen sizes."""
        self.style.configure(
            "HeaderTitle.TLabel",
            font=("Segoe UI", 14, "bold"),
        )
        self.style.configure(
            "HeaderSubtitle.TLabel",
            font=("Segoe UI", 9, "italic"),
        )
        self.style.configure(
            "Status.TLabel",
            font=("Segoe UI", 9),
        )
        self.style.configure(
            "MetricValue.TLabel",
            font=("Segoe UI", 10, "bold"),
        )
        self.style.configure(
            "Section.TLabelframe.Label",
            font=("Segoe UI", 10, "bold"),
        )
        self.style.configure(
            "Nav.TButton",
            font=("Segoe UI", 9, "bold"),
            padding=(8, 4),
        )
        self.style.configure(
            "Action.TButton",
            font=("Segoe UI", 9, "bold"),
            padding=(10, 5),
        )
        self.style.configure(
            "Wide.TButton",
            font=("Segoe UI", 9, "bold"),
            padding=(10, 6),
        )
        self.style.configure(
            "Monitor.TButton",
            font=("Segoe UI", 9, "bold"),
            padding=(9, 3),
        )

    def _build_layout(self):
        self._configure_ui_styles()

        # ----- MAIN -----
        main = ttk.Frame(self.root)
        main.pack(fill="both", expand=True)

        # Keep the control area compact and use any additional display height
        # for operational evidence in Logs rather than empty space.
        main.grid_columnconfigure(0, weight=1)
        main.grid_columnconfigure(1, weight=1)
        main.grid_rowconfigure(0, weight=0)
        main.grid_rowconfigure(1, weight=1)
        main.grid_rowconfigure(2, weight=2)

        # ----- HEADER (logos + titre + status) -----
        header = ttk.Frame(main)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=(2, 2))
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
            text="Remote Borne Control Interface (RBM)",
            style="HeaderTitle.TLabel",
            anchor="center",
        ).pack(fill="x")
        self.simulation_banner = ttk.Label(
            center_fr,
            textvariable=self.simulation_var,
            bootstyle="warning",
            anchor="center",
        )
        self.simulation_banner.pack(fill="x")

        right_logo_fr = ttk.Frame(header)
        right_logo_fr.grid(row=0, column=2, sticky="e")
        if self.logo_right:
            ttk.Label(right_logo_fr, image=self.logo_right).pack(anchor="e")

        # ----- LEFT : FILE BROWSER -----
        left = ttk.Labelframe(
            main,
            text=f"EVSE Local Grid Code Configuration Files",
            style="Section.TLabelframe",
            padding=5,
        )
        left.grid(row=1, column=0, sticky="nsew", padx=(10, 5), pady=5)

        # 🔥 IMPORTANT (responsive)
        left.grid_rowconfigure(0, weight=0)   # barre de path
        left.grid_rowconfigure(1, weight=0)   # barre de recherche
        left.grid_rowconfigure(2, weight=1)   # liste fichiers
        left.grid_columnconfigure(0, weight=1)

        # Path bar
        path_row = ttk.Frame(left)
        path_row.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        path_row.grid_columnconfigure(1, weight=1)

        ttk.Label(path_row, text="Path:").grid(row=0, column=0, sticky="w")
        self.path_entry = ttk.Entry(path_row)
        self.path_entry.grid(row=0, column=1, sticky="ew", padx=2)
        self.path_entry.insert(0, self.current_path)

        self.btn_go = ttk.Button(
            path_row, text="Go", width=6, style="Nav.TButton", command=self._go_to_path
        )
        self.btn_go.grid(
            row=0, column=2, padx=2
        )
        self.btn_up = ttk.Button(
            path_row, text="Up", width=6, style="Nav.TButton", command=self._go_parent
        )
        self.btn_up.grid(
            row=0, column=3, padx=2
        )
        self.btn_root = ttk.Button(
            path_row, text="Root", width=6, style="Nav.TButton", command=self._go_root
        )
        self.btn_root.grid(
            row=0, column=4, padx=2
        )
        # Find stays visible beside the path controls, without opening a
        # secondary window or changing the remote navigation flow.
        find_row = ttk.Frame(left)
        find_row.grid(row=1, column=0, sticky="ew", pady=(0, 4))
        find_row.grid_columnconfigure(1, weight=1)
        ttk.Label(find_row, text="Find:").grid(row=0, column=0, sticky="w")
        self.find_entry = ttk.Entry(find_row, textvariable=self._file_find_var)
        self.find_entry.grid(row=0, column=1, sticky="ew", padx=2)
        self.find_entry.bind("<Return>", lambda _event: self._apply_file_filter_from_entry())
        self._file_find_var.trace_add("write", self._on_file_find_changed)
        self.btn_find = ttk.Button(
            find_row,
            text="Find",
            width=6,
            style="Nav.TButton",
            command=self._apply_file_filter_from_entry,
        )
        self.btn_find.grid(row=0, column=2, padx=2)
        self.btn_clear_find = ttk.Button(
            find_row,
            text="Clear",
            width=6,
            style="Nav.TButton",
            command=self._clear_file_filter,
        )
        self.btn_clear_find.grid(row=0, column=3, padx=(2, 0))

        # File list
        list_frame = ttk.Frame(left)
        list_frame.grid(row=2, column=0, sticky="nsew")
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(2, weight=1)     # <--- AJOUT NECESSAIRE
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

        # ----- RIGHT : COMPACT OPERATIONS STACK -----
        # On wide screens this avoids the former oversized empty Test
        # Configuration panel while keeping all operating controls together.
        right_stack = ttk.Frame(main)
        right_stack.grid(row=1, column=1, sticky="nsew", padx=(5, 10), pady=5)
        right_stack.grid_columnconfigure(0, weight=1)
        right_stack.grid_rowconfigure(0, weight=0)
        right_stack.grid_rowconfigure(1, weight=0)
        right_stack.grid_rowconfigure(2, weight=1)

        # ----- RIGHT TOP : STATUS + CONTROLS -----
        right_top = ttk.Labelframe(
            right_stack, text="Status & Controls", style="Section.TLabelframe", padding=5
        )
        right_top.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        right_top.grid_columnconfigure(0, weight=1)

        # Status row
        status_row = ttk.Frame(right_top)
        status_row.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        status_row.grid_columnconfigure(1, weight=1)

        self.ip_label = ttk.Label(
            status_row, text=f"IP: {self.host or '-'}", style="Status.TLabel", anchor="w"
        )
        self.ip_label.grid(row=0, column=0, sticky="w")

        self.user_label = ttk.Label(
            status_row, text=f"User: {self.user or '-'}", style="Status.TLabel", anchor="w"
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
            style="Success.TButton",
            command=self.force_reconnect,
        )
        self.btn_connect.grid(row=0, column=0, padx=2, pady=2, sticky="ew")

        self.btn_disconnect = ttk.Button(
            btn_row,
            text="Disconnect",
            style="Warning.TButton",
            command=self._manual_disconnect,
        )
        self.btn_disconnect.grid(row=0, column=1, padx=2, pady=2, sticky="ew")

        self.btn_exit = ttk.Button(
            btn_row, text="Exit", style="Secondary.TButton", command=self.on_exit
        )
        self.btn_exit.grid(row=0, column=2, padx=2, pady=2, sticky="ew")

        # File actions
        file_actions = ttk.Labelframe(
            right_top, text="Test Configuration", style="Section.TLabelframe", padding=5
        )
        file_actions.grid(row=2, column=0, sticky="nsew", pady=(4, 0))

        # Layout tuned for long labels: short actions on first row,
        # long actions on a second row with wider buttons.
        file_actions.grid_columnconfigure(0, weight=1)
        file_actions.grid_columnconfigure(1, weight=1)
        file_actions.grid_columnconfigure(2, weight=1)
        file_actions.grid_columnconfigure(3, weight=1)
        file_actions.grid_rowconfigure(0, weight=0)
        file_actions.grid_rowconfigure(1, weight=0)

        # Row 1: short actions
        self.btn_refresh = ttk.Button(
            file_actions, text="Refresh", style="Action.TButton", command=self.refresh_file_list
        )
        self.btn_refresh.grid(row=0, column=0, padx=3, pady=3, sticky="ew")

        self.btn_download = ttk.Button(
            file_actions, text="Download", style="Action.TButton", command=self._menu_download
        )
        self.btn_download.grid(row=0, column=1, padx=3, pady=3, sticky="ew")

        self.btn_edit = ttk.Button(
            file_actions, text="Edit", style="Action.TButton", command=self._menu_edit
        )
        self.btn_edit.grid(row=0, column=2, padx=3, pady=3, sticky="ew")

        self.btn_print = ttk.Button(
            file_actions, text="Print", style="Action.TButton", command=self._menu_print
        )
        self.btn_print.grid(row=0, column=3, padx=3, pady=3, sticky="ew")

        # Row 2: configuration actions and direct operational shortcuts.
        # Keeping all four on one row prevents them from being clipped on a
        # standard 1080p display.
        self.btn_upload = ttk.Button(
            file_actions,
            text="Upload",
            style="Wide.TButton",
            command=self.upload_files_to_current_path,
        )
        self.btn_upload.grid(row=1, column=0, padx=3, pady=3, sticky="ew")

        self.btn_copy_panel = ttk.Button(
            file_actions,
            text="Apply Grid Code",
            style="Wide.TButton",
            command=self.copy_selected_to_gridcodes,
        )
        self.btn_copy_panel.grid(row=1, column=1, padx=3, pady=3, sticky="ew")

        self.btn_edit_current_properties = ttk.Button(
            file_actions,
            text="Active properties",
            style="Wide.TButton",
            command=self.edit_current_gridcodes_properties,
        )
        self.btn_edit_current_properties.grid(row=1, column=2, padx=3, pady=3, sticky="ew")

        self.btn_netlogger = ttk.Button(
            file_actions,
            text="NetLogger logs",
            style="Wide.TButton",
            command=self.open_netlogger_download,
        )
        self.btn_netlogger.grid(row=1, column=3, padx=3, pady=3, sticky="ew")

        # ----- RIGHT MIDDLE : ENERGY MANAGER -----
        em_frame = ttk.Labelframe(
            right_stack, text="Energy Manager Controls", style="Section.TLabelframe", padding=5
        )
        em_frame.grid(row=1, column=0, sticky="ew")
        em_frame.grid_columnconfigure(0, weight=1)
        em_frame.grid_columnconfigure(1, weight=1)

        # Validateur float commun à tous les champs P/Q/CosPhi
        vcmd_float = (self.root.register(self._validate_float_key), "%P")

        # Pn is an operator-side limit for the active-power fields. It can be
        # typed, adjusted with the slider, or loaded from GridCodes.properties.
        pn_frame = ttk.Labelframe(
            em_frame, text="Active Power Limit (Pn)", style="Section.TLabelframe", padding=(5, 3)
        )
        pn_frame.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        pn_frame.grid_columnconfigure(1, weight=0)

        ttk.Label(pn_frame, text="Pn max [W]:").grid(row=0, column=0, sticky="w")
        self.pn_entry = ttk.Entry(
            pn_frame,
            textvariable=self.pn_value_var,
            width=9,
            justify="right",
            validate="key",
            validatecommand=vcmd_float,
        )
        self.pn_entry.grid(row=0, column=1, sticky="w", padx=(6, 6))
        self.pn_entry.bind("<Return>", self._commit_manual_pn)
        self.pn_entry.bind("<FocusOut>", self._commit_manual_pn)

        self.btn_read_pn = ttk.Button(
            pn_frame,
            text="Read Pn",
            command=self.read_pn_from_gridcodes_properties,
        )
        self.btn_read_pn.grid(row=0, column=2, sticky="w", padx=(0, 12))

        # Compact HMI-style feedback: the last target-confirmed P value is
        # shown as a dedicated read-only metric rather than a long message.
        ttk.Label(pn_frame, text="Last confirmed P [W]:").grid(
            row=1, column=0, sticky="w", pady=(3, 0)
        )
        ttk.Label(
            pn_frame,
            textvariable=self.last_active_power_var,
            style="MetricValue.TLabel",
            width=10,
            anchor="e",
        ).grid(row=1, column=1, sticky="w", padx=(6, 6), pady=(3, 0))
        self.btn_read_last_active_power = ttk.Button(
            pn_frame,
            text="Refresh P",
            command=self.read_last_active_power_from_energy_log,
        )
        self.btn_read_last_active_power.grid(row=1, column=2, sticky="w", pady=(3, 0))

        ttk.Label(pn_frame, text="P [%]:").grid(row=0, column=3, sticky="w")
        pn_frame.grid_columnconfigure(4, weight=1)
        self.pn_scale = tk.Scale(
            pn_frame,
            from_=-100,
            to=100,
            resolution=1,
            orient="horizontal",
            showvalue=False,
            variable=self.pn_slider_var,
            command=self._on_pn_slider_changed,
            highlightthickness=0,
        )
        self.pn_scale.grid(row=0, column=4, sticky="ew", padx=(6, 6))
        self.pn_percent_entry = ttk.Entry(
            pn_frame,
            textvariable=self.pn_percent_var,
            width=6,
            justify="right",
            validate="key",
            validatecommand=vcmd_float,
        )
        self.pn_percent_entry.grid(row=0, column=5, sticky="e")
        self.pn_percent_entry.bind("<Return>", self._commit_manual_percent)
        self.pn_percent_entry.bind("<FocusOut>", self._commit_manual_percent)
        ttk.Label(pn_frame, text="%").grid(row=0, column=6, sticky="w", padx=(3, 0))

        # P/Q
        pq_frame = ttk.Labelframe(
            em_frame, text="P / Q Setpoint", style="Section.TLabelframe", padding=5
        )
        pq_frame.grid(row=1, column=0, sticky="nsew", padx=(0, 4))
        # Setpoints are short numerical values. Keeping P and Q on one row
        # leaves enough vertical space for the monitoring panel on laptops.
        pq_frame.grid_columnconfigure(1, weight=0)
        pq_frame.grid_columnconfigure(3, weight=0)

        ttk.Label(pq_frame, text="Active (P) [W]:").grid(row=0, column=0, sticky="w")
        self.active_entry = ttk.Entry(
            pq_frame,
            width=10,
            justify="right",
            validate="key",
            validatecommand=vcmd_float,
        )
        self.active_entry.grid(row=0, column=1, sticky="w", padx=(5, 12), pady=2)
        # Default value for active
        self.active_entry.insert(0, "0")

        ttk.Label(pq_frame, text="Reactive (Q) [var]:").grid(
            row=0, column=2, sticky="w"
        )
        self.reactive_entry = ttk.Entry(
            pq_frame,
            width=10,
            justify="right",
            validate="key",
            validatecommand=vcmd_float,
        )
        self.reactive_entry.grid(row=0, column=3, sticky="w", padx=(5, 0), pady=2)
        # An empty Q field means that no reactive-power option is sent.

        self.btn_send_power = ttk.Button(
            pq_frame,
            text="Send",
            style="Accent.TButton",
            command=self.send_power_command,
        )
        self.btn_send_power.grid(
            row=1, column=0, columnspan=4, pady=(4, 0), sticky="ew"
        )
        self.btn_send_power.configure(padding=(8, 3))

        # CosPhi
        cosphi_frame = ttk.Labelframe(
            em_frame, text="CosPhi Setpoint", style="Section.TLabelframe", padding=5
        )
        cosphi_frame.grid(row=1, column=1, sticky="nsew", padx=(4, 0))
        cosphi_frame.grid_columnconfigure(1, weight=0)
        cosphi_frame.grid_columnconfigure(3, weight=0)

        ttk.Checkbutton(
            cosphi_frame,
            text="Use CosPhi mode",
            variable=self.use_cosphi_var,
            command=self._on_cosphi_toggle,
        ).grid(row=0, column=0, columnspan=4, sticky="w")

        ttk.Label(cosphi_frame, text="Active (P) [W]:").grid(
            row=1, column=0, sticky="w"
        )
        self.cosphi_active_entry = ttk.Entry(
            cosphi_frame,
            width=10,
            justify="right",
            validate="key",
            validatecommand=vcmd_float,
        )
        self.cosphi_active_entry.grid(
            row=1, column=1, sticky="w", padx=(5, 12), pady=2
        )
        # Default value for active
        self.cosphi_active_entry.insert(0, "0")

        ttk.Label(cosphi_frame, text="CosPhi:").grid(row=1, column=2, sticky="w")
        self.cosphi_entry = ttk.Entry(
            cosphi_frame,
            width=10,
            justify="right",
            validate="key",
            validatecommand=vcmd_float,
        )
        self.cosphi_entry.grid(row=1, column=3, sticky="w", padx=(5, 0), pady=2)
        # A neutral value is inserted when CosPhi mode is enabled or sent.

        self.btn_send_cosphi = ttk.Button(
            cosphi_frame,
            text="Send",
            style="Accent.TButton",
            command=self.send_cosphi_command,
        )
        self.btn_send_cosphi.grid(
            row=2, column=0, columnspan=4, pady=(4, 0), sticky="ew"
        )
        self.btn_send_cosphi.configure(padding=(8, 3))

        # Services
        srv_frame = ttk.Labelframe(
            em_frame, text="Services", style="Section.TLabelframe", padding=5
        )
        srv_frame.grid(row=2, column=0, sticky="nsew", padx=(0, 4), pady=(4, 0))
        srv_frame.grid_columnconfigure(0, weight=1)
        srv_frame.grid_columnconfigure(1, weight=1)
        srv_frame.grid_rowconfigure(1, weight=0)

        self.btn_restart_services = ttk.Button(
            srv_frame,
            text="Restart services",
            style="Warning.TButton",
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
            em_frame, text="Temperature / Derating", style="Section.TLabelframe", padding=5
        )
        derate_frame.grid(
            row=2, column=1, sticky="nsew", padx=(4, 0), pady=(4, 0)
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
        log_frame = ttk.Labelframe(
            main, text="Logs", style="Section.TLabelframe", padding=5
        )
        log_frame.grid(
            row=2, column=0, columnspan=2, sticky="nsew", padx=10, pady=(0, 10)
        )

        # On large displays, the log grows into the remaining area. Its
        # requested height still keeps the operational controls prioritized
        # on compact laptop screens.
        main.grid_rowconfigure(2, weight=2)

        log_frame.grid_columnconfigure(0, weight=1)
        log_frame.grid_rowconfigure(0, weight=1)

        self.log_text = tk.Text(
            log_frame,
            height=5,
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

    def _simulator_directory(self):
        return os.path.join(TOOLS_DIR, "simulator")

    def _set_simulation_mode(self, enabled: bool):
        """Show an unambiguous local-only status without changing config.ini."""
        self._simulation_mode = bool(enabled)
        if enabled:
            self.simulation_var.set(
                f"SIMULATION MODE - Local EVSE {SIMULATOR_HOST}:{SIMULATOR_PORT}"
            )
            self.root.title("Remote Borne Control Interface - SIMULATION MODE")
        else:
            self.simulation_var.set("")
            self.root.title("Remote Borne Control Interface")

    def _ssh_queue_is_idle(self):
        """Do not retarget an EVSE while a real command could still be queued."""
        try:
            return not self.ssh_queue.busy and self.ssh_queue.q.empty()
        except Exception:
            return False

    def _load_simulator_module(self):
        if self._simulator_module is not None:
            return self._simulator_module

        source_path = os.path.join(
            self._simulator_directory(), "rbm_local_evse_simulator.py"
        )
        if not os.path.isfile(source_path):
            raise FileNotFoundError(
                "Local simulator files are missing. Rebuild RBM with the simulator files included."
            )
        spec = importlib.util.spec_from_file_location("rbm_local_evse_simulator", source_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("Unable to load the local simulator module.")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        self._simulator_module = module
        return module

    def _switch_ssh_target(self, profile, simulation: bool):
        """Retarget the live SSH manager without persisting a temporary profile."""
        if not self._ssh_queue_is_idle():
            self._popup_warning(
                "Simulator",
                "Wait for the current SSH command to finish before switching target.",
            )
            return False

        self._close_aux_windows("simulator target change")
        self._manual_disconnect_mode = False
        self._refresh_running = False
        self._refresh_pending = False
        self._refresh_pending_navigation = False
        self._navigation_in_progress = False
        self.connected = False
        self._clear_file_list_ui()

        self.host = profile["host"]
        self.user = profile["user"]
        self.password = profile["password"]
        self.port = int(profile["port"])
        self.default_path = profile["remote_path"]
        self.remote_file = profile["remote_file"]
        self.netlogger_path = profile["netlogger_path"]
        self.current_path = self.default_path

        if self.ip_label is not None:
            self.ip_label.configure(text=f"IP: {self.host}")
        if self.user_label is not None:
            self.user_label.configure(text=f"User: {self.user}")
        if self.path_entry is not None:
            self.path_entry.delete(0, "end")
            self.path_entry.insert(0, self.current_path)

        self._set_simulation_mode(simulation)
        self.status_var.set("Connecting to simulator..." if simulation else "Reconnecting...")
        self._set_led(False)
        self._update_controls_state()
        self.ssh.update_target(self.host, self.user, self.password, self.port)
        target_name = "local simulator" if simulation else "configured charger"
        self.log(f"[SIMULATOR] Switching SSH target to {target_name}: {self.host}:{self.port}.")
        return True

    def _simulator_profile(self):
        return {
            "host": SIMULATOR_HOST,
            "user": SIMULATOR_USER,
            "password": SIMULATOR_PASSWORD,
            "port": SIMULATOR_PORT,
            "remote_path": SIMULATOR_GRID_CODES_PATH,
            "remote_file": "GridCodes.properties",
            "netlogger_path": "/var/aux/netlogger",
        }

    def _configured_profile(self):
        ssh_cfg = self.config["SSH"]
        paths_cfg = self.config["PATHS"]
        return {
            "host": ssh_cfg.get("host", ""),
            "user": ssh_cfg.get("username", ""),
            "password": ssh_cfg.get("password", ""),
            "port": int(ssh_cfg.get("port", "22")),
            "remote_path": paths_cfg.get("remote_path", SIMULATOR_GRID_CODES_PATH),
            "remote_file": paths_cfg.get("remote_file", "GridCodes.properties"),
            "netlogger_path": paths_cfg.get("netlogger_path", NETLOGGER_DEFAULT_PATH),
        }

    def start_local_simulator_and_connect(self):
        """Start the bundled simulator in-process, then switch only this session."""
        if self._sequence_operation_blocked("Starting local simulator"):
            return
        if not self._simulation_mode and self.connected and not messagebox.askyesno(
            "Start local simulator",
            "RBM will disconnect from the configured charger and switch this session "
            "to the local simulator. config.ini will not be changed.\n\nContinue?",
            parent=self.root,
        ):
            return
        try:
            if self._local_simulator_server is None:
                module = self._load_simulator_module()
                runtime_dir = os.path.join(self._simulator_directory(), "runtime", "evse_fs")
                evse = module.SimulatedEvse(runtime_dir, SIMULATOR_PASSWORD)
                host_key = os.path.join(self._simulator_directory(), "runtime", "host_key.pem")
                server = module.LocalSshServer(
                    SIMULATOR_HOST, SIMULATOR_PORT, evse, host_key
                )
                server.start()
                self._local_simulator_evse = evse
                self._local_simulator_server = server
                self.log(
                    f"[SIMULATOR] Local EVSE started on {SIMULATOR_HOST}:{SIMULATOR_PORT}."
                )
        except Exception as exc:
            self.log(f"[SIMULATOR ERROR] Unable to start local simulator: {exc}")
            self._popup_error(
                "Simulator",
                "Unable to start the local simulator.\n\n"
                f"{exc}\n\nIf port {SIMULATOR_PORT} is already used, select "
                "Connect to local simulator only when that server is trusted.",
            )
            return
        self.connect_to_local_simulator(confirm=False)

    def connect_to_local_simulator(self, confirm=True):
        """Connect to a simulator already listening on the fixed local endpoint."""
        if self._sequence_operation_blocked("Connecting to local simulator"):
            return
        if not self._simulation_mode and self.connected and confirm and not messagebox.askyesno(
            "Connect to local simulator",
            "RBM will disconnect from the configured charger and switch this session "
            "to 127.0.0.1:2222. config.ini will not be changed.\n\nContinue?",
            parent=self.root,
        ):
            return
        self._switch_ssh_target(self._simulator_profile(), simulation=True)

    def reset_local_simulator(self):
        if self._local_simulator_evse is None:
            self._popup_info(
                "Simulator",
                "No RBM-managed local simulator is running. Start it first.",
            )
            return
        if not messagebox.askyesno(
            "Reset local simulator",
            "Restore the simulator files, logs, telemetry and setpoints to their demo state?",
            parent=self.root,
        ):
            return
        self._local_simulator_evse.reset()
        self.log("[SIMULATOR] Local EVSE reset to demo state.")
        if self._simulation_mode and self.connected:
            self.refresh_file_list()
            self.refresh_temperature_and_soc()

    def return_to_configured_charger(self):
        if not self._simulation_mode:
            self._popup_info("Simulator", "RBM is already using the configured charger profile.")
            return
        if not messagebox.askyesno(
            "Return to configured charger",
            "Disconnect from the local simulator and reconnect to the charger defined in config.ini?",
            parent=self.root,
        ):
            return
        self._switch_ssh_target(self._configured_profile(), simulation=False)

    def _stop_local_simulator_server(self):
        server = self._local_simulator_server
        self._local_simulator_server = None
        self._local_simulator_evse = None
        if server is not None:
            try:
                server.stop()
                self.log("[SIMULATOR] Local EVSE stopped.")
            except Exception as exc:
                self.log(f"[SIMULATOR ERROR] Unable to stop local simulator: {exc}")

    def stop_local_simulator(self):
        if self._local_simulator_server is None:
            self._popup_info("Simulator", "No RBM-managed local simulator is running.")
            return
        if not messagebox.askyesno(
            "Stop local simulator",
            "Stop the local simulator? RBM will return to the configured charger profile first.",
            parent=self.root,
        ):
            return
        if self._simulation_mode and not self._switch_ssh_target(
            self._configured_profile(), simulation=False
        ):
            return
        self._stop_local_simulator_server()

    def _manual_disconnect(self):
        self._manual_disconnect_mode = True
        self._refresh_running = False
        self._refresh_pending = False
        self._refresh_pending_navigation = False
        self._navigation_in_progress = False
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
        self._cancel_scheduled_recursive_file_search()
        self._file_list_path = None
        self._file_entries = []
        self._file_filter_query = ""
        self._recursive_search_active = False
        self._recursive_search_running = False
        self._recursive_search_rows = {}
        self._file_find_var.set("")
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
        _safe_destroy(getattr(self, "_browser_find_dialog", None))
        self._browser_find_dialog = None

        close_terminal = getattr(self, "_close_terminal_window", None)
        terminal_closed = False
        if callable(close_terminal):
            try:
                terminal_closed = close_terminal(force=True) is not False
                closed_any = closed_any or terminal_closed
            except Exception:
                _safe_destroy(getattr(self, "_terminal_window", None))
                terminal_closed = True
        else:
            _safe_destroy(getattr(self, "_terminal_window", None))
            terminal_closed = True
        if terminal_closed:
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

        sequence_win = getattr(self, "_sequence_win", None)
        if sequence_win is not None:
            try:
                sequence_win.close(force=True)
                closed_any = True
            except Exception:
                _safe_destroy(getattr(sequence_win, "win", None))
        self._sequence_win = None
        self._sequence_modal_open = False
        self._sequence_running = False
        try:
            self.ssh_queue.pause_monitoring = False
        except Exception:
            pass

        if force:
            try:
                tracked = {
                    getattr(self, "_editor_window", None),
                    getattr(self, "_find_dialog", None),
                    getattr(self, "_browser_find_dialog", None),
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
            getattr(self, "_browser_find_dialog", None),
            getattr(self, "_terminal_window", None),
            getattr(getattr(self, "_energy_win", None), "win", None),
            getattr(getattr(self, "_sequence_win", None), "win", None),
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
    def _run_alive_probe(self, heartbeat_timeout):
        """Run one SSH heartbeat only while the regular command queue is idle.

        The original heartbeat was queued behind normal operations.  A failed
        probe could therefore remain pending indefinitely and leave the UI in
        the Connected state after the EVSE was powered off.  Acquiring the
        queue lock here keeps scripts and operator commands exclusive while
        still allowing an idle connection to be checked promptly.
        """
        queue = getattr(self, "ssh_queue", None)
        ssh = getattr(self, "ssh", None)
        if queue is None or ssh is None:
            return None
        if self._manual_disconnect_mode or getattr(ssh, "_reconnect_in_progress", False):
            return None
        if not getattr(ssh, "connected", False):
            return False

        # Never delay an operator command or a running terminal script.
        pending_commands = getattr(queue, "q", None)
        if getattr(queue, "busy", False) or getattr(queue, "pause_monitoring", False):
            return None
        try:
            if pending_commands is not None and not pending_commands.empty():
                return None
        except Exception:
            return None

        lock = getattr(queue, "lock", None)
        if lock is None or not lock.acquire(blocking=False):
            return None

        try:
            # A command can have started between the idle check and the lock.
            if getattr(queue, "busy", False) or not getattr(ssh, "connected", False):
                return False
            result = ssh.execute_sync(
                "echo alive",
                timeout=heartbeat_timeout,
                auto_retry=False,
                log_errors=False,
            )
        except Exception as exc:
            result = {"success": False, "err": str(exc), "out": ""}
        finally:
            lock.release()

        if result.get("success"):
            return True

        reason = (result.get("err") or result.get("out") or "unknown error").strip()
        self.log("[ALIVE] Heartbeat failed; marking SSH disconnected.")
        # ``echo alive`` has no application-level failure mode: one failed
        # response means that the charger connection is not usable.
        ssh.report_connection_lost(reason, force_event=True)
        return False

    def _start_alive_monitor(self):
        """
        Start a fast SSH heartbeat to keep the visible connection state honest.

        A charger power loss must not leave the operator-facing UI in the
        Connected state while waiting for the slower temperature poll.
        """
        if hasattr(self, "_alive_thread_started") and self._alive_thread_started:
            return
        self._alive_thread_started = True

        def worker():
            last_reconnect_try = 0.0
            # Check immediately after connection, then at most every five
            # seconds. A probe runs only while SSHQueue is idle, so a running
            # script retains its requested priority over other SSH actions.
            monitor_interval = min(5, max(3, self.alive_interval))
            heartbeat_timeout = min(4, self.ssh_timeout)
            self.log(
                f"[ALIVE] Heartbeat every {monitor_interval}s "
                f"(timeout {heartbeat_timeout}s)."
            )
            while not self._alive_stop:
                # Si l’app est fermée, on sort
                if not hasattr(self, "ssh"):
                    break
                if getattr(self.ssh, "_reconnect_in_progress", False):
                    time.sleep(monitor_interval)
                    continue
                # Si pas connecté -> on tente une reconnexion périodique
                if not self.ssh.connected:
                    if self._manual_disconnect_mode:
                        time.sleep(monitor_interval)
                        continue
                    now = time.time()
                    if now - last_reconnect_try >= 30:
                        self.log("[ALIVE] Disconnected, attempting reconnect.")
                        self.ssh.restart()
                        last_reconnect_try = now
                    time.sleep(monitor_interval)
                    continue

                probe_result = self._run_alive_probe(heartbeat_timeout)
                if probe_result is False and not self._manual_disconnect_mode:
                    now = time.time()
                    if now - last_reconnect_try >= 30:
                        self.log("[ALIVE] Starting automatic reconnect after heartbeat failure.")
                        self.ssh.force_reconnect()
                        last_reconnect_try = now
                # Keep the first control immediate, then wait after each
                # attempt. A failed heartbeat updates the UI in roughly four
                # seconds when the charger is switched off and the queue is idle.
                if self._alive_stop:
                    break
                time.sleep(monitor_interval)

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
        """Manual refresh button: Temp, SoC, and the last confirmed P setpoint."""
        if self._sequence_operation_blocked("Manual monitor refresh"):
            return
        if not self.connected:
            self.log("[MONITOR] Refresh: not connected.")
            return
        self.log("[MONITOR] Manual refresh requested...")
        self.update_temp_and_soc(manual=True)
        # Queue this read after the lightweight monitor command so the UI
        # refreshes all displayed live values without blocking the operator.
        self.read_last_active_power_from_energy_log()

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
            # A vehicle may be absent: do not turn a missing SoC into a
            # transport failure that also hides the available temperatures.
            'grep -oE "evPresentSo[Cc]: [0-9]+" /var/aux/ChargerApp/ChargerApp.log 2>/dev/null | tail -1 | grep -oE "[0-9]+" || true'
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
                    f"Battery SoC (last known): {soc_value}"
                    if soc_value is not None
                    else "Battery SoC: --"
                )

            try:
                if not self._closing and self.root.winfo_exists():
                    self.root.after(0, apply_ui)
            except Exception:
                pass

        queued = self.ssh_queue.execute(
            cmd,
            callback=cb,
            timeout=min(self.ssh_timeout, 5),
            command_type="monitor_temp_soc",
            label="Monitor Temp + SoC",
            silent=False,
            auto_retry=False,
            log_errors=False,
            dedupe_key="monitor_temp_soc",
        )
        if manual and not queued:
            self.log("[MONITOR] Refresh already queued or running.")

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
                self._refresh_pending_navigation = False
                self._navigation_in_progress = False
                self._navigation_locked = False
                self.status_var.set("Disconnected")
                self.log("[SSH] Disconnected")
                self._close_aux_windows("SSH disconnect")
                self._set_led(False)
                self._clear_file_list_ui()
                self.temp_label_var.set("Relay: -- °C")
                self.temp_label.configure(foreground="")
                self.soc_label_var.set("Battery SoC: --")
                self.last_active_power_var.set("--")
                self._update_controls_state()

            elif ev_type == "reconnecting":
                self.connected = False
                self._refresh_running = False
                self._refresh_pending = False
                self._refresh_pending_navigation = False
                self._navigation_in_progress = False
                self._navigation_locked = False
                self.status_var.set("Reconnecting…")
                self.log("[SSH] Reconnecting…")
                self._close_aux_windows("SSH reconnect")
                self._set_led(False)
                self._clear_file_list_ui()
                self.temp_label_var.set("Relay: -- °C")
                self.temp_label.configure(foreground="")
                self.soc_label_var.set("Battery SoC: --")
                self.last_active_power_var.set("--")
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
    def _sequence_operation_blocked(self, action: str) -> bool:
        """Reject direct calls that bypass disabled controls during a sequence."""
        if not bool(getattr(self, "_sequence_modal_open", False)):
            return False
        message = (
            f"{action} is unavailable while the Test Sequence window is open. "
            "Close Test Sequence before using other RBM actions."
        )
        self.log(f"[SEQUENCE] Blocked: {action}.")
        self._popup_warning("Test Sequence open", message)
        return True

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
            self.btn_edit_current_properties,
            self.btn_netlogger,
            self.btn_upload,
            self.btn_read_pn,
            self.btn_read_last_active_power,
            self.btn_send_power,
            self.btn_send_cosphi,
            self.btn_restart_services,
            self.btn_reboot,
            self.btn_monitor,
            self.btn_find,
            self.btn_clear_find,
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

        sequence_locked = bool(getattr(self, "_sequence_modal_open", False))

        # ----- Boutons qui nécessitent une connexion -----
        for b in needs_conn:
            if b:
                enabled = self.connected and not sequence_locked
                b.configure(state="normal" if enabled else "disabled")

        # ----- Menus -----
        try:
            state_conn = tk.NORMAL if self.connected else tk.DISABLED
            state_action = (
                tk.NORMAL if self.connected and not sequence_locked else tk.DISABLED
            )
            state_not_conn = tk.NORMAL if not self.connected else tk.DISABLED

            if self.file_menu:
                # Connect only when disconnected
                self.file_menu.entryconfig("Connect", state=state_not_conn)
                # Disconnect only when connected
                self.file_menu.entryconfig("Disconnect", state=state_conn)
                # Actions needing connection
                self.file_menu.entryconfig("Download", state=state_action)
                self.file_menu.entryconfig("Print", state=state_action)
                self.file_menu.entryconfig("Edit", state=state_action)
                self.file_menu.entryconfig("Restart services", state=state_action)
                self.file_menu.entryconfig("Reboot device", state=state_action)

            if hasattr(self, "debug_menu"):
                self.debug_menu.entryconfig("Debug logs", state=state_action)
            if hasattr(self, "energy_menu") and self.energy_menu:
                self.energy_menu.entryconfig("Energy Manager PRO", state=state_action)
            if hasattr(self, "terminal_menu") and self.terminal_menu:
                self.terminal_menu.entryconfig("Open Terminal", state=state_action)
            if hasattr(self, "tests_menu") and self.tests_menu:
                self.tests_menu.entryconfig(
                    "Test Sequence",
                    state=tk.DISABLED if sequence_locked else state_conn,
                )

        except Exception:
            pass

        # ----- Liste de fichiers (GridCodes browser) -----
        if hasattr(self, "file_list") and self.file_list:
            if self.connected and not sequence_locked:
                self.file_list.configure(state="normal")
            else:
                self.file_list.configure(state="disabled")
                try:
                    self.file_list.selection_clear(0, "end")
                except Exception:
                    pass

        self._set_navigation_locked(
            self._navigation_locked or sequence_locked, update_model=False
        )

        # CosPhi exclusif vs P/Q
        self._on_cosphi_toggle(update_only=True)
        if sequence_locked:
            for button in (self.btn_send_power, self.btn_send_cosphi):
                if button:
                    button.configure(state="disabled")

    # ==================================================================
    # FILE ACTION LOCK — désactive les boutons fichier pendant une action
    # ==================================================================
    def _lock_file_actions(self, reason: str = ""):
        """Désactive Edit, Download, Print, Copy tant qu'une action est en cours."""
        for b in [
            self.btn_edit,
            self.btn_download,
            self.btn_print,
            self.btn_upload,
            self.btn_copy_panel,
            self.btn_edit_current_properties,
            self.btn_netlogger,
        ]:
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
        for b in [
            self.btn_edit,
            self.btn_download,
            self.btn_print,
            self.btn_upload,
            self.btn_copy_panel,
            self.btn_edit_current_properties,
            self.btn_netlogger,
        ]:
            try:
                if b:
                    b.configure(state="normal")
            except Exception:
                pass

    # ==================================================================
    # NAVIGATION FICHIERS — VERSION ASYNC AVEC SSHManager.execute
    # ==================================================================
    def _set_navigation_locked(self, locked: bool, update_model: bool = True):
        if update_model:
            self._navigation_locked = locked
        state = "disabled" if locked or not self.connected else "normal"
        for widget in (self.btn_go, self.btn_up, self.btn_root, self.btn_refresh, self.path_entry):
            try:
                if widget is not None:
                    widget.configure(state=state)
            except Exception:
                pass

    def _set_file_list_loading(self, loading: bool):
        """Prevent selection of stale entries without blanking the browser."""
        if self.file_list is None:
            return
        try:
            self.file_list.configure(state="normal")
            if loading:
                self.file_list.selection_clear(0, "end")
                # Keep the last valid listing visible while SSH fetches the next
                # folder. Clearing it made normal navigation look frozen.
                self.file_list.configure(state="disabled")
            else:
                state = "normal" if self.connected else "disabled"
                self.file_list.configure(state=state)
        except Exception:
            pass

    def _begin_navigation(self) -> bool:
        if not self.connected:
            return False
        if self._navigation_in_progress:
            if not self._navigation_pending_logged:
                self.log("[FILES] Navigation already in progress; additional click ignored.")
                self._navigation_pending_logged = True
            return False
        # Keep controls visually available, but accept one navigation intent at
        # a time. This avoids piling up Go/Up/Root commands in the SSH queue.
        self._navigation_in_progress = True
        self._navigation_pending_logged = False
        return True

    def _finish_navigation(self):
        self._navigation_in_progress = False
        self._navigation_pending_logged = False

    @staticmethod
    def _file_name_matches_query(entry: str, query: str) -> bool:
        """Match a name as a case-insensitive contains search with wildcards."""
        query = query.strip().casefold()
        if not query:
            return True
        candidate = entry.casefold()
        if "*" in query or "?" in query:
            # Find is a contains search. Preserve wildcard segments inside the
            # query, but add outer wildcards so ``5*5`` matches any filename
            # containing a 5 followed later by another 5.
            pattern = query
            if not pattern.startswith("*"):
                pattern = "*" + pattern
            if not pattern.endswith("*"):
                pattern += "*"
            return fnmatch.fnmatchcase(candidate, pattern)
        return query in candidate

    def _file_entry_matches_filter(self, entry: str) -> bool:
        """Match a local GridCodes entry without sending another SSH command."""
        return self._file_name_matches_query(
            entry, getattr(self, "_file_filter_query", "")
        )

    def _render_file_entries(self):
        """Render the cached remote list, optionally filtered by the Find query."""
        if self.file_list is None:
            return 0, 0
        try:
            self.file_list.delete(0, "end")
            if self.current_path.rstrip("/") != self.default_path.rstrip("/"):
                self.file_list.insert("end", "[.] (Parent)")

            entries = list(getattr(self, "_file_entries", []))
            shown = 0
            for entry in entries:
                if self._file_entry_matches_filter(entry):
                    self.file_list.insert("end", entry)
                    shown += 1
            return shown, len(entries)
        except Exception as exc:
            self.log(f"[FILES ERROR] Unable to render file list: {exc}")
            return 0, 0

    def _on_file_find_changed(self, *_):
        """Filter locally first, then search subfolders after a short pause."""
        if not self.connected or not getattr(self, "_file_entries", []):
            return
        self._apply_file_filter_from_entry(log_result=False, allow_recursive=False)
        query = self._file_find_var.get().strip()
        if query:
            self._schedule_recursive_file_search(query)
        else:
            self._cancel_scheduled_recursive_file_search()

    def _apply_file_filter_from_entry(
        self, log_result: bool = True, allow_recursive: bool = True
    ):
        """Apply the visible Find field to the already loaded folder entries."""
        if not self.connected:
            if log_result:
                self.log("[FILES] Please connect before using Find.")
            return
        self._file_filter_query = self._file_find_var.get().strip()
        if (
            allow_recursive
            and self._file_filter_query
        ):
            self._cancel_scheduled_recursive_file_search()
            self._search_files_in_subfolders(self._file_filter_query)
            return
        self._recursive_search_active = False
        self._recursive_search_rows = {}
        shown, total = self._render_file_entries()
        if log_result and self._file_filter_query:
            self.log(f"[FILES] Find '{self._file_filter_query}': {shown}/{total} match(es).")
        elif log_result:
            self.log(f"[FILES] Find cleared: {total} item(s) displayed.")

    def _clear_file_filter(self):
        self._cancel_scheduled_recursive_file_search()
        self._recursive_search_active = False
        self._recursive_search_rows = {}
        self._file_find_var.set("")
        self._apply_file_filter_from_entry()
        try:
            if self.find_entry is not None:
                self.find_entry.focus_set()
        except Exception:
            pass

    def _cancel_scheduled_recursive_file_search(self):
        """Cancel a debounce timer and discard a superseded pending query."""
        after_id = getattr(self, "_recursive_search_after_id", None)
        if after_id is not None:
            try:
                self.root.after_cancel(after_id)
            except (tk.TclError, AttributeError):
                pass
        self._recursive_search_after_id = None
        self._recursive_search_pending_query = None

    def _schedule_recursive_file_search(self, query: str, delay_ms: int = 600):
        """Start one recursive search after typing pauses, like Explorer search."""
        after_id = getattr(self, "_recursive_search_after_id", None)
        if after_id is not None:
            try:
                self.root.after_cancel(after_id)
            except (tk.TclError, AttributeError):
                pass

        def start_search():
            self._recursive_search_after_id = None
            if (
                self._closing
                or not self.connected
                or self._file_find_var.get().strip() != query
                or self.current_path != getattr(self, "_file_list_path", None)
            ):
                return
            if self._recursive_search_running:
                # The active request will schedule this final query when it
                # completes, preventing concurrent find commands on the EVSE.
                self._recursive_search_pending_query = query
                return
            self._search_files_in_subfolders(query)

        try:
            self._recursive_search_after_id = self.root.after(delay_ms, start_search)
        except tk.TclError:
            self._recursive_search_after_id = None

    def _render_recursive_search_results(self, paths, base_path: str):
        """Show recursive matches grouped by their remote parent folder."""
        if self.file_list is None:
            return 0, 0
        groups = {}
        for remote_path in paths:
            parent = posixpath.dirname(remote_path) or "/"
            groups.setdefault(parent, []).append(remote_path)

        self.file_list.delete(0, "end")
        self._recursive_search_rows = {}
        row = 0
        for folder in sorted(groups, key=str.casefold):
            relative_folder = posixpath.relpath(folder, base_path)
            label = "." if relative_folder == "." else relative_folder
            self.file_list.insert("end", f"[DIR] {label}/")
            self._recursive_search_rows[row] = ("folder", folder)
            row += 1
            for remote_path in sorted(groups[folder], key=lambda item: posixpath.basename(item).casefold()):
                self.file_list.insert("end", f"    {posixpath.basename(remote_path)}")
                self._recursive_search_rows[row] = ("file", remote_path)
                row += 1

        if not paths:
            self.file_list.insert("end", "[No matching file in subfolders]")
        return len(paths), len(groups)

    def _search_files_in_subfolders(self, query: str):
        """Find files asynchronously below the current folder and group matches locally."""
        if self._recursive_search_running:
            self._recursive_search_pending_query = query
            return
        if getattr(self, "_file_list_path", None) != self.current_path:
            self.log("[FILES] Wait for the current folder list before searching subfolders.")
            return

        base_path = self.current_path
        self._recursive_search_running = True
        self._recursive_search_pending_query = None
        self.log(f"[FILES] Searching all folders below {base_path} for '{query}'...")
        # Matching is performed locally for consistent case-insensitive and
        # wildcard behavior across EVSE images. Limit output to keep the UI
        # responsive on unusually large test folders.
        command = f"find {shlex.quote(base_path)} -type f -print 2>/dev/null | head -n 2000"

        def callback(result):
            def apply_ui():
                self._recursive_search_running = False
                pending_query = self._recursive_search_pending_query
                self._recursive_search_pending_query = None
                if self._closing or not self.connected:
                    return
                if self.current_path != base_path:
                    self.log("[FILES] All-folder search ignored because the folder changed.")
                    return
                # The operator may have cleared or changed the query while
                # the remote find command was running. Do not overwrite the
                # newer local view with this older response.
                if (
                    self._file_find_var.get().strip() != query
                ):
                    self.log("[FILES] All-folder search ignored because the query changed.")
                    if pending_query:
                        self._schedule_recursive_file_search(pending_query, delay_ms=100)
                    return
                if not result.get("success"):
                    message = (
                        result.get("stderr")
                        or result.get("err")
                        or result.get("stdout")
                        or result.get("out")
                        or "Search failed."
                    ).strip()
                    self.log(f"[FILES] All-folder search error: {message}")
                    return
                all_paths = [
                    path.strip()
                    for path in (result.get("stdout") or result.get("out") or "").splitlines()
                    if path.strip().startswith("/")
                ]
                matches = [
                    path
                    for path in all_paths
                    if self._file_name_matches_query(posixpath.basename(path), query)
                ]
                self._recursive_search_active = True
                count, folders = self._render_recursive_search_results(matches, base_path)
                self.log(
                    f"[FILES] All-folder Find '{query}': {count} file(s) in {folders} folder(s)."
                )
                if len(all_paths) >= 2000:
                    self.log("[FILES] All-folder search reached the 2000-file safety limit.")
                if pending_query and pending_query != query:
                    self._schedule_recursive_file_search(pending_query, delay_ms=100)

            try:
                if not self._closing and self.root.winfo_exists():
                    self.root.after(0, apply_ui)
            except Exception:
                self._recursive_search_running = False

        self.ssh_queue.execute(
            command,
            callback=callback,
            timeout=max(self.ssh_timeout, 60),
            command_type="recursive_find",
            label="Find files in all folders",
            silent=True,
        )

    def _open_file_find_dialog(self):
        """Open a non-blocking local filter for the currently displayed folder."""
        if not self.connected:
            self.log("[FILES] Please connect before using Find.")
            return
        if not getattr(self, "_file_entries", []):
            self._popup_warning("Find", "Refresh the file list before searching.")
            return

        dialog = getattr(self, "_browser_find_dialog", None)
        try:
            if dialog is not None and dialog.winfo_exists():
                dialog.lift()
                dialog.focus_force()
                return
        except Exception:
            self._browser_find_dialog = None

        dialog = tk.Toplevel(self.root)
        dialog.withdraw()
        self._browser_find_dialog = dialog
        dialog.title("Find in GridCodes")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        # Leave room for the action row on compact displays and themed buttons.
        dialog.geometry("460x190")
        dialog.minsize(460, 190)

        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill="both", expand=True)
        frame.grid_columnconfigure(0, weight=1)

        ttk.Label(
            frame,
            text="Find file or folder name (example: Power or *Power*):",
        ).grid(row=0, column=0, sticky="w")
        query_var = tk.StringVar(value=getattr(self, "_file_filter_query", ""))
        query_entry = ttk.Entry(frame, textvariable=query_var, width=48)
        query_entry.grid(row=1, column=0, sticky="ew", pady=(5, 8))
        status_var = tk.StringVar(value="The search is local to the current folder.")
        ttk.Label(frame, textvariable=status_var).grid(row=2, column=0, sticky="w")

        actions = ttk.Frame(frame)
        actions.grid(row=3, column=0, sticky="ew", pady=(10, 0))

        def close_dialog():
            try:
                dialog.destroy()
            except Exception:
                pass
            self._browser_find_dialog = None

        def apply_filter(*_):
            self._file_filter_query = query_var.get().strip()
            shown, total = self._render_file_entries()
            if self._file_filter_query:
                status_var.set(f"{shown} match(es) out of {total} item(s).")
                self.log(f"[FILES] Find '{self._file_filter_query}': {shown}/{total} match(es).")
            else:
                status_var.set(f"Filter cleared: {total} item(s) displayed.")

        def clear_filter():
            query_var.set("")
            apply_filter()
            query_entry.focus_set()

        ttk.Button(actions, text="Find", command=apply_filter, width=10).pack(side="left")
        ttk.Button(actions, text="Clear", command=clear_filter, width=10).pack(side="left", padx=6)
        ttk.Button(actions, text="Close", command=close_dialog, width=10).pack(side="right")
        query_entry.bind("<Return>", apply_filter)
        dialog.bind("<Escape>", lambda _event: close_dialog())
        dialog.protocol("WM_DELETE_WINDOW", close_dialog)
        dialog.deiconify()
        dialog.lift()
        dialog.focus_force()
        query_entry.focus_set()
        query_entry.selection_range(0, "end")

    def refresh_file_list(self, navigation: bool = False):
        """Refresh the remote file list."""

        if not self.connected:
            self.log("[FILES] Please connect before refreshing list.")
            if navigation:
                self._finish_navigation()
            return

        # Find is intentionally scoped to one displayed folder. A new remote
        # location always starts with the complete list so it cannot look empty.
        if navigation:
            self._cancel_scheduled_recursive_file_search()
            self._file_filter_query = ""
            self._file_find_var.set("")
            self._recursive_search_active = False
            self._recursive_search_rows = {}
            dialog = getattr(self, "_browser_find_dialog", None)
            try:
                if dialog is not None and dialog.winfo_exists():
                    dialog.destroy()
            except Exception:
                pass
            self._browser_find_dialog = None

        # The visible list belongs to the previous request until this one ends.
        # It must not be used to build another remote path in the meantime.
        self._file_list_path = None
        self._set_file_list_loading(True)

        if getattr(self, "_refresh_running", False):
            if not getattr(self, "_refresh_pending", False):
                self.log("[FILES] Refresh already in progress, queued.")
            self._refresh_pending = True
            self._refresh_pending_navigation = (
                self._refresh_pending_navigation or navigation
            )
            return

        self._refresh_running = True
        self._refresh_pending = False

        if not getattr(self, "current_path", None):
            self.current_path = self.default_path

        requested_path = self.current_path
        if hasattr(self, "path_entry"):
            self.path_entry.delete(0, "end")
            self.path_entry.insert(0, requested_path)
        cmd = f"ls -Ap {shlex.quote(requested_path)}"
        self.log(f"[FILES] Listing {requested_path}")

        self._file_refresh_seq += 1
        req_id = self._file_refresh_seq

        def recover_stalled_refresh():
            # A queued command should always complete within its SSH timeout.
            # If its UI callback never arrives, invalidate that request and
            # retry the latest requested folder instead of leaving the browser
            # permanently in "refresh in progress" state.
            if (
                self._closing
                or not self.connected
                or req_id != self._file_refresh_seq
                or not self._refresh_running
            ):
                return
            self._file_refresh_seq += 1
            self._refresh_running = False
            self._refresh_pending = False
            retry_navigation = navigation or self._refresh_pending_navigation
            self._refresh_pending_navigation = False
            self.log("[FILES] Refresh timeout recovered; retrying latest path.")
            try:
                self.root.after(
                    0,
                    lambda nav=retry_navigation: self.refresh_file_list(
                        navigation=nav
                    ),
                )
            except Exception:
                if retry_navigation:
                    self._finish_navigation()
                pass

        try:
            self.root.after((self.ssh_timeout + 5) * 1000, recover_stalled_refresh)
        except Exception:
            pass

        def cb(res):
            def apply_ui():
                # A timed-out or superseded response must not clear the state
                # of a newer refresh request.
                if req_id != self._file_refresh_seq:
                    return

                self._refresh_running = False
                rerun_needed = bool(getattr(self, "_refresh_pending", False))
                rerun_navigation = bool(
                    getattr(self, "_refresh_pending_navigation", False)
                )
                self._refresh_pending = False
                self._refresh_pending_navigation = False

                try:
                    if self.current_path != requested_path:
                        rerun_needed = True
                        rerun_navigation = rerun_navigation or navigation
                        return

                    # A disabled Tk Listbox rejects programmatic insertions.
                    # Re-enable it before populating the refreshed directory.
                    self._set_file_list_loading(False)

                    if not res.get("success"):
                        msg = (
                            res.get("stderr")
                            or res.get("err")
                            or res.get("stdout")
                            or res.get("out")
                            or ""
                        ).strip()
                        self.log(f"[FILES] Error: {msg}")
                        self._file_entries = []
                        self.file_list.delete(0, "end")
                        self.file_list.insert(
                            "end", "[Unable to load folder - click Refresh]"
                        )
                        return

                    lines = (res.get("stdout") or res.get("out") or "").splitlines()
                    self._file_entries = [entry.strip() for entry in lines if entry.strip()]
                    count = len(self._file_entries)
                    shown, _total = self._render_file_entries()

                    if hasattr(self, "path_entry"):
                        self.path_entry.delete(0, "end")
                        self.path_entry.insert(0, requested_path)

                    self._file_list_path = requested_path
                    self._navigation_pending_logged = False
                    if self._file_filter_query:
                        self.log(
                            f"[FILES] {count} entries in {requested_path}; "
                            f"Find shows {shown} match(es)."
                        )
                    else:
                        self.log(f"[FILES] {count} entries in {requested_path}")

                except Exception as ex:
                    self.log(f"[FILES ERROR] {ex}")
                finally:
                    # The refresh queue already coalesces successive requests.
                    # Do not keep the navigation controls disabled while a
                    # queued refresh is waiting for the latest path.
                    if rerun_needed and self.connected and not self._closing:
                        try:
                            self.root.after(
                                0,
                                lambda nav=rerun_navigation: self.refresh_file_list(
                                    navigation=nav
                                ),
                            )
                        except Exception:
                            self._set_file_list_loading(False)
                            if rerun_navigation:
                                self._finish_navigation()
                    else:
                        self._set_file_list_loading(False)
                        if navigation:
                            self._finish_navigation()

            try:
                if not self._closing and self.root.winfo_exists():
                    self.root.after(0, apply_ui)
                else:
                    self._refresh_running = False
                    self._refresh_pending = False
                    self._refresh_pending_navigation = False
                    if navigation:
                        self._finish_navigation()
            except Exception:
                self._refresh_running = False
                self._refresh_pending = False
                self._refresh_pending_navigation = False
                if navigation:
                    self._finish_navigation()

        self.ssh_queue.execute(
            cmd,
            callback=cb,
            timeout=self.ssh_timeout,
            command_type="refresh",
            label="Refresh file list",
            silent=False,
        )

    def _go_root(self):
        if not self._begin_navigation():
            return
        self.current_path = self.default_path
        self.refresh_file_list(navigation=True)

    def _go_to_path(self):
        if not self._begin_navigation():
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
                self.refresh_file_list(navigation=True)
            else:
                self._finish_navigation()
                self._popup_error("Path", f"Remote folder not found:\n{target}")

        self.ssh_queue.execute(
            f"test -d {shlex.quote(target)}",
            callback=cb,
            timeout=self.ssh_timeout,
            auto_retry=False,
            log_errors=False,
            command_type="path_check",
            silent=True,
            label="Validate remote path",
        )

    def _go_parent(self):
        if not self._begin_navigation():
            return
        if self.current_path.rstrip("/") == self.default_path.rstrip("/"):
            self._finish_navigation()
            return
        import posixpath
        self.current_path = posixpath.dirname(self.current_path.rstrip("/")) or "/"
        self.refresh_file_list(navigation=True)
    
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

    @staticmethod
    def _terminal_command_for_script(remote_path: str):
        """Return the command prefilled for a supported remote test script."""
        lower_path = remote_path.lower()
        if lower_path.endswith(".py"):
            return f"python3 {shlex.quote(remote_path)}"
        if lower_path.endswith(".sh"):
            return f"sh {shlex.quote(remote_path)}"
        return None

    def _selected_recursive_search_target(self):
        """Return the mapped remote item for the selected recursive Find row."""
        if not self._recursive_search_active:
            return None
        try:
            selection = self.file_list.curselection()
            if not selection:
                return None
            return self._recursive_search_rows.get(selection[0])
        except (tk.TclError, AttributeError):
            return None

    def _open_recursive_search_folder(self, folder: str):
        """Navigate to a Find result's parent folder with normal file actions."""
        if not self._begin_navigation():
            return
        self.current_path = folder or "/"
        self.refresh_file_list(navigation=True)

    def on_file_double_click(self, event):
        if not self.connected:
            return

        # Recursive results carry their original remote path. Files therefore
        # behave exactly like normal list entries; folder headings navigate.
        if self._recursive_search_active:
            target = self._selected_recursive_search_target()
            if target is None:
                return
            kind, remote_path = target
            if kind == "folder":
                self._open_recursive_search_folder(remote_path)
                return

            script_cmd = self._terminal_command_for_script(remote_path)
            if script_cmd:
                self.open_terminal(initial_command=script_cmd)
                return
            self.open_file_editor(remote_path)
            return

        # A delayed double-click can still target the old list. Ignore it
        # rather than appending its folder name to the current remote path.
        if getattr(self, "_file_list_path", None) != self.current_path:
            if not self._navigation_pending_logged:
                self.log("[FILES] Navigation pending; wait for the folder list to load.")
                self._navigation_pending_logged = True
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
            if not self._begin_navigation():
                return
            self._file_list_path = None
            self._set_file_list_loading(True)
            self.current_path = full_path.rstrip("/")
            self.refresh_file_list(navigation=True)
            return

        # Fichier → ouvre l’éditeur
        script_cmd = self._terminal_command_for_script(full_path)
        if script_cmd:
            self.open_terminal(initial_command=script_cmd)
            return

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

        if self._recursive_search_active:
            target = self._selected_recursive_search_target()
            if target is None:
                return
            kind, remote_path = target
            menu = tk.Menu(self.root, tearoff=0)
            if kind == "folder":
                menu.add_command(
                    label="Open folder",
                    command=lambda path=remote_path: self._open_recursive_search_folder(path),
                )
            else:
                script_cmd = self._terminal_command_for_script(remote_path)
                if script_cmd:
                    menu.add_command(
                        label="Run in Terminal",
                        command=lambda command=script_cmd: self.open_terminal(
                            initial_command=command
                        ),
                    )
                    menu.add_separator()
                menu.add_command(
                    label="Edit", command=lambda path=remote_path: self.open_file_editor(path)
                )
                menu.add_command(label="Download", command=self._menu_download)
                menu.add_command(label="Print", command=self._menu_print)
                menu.add_separator()
                menu.add_command(
                    label="Copy to GridCodes.properties",
                    command=self.copy_selected_to_gridcodes,
                )
                menu.add_separator()
                menu.add_command(label="Delete", command=self.delete_selected_remote)
            menu.post(event.x_root, event.y_root)
            return

        item = self._get_selected_item()
        if not item or item.startswith("[.]"):
            return
        is_dir = item.endswith("/")

        menu = tk.Menu(self.root, tearoff=0)
        if not is_dir:
            script_cmd = self._terminal_command_for_script(
                self._join_remote(self.current_path, item)
            )
            if script_cmd:
                menu.add_command(
                    label="Run in Terminal",
                    command=lambda command=script_cmd: self.open_terminal(
                        initial_command=command
                    ),
                )
                menu.add_separator()
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
        full_path = self._selected_remote_file()
        if not full_path:
            return
        self.open_file_editor(full_path)


    def _download_from_context(self):
        full_path = self._selected_remote_file()
        if not full_path:
            return
        self.download_file(full_path)

    def _print_from_context(self):
        full_path = self._selected_remote_file()
        if not full_path:
            return
        self.print_file(full_path)

    # ==================================================================
    # COPY / DOWNLOAD / PRINT / EDIT
    # ==================================================================
    def _selected_remote_file(self):
        target = self._selected_recursive_search_target()
        if target is not None:
            kind, remote_path = target
            if kind == "file":
                return remote_path
            self._popup_warning("GridCodes", "Please select a file, not a folder heading.")
            return None
        item = self._get_selected_item()
        if not item or item.startswith("[.]"):
            self._popup_warning("GridCodes", "Please select a file.")
            return None
        return posixpath.join(self.current_path, item)

    def delete_selected_remote(self):
        if self._sequence_operation_blocked("Deleting a remote file"):
            return
        if self._closing:
            return
        if not self.connected:
            self._popup_warning("Delete", "Please connect first.")
            return

        target = self._selected_recursive_search_target()
        if target is not None:
            kind, remote_path = target
            # Recursive Find lists files only. A folder heading is navigation,
            # never an implicit delete target.
            if kind != "file":
                self._popup_warning("Delete", "Open the folder before deleting it.")
                return
            is_dir = False
        else:
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

        quoted_path = shlex.quote(remote_path)
        cmd = f"rm -rf -- {quoted_path}" if is_dir else f"rm -f -- {quoted_path}"
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
            dedupe_key=f"delete_remote:{remote_path}",
        )

    def copy_selected_to_gridcodes(self):
        if self._sequence_operation_blocked("Applying a Grid Code"):
            return
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

        cmd = f"cp -- {shlex.quote(src)} {shlex.quote(dst)}"
        def _copy_cb(res):
            self._unlock_file_actions()
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

        queued = self.ssh_queue.execute(
            cmd,
            callback=_copy_cb,
            timeout=self.ssh_timeout,
            critical=True,
            label="Copy GridCodes.properties",
            silent=False,
            dedupe_key="copy_gridcodes",
        )
        if queued:
            self._lock_file_actions("Loading Grid Code configuration")

    def _menu_download(self):
        self._safe_mark_user_command()
        remote = self._selected_remote_file()
        if not remote:
            return
        self.download_file(remote)


    def download_file(self, remote_path: str):
        if self._sequence_operation_blocked("Downloading a file"):
            return
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
            # Keep the name and extension returned by the target. A type-specific
            # filter would make Windows append .properties to scripts such as .sh.
            filetypes=[("All files", "*.*")],
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
        if self._sequence_operation_blocked("Uploading a file"):
            return
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
                    quoted_remote = shlex.quote(remote_path)
                    check_cmd = f"test -f {quoted_remote} && wc -c < {quoted_remote}"
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

    def edit_current_gridcodes_properties(self):
        """Open the active GridCodes.properties without requiring selection."""
        if self._sequence_operation_blocked("Editing active GridCodes.properties"):
            return
        if not self.connected:
            self._popup_warning("Edit", "Please connect first.")
            return
        remote_path = posixpath.join(self.default_path, self.remote_file)
        self.log(f"[EDIT] Opening active configuration: {remote_path}")
        self.open_file_editor(remote_path)

    def open_netlogger_download(self):
        """List NetLogger files and let the operator download several at once."""
        if self._sequence_operation_blocked("Downloading NetLogger files"):
            return
        self._safe_mark_user_command()
        if not self.connected:
            self._popup_warning("NetLogger", "Please connect first.")
            return

        remote_dir = (self.netlogger_path or NETLOGGER_DEFAULT_PATH).rstrip("/")
        if not remote_dir:
            remote_dir = NETLOGGER_DEFAULT_PATH

        dialog = tk.Toplevel(self.root)
        dialog.withdraw()
        dialog.title("NetLogger logs")
        dialog.transient(self.root)
        # This window must never lock the main application. A missing log
        # directory is a normal EVSE configuration difference, not an error
        # that should prevent the operator from continuing to work.
        # Transient keeps this non-modal window above RBM, without forcing it
        # above unrelated applications on the desktop.
        dialog.minsize(650, 420)
        self._center_toplevel(dialog, 760, 520, parent=self.root)

        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill="both", expand=True)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(2, weight=1)

        ttk.Label(frame, text="Remote folder:").grid(
            row=0, column=0, sticky="w"
        )
        folder_var = tk.StringVar(value=remote_dir)
        folder_entry = ttk.Entry(frame, textvariable=folder_var)
        folder_entry.grid(row=1, column=0, sticky="ew", pady=(3, 8))

        files_frame = ttk.Frame(frame)
        files_frame.grid(row=2, column=0, sticky="nsew")
        files_frame.grid_columnconfigure(0, weight=1)
        files_frame.grid_rowconfigure(0, weight=1)
        file_list = tk.Listbox(files_frame, selectmode="extended", exportselection=False)
        file_list.grid(row=0, column=0, sticky="nsew")
        file_scroll = ttk.Scrollbar(
            files_frame, orient="vertical", command=file_list.yview
        )
        file_scroll.grid(row=0, column=1, sticky="ns")
        file_list.configure(yscrollcommand=file_scroll.set)

        status_var = tk.StringVar(value="Loading file list...")
        ttk.Label(frame, textvariable=status_var).grid(
            row=3, column=0, sticky="w", pady=(8, 4)
        )

        actions = ttk.Frame(frame)
        actions.grid(row=4, column=0, sticky="ew")
        actions.grid_columnconfigure(0, weight=1)

        def list_files():
            requested_dir = folder_var.get().strip().rstrip("/")
            if not requested_dir:
                status_var.set("Enter an absolute remote folder, then refresh the list.")
                folder_entry.focus_set()
                return
            file_list.delete(0, "end")
            status_var.set("Loading file list...")
            reload_button.configure(state="disabled")
            download_button.configure(state="disabled")
            cmd = (
                f"if [ -d {shlex.quote(requested_dir)} ]; then "
                f"cd {shlex.quote(requested_dir)} && "
                "for item in ./*; do "
                '[ -f "$item" ] || continue; '
                'printf "%s\\n" "${item#./}"; '
                "done | sort; "
                "else echo 'NetLogger directory not found' >&2; exit 2; fi"
            )

            def listed(res):
                reload_button.configure(state="normal" if self.connected else "disabled")
                if not res.get("success"):
                    error = (res.get("err") or res.get("out") or "Unknown error").strip()
                    status_var.set(
                        "Folder not found. Use Detect folder or enter the NetLogger path for this EVSE."
                    )
                    self.log(f"[NETLOGGER ERROR] {error}")
                    folder_entry.focus_set()
                    folder_entry.selection_range(0, tk.END)
                    return

                names = [
                    name.strip()
                    for name in (res.get("out") or "").splitlines()
                    if name.strip()
                    and posixpath.basename(name.strip()) == name.strip()
                ]
                for name in names:
                    file_list.insert("end", name)
                status_var.set(
                    f"{len(names)} file(s) in {requested_dir}. Select one or more files."
                )
                download_button.configure(
                    state="normal" if names and self.connected else "disabled"
                )
                self.netlogger_path = requested_dir
                self.log(f"[NETLOGGER] {len(names)} file(s) listed in {requested_dir}")

            self.ssh_queue.execute(
                cmd,
                callback=listed,
                timeout=self.ssh_timeout,
                auto_retry=False,
                log_errors=False,
                label="List NetLogger files",
                silent=True,
                dedupe_key="list_netlogger_files",
            )

        def detect_folder():
            """Find common NetLogger directories without blocking the UI."""
            status_var.set("Searching for a NetLogger folder...")
            detect_button.configure(state="disabled")
            reload_button.configure(state="disabled")
            search_cmd = (
                "find /var/aux /var/log -type d 2>/dev/null | "
                "grep -iE '/net-?logger' | head -n 20"
            )

            def detected(res):
                detect_button.configure(state="normal" if self.connected else "disabled")
                if not res.get("success"):
                    status_var.set("NetLogger folder was not detected. Enter its path manually.")
                    reload_button.configure(state="normal" if self.connected else "disabled")
                    folder_entry.focus_set()
                    return
                candidates = [
                    line.strip()
                    for line in (res.get("out") or "").splitlines()
                    if line.strip().startswith("/")
                ]
                if not candidates:
                    status_var.set("NetLogger folder was not detected. Enter its path manually.")
                    reload_button.configure(state="normal" if self.connected else "disabled")
                    folder_entry.focus_set()
                    return
                folder_var.set(candidates[0])
                status_var.set(f"Detected {candidates[0]}. Loading files...")
                self.log(f"[NETLOGGER] Detected folder: {candidates[0]}")
                list_files()

            self.ssh_queue.execute(
                search_cmd,
                callback=detected,
                timeout=min(self.ssh_timeout, 10),
                auto_retry=False,
                log_errors=False,
                label="Detect NetLogger folder",
                silent=True,
                dedupe_key="detect_netlogger_folder",
            )

        def download_selected():
            indexes = file_list.curselection()
            if not indexes:
                self._popup_warning("NetLogger", "Select at least one log file.")
                return
            selected = [file_list.get(index) for index in indexes]
            selected = [
                name
                for name in selected
                if posixpath.basename(name) == name and name not in (".", "..")
            ]
            if not selected:
                self._popup_warning("NetLogger", "No valid file was selected.")
                return

            destination = filedialog.askdirectory(
                parent=dialog,
                title="Select folder for NetLogger logs",
                initialdir=self.local_default_path,
            )
            if not destination:
                return

            requested_dir = folder_var.get().strip().rstrip("/")
            reload_button.configure(state="disabled")
            download_button.configure(state="disabled")
            status_var.set(f"Downloading 0/{len(selected)} file(s)...")

            def worker():
                downloaded = []
                failures = []
                for index, name in enumerate(selected, start=1):
                    remote_file = posixpath.join(requested_dir, name)
                    local_file = os.path.join(destination, name)
                    try:
                        with self._scp_lock:
                            result = self.ssh.scp_get(
                                remote_file, local_file, timeout=self.ssh_timeout
                            )
                    except Exception as exc:
                        result = {"success": False, "out": "", "err": str(exc)}

                    if result.get("success"):
                        downloaded.append(name)
                        self.log(f"[NETLOGGER] Downloaded: {remote_file}")
                    else:
                        error = (result.get("err") or result.get("out") or "Unknown error").strip()
                        failures.append(f"{name}: {error}")
                        self.log(f"[NETLOGGER ERROR] {name}: {error}")

                    try:
                        self.root.after(
                            0,
                            lambda current=index: status_var.set(
                                f"Downloading {current}/{len(selected)} file(s)..."
                            ),
                        )
                    except Exception:
                        pass

                def done():
                    if not dialog.winfo_exists():
                        return
                    reload_button.configure(state="normal" if self.connected else "disabled")
                    download_button.configure(state="normal" if self.connected else "disabled")
                    status_var.set(
                        f"Download complete: {len(downloaded)} succeeded, {len(failures)} failed."
                    )
                    message = (
                        f"Saved {len(downloaded)} file(s) to:\n{destination}"
                        f"\n\nFailed: {len(failures)}"
                    )
                    if failures:
                        message += "\n\n" + "\n".join(failures[:3])
                    if failures:
                        self._popup_warning("NetLogger", message, parent=dialog)
                    else:
                        self._popup_info("NetLogger", message, parent=dialog)

                try:
                    self.root.after(0, done)
                except Exception:
                    pass

            threading.Thread(target=worker, daemon=True).start()

        detect_button = ttk.Button(actions, text="Detect folder", command=detect_folder)
        detect_button.grid(row=0, column=0, sticky="w", padx=(0, 6))
        reload_button = ttk.Button(actions, text="Refresh list", command=list_files)
        reload_button.grid(row=0, column=1, padx=(0, 6))
        download_button = ttk.Button(
            actions,
            text="Download selected",
            style="Accent.TButton",
            command=download_selected,
            state="disabled",
        )
        download_button.grid(row=0, column=2, padx=(0, 6))
        ttk.Button(actions, text="Close", command=dialog.destroy).grid(row=0, column=3)

        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        dialog.deiconify()
        dialog.lift()
        dialog.focus_force()
        list_files()

    def _on_pn_slider_changed(self, value):
        """Convert the selected Pn percentage into an active-power value."""
        try:
            percent = int(round(float(value)))
        except (TypeError, ValueError):
            return
        self.pn_percent_var.set(str(percent))
        self._sync_active_power_from_percent(percent)

    def _commit_manual_percent(self, _event=None):
        """Apply a typed percentage to the slider and active-power fields."""
        try:
            percent = int(round(float(self.pn_percent_var.get().strip())))
        except ValueError:
            self._popup_warning("P [%]", "Percentage must be a numeric value between -100 and 100.")
            self.pn_percent_var.set(str(int(round(self.pn_slider_var.get()))))
            return "break"
        if not -100 <= percent <= 100:
            self._popup_warning("P [%]", "Percentage must be between -100 and 100.")
            self.pn_percent_var.set(str(int(round(self.pn_slider_var.get()))))
            return "break"
        self.pn_slider_var.set(percent)
        self._on_pn_slider_changed(percent)
        return "break"

    def _sync_active_power_from_percent(self, percent=None):
        """Write the slider-derived P value into both available power fields."""
        if percent is None:
            percent = int(round(self.pn_slider_var.get()))
        active_value = int(round(self.pn_limit_w * float(percent) / 100.0))
        for entry in (self.active_entry, self.cosphi_active_entry):
            if entry is None:
                continue
            try:
                entry.delete(0, tk.END)
                entry.insert(0, str(active_value))
            except tk.TclError:
                pass

    def _set_pn_limit(self, value, source: str = "", sync_active: bool = False) -> bool:
        try:
            pn_value = float(value)
        except (TypeError, ValueError):
            self._popup_warning("Pn", "Pn must be a valid numeric value.")
            return False
        if not (0 < pn_value <= MAX_PN_LIMIT_W):
            self._popup_warning(
                "Pn",
                f"Pn must be greater than 0 and no more than {int(MAX_PN_LIMIT_W)} W.",
            )
            return False

        pn_value = float(int(round(pn_value)))
        self.pn_limit_w = pn_value
        self.pn_value_var.set(str(int(pn_value)))
        if sync_active:
            self._sync_active_power_from_percent()
        if source:
            self.log(f"[PN] Pn set to {int(pn_value)} W ({source}).")
        return True

    def _commit_manual_pn(self, _event=None):
        """Accept a manually entered Pn without a separate Apply button."""
        if self._set_pn_limit(
            self.pn_value_var.get(), "manual input", sync_active=True
        ):
            return "break"
        self.pn_value_var.set(str(int(self.pn_limit_w)))
        return "break"

    def _get_pn_limit(self) -> float:
        """Return a validated Pn, falling back to the current safe default."""
        raw_value = self.pn_value_var.get().strip()
        try:
            value = float(raw_value)
        except ValueError:
            return self.pn_limit_w
        return value if 0 < value <= MAX_PN_LIMIT_W else self.pn_limit_w

    def read_pn_from_gridcodes_properties(self, on_complete=None, parent=None):
        """Read the active-power limit from GridTopology and PowerMax values."""
        def complete(success: bool):
            if callable(on_complete):
                try:
                    on_complete(bool(success))
                except Exception as exc:
                    self.log(f"[PN] Completion callback ignored: {exc}")

        if not self.connected:
            self._popup_warning("Pn", "Please connect first.", parent=parent)
            complete(False)
            return False
        remote_path = posixpath.join(self.default_path, self.remote_file)
        if self.btn_read_pn:
            self.btn_read_pn.configure(state="disabled")
        self.log(f"[PN] Reading limit from {remote_path}")

        def received(res):
            if self.btn_read_pn:
                self.btn_read_pn.configure(state="normal" if self.connected else "disabled")
            if not res.get("success"):
                error = (res.get("err") or res.get("out") or "Unknown error").strip()
                self.log(f"[PN ERROR] Unable to read {remote_path}: {error}")
                self._popup_error(
                    "Pn", f"Unable to read GridCodes.properties:\n{error}", parent=parent
                )
                complete(False)
                return

            content = res.get("out") or ""

            def property_value(name):
                return re.search(
                    rf"(?im)^\s*{re.escape(name)}\s*[:=]\s*"
                    r"([-+]?\d+(?:\.\d+)?)\b",
                    content,
                )

            topology_match = re.search(
                r"(?im)^\s*GridTopology\s*[:=]\s*(SinglePhase|ThreePhase)\b",
                content,
            )
            topology = topology_match.group(1).lower() if topology_match else ""
            power_key = {
                "singlephase": "PowerMax_1Ph_VAr",
                "threephase": "PowerMax_3Ph_VAr",
            }.get(topology)

            if power_key:
                match = property_value(power_key)
                if match:
                    self._set_pn_limit(
                        match.group(1),
                        f"{power_key} ({topology_match.group(1)})",
                        sync_active=True,
                    )
                    complete(True)
                    return
                self.log(
                    f"[PN] {power_key} is missing for GridTopology={topology_match.group(1)}."
                )
                self._popup_warning(
                    "Pn",
                    f"GridTopology is {topology_match.group(1)}, but {power_key} is missing.\n"
                    "Enter Pn manually or correct GridCodes.properties.",
                    parent=parent,
                )
                complete(False)
                return

            # Legacy files can still expose a direct Pn/Pmax value. Do not
            # guess between 1Ph and 3Ph values if GridTopology is unavailable.
            generic_match = re.search(
                r"(?im)^\s*(?:pn(?:_w)?|pmax(?:_w)?|nominalpower(?:_w)?)\s*[:=]\s*"
                r"([-+]?\d+(?:\.\d+)?)\b",
                content,
            )
            if generic_match:
                self._set_pn_limit(
                    generic_match.group(1),
                    "legacy Pn/Pmax property",
                    sync_active=True,
                )
                complete(True)
                return

            has_1ph = property_value("PowerMax_1Ph_VAr") is not None
            has_3ph = property_value("PowerMax_3Ph_VAr") is not None
            if has_1ph or has_3ph:
                self.log("[PN] GridTopology is missing or invalid; Pn was not changed.")
                self._popup_warning(
                    "Pn",
                    "PowerMax values were found, but GridTopology is missing or invalid.\n"
                    "Use GridTopology=SinglePhase or GridTopology=ThreePhase, or enter Pn manually.",
                    parent=parent,
                )
                complete(False)
                return

            self.log("[PN] No compatible Pn property found in GridCodes.properties.")
            self._popup_warning(
                "Pn",
                "No GridTopology / PowerMax_1Ph_VAr / PowerMax_3Ph_VAr value was found.",
                parent=parent,
            )
            complete(False)

        return self.ssh_queue.execute(
            f"cat -- {shlex.quote(remote_path)}",
            callback=received,
            timeout=self.ssh_timeout,
            auto_retry=False,
            log_errors=False,
            label="Read Pn from GridCodes.properties",
            silent=True,
            dedupe_key="read_gridcodes_pn",
        )

    def read_last_active_power_from_energy_log(self):
        """Read the most recent active-power setpoint accepted by GridCodes."""
        if self._sequence_operation_blocked("Reading the last active power"):
            return
        if not self.connected:
            self._popup_warning("Last P", "Please connect first.")
            return

        if self.btn_read_last_active_power:
            self.btn_read_last_active_power.configure(state="disabled")
        self.log("[POWER] Reading the last confirmed active setpoint from EnergyManager.log...")

        def received(res):
            if self.btn_read_last_active_power:
                self.btn_read_last_active_power.configure(
                    state="normal" if self.connected else "disabled"
                )
            if not res.get("success"):
                error = (res.get("err") or res.get("out") or "Unknown error").strip()
                self.last_active_power_var.set("N/A")
                self.log(f"[POWER ERROR] Unable to read EnergyManager.log: {error}")
                return

            # GridCodes records the active command as
            # "Request to accept setpoint ... { P: {power_W: value} }".
            values = re.findall(
                r"Request to accept setpoint.*?\{\s*P:\s*\{\s*power_W:\s*"
                r"([-+]?\d+(?:\.\d+)?)",
                res.get("out") or "",
                flags=re.IGNORECASE,
            )
            if not values:
                self.last_active_power_var.set("--")
                self.log("[POWER] No confirmed active setpoint found in EnergyManager.log.")
                return

            value = float(values[-1])
            display = str(int(value)) if value.is_integer() else f"{value:g}"
            self.last_active_power_var.set(display)
            self.log(f"[POWER] Last active setpoint confirmed by GridCodes: {display} W.")

        queued = self.ssh_queue.execute(
            "tail -n 600 /var/aux/EnergyManager/EnergyManager.log",
            callback=received,
            timeout=self.ssh_timeout,
            auto_retry=False,
            log_errors=False,
            label="Read last active P from EnergyManager.log",
            silent=True,
            dedupe_key="read_last_active_power",
        )
        if not queued and self.btn_read_last_active_power:
            self.btn_read_last_active_power.configure(
                state="normal" if self.connected else "disabled"
            )

    def open_file_editor(self, remote_path: str):
        if self._sequence_operation_blocked("Editing a remote file"):
            return
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
        win.withdraw()
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
                    self._find_dialog.grab_release()
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
                win.grab_release()
                win.destroy()
            except Exception:
                pass

        # Keep the real close routine so a disconnect or application exit
        # releases the editor modal grab and cleans its temporary file too.
        self._close_editor_window = close_editor

        # Alias de compatibilité: certains builds/appels réfèrent encore "on_close"
        on_close = close_editor
        win.protocol("WM_DELETE_WINDOW", close_editor)

        def open_find_dialog():
            if hasattr(self, "_find_dialog") and self._find_dialog and self._find_dialog.winfo_exists():
                self._find_dialog.lift()
                self._find_dialog.focus_force()
                return

            dialog = tk.Toplevel(win)
            dialog.withdraw()
            self._find_dialog = dialog
            dialog.title("Find (Ctrl+F)")
            dialog.transient(win)
            dialog.resizable(False, False)
            self._center_toplevel(dialog, 520, 170, parent=win)
            dialog.grid_columnconfigure(0, weight=0)
            dialog.grid_columnconfigure(1, weight=1)
            dialog.grid_rowconfigure(0, weight=0)
            dialog.grid_rowconfigure(1, weight=0)
            def close_find_dialog():
                try:
                    dialog.grab_release()
                    dialog.destroy()
                except Exception:
                    pass
                self._find_dialog = None
                # Restore the editor's modal ownership after closing Find.
                try:
                    if win.winfo_exists():
                        win.grab_set()
                        win.lift()
                        win.focus_force()
                except Exception:
                    pass

            dialog.protocol("WM_DELETE_WINDOW", close_find_dialog)

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
            dialog.bind("<Escape>", lambda _e: close_find_dialog())
            dialog.deiconify()
            dialog.lift()
            dialog.focus_force()
            dialog.grab_set()

        def _write_local_and_upload(target_remote: str, check_existing: bool = True):
            content = txt.get("1.0", "end-1c")
            content = content.replace("\r\n", "\n").replace("\r", "\n")
            try:
                with open(tmp_local, "w", encoding="utf-8", newline="\n") as f:
                    f.write(content)
            except Exception as e:
                self._popup_error("Save", f"Local save error:\n{e}", parent=win)
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
                            self._popup_error("Save", f"Upload failed:\n{err2}", parent=win)
                            return

                        self.log("[EDIT] Save upload done.")
                        self.refresh_file_list()

                        if (
                            posixpath.basename(target_remote) == self.remote_file
                            and messagebox.askyesno(
                                "Services",
                                "GridCodes.properties modified.\nRestart services now?",
                                parent=win,
                            )
                        ):
                            # The editor owns a modal grab. Release it before
                            # showing the mandatory cable safety confirmation.
                            close_editor()
                            self.root.after_idle(self.restart_initd_services)

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
                f"test -e {shlex.quote(target_remote)}",
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
                self._popup_warning("Save", "Filename cannot be empty.", parent=win)
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
        # Display the finished modal editor in one operation. This avoids a
        # temporary empty window while the text and toolbar are being built.
        win.transient(self.root)
        win.deiconify()
        win.lift()
        win.focus_force()
        win.grab_set()

    # ==================================================================
    # ENERGY MANAGER – P/Q (ULTIMATE)
    # ==================================================================
    def send_power_command(self):
        if self._sequence_operation_blocked("Sending a P/Q setpoint"):
            return
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

        # Active defaults to zero; an empty reactive field deliberately means
        # "leave reactive power unchanged" on the target.
        if active == "":
            active = "0"

        try:
            active_val = float(active)
        except ValueError:
            messagebox.showwarning(
                "Energy Manager", "Active power must be a valid numeric value."
            )
            return

        reactive_val = None
        if reactive:
            try:
                reactive_val = float(reactive)
            except ValueError:
                messagebox.showwarning(
                    "Energy Manager", "Reactive power must be a valid numeric value."
                )
                return

        if not self._set_pn_limit(self.pn_value_var.get()):
            return
        pn_limit = self._get_pn_limit()
        if abs(active_val) > pn_limit:
            messagebox.showwarning(
                "Energy Manager",
                f"Active (P) must be between -{int(pn_limit)} and {int(pn_limit)} W (Pn).",
            )
            return
        if reactive_val is not None and (reactive_val < -11000 or reactive_val > 11000):
            messagebox.showwarning(
                "Energy Manager",
                "Reactive (Q) must be between -11000 and 11000 var.",
            )
            return

        # On envoie des entiers
        active_int = int(round(active_val))
        reactive_int = int(round(reactive_val)) if reactive_val is not None else None

        if reactive_int is None:
            self.log(f"Sending setpoint: Active={active_int} W, Reactive omitted")
            reactive_option = ""
        else:
            self.log(
                f"Sending setpoint: Active={active_int} W, Reactive={reactive_int} var"
            )
            reactive_option = f" --reactive-power {reactive_int}"

        remote_cmd = (
            "cd /var/aux/EnergyManager && "
            "export LD_LIBRARY_PATH=/usr/local/lib && "
            f"{ENERGY_TOOL_RESOLVE}"
            f"\"$EM_TOOL\" -S -s ocpp -a "
            f"--power {active_int}{reactive_option} "
            "-m CentralSetpoint"
        )

        def cb(res):
            try:
                if res["success"]:
                    self.log("Power command sent successfully.")
                else:
                    err = res["err"] or res["out"] or "unknown error"
                    self.log(f"[ERROR] {err}")
            finally:
                if self.connected:
                    self._on_cosphi_toggle(update_only=True)

        queued = self.ssh_queue.execute(
            remote_cmd,
            callback=cb,
            timeout=self.ssh_timeout,
            label="Power setpoint",
            silent=False,
            dedupe_key="power_setpoint",
        )
        if queued:
            if self.btn_send_power:
                self.btn_send_power.configure(state="disabled")
        else:
            self.log("[POWER] Setpoint already queued or running.")

    # ==================================================================
    # ENERGY MANAGER – CosPhi (ULTIMATE)
    # ==================================================================
    def send_cosphi_command(self):
        if self._sequence_operation_blocked("Sending a CosPhi setpoint"):
            return
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

        # An empty field means unity power factor, which is a safe neutral default.
        if cosphi == "":
            cosphi = "1"
            self.cosphi_entry.delete(0, tk.END)
            self.cosphi_entry.insert(0, cosphi)
            self.log("[COSPHI] Empty value defaulted to 1.")

        try:
            active_val = float(active)
            cosphi_val = float(cosphi)
        except ValueError:
            messagebox.showwarning(
                "Energy Manager",
                "Active and CosPhi must be valid numeric values.",
            )
            return

        if not self._set_pn_limit(self.pn_value_var.get()):
            return
        pn_limit = self._get_pn_limit()
        if abs(active_val) > pn_limit:
            messagebox.showwarning(
                "Energy Manager",
                f"Active (P) must be between -{int(pn_limit)} and {int(pn_limit)} W (Pn).",
            )
            return

        if not self._is_valid_cosphi(cosphi_val):
            messagebox.showwarning(
                "Energy Manager",
                "CosPhi must be between -0.99 and 1.00.\n"
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
        request_id = f"{int(time.time() * 1000)}_{id(self)}"
        result_path = f"/tmp/rbm_cosphi_{request_id}.status"
        output_path = f"/tmp/rbm_cosphi_{request_id}.log"
        started_at = time.monotonic()

        # Keep the UI responsive while the target executes both tool calls.
        # The status file lets us report the real result without guessing.
        remote_cmd = (
            "(cd /var/aux/EnergyManager && "
            "export LD_LIBRARY_PATH=/usr/local/lib && "
            'EM_TOOL="$(command -v EnergyManagerTestingTool 2>/dev/null || true)"; '
            'if [ -z "$EM_TOOL" ]; then '
            'for p in /usr/local/bin/EnergyManagerTestingTool /usr/bin/EnergyManagerTestingTool; do '
            '[ -x "$p" ] && EM_TOOL="$p" && break; '
            "done; "
            "fi; "
            'if [ -z "$EM_TOOL" ]; then '
            "echo 'EnergyManagerTestingTool not found on target' >&2; status=127; "
            "else "
            f"{grid_opt_cmd} && {setpoint_cmd}; status=$?; "
            "fi; "
            f'echo "$status" > "{result_path}") > "{output_path}" 2>&1 &'
        )

        def restore_button():
            if self.connected:
                self._on_cosphi_toggle(update_only=True)

        def poll_result(attempt=0):
            if not self.connected:
                restore_button()
                self.log("[COSPHI] Result unavailable: SSH disconnected.")
                return
            if attempt >= 15:
                restore_button()
                self.log("[COSPHI] Result not received after 30 s; check Debug logs.")
                return

            poll_cmd = (
                f'if [ -f "{result_path}" ]; then '
                f'echo "===RBM_STATUS===$(cat "{result_path}")"; '
                f'cat "{output_path}"; '
                f'rm -f "{result_path}" "{output_path}"; '
                "fi"
            )

            def poll_cb(res):
                output = (res.get("out") or res.get("stdout") or "").strip()
                match = re.search(r"===RBM_STATUS===(\d+)", output)
                if not res.get("success") or not match:
                    try:
                        self.root.after(2000, lambda: poll_result(attempt + 1))
                    except Exception:
                        restore_button()
                    return

                restore_button()
                elapsed = time.monotonic() - started_at
                if match.group(1) == "0":
                    self.log(f"[COSPHI] Command confirmed in {elapsed:.1f} s.")
                else:
                    detail = output.split("===RBM_STATUS===", 1)[-1].split("\n", 1)
                    detail = detail[1].strip() if len(detail) > 1 else "unknown error"
                    self.log(f"[COSPHI ERROR] Command failed after {elapsed:.1f} s: {detail}")

            self.ssh_queue.execute(
                poll_cmd,
                callback=poll_cb,
                timeout=self.ssh_timeout,
                auto_retry=False,
                log_errors=False,
                label="CosPhi result check",
                silent=True,
            )

        def cb(res):
            if res["success"]:
                self.log("[COSPHI] Command sent. Applying on the target...")
                try:
                    self.root.after(1000, poll_result)
                except Exception:
                    restore_button()
            else:
                err = res["err"] or res["out"] or "unknown error"
                restore_button()
                self.log(f"[COSPHI ERROR] Command was not sent: {err}")

        if self.btn_send_cosphi:
            self.btn_send_cosphi.configure(state="disabled")

        queued = self.ssh_queue.execute(
            remote_cmd,
            callback=cb,
            timeout=self.ssh_timeout,
            label="CosPhi setpoint",
            silent=False,
            dedupe_key="cosphi_setpoint",
        )
        if not queued:
            restore_button()
            self.log("[COSPHI] Command already queued or running.")


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
            if use_cosphi and not self.cosphi_entry.get().strip():
                self.cosphi_entry.insert(0, "1")
        if self.btn_send_cosphi:
            self.btn_send_cosphi.configure(state=cos_state if self.connected else "disabled")

    # ==================================================================
    # SERVICES / REBOOT
    # ==================================================================
    def restart_initd_services(self):
        if self._sequence_operation_blocked("Restarting services"):
            return
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

        cmd_parts = ["status=0"]
        for s in services:
            cmd_parts.append(f'echo "Stopping {s}"')
            cmd_parts.append(
                f"/etc/init.d/{s} stop || {{ echo 'Error stopping {s}'; status=1; }}"
            )
            cmd_parts.append(f'echo \"Starting {s}\"')
            cmd_parts.append(
                f"/etc/init.d/{s} start || {{ echo 'Error starting {s}'; status=1; }}"
            )
            cmd_parts.append('echo "--------------------------------"')

        cmd = " ; ".join(cmd_parts) + " ; exit $status"
        self.log("[SERVICES] Restarting services.")

        def cb(res):
            try:
                if res["out"]:
                    for line in res["out"].splitlines():
                        self.log(line)
                if not res["success"]:
                    self.log(f"[SERVICES ERROR] {res['err'] or res['out']}")
                    self._popup_error("Services", "Restart failed.")
                else:
                    self.log("[SERVICES] Restart sequence finished.")
                    self._popup_info("Services", "Restart sequence finished.")
            finally:
                if self.btn_restart_services:
                    self.btn_restart_services.configure(
                        state="normal" if self.connected else "disabled"
                    )

        queued = self.ssh_queue.execute(
            cmd,
            callback=cb,
            timeout=max(SERVICE_RESTART_TIMEOUT, self.ssh_timeout),
            label="Restart services",
            silent=False,
            dedupe_key="restart_services",
        )
        if queued:
            if self.btn_restart_services:
                self.btn_restart_services.configure(state="disabled")
        else:
            self.log("[SERVICES] Restart already queued or running.")

    def reboot_device(self):
        if self._sequence_operation_blocked("Rebooting the device"):
            return
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
                if self.btn_reboot:
                    self.btn_reboot.configure(
                        state="normal" if self.connected else "disabled"
                    )
            else:
                self.log("[REBOOT] Command sent. Device will reboot.")
                self._popup_info("Reboot", "Reboot command sent.")

        queued = self.ssh_queue.execute(
            "reboot",
            callback=cb,
            timeout=15,
            auto_retry=False,
            label="Reboot device",
            silent=False,
            dedupe_key="reboot_device",
        )
        if queued:
            if self.btn_reboot:
                self.btn_reboot.configure(state="disabled")
        else:
            self.log("[REBOOT] Reboot already queued or running.")

    def open_energy_manager(self):
        if self._sequence_operation_blocked("Opening Energy Manager PRO"):
            return
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
                    self.log("[UI] Energy Manager brought to foreground.")
                    return

            self.log("[UI] Opening Energy Manager...")
            self._energy_win = energy_manager.EnergyManagerWindow(
                self.root,
                self.ssh,
                ssh_queue=self.ssh_queue,
                on_close=lambda: setattr(self, "_energy_win", None),
                pn_limit_provider=self._get_pn_limit,
            )
            try:
                win = getattr(self._energy_win, "win", self._energy_win)
                win.update_idletasks()
                self.log("[UI] Energy Manager opened.")
            except Exception:
                pass
        except Exception as e:
            self.log(f"[ERROR] Unable to open Energy Manager: {e}")
            self._popup_error(
                "Energy Manager",
                f"Unable to open Energy Manager:\n{e}",
            )

    def _normalise_test_sequence_step(self, step):
        """Return a safe, portable representation of one saved plateau."""
        if not isinstance(step, dict):
            raise ValueError("Step must be an object.")

        mode = str(step.get("mode", "")).strip()
        if mode not in ("P/Q", "CosPhi"):
            raise ValueError("Unsupported sequence mode.")

        active = int(round(float(step.get("active"))))
        pn_limit = self._get_pn_limit()
        if pn_limit <= 0 or abs(active) > pn_limit:
            raise ValueError(
                f"Active P is outside the current +/-{int(pn_limit)} W Pn limit."
            )
        hold = int(round(float(step.get("hold"))))
        if not (test_sequence.TestSequenceWindow.MIN_HOLD_SECONDS <= hold <=
                test_sequence.TestSequenceWindow.MAX_HOLD_SECONDS):
            raise ValueError("Hold time is outside the supported range.")

        saved = {
            "mode": mode,
            "active": active,
            "hold": hold,
            "status": str(step.get("status", "Ready"))[:80] or "Ready",
        }
        if mode == "P/Q":
            reactive = step.get("reactive")
            if reactive in (None, ""):
                saved["reactive"] = None
            else:
                reactive = int(round(float(reactive)))
                if abs(reactive) > test_sequence.TestSequenceWindow.MAX_REACTIVE_VAR:
                    raise ValueError("Reactive Q is outside the supported range.")
                saved["reactive"] = reactive
        else:
            cosphi = float(step.get("cosphi", 1))
            if not self._is_valid_cosphi(cosphi):
                raise ValueError("CosPhi is outside the supported range.")
            saved["cosphi"] = cosphi
        return saved

    def _load_test_sequence_steps(self):
        """Restore steps from the current RBM session only."""
        try:
            raw_steps = getattr(self, "_test_sequence_session_steps", [])
            steps = [
                self._normalise_test_sequence_step(step)
                for step in raw_steps
            ]
            if steps:
                self.log(f"[SEQUENCE] Restored {len(steps)} step(s) from this session.")
            return steps
        except Exception as exc:
            self.log(f"[SEQUENCE] Session steps ignored: {exc}")
            return []

    def _save_test_sequence_steps(self, sequence, announce: bool = False):
        """Keep editable steps in memory until this RBM session ends."""
        try:
            steps = [
                self._normalise_test_sequence_step(step)
                for step in getattr(sequence, "steps", [])
            ]
            self._test_sequence_session_steps = steps
            if announce:
                self.log(f"[SEQUENCE] Kept {len(steps)} step(s) for this session.")
            return True
        except Exception as exc:
            self.log(f"[SEQUENCE] Unable to keep session steps: {exc}")
            return False

    def _export_test_sequence_to_path(self, sequence, path: str) -> bool:
        """Write a portable Test Sequence CSV compatible with RBM export."""
        try:
            steps = [
                self._normalise_test_sequence_step(step)
                for step in getattr(sequence, "steps", [])
            ]
            with open(path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(
                    [
                        "step",
                        "mode",
                        "active_w",
                        "reactive_var",
                        "cosphi",
                        "hold_seconds",
                        "status",
                    ]
                )
                for index, step in enumerate(steps, start=1):
                    writer.writerow(
                        [
                            index,
                            step["mode"],
                            step["active"],
                            step.get("reactive", ""),
                            step.get("cosphi", ""),
                            step["hold"],
                            step.get("status", ""),
                        ]
                    )
            return True
        except Exception as exc:
            self.log(f"[SEQUENCE] Export failed: {exc}")
            self._popup_error("Test Sequence", f"Unable to save sequence:\n{exc}", parent=sequence.win)
            return False

    def _import_test_sequence_from_path(self, path: str):
        """Read and validate an RBM Test Sequence CSV without contacting the EVSE."""
        required_columns = {
            "step",
            "mode",
            "active_w",
            "reactive_var",
            "cosphi",
            "hold_seconds",
            "status",
        }
        with open(path, "r", newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or not required_columns.issubset(reader.fieldnames):
                raise ValueError("The CSV does not match the RBM Test Sequence format.")
            steps = []
            for row in reader:
                mode = (row.get("mode") or "").strip()
                step = {
                    "mode": mode,
                    "active": row.get("active_w"),
                    "hold": row.get("hold_seconds"),
                    "status": row.get("status") or "Ready",
                }
                if mode == "P/Q":
                    step["reactive"] = row.get("reactive_var") or None
                else:
                    step["cosphi"] = row.get("cosphi") or "1"
                steps.append(self._normalise_test_sequence_step(step))
        return steps

    def _save_test_sequence_as(self, sequence):
        if bool(getattr(sequence, "running", False)):
            self._popup_warning(
                "Test Sequence",
                "Stop the running sequence before saving it.",
                parent=sequence.win,
            )
            return
        path = filedialog.asksaveasfilename(
            parent=sequence.win,
            title="Save Test Sequence As",
            initialdir=EXPORTS_DIR,
            initialfile="RBM_Test_Sequence.csv",
            defaultextension=".csv",
            filetypes=[("RBM Test Sequence CSV", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        if self._export_test_sequence_to_path(sequence, path):
            self.log(f"[SEQUENCE] Exported {len(sequence.steps)} step(s): {path}")
            self._popup_info("Test Sequence", "Sequence saved successfully.", parent=sequence.win)

    def _import_test_sequence(self, sequence):
        if bool(getattr(sequence, "running", False)):
            self._popup_warning(
                "Test Sequence",
                "Stop the running sequence before importing another one.",
                parent=sequence.win,
            )
            return
        path = filedialog.askopenfilename(
            parent=sequence.win,
            title="Import Test Sequence",
            initialdir=EXPORTS_DIR,
            filetypes=[("RBM Test Sequence CSV", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            steps = self._import_test_sequence_from_path(path)
        except Exception as exc:
            self.log(f"[SEQUENCE] Import failed: {exc}")
            self._popup_error("Test Sequence", f"Unable to import sequence:\n{exc}", parent=sequence.win)
            return
        if sequence.steps and not messagebox.askyesno(
            "Import Test Sequence",
            "Replace the current sequence with the imported steps?",
            parent=sequence.win,
        ):
            return
        sequence.steps = steps
        if steps:
            sequence._render_steps(select_index=0)
        else:
            sequence._render_steps()
        self._save_test_sequence_steps(sequence)
        self.log(f"[SEQUENCE] Imported {len(steps)} step(s): {path}")

    def _add_test_sequence_file_actions(self, sequence):
        """Add import/export next to the sequencer's visible footer controls."""
        if getattr(sequence, "_rbm_file_actions_added", False):
            return

        footer = None
        export_button = None

        def visit(widget):
            nonlocal footer, export_button
            try:
                if widget.cget("text") == "Export CSV":
                    footer = widget.master
                    export_button = widget
                    return
            except Exception:
                pass
            try:
                for child in widget.winfo_children():
                    visit(child)
                    if footer is not None:
                        return
            except Exception:
                pass

        visit(sequence.win)
        if footer is None:
            self.log("[SEQUENCE] Import/export controls could not be added to the footer.")
            return

        # Save sequence now produces the same CSV format, so the former
        # one-way Export CSV control would only duplicate the user workflow.
        try:
            export_button.destroy()
        except Exception:
            pass

        ttk.Button(
            footer,
            text="Import sequence",
            command=lambda: self._import_test_sequence(sequence),
        ).pack(side="right", padx=(6, 0))
        ttk.Button(
            footer,
            text="Save as CSV",
            bootstyle="primary",
            command=lambda: self._save_test_sequence_as(sequence),
        ).pack(side="right", padx=(6, 0))
        sequence._rbm_file_actions_added = True

    def _add_test_sequence_pn_helper(self, sequence):
        """Add a Pn/percentage helper without changing the sequencer engine."""
        if getattr(sequence, "_rbm_pn_helper_added", False):
            return

        editor = None

        def find_editor(widget):
            nonlocal editor
            try:
                if widget.cget("text") == "Plateau editor":
                    editor = widget
                    return
            except Exception:
                pass
            try:
                for child in widget.winfo_children():
                    find_editor(child)
                    if editor is not None:
                        return
            except Exception:
                pass

        find_editor(sequence.win)
        if editor is None:
            self.log("[SEQUENCE] Pn helper could not find the plateau editor.")
            return

        container = editor.master
        # The original sequence UI uses rows 0..4. Make a dedicated, compact
        # Pn row just above its editor and preserve every existing widget.
        try:
            for child in container.winfo_children():
                info = child.grid_info()
                row = info.get("row")
                if row is not None and int(row) >= 1:
                    child.grid_configure(row=int(row) + 1)
            container.grid_rowconfigure(2, weight=0)
            container.grid_rowconfigure(3, weight=1)
            container.grid_rowconfigure(4, weight=0)
            container.grid_rowconfigure(5, weight=1)
        except (tk.TclError, TypeError, ValueError) as exc:
            self.log(f"[SEQUENCE] Pn helper layout could not be prepared: {exc}")
            return

        helper = ttk.Labelframe(container, text="Active Power Helper (Pn)", padding=(8, 4))
        helper.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        helper.grid_columnconfigure(5, weight=1)

        pn_var = tk.StringVar(value=str(int(round(self._get_pn_limit()))))
        percent_var = tk.StringVar(value="0")
        slider_var = tk.DoubleVar(value=0.0)
        vcmd_float = (self.root.register(self._validate_float_key), "%P")

        ttk.Label(helper, text="Pn max [W]:").grid(row=0, column=0, sticky="w")
        pn_entry = ttk.Entry(
            helper,
            textvariable=pn_var,
            width=9,
            justify="right",
            validate="key",
            validatecommand=vcmd_float,
        )
        pn_entry.grid(row=0, column=1, sticky="w", padx=(6, 6))

        ttk.Label(helper, text="P [%]:").grid(row=0, column=3, sticky="w")
        percent_entry = ttk.Entry(
            helper,
            textvariable=percent_var,
            width=6,
            justify="right",
            validate="key",
            validatecommand=vcmd_float,
        )
        percent_entry.grid(row=0, column=4, sticky="w", padx=(6, 6))
        percent_scale = tk.Scale(
            helper,
            from_=-100,
            to=100,
            resolution=1,
            orient="horizontal",
            showvalue=False,
            variable=slider_var,
            highlightthickness=0,
        )
        percent_scale.grid(row=0, column=5, sticky="ew", padx=(0, 8))

        ttk.Label(
            helper,
            text="Sets Active P from Pn x percentage; exact manual values remain possible.",
            bootstyle="secondary",
        ).grid(row=1, column=0, columnspan=6, sticky="w", pady=(3, 0))

        def set_editor_active(percent):
            try:
                percent = int(round(float(percent)))
            except (TypeError, ValueError):
                return False
            if not -100 <= percent <= 100:
                return False
            try:
                pn = float(pn_var.get().strip())
            except ValueError:
                return False
            if not (0 < pn <= MAX_PN_LIMIT_W):
                return False
            active = int(round(pn * percent / 100.0))
            percent_var.set(str(percent))
            if int(round(slider_var.get())) != percent:
                slider_var.set(percent)
            sequence.active_var.set(str(active))
            return True

        def commit_pn(_event=None):
            try:
                pn_value = float(pn_var.get().strip())
            except ValueError:
                pn_value = 0
            if not (0 < pn_value <= MAX_PN_LIMIT_W):
                self._popup_warning(
                    "Test Sequence",
                    f"Pn must be greater than 0 and no more than {int(MAX_PN_LIMIT_W)} W.",
                    parent=sequence.win,
                )
                pn_var.set(str(int(round(self._get_pn_limit()))))
                return "break"
            self._set_pn_limit(pn_value, "Test Sequence", sync_active=False)
            pn_var.set(str(int(round(self.pn_limit_w))))
            set_editor_active(slider_var.get())
            return "break"

        def commit_percent(_event=None):
            if not set_editor_active(percent_var.get()):
                self._popup_warning(
                    "Test Sequence",
                    "P [%] must be a numeric value between -100 and 100, and Pn must be valid.",
                    parent=sequence.win,
                )
                percent_var.set(str(int(round(slider_var.get()))))
            return "break"

        def on_slider(value):
            if not set_editor_active(value):
                percent_scale.set(0)

        def read_pn():
            read_button.configure(state="disabled")

            def refreshed(success):
                try:
                    if sequence.win.winfo_exists():
                        read_button.configure(
                            state=(
                                "normal"
                                if self.connected and not bool(sequence.running)
                                else "disabled"
                            )
                        )
                        if success:
                            pn_var.set(str(int(round(self.pn_limit_w))))
                            set_editor_active(slider_var.get())
                except tk.TclError:
                    pass

            self.read_pn_from_gridcodes_properties(
                on_complete=refreshed,
                parent=sequence.win,
            )

        read_button = ttk.Button(
            helper,
            text="Read Pn",
            bootstyle="primary",
            command=read_pn,
        )
        read_button.grid(row=0, column=2, sticky="w", padx=(0, 14))
        pn_entry.bind("<Return>", commit_pn)
        pn_entry.bind("<FocusOut>", commit_pn)
        percent_entry.bind("<Return>", commit_percent)
        percent_entry.bind("<FocusOut>", commit_percent)
        percent_scale.configure(command=on_slider)

        sequence._rbm_pn_helper_added = True
        sequence.register_editable_widgets(
            pn_entry, percent_entry, percent_scale, read_button
        )

    def _save_and_close_test_sequence(self):
        """Persist steps before releasing the modal Test Sequence window."""
        sequence = getattr(self, "_sequence_win", None)
        if sequence is not None:
            self._save_test_sequence_steps(sequence, announce=True)
        self._on_test_sequence_closed()

    def _size_test_sequence_window(self, sequence_window):
        """Apply the final adaptive Test Sequence geometry in one operation."""
        screen_width = sequence_window.winfo_screenwidth()
        screen_height = sequence_window.winfo_screenheight()
        sequence_width = min(1180, max(900, screen_width - 100))
        sequence_height = min(800, max(650, screen_height - 130))
        sequence_window.minsize(
            min(900, sequence_width), min(650, sequence_height)
        )
        self._center_toplevel(
            sequence_window,
            sequence_width,
            sequence_height,
            parent=self.root,
        )

    def open_test_sequence(self):
        """Open the isolated P/Q and CosPhi plateau sequencer."""
        if not self.connected:
            self._popup_warning(
                "Test Sequence",
                "Please connect before opening Test Sequence.",
            )
            return
        try:
            if self._sequence_win is not None:
                win = getattr(self._sequence_win, "win", None)
                if win is not None and win.winfo_exists():
                    win.deiconify()
                    win.lift()
                    win.focus_force()
                    self.log("[UI] Test Sequence brought to foreground.")
                    return

            self._sequence_win = test_sequence.TestSequenceWindow(
                self.root,
                ssh_queue=self.ssh_queue,
                is_connected=lambda: bool(
                    self.connected and getattr(self.ssh, "connected", False)
                ),
                pn_limit_provider=self._get_pn_limit,
                on_close=self._save_and_close_test_sequence,
                on_steps_changed=self._save_test_sequence_steps,
            )
            self._size_test_sequence_window(self._sequence_win.win)
            saved_steps = self._load_test_sequence_steps()
            if saved_steps:
                self._sequence_win.steps = saved_steps
                self._sequence_win._render_steps(select_index=0)
            self._add_test_sequence_file_actions(self._sequence_win)
            self._add_test_sequence_pn_helper(self._sequence_win)
            self._sequence_modal_open = True
            sequence_window = self._sequence_win.win
            sequence_window.transient(self.root)
            # The complete layout is ready: map the window only once, at its
            # final size, then make it modal above the RBM main window.
            sequence_window.deiconify()
            sequence_window.lift()
            sequence_window.focus_force()
            sequence_window.grab_set()
            sequence_start = self._sequence_win.start

            def start_and_lock():
                sequence_start()
                self._watch_test_sequence_state()

            self._sequence_win.btn_start.configure(command=start_and_lock)
            self._update_controls_state()
            self._watch_test_sequence_state()
            self.log("[UI] Test Sequence opened: main application locked until close.")
        except Exception as exc:
            self.log(f"[ERROR] Unable to open Test Sequence: {exc}")
            self._popup_error(
                "Test Sequence",
                f"Unable to open Test Sequence:\n{exc}",
            )

    def _on_test_sequence_closed(self):
        """Restore main-window access after the modal sequencer is closed."""
        sequence_window = getattr(getattr(self, "_sequence_win", None), "win", None)
        try:
            if sequence_window is not None:
                sequence_window.grab_release()
        except Exception:
            pass
        self._sequence_win = None
        self._sequence_modal_open = False
        self._sequence_running = False
        try:
            self.ssh_queue.pause_monitoring = False
        except Exception:
            pass
        self._update_controls_state()
        self.log("[UI] Test Sequence closed: main application unlocked.")

    def _watch_test_sequence_state(self):
        """Mirror the sequencer state without changing its tested command flow."""
        sequence = getattr(self, "_sequence_win", None)
        sequence_window = getattr(sequence, "win", None)
        exists = False
        try:
            exists = sequence_window is not None and sequence_window.winfo_exists()
        except Exception:
            pass

        if not exists and bool(getattr(self, "_sequence_modal_open", False)):
            self._on_test_sequence_closed()
            return

        running = bool(exists and getattr(sequence, "running", False))
        if running != bool(getattr(self, "_sequence_running", False)):
            self._on_sequence_running_changed(running)

        if exists and not self._closing:
            try:
                self.root.after(150, self._watch_test_sequence_state)
            except Exception:
                pass

    def _on_sequence_running_changed(self, running: bool):
        """Lock concurrent remote actions for the duration of a test sequence."""
        self._sequence_running = bool(running)
        try:
            self.ssh_queue.pause_monitoring = self._sequence_running
        except Exception:
            pass
        self._update_controls_state()
        if self._sequence_running:
            self.log("[SEQUENCE] Remote actions locked while the test sequence is running.")
        elif bool(getattr(self, "_sequence_modal_open", False)):
            self.log("[SEQUENCE] Sequence stopped; main application remains locked until close.")
        else:
            self.log("[SEQUENCE] Remote actions unlocked.")

    def open_terminal(self, initial_command: str = None):
        if self._sequence_operation_blocked("Opening the terminal"):
            return
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
                    if initial_command and callable(self._terminal_prefill_command):
                        self._terminal_prefill_command(initial_command)
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
            command=lambda: _on_close(),
        ).pack(side="right", padx=5, pady=5)

        history = []
        history_index = [-1]
        terminal_busy = [False]
        script_running = [False]
        completion_pending = [False]

        def cancel_script():
            if not script_running[0]:
                return
            if not messagebox.askyesno(
                "Stop script",
                "Stop the running script?\n\n"
                "RBM will stop the local SSH process. The target command may "
                "continue if it has already detached on the EVSE.",
                parent=win,
            ):
                return
            if self.ssh_queue.cancel_active_stream("terminal_script"):
                stop_script_btn.configure(state="disabled")
                append("[INFO] Stop requested for the running script.\n")
            else:
                append("[INFO] No running terminal script could be stopped.\n")

        stop_script_btn = ttk.Button(
            btn_frame,
            text="Stop script",
            style="Warning.TButton",
            command=cancel_script,
            state="disabled",
        )
        stop_script_btn.pack(side="left", padx=5, pady=5)

        def set_terminal_busy(is_busy):
            terminal_busy[0] = is_busy
            entry.configure(state="disabled" if is_busy else "normal")
            stop_script_btn.configure(
                state="normal" if is_busy and script_running[0] else "disabled"
            )
            if not is_busy:
                entry.focus_force()

        def prefill_command(command):
            if terminal_busy[0]:
                append("[INFO] Wait for the current command before preparing another script.\n")
                return
            entry.configure(state="normal")
            entry.delete(0, "end")
            entry.insert(0, command)
            entry.focus_force()

        self._terminal_prefill_command = prefill_command

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
                "  sh script.sh\n"
                "  Tab completes commands and remote paths\n\n"
                "A running script has SSH priority; RBM commands wait until it ends.\n"
                "Use Stop script only when the script must be interrupted.\n\n"
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

            if terminal_busy[0]:
                append("[INFO] A command is already running. Wait for it to finish.\n")
                return

            if cmd.startswith("cd"):
                parts = cmd.split(maxsplit=1)
                if len(parts) == 1:
                    new_dir = self.default_path
                else:
                    new_dir = parts[1].strip()

                if not new_dir.startswith("/"):
                    new_dir = current_dir.rstrip("/") + "/" + new_dir

                test_cmd = f"test -d {shlex.quote(new_dir)}"

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

            # Preserve exactly what the operator typed. File operations can
            # overwrite or delete data, so RBM asks before sending them but
            # never silently adds force flags such as ``-f``.
            try:
                command_name = shlex.split(cmd, posix=True)[0]
            except (ValueError, IndexError):
                command_name = cmd.split(maxsplit=1)[0] if cmd.split() else ""
            if command_name in {"rm", "mv", "cp"}:
                operation = {
                    "rm": "delete files",
                    "mv": "move or overwrite files",
                    "cp": "copy or overwrite files",
                }[command_name]
                if not messagebox.askyesno(
                    "Confirm file operation",
                    f"This command can {operation}.\n\n"
                    "RBM will send it exactly as typed:\n"
                    f"{cmd}\n\nContinue?",
                    parent=win,
                ):
                    append("[INFO] File operation cancelled.\n")
                    return

            interactive_cmds = ["vim", "vi", "nano", "top", "htop", "less", "more"]
            base_cmd = cmd.split()[0] if cmd.split() else ""
            if base_cmd in interactive_cmds:
                append(
                    f"[INFO] '{base_cmd}' is an interactive command and cannot run "
                    f"in this terminal.\n"
                    f"       Use a system terminal for interactive editors or tools.\n"
                )
                return

            is_script = (
                cmd.startswith("python ")
                or cmd.startswith("python3 ")
                or cmd.startswith("sh ")
                or cmd.startswith("bash ")
                or cmd.endswith(".sh")
                or ".sh " in cmd
                or cmd.endswith(".py")
                or ".py " in cmd
            )
            # Test scripts often invoke EnergyManagerTestingTool directly.
            # Give them the same standard PATH and library setup as RBM Send.
            script_environment = ""
            if is_script:
                script_environment = (
                    "export PATH=/usr/local/bin:/usr/bin:/bin:$PATH; "
                    "export LD_LIBRARY_PATH=/usr/local/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}; "
                )
            full_cmd = f"cd {shlex.quote(current_dir)} && {script_environment}{cmd}"
            append(f"\n{current_dir} $ {cmd}\n")
            if is_script:
                append("[INFO] Script started. Output will appear as it is received.\n")
            script_running[0] = is_script
            set_terminal_busy(True)

            def cb(res):
                try:
                    stdout = (res.get("out") or "").strip()
                    stderr = (res.get("err") or "").strip()
                    success = res.get("success", False)

                    def _ui():
                        if stdout and not is_script:
                            append(stdout + "\n")
                        if stderr:
                            append("[ERROR] " + stderr + "\n")
                        if success and not stdout and not stderr:
                            append("[OK]\n")
                        if is_script:
                            if success:
                                append("[INFO] Script finished.\n")
                            else:
                                if not stderr:
                                    code = res.get("returncode")
                                    append(
                                        "[ERROR] Script stopped"
                                        f" (exit code {code}).\n"
                                    )
                                append("[INFO] Script stopped with an error.\n")
                        script_running[0] = False
                        set_terminal_busy(False)

                    try:
                        if not self._closing and self.root.winfo_exists():
                            self.root.after(0, _ui)
                    except Exception:
                        pass
                except Exception as e:
                    try:
                        self.root.after(
                            0,
                            lambda: (
                                append(f"[ERROR] {e}\n"),
                                script_running.__setitem__(0, False),
                                set_terminal_busy(False),
                            ),
                        )
                    except Exception:
                        pass

            def on_stream(chunk):
                append(chunk)

            self.ssh_queue.execute(
                full_cmd,
                callback=cb,
                timeout=None if is_script else self.ssh_timeout,
                auto_retry=False,
                log_errors=False,
                command_type="terminal_cmd",
                silent=False,
                label=f"Terminal: {cmd[:60]}",
                stream_callback=on_stream if is_script else None,
                cancel_token="terminal_script" if is_script else None,
            )

        def complete_token(event=None):
            """Complete a command name or a remote file path with the Tab key."""
            if terminal_busy[0]:
                append("[INFO] Completion is unavailable while a command is running.\n")
                return "break"
            if completion_pending[0]:
                return "break"

            value = entry.get()
            stripped = value.lstrip()
            if not stripped:
                append("[INFO] Type a command or path before pressing Tab.\n")
                return "break"

            words = stripped.split()
            if len(words) == 1 and " " not in stripped:
                commands = [
                    "ls", "cd", "pwd", "cat", "cp", "mv", "rm",
                    "python3", "sh", "bash", "grep", "tail", "journalctl",
                    "clear", "help",
                ]
                matches = [command for command in commands if command.startswith(stripped)]
                if len(matches) == 1:
                    entry.delete(0, "end")
                    entry.insert(0, matches[0] + " ")
                elif len(matches) > 1:
                    append("[TAB] " + "  ".join(matches) + "\n")
                else:
                    append(f"[TAB] No command starts with '{stripped}'.\n")
                return "break"

            token = words[-1]
            value_prefix = value[: len(value) - len(token)]
            completion_cmd = (
                f"cd {shlex.quote(current_dir)} && "
                f"for item in {shlex.quote(token)}*; do "
                '[ -e "$item" ] || continue; '
                'if [ -d "$item" ]; then printf "%s/\\n" "$item"; '
                'else printf "%s\\n" "$item"; fi; '
                "done"
            )
            requested_value = value
            completion_pending[0] = True

            def completion_callback(res):
                completion_pending[0] = False
                candidates = [
                    line.strip()
                    for line in (res.get("out") or "").splitlines()
                    if line.strip()
                ]
                error = (res.get("err") or "").strip()
                if error:
                    append("[ERROR] " + error + "\n")
                    return
                if not candidates:
                    append(f"[TAB] No match for '{token}'.\n")
                    return
                if len(candidates) == 1 and entry.get() == requested_value:
                    entry.delete(0, "end")
                    entry.insert(0, value_prefix + candidates[0])
                    return
                append("[TAB] " + "  ".join(candidates) + "\n")

            self.ssh_queue.execute(
                completion_cmd,
                callback=completion_callback,
                timeout=min(self.ssh_timeout, 5),
                auto_retry=False,
                log_errors=False,
                command_type="terminal_completion",
                silent=True,
                label="Terminal completion",
            )
            return "break"

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
        entry.bind("<Tab>", complete_token)
        entry.bind("<Up>", history_up)
        entry.bind("<Down>", history_down)
        entry.focus_force()

        append(
            "RBM SSH Terminal ready.\n"
            f"Connected to {self.host}\n"
            "Type 'help' for commands.\n"
        )

        def _on_close(force=False):
            if script_running[0]:
                if not force:
                    self._popup_warning(
                        "Terminal",
                        "A script is still running. Stop it or wait for completion before closing the terminal.",
                    )
                    return False
                self.ssh_queue.cancel_active_stream("terminal_script")
                script_running[0] = False
                terminal_busy[0] = False
            try:
                self._close_terminal_window = None
                self._terminal_window = None
                self._terminal_prefill_command = None
            except Exception:
                pass
            try:
                win.destroy()
            except Exception:
                pass
            return True

        self._close_terminal_window = _on_close
        win.protocol("WM_DELETE_WINDOW", _on_close)

        if initial_command:
            prefill_command(initial_command)

    
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

                self.host = ssh_cfg.get("host", "")
                self.user = ssh_cfg.get("username", "")
                self.password = ssh_cfg.get("password", "")
                self.port = int(ssh_cfg.get("port", "22"))
                self.default_path = paths_cfg.get(
                    "remote_path", "/etc/iotecha/configs/GridCodes"
                )
                self.remote_file = paths_cfg.get("remote_file", "GridCodes.properties")
                self.local_default_path = _ensure_local_export_dir(
                    paths_cfg.get("local_path", EXPORTS_DIR)
                )
                self.netlogger_path = paths_cfg.get(
                    "netlogger_path", NETLOGGER_DEFAULT_PATH
                ).strip() or NETLOGGER_DEFAULT_PATH
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
                    target_changed = (
                        previous_ssh[0] != self.host
                        or previous_ssh[3] != self.port
                    )
                    if target_changed:
                        # A new EVSE can legitimately reuse an old test IP.
                        # Remove only this target's stale PuTTY key before the
                        # application restarts and verifies the new target.
                        self.ssh.clear_cached_host_keys(self.host, self.port)
                    # Close the active session first so the former EVSE cannot
                    # remain connected while the replacement process starts.
                    self.log("[NETWORK] SSH target changed, closing current session.")
                    self._manual_disconnect()
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
        if self._sequence_operation_blocked("Opening Debug logs"):
            return
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
        self._stop_local_simulator_server()
        self.root.after(150, self.root.destroy)

    # --------------------------------------------------------------
    # Helpers pour popups MODALES et toujours au premier plan
    # --------------------------------------------------------------
    def _show_popup(self, popup, title: str, message: str, parent=None):
        """Show a native dialog without lowering an already-modal parent."""
        win = parent or self.root
        try:
            was_topmost = bool(int(win.attributes("-topmost")))
        except (tk.TclError, TypeError, ValueError):
            was_topmost = False
        try:
            win.lift()
            win.attributes("-topmost", True)
            popup(title, message, parent=win)
        finally:
            try:
                win.attributes("-topmost", was_topmost)
                if was_topmost:
                    win.lift()
            except tk.TclError:
                pass

    def _popup_info(self, title: str, message: str, parent=None):
        self._show_popup(messagebox.showinfo, title, message, parent)

    def _popup_warning(self, title: str, message: str, parent=None):
        self._show_popup(messagebox.showwarning, title, message, parent)

    def _popup_error(self, title: str, message: str, parent=None):
        self._show_popup(messagebox.showerror, title, message, parent)

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
