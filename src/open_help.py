import datetime
import os
import sys
import tkinter as tk
from tkinter import ttk

try:
    from .utils_ui import center_window
except ImportError:
    try:
        from utils_ui import center_window
    except ImportError:
        from src.utils_ui import center_window


def open_help(parent=None):
    if parent is not None:
        try:
            if getattr(parent, "_closing", False):
                return
        except Exception:
            pass

    win = tk.Toplevel(parent)
    win.withdraw()
    win.title("RBM V16.1.0 Help")
    win.geometry("1000x800")
    win.minsize(850, 600)

    center_window(parent, win, 980, 760)

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
        text="Remote Borne Control Interface V16.1.0 - User Guide",
        font=("Segoe UI", 16, "bold"),
    ).pack(side="left")

    search_var = tk.StringVar()
    search_entry = ttk.Entry(top, textvariable=search_var, width=35)
    search_entry.pack(side="right", padx=(5, 0))
    search_entry.focus_set()
    ttk.Label(top, text="Find:").pack(side="right")

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
        "Remote Borne Control Interface (RBM) is an industrial desktop application used to manage chargers remotely through SSH and SCP.\n\n",
        "normal",
    )
    text.insert("end", "Main capabilities:\n", "subtitle")
    for item in [
        "SSH connection and session monitoring",
        "GridCodes browser with full right-click menu",
        "remote editing, upload, download, and PDF print",
        "direct access to the active GridCodes.properties and NetLogger log downloads",
        "Energy Manager PRO in P/Q and CosPhi modes",
        "automated P/Q and CosPhi Test Sequence with CSV import and save",
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
        "When the IP address, port, or credentials are changed from Network config, RBM closes the active SSH session before restarting with the new settings.\n\n"
        "While connected, RBM monitors the SSH transport and attempts recovery after repeated communication failures. Disconnect intentionally stops automatic reconnection.\n\n"
        "Practical notes:\n"
        "- a new SSH host key requires explicit operator confirmation; a changed cached key blocks the connection\n"
        "- Network config also stores the default GridCodes paths used by the browser and editor\n"
        "- after an application restart, reconnect normally from the main window\n",
        "normal",
    )

    text.insert("end", "\n4. GRIDCODES BROWSER\n", "section")
    text.insert(
        "end",
        "The remote browser supports:\n"
        "- double-click a folder to enter it\n"
        "- double-click [.] (Parent) to go up\n"
        "- remote list refresh\n"
        "- Find filters the current folder locally while typing; after a short pause, RBM searches the current folder and all subfolders\n"
        "- Find or Enter starts that recursive search immediately; use a word or a wildcard such as *Power*. Results are grouped by folder and a double-click opens the result folder\n"
        "- Clear or a folder navigation restores the full list\n"
        "- current path update\n"
        "- one navigation action at a time; repeated clicks are ignored until the remote action completes\n"
        "- the previous valid listing remains visible while the next folder loads\n\n"
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
        "- Save overwrites the current remote file\n"
        "- Save As uploads to a new remote target name or path\n"
        "- LF line ending normalization\n\n"
        "Download, Print, and editor file loading run in background workers to avoid UI freezes.\n\n"
        "Upload includes a remote file size verification step.\n"
        "If a file already exists remotely, RBM asks for confirmation before overwrite.\n",
        "normal",
    )

    add_subtitle("Active GridCodes.properties\n", "Use Edit current GridCodes.properties to open the active configuration directly, without searching for it in the browser.")
    add_subtitle("NetLogger logs\n", "Use NetLogger logs to list the files in the configured NetLogger folder, select multiple files, and download them to one local folder. The remote NetLogger folder can be changed in Network configuration.")

    text.insert("end", "\n6. TEMPERATURE / BATTERY SOC MONITORING\n", "section")
    text.insert(
        "end",
        "The Temperature / Derating panel shows charger temperature and Battery SoC.\n"
        "The manual refresh button performs an immediate refresh of both values. Temperature remains available when no SoC is present in the charger log.\n"
        "Automatic updates continue while the SSH session remains healthy.\n",
        "normal",
    )

    text.insert("end", "\n7. ENERGY MANAGER PRO\n", "section")
    text.insert(
        "end",
        "Energy Manager PRO is used for energy control through a dedicated window.\n\n"
        "P/Q mode:\n"
        "- Pn max: type a value or read it from GridCodes.properties; use either the -100% to +100% slider or the P [%] field to write the calculated value into Active Power P\n"
        "  (PowerMax_1Ph_VAr for GridTopology=SinglePhase; PowerMax_3Ph_VAr for GridTopology=ThreePhase)\n"
        "- Active Power P\n"
        "- Reactive Power Q\n"
        "- Send P/Q\n\n"
        "CosPhi mode:\n"
        "- Active Power P\n"
        "- CosPhi\n"
        "- Calculate Q\n"
        "- Send CosPhi\n\n"
        "CosPhi returns immediately as sent, prevents repeated clicks while execution is pending, then reports confirmation or error after the target completes the command.\n\n"
        "The lower area provides command history export and a service monitor / restart panel.\n\n",
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
        "- Tab completion for commands and remote paths\n"
        "- clear\n"
        "- help\n"
        "- simple shell commands\n"
        "- Python and shell script execution\n\n"
        "Double-click a .py or .sh file in the GridCodes browser to open this terminal with its command prefilled. Add any required options, then press Enter.\n\n"
        "A running script has SSH priority: other RBM commands wait until it completes.\n"
        "Use Stop script only when interruption is required; a detached target process may continue on the EVSE.\n\n"
        "Typical safe examples:\n"
        "- pwd\n"
        "- ls\n"
        "- cd /etc/iotecha/configs/GridCodes\n"
        "- python FR_cosphi_to_Q.py\n\n"
        "Blocked interactive commands:\n"
        "- vim\n"
        "- vi\n"
        "- nano\n"
        "- top\n"
        "- htop\n"
        "- less\n"
        "- more\n\n"
        "Use rm, mv, and cp with caution: they can change or remove files on the EVSE. "
        "RBM asks for confirmation and sends the command exactly as typed; it never adds force options automatically.\n",
        "normal",
    )

    text.insert("end", "\n9. TEST SEQUENCE\n", "section")
    text.insert(
        "end",
        "Open Test Sequence from Tests > Test Sequence in the main menu. It runs a controlled list of P/Q and CosPhi plateaus in the configured order.\n\n"
        "For each step:\n"
        "- use Active Power Helper (Pn): Read Pn reads the active GridCodes.properties limit, then P [%] automatically fills Active Power P from -100% to +100%\n"
        "- select P/Q or CosPhi mode\n"
        "- enter Active Power P and the hold duration in seconds\n"
        "- in P/Q mode, Reactive Power Q is optional; leave it blank to send P without a reactive option\n"
        "- in CosPhi mode, leave CosPhi blank to use 1\n"
        "- use Add, Update, Remove, and Move controls to prepare the scenario\n\n"
        "Test Sequence is a modal window: while it remains open, RBM blocks access to the main application, including GridCodes changes, manual setpoints, maintenance, Terminal, and Debug logs. Close Test Sequence to restore main-window access. Start sends one plateau at a time. Pause freezes the remaining hold time, Resume continues it, and Stop prevents all remaining plateaus from being sent. A remote command error or SSH disconnection stops the sequence automatically. Use Save as CSV to choose the sequence file name and location; use Import sequence to reload a saved scenario. Steps are kept only for the current RBM session, so import the saved CSV again after a full application restart.\n\n"
        "Validate the full scenario and the EVSE test conditions before starting. Monitor the main logs during execution; the sequence does not replace the protected Restart services or Reboot device procedures.\n",
        "normal",
    )

    text.insert("end", "\n10. LOCAL SIMULATOR\n", "section")
    text.insert(
        "end",
        "Use Tools -> Start local simulator and connect to validate RBM without a physical charger. "
        "RBM starts an isolated SSH/SCP EVSE on 127.0.0.1:2222, switches only the current session, "
        "and displays a SIMULATION MODE banner. The configured charger profile in config.ini is never changed. "
        "Use Reset local simulator to restore demo GridCodes, logs, temperatures and SoC. Use Return to configured charger "
        "before Stop local simulator, or simply close RBM: the local simulator stops automatically. "
        "This mode validates RBM workflows, not electrical or firmware behaviour of a real EVSE.\n",
        "normal",
    )

    text.insert("end", "\n11. DEBUG LOGS AND MAINTENANCE\n", "section")
    text.insert(
        "end",
        "The Debug logs menu opens the remote log follow window.\n\n"
        "Debug log window features:\n"
        "- live follow of the main remote logs\n"
        "- uses the host key already approved for the current RBM connection\n"
        "- local save of the captured output\n"
        "- safer close behavior while readers are still stopping\n\n"
        "Available maintenance actions:\n"
        "- Restart services\n"
        "- Reboot device\n"
        "- Debug logs\n",
        "normal",
    )

    text.insert("end", "\n12. ARCHITECTURE AND STABILITY\n", "section")
    text.insert(
        "end",
        "RBM relies on a centralized architecture with SSHQueue for critical commands, explicit SCP timeouts, protected Tkinter callbacks, and cleaner transport failure handling.\n",
        "normal",
    )
    text.insert("end", "Recommended for controlled local industrial networks.\n", "warning")

    text.insert("end", "\n13. KNOWN LIMITS\n", "section")
    text.insert(
        "end",
        "- Battery SoC depends on the latest value available in charger logs and current vehicle activity\n"
        "- long-duration and rapid multi-action scenarios should still be revalidated on the real bench after infrastructure changes\n"
        "- host key changes on the target still require normal SSH trust verification before reconnecting\n",
        "normal",
    )

    text.insert("end", "\n14. VERSION\n", "section")
    text.insert(
        "end",
        f"Remote Borne Control Interface V16.1.0\nHelp snapshot date: {today}\n\nAuthor: Nabil RAISSI\n",
        "normal",
    )

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
    ttk.Label(
        bottom,
        text="Tip: press Enter in the search box to highlight matching text.",
    ).pack(side="left", padx=(0, 12))
    ttk.Button(bottom, text="Find", command=find_text).pack(side="left")
    ttk.Button(bottom, text="Close", command=_close).pack(side="right")

    text.configure(state="disabled")
    # Map the completed help window once, above RBM but not above other apps.
    if parent is not None:
        win.transient(parent)
    win.deiconify()
    win.lift()
    win.focus_force()
