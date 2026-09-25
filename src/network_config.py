import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import configparser
import os
import ipaddress

try:
    from .utils_ui import center_window
except ImportError:
    try:
        from utils_ui import center_window
    except ImportError:
        from src.utils_ui import center_window


def open_network_config(parent, config_path, on_saved=None):
    """
    Ouvre la configuration réseau (SSH + PATHS) en modal strict.

    parent      : fenêtre parente Tk
    config_path : chemin complet du config.ini (ex: .../config/config.ini)
    on_saved    : callback appelé après sauvegarde (peut être None)
    """
    # S'assure que le dossier de config existe
    config_dir = os.path.dirname(config_path)
    os.makedirs(config_dir, exist_ok=True)

    # Charger ou créer la config
    cfg = configparser.ConfigParser()
    if os.path.exists(config_path):
        cfg.read(config_path, encoding="utf-8")
    if "SSH" not in cfg:
        cfg["SSH"] = {
            "host": "",
            "username": "root",
            "password": "",
            "port": "22",
        }
    runtime_root = os.path.dirname(os.path.dirname(os.path.abspath(config_path)))
    export_dir = os.path.join(runtime_root, "exports")

    def normalize_local_dir(value: str) -> str:
        candidate = os.path.normpath(os.path.expanduser((value or "").strip()))
        if candidate and os.path.splitext(os.path.basename(candidate))[1]:
            candidate = os.path.dirname(candidate)
        if candidate and not os.path.isabs(candidate):
            candidate = os.path.join(runtime_root, candidate)
        return os.path.abspath(candidate) if candidate else export_dir

    if "PATHS" not in cfg:
        cfg["PATHS"] = {
            "remote_path": "/etc/iotecha/configs/GridCodes",
            "remote_file": "GridCodes.properties",
            "local_path": export_dir,
            "netlogger_path": "/var/aux/netlogger",
        }

    # Fenêtre
    win = tk.Toplevel(parent)
    win.withdraw()
    win.title("Network Configuration")
    win.geometry("640x475")
    win.resizable(False, False)
    center_window(parent, win, 640, 430)

    def show_error(title: str, message: str):
        win.lift()
        messagebox.showerror(title, message, parent=win)
        win.lift()
        win.focus_force()

    def show_info(title: str, message: str):
        win.lift()
        messagebox.showinfo(title, message, parent=win)
        win.lift()
        win.focus_force()

    def close_window():
        try:
            win.grab_release()
        except tk.TclError:
            pass
        try:
            win.destroy()
        except tk.TclError:
            pass

    win.protocol("WM_DELETE_WINDOW", close_window)

    main_frame = ttk.Frame(win, padding=20)
    main_frame.pack(expand=True, fill="both")

    # Titre
    ttk.Label(
        main_frame,
        text="SSH and Path Configuration",
        font=("Segoe UI", 14, "bold"),
    ).grid(row=0, column=0, columnspan=3, pady=(0, 20), sticky="w")

    # Champs SSH
    ttk.Label(main_frame, text="IP Address:").grid(
        row=1, column=0, sticky="w", padx=10, pady=5
    )
    ip_entry = ttk.Entry(main_frame)
    ip_entry.insert(0, cfg["SSH"].get("host", ""))
    ip_entry.grid(row=1, column=1, columnspan=2, sticky="ew", padx=10)

    ttk.Label(main_frame, text="Username:").grid(
        row=2, column=0, sticky="w", padx=10, pady=5
    )
    user_entry = ttk.Entry(main_frame)
    user_entry.insert(0, cfg["SSH"].get("username", "root"))
    user_entry.grid(row=2, column=1, columnspan=2, sticky="ew", padx=10)

    ttk.Label(main_frame, text="Password:").grid(
        row=3, column=0, sticky="w", padx=10, pady=5
    )
    pass_entry = ttk.Entry(main_frame, show="*")
    pass_entry.insert(0, cfg["SSH"].get("password", ""))
    pass_entry.grid(row=3, column=1, columnspan=2, sticky="ew", padx=10)

    ttk.Label(main_frame, text="Port:").grid(
        row=4, column=0, sticky="w", padx=10, pady=5
    )
    port_entry = ttk.Entry(main_frame, width=8)
    port_entry.insert(0, cfg["SSH"].get("port", "22"))
    port_entry.grid(row=4, column=1, sticky="w", padx=10)

    # PATHS
    ttk.Label(main_frame, text="Remote path:").grid(
        row=5, column=0, sticky="w", padx=10, pady=5
    )
    rpath_entry = ttk.Entry(main_frame)
    rpath_entry.insert(0, cfg["PATHS"].get("remote_path", ""))
    rpath_entry.grid(row=5, column=1, sticky="ew", padx=10)

    ttk.Label(main_frame, text="Remote file:").grid(
        row=6, column=0, sticky="w", padx=10, pady=5
    )
    rfile_entry = ttk.Entry(main_frame)
    rfile_entry.insert(0, cfg["PATHS"].get("remote_file", "GridCodes.properties"))
    rfile_entry.grid(row=6, column=1, sticky="ew", padx=10)

    ttk.Label(main_frame, text="Local export folder:").grid(
        row=7, column=0, sticky="w", padx=10, pady=5
    )
    lpath_entry = ttk.Entry(main_frame)
    lpath_entry.insert(0, normalize_local_dir(cfg["PATHS"].get("local_path", "")))
    lpath_entry.grid(row=7, column=1, sticky="ew", padx=10)

    def browse_local():
        folder = filedialog.askdirectory(parent=win, title="Select local folder")
        if folder:
            lpath_entry.delete(0, tk.END)
            lpath_entry.insert(0, folder)

    ttk.Button(main_frame, text="Browse", command=browse_local).grid(
        row=7, column=2, padx=5
    )

    ttk.Label(main_frame, text="NetLogger folder:").grid(
        row=8, column=0, sticky="w", padx=10, pady=5
    )
    netlogger_entry = ttk.Entry(main_frame)
    netlogger_entry.insert(
        0, cfg["PATHS"].get("netlogger_path", "/var/aux/netlogger")
    )
    netlogger_entry.grid(row=8, column=1, columnspan=2, sticky="ew", padx=10)

    # Boutons
    def _is_valid_host(value: str) -> bool:
        if not value:
            return False
        # Accepte IPv4/IPv6 ou hostname simple
        try:
            ipaddress.ip_address(value)
            return True
        except ValueError:
            return all(
                chunk and chunk.replace("-", "").isalnum()
                for chunk in value.split(".")
            )

    def save_and_close():
        host = ip_entry.get().strip()
        username = user_entry.get().strip()
        password = pass_entry.get().strip()
        port_raw = port_entry.get().strip()
        remote_path = rpath_entry.get().strip()
        remote_file = rfile_entry.get().strip()
        local_path = normalize_local_dir(lpath_entry.get())
        netlogger_path = netlogger_entry.get().strip()

        if not _is_valid_host(host):
            show_error("Validation", "Invalid IP address or hostname.")
            return
        if not username:
            show_error("Validation", "Username is required.")
            return
        try:
            port = int(port_raw)
            if not (1 <= port <= 65535):
                raise ValueError
        except ValueError:
            show_error("Validation", "Invalid port (1-65535).")
            return
        if not remote_path:
            show_error("Validation", "Remote path is required.")
            return
        if not remote_file:
            show_error("Validation", "Remote file is required.")
            return
        if not local_path:
            show_error("Validation", "Local path is required.")
            return
        if not netlogger_path.startswith("/"):
            show_error(
                "Validation", "NetLogger folder must be an absolute remote path."
            )
            return

        try:
            os.makedirs(local_path, exist_ok=True)
        except Exception as e:
            show_error("Validation", f"Local path inaccessible:\n{e}")
            return

        cfg["SSH"]["host"] = host
        cfg["SSH"]["username"] = username
        cfg["SSH"]["password"] = password
        cfg["SSH"]["port"] = str(port)

        cfg["PATHS"]["remote_path"] = remote_path
        cfg["PATHS"]["remote_file"] = remote_file
        cfg["PATHS"]["local_path"] = local_path
        cfg["PATHS"]["netlogger_path"] = netlogger_path

        try:
            with open(config_path, "w", encoding="utf-8") as f:
                cfg.write(f)
            show_info("Network", "Configuration saved successfully.")
            if callable(on_saved):
                on_saved()
            close_window()
        except Exception as e:
            show_error("Error", f"Error saving configuration:\n{e}")

    ttk.Button(main_frame, text="Save", command=save_and_close).grid(
        row=9, column=1, pady=(24, 8), sticky="e", padx=5
    )
    ttk.Button(main_frame, text="Cancel", command=close_window).grid(
        row=9, column=2, pady=(24, 8), sticky="w", padx=5
    )

    main_frame.columnconfigure(1, weight=1)
    win.minsize(620, 465)

    # Build first, then show the completed modal window above RBM only.
    win.transient(parent)
    win.deiconify()
    win.lift()
    win.focus_force()
    win.grab_set()

    # Non-bloquant: la fenêtre reste modale via grab_set mais n'arrête pas la boucle appelante
