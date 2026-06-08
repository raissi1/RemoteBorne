import datetime
import os
import sys
import tkinter as tk
from tkinter import ttk


def _center_over_parent(parent, win, w=980, h=760):
    if parent is not None:
        try:
            parent.update_idletasks()
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            if pw > 1 and ph > 1:
                x = px + (pw - w) // 2
                y = py + (ph - h) // 2
                win.geometry(f"{w}x{h}+{max(x, 0)}+{max(y, 0)}")
                return
        except Exception:
            pass

    win.update_idletasks()
    sw = win.winfo_screenwidth()
    sh = win.winfo_screenheight()
    x = (sw - w) // 2
    y = (sh - h) // 2
    win.geometry(f"{w}x{h}+{max(x, 0)}+{max(y, 0)}")


def open_help(parent=None):
    if parent is not None:
        try:
            if getattr(parent, "_closing", False):
                return
        except Exception:
            pass

    win = tk.Toplevel(parent)
    win.title("RBM Help")
    win.geometry("1000x800")
    win.minsize(850, 600)

    try:
        if parent is not None:
            win.transient(parent)
            win.grab_set()
            win.focus_force()
            win.lift()
    except Exception:
        pass

    _center_over_parent(parent, win, 980, 760)
    win.after(30, lambda: _center_over_parent(parent, win, 980, 760))

    def _close():
        try:
            if win.winfo_exists():
                win.destroy()
        except Exception:
            pass

    win.bind("<Escape>", lambda _e: _close())

    main = ttk.Frame(win)
    main.pack(fill="both", expand=True, padx=10, pady=10)

    top = ttk.Frame(main)
    top.pack(fill="x", pady=(0, 10))

    ttk.Label(
        top,
        text="Remote Borne Manager - User Guide",
        font=("Segoe UI", 16, "bold"),
    ).pack(side="left")

    search_var = tk.StringVar()
    search_entry = ttk.Entry(top, textvariable=search_var, width=35)
    search_entry.pack(side="right", padx=(5, 0))
    search_entry.focus_set()

    text_frame = ttk.Frame(main)
    text_frame.pack(fill="both", expand=True)

    text = tk.Text(
        text_frame,
        wrap="word",
        font=("Segoe UI", 10),
        padx=20,
        pady=20,
        spacing3=6,
        background="#FFFFFF",
        foreground="#1E1E1E",
        relief="flat",
    )
    scroll = ttk.Scrollbar(text_frame, orient="vertical", command=text.yview)
    text.configure(yscrollcommand=scroll.set)
    text.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")

    text.tag_configure("title", font=("Segoe UI", 18, "bold"), foreground="#0F172A", spacing3=20)
    text.tag_configure("section", font=("Segoe UI", 13, "bold"), foreground="#1D4ED8", spacing1=20, spacing3=10)
    text.tag_configure("subtitle", font=("Segoe UI", 11, "bold"), foreground="#0F766E", spacing1=10, spacing3=5)
    text.tag_configure("normal", font=("Segoe UI", 10), spacing3=4)
    text.tag_configure("code", font=("Consolas", 10), foreground="#7C2D12", background="#F8FAFC")
    text.tag_configure("warning", foreground="#B91C1C", font=("Segoe UI", 10, "bold"))
    text.tag_configure("highlight", background="#FFF59D", foreground="#000000")

    script_name = os.path.basename(sys.argv[0])
    today = datetime.date.today()

    def add_subtitle(title, body, tag="normal"):
        text.insert("end", title, "subtitle")
        text.insert("end", body + "\n", tag)

    text.insert("end", "Remote Borne Manager - Help\n", "title")

    text.insert("end", "\n1. OVERVIEW\n", "section")
    text.insert(
        "end",
        "Remote Borne Manager (RBM) is an industrial desktop application used to manage chargers remotely through SSH and SCP.\n\n",
        "normal",
    )
    text.insert("end", "Main capabilities:\n", "subtitle")
    for item in [
        "SSH connection and session monitoring",
        "GridCodes browser with full right-click menu",
        "remote editing, upload, download, and PDF print",
        "Energy Manager PRO in P/Q and CosPhi modes",
        "Restart services, Reboot device, and Debug logs",
        "Network config with clean restart when SSH settings change",
        "temperature and Battery SoC monitoring",
        "integrated SSH terminal with history and persistent cd",
    ]:
        text.insert("end", f"- {item}\n", "normal")

    text.insert("end", "\n2. STARTUP\n", "section")
    add_subtitle("Python mode\n", f"python {script_name}\n", "code")
    add_subtitle("Executable mode\n", "Launch RBM.exe\n", "code")

    text.insert("end", "\n3. CONNECTION AND NETWORK\n", "section")
    text.insert(
        "end",
        "The Connect button opens the SSH session and initializes the remote interface. Disconnect closes the session and prevents an immediate auto reconnect.\n\n"
        "When the IP address, port, or credentials are changed from Network config, the application saves the new settings and restarts cleanly. This replaces the older hot reconnect approach.\n",
        "normal",
    )

    text.insert("end", "\n4. GRIDCODES BROWSER\n", "section")
    text.insert(
        "end",
        "The remote browser supports:\n"
        "- double-click a folder to enter it\n"
        "- double-click [.] (Parent) to go up\n"
        "- remote list refresh\n"
        "- current path update\n\n"
        "File context menu:\n"
        "- Edit\n"
        "- Download\n"
        "- Print\n"
        "- Copy to GridCodes.properties\n"
        "- Delete\n\n"
        "Folder context menu:\n"
        "- Delete\n",
        "normal",
    )

    text.insert("end", "\n5. EDIT, UPLOAD, DOWNLOAD, PRINT\n", "section")
    text.insert(
        "end",
        "Remote editor features:\n"
        "- local Find in the editor\n"
        "- Save and Save As\n"
        "- LF line ending normalization\n\n"
        "Download, Print, and editor file loading run in background workers to avoid UI freezes.\n\n"
        "Upload includes a remote file size verification step.\n",
        "normal",
    )

    text.insert("end", "\n6. TEMPERATURE / BATTERY SOC MONITORING\n", "section")
    text.insert(
        "end",
        "The Temperature / Derating panel shows charger temperature and Battery SoC.\n"
        "The ↻ button performs an immediate manual refresh of both values.\n",
        "normal",
    )

    text.insert("end", "\n7. ENERGY MANAGER PRO\n", "section")
    text.insert(
        "end",
        "Energy Manager PRO is used for energy control through a dedicated window.\n\n"
        "P/Q mode:\n"
        "- Active Power P\n"
        "- Reactive Power Q\n"
        "- Send P/Q\n\n"
        "CosPhi mode:\n"
        "- Active Power P\n"
        "- CosPhi\n"
        "- Calculate Q\n"
        "- Send CosPhi\n\n",
        "normal",
    )
    text.insert("end", "Q = |P| * tan(acos(CosPhi))\n", "code")

    text.insert("end", "\n8. INTEGRATED SSH TERMINAL\n", "section")
    text.insert(
        "end",
        "Open it from Terminal -> Open Terminal.\n\n"
        "Features:\n"
        "- Up / Down history\n"
        "- persistent cd\n"
        "- clear\n"
        "- help\n"
        "- simple shell commands\n"
        "- Python and shell script execution\n\n"
        "Blocked interactive commands:\n"
        "- vim\n"
        "- vi\n"
        "- nano\n"
        "- top\n"
        "- htop\n"
        "- less\n"
        "- more\n\n"
        "For UI safety and consistency, rm / mv / cp are forced with -f.\n",
        "normal",
    )

    text.insert("end", "\n9. DEBUG LOGS AND MAINTENANCE\n", "section")
    text.insert(
        "end",
        "The Debug logs menu opens the remote log follow window.\n\n"
        "Available maintenance actions:\n"
        "- Restart services\n"
        "- Reboot device\n"
        "- Debug logs\n",
        "normal",
    )

    text.insert("end", "\n10. ARCHITECTURE AND STABILITY\n", "section")
    text.insert(
        "end",
        "RBM relies on a centralized architecture with SSHQueue for critical commands, explicit SCP timeouts, protected Tkinter callbacks, and cleaner transport failure handling.\n",
        "normal",
    )
    text.insert("end", "Recommended for controlled local industrial networks.\n", "warning")

    text.insert("end", "\n11. KNOWN LIMITS\n", "section")
    text.insert(
        "end",
        "- Save and Save As still share a very similar remote naming flow\n"
        "- exact Battery SoC accuracy still needs hardware revalidation\n"
        "- some long-duration and rapid multi-action scenarios still need field retesting\n",
        "normal",
    )

    text.insert("end", "\n12. VERSION\n", "section")
    text.insert("end", f"Remote Borne Manager 3.x PRO\nDate: {today}\n\nAuthor: Nabil RAISSI\n", "normal")

    text.bind("<Key>", lambda _e: "break")

    def find_text():
        text.tag_remove("highlight", "1.0", "end")
        query = search_var.get().strip()
        if not query:
            return
        start = "1.0"
        while True:
            pos = text.search(query, start, stopindex="end", nocase=True)
            if not pos:
                break
            end = f"{pos}+{len(query)}c"
            text.tag_add("highlight", pos, end)
            start = end
        ranges = text.tag_ranges("highlight")
        if ranges:
            text.see(ranges[0])

    search_entry.bind("<Return>", lambda _e: find_text())

    bottom = ttk.Frame(main)
    bottom.pack(fill="x", pady=(10, 0))
    ttk.Button(bottom, text="Find", command=find_text).pack(side="left")
    ttk.Button(bottom, text="Close", command=_close).pack(side="right")

    text.configure(state="disabled")
