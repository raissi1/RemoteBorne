import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import configparser
import os


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
    if "PATHS" not in cfg:
        cfg["PATHS"] = {
            "remote_path": "/etc/iotecha/configs/GridCodes",
            "remote_file": "GridCodes.properties",
            "local_path": os.path.expanduser("~/Downloads"),
        }

    # Fenêtre
    win = tk.Toplevel(parent)
    win.title("Network Configuration")
    win.geometry("600x350")
    win.resizable(False, False)
    win.transient(parent)
    win.grab_set()

    win.update_idletasks()
    x = (win.winfo_screenwidth() - 600) // 2
    y = (win.winfo_screenheight() - 350) // 2
    win.geometry(f"+{x}+{y}")

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

    # PATHS
    ttk.Label(main_frame, text="Remote path:").grid(
        row=4, column=0, sticky="w", padx=10, pady=5
    )
    rpath_entry = ttk.Entry(main_frame)
    rpath_entry.insert(0, cfg["PATHS"].get("remote_path", ""))
    rpath_entry.grid(row=4, column=1, sticky="ew", padx=10)

    ttk.Label(main_frame, text="Remote file:").grid(
        row=5, column=0, sticky="w", padx=10, pady=5
    )
    rfile_entry = ttk.Entry(main_frame)
    rfile_entry.insert(0, cfg["PATHS"].get("remote_file", "GridCodes.properties"))
    rfile_entry.grid(row=5, column=1, sticky="ew", padx=10)

    ttk.Label(main_frame, text="Local path:").grid(
        row=6, column=0, sticky="w", padx=10, pady=5
    )
    lpath_entry = ttk.Entry(main_frame)
    lpath_entry.insert(0, cfg["PATHS"].get("local_path", ""))
    lpath_entry.grid(row=6, column=1, sticky="ew", padx=10)

    def browse_local():
        folder = filedialog.askdirectory(title="Select local folder")
        if folder:
            lpath_entry.delete(0, tk.END)
            lpath_entry.insert(0, folder)

    ttk.Button(main_frame, text="Browse", command=browse_local).grid(
        row=6, column=2, padx=5
    )

    # Boutons
    def save_and_close():
        cfg["SSH"]["host"] = ip_entry.get().strip()
        cfg["SSH"]["username"] = user_entry.get().strip()
        cfg["SSH"]["password"] = pass_entry.get().strip()
        cfg["SSH"]["port"] = cfg["SSH"].get("port", "22")

        cfg["PATHS"]["remote_path"] = rpath_entry.get().strip()
        cfg["PATHS"]["remote_file"] = rfile_entry.get().strip()
        cfg["PATHS"]["local_path"] = lpath_entry.get().strip()

        try:
            with open(config_path, "w", encoding="utf-8") as f:
                cfg.write(f)
            messagebox.showinfo("Network", "Configuration saved successfully.")
            if callable(on_saved):
                on_saved()
            win.destroy()
        except Exception as e:
            messagebox.showerror("Error", f"Error saving configuration:\n{e}")

    ttk.Button(main_frame, text="Save", command=save_and_close).grid(
        row=7, column=1, pady=20, sticky="e", padx=5
    )
    ttk.Button(main_frame, text="Cancel", command=win.destroy).grid(
        row=7, column=2, pady=20, sticky="w", padx=5
    )

    main_frame.columnconfigure(1, weight=1)
    win.minsize(550, 350)

    win.wait_window()
