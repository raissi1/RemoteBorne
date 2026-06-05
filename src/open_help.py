import os
import sys
import tkinter as tk
from tkinter import ttk, messagebox
import datetime


# ==========================================================
# CENTER WINDOW
# ==========================================================
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

                win.geometry(
                    f"{w}x{h}+{max(x, 0)}+{max(y, 0)}"
                )

                return

        except Exception:
            pass

    win.update_idletasks()

    sw = win.winfo_screenwidth()
    sh = win.winfo_screenheight()

    x = (sw - w) // 2
    y = (sh - h) // 2

    win.geometry(
        f"{w}x{h}+{max(x, 0)}+{max(y, 0)}"
    )


# ==========================================================
# OPEN HELP
# ==========================================================
def open_help(parent=None):

    # ======================================================
    # PROTECTION
    # ======================================================
    if parent is not None:

        try:

            if getattr(parent, "_closing", False):
                return

        except Exception:
            pass

    # ======================================================
    # WINDOW
    # ======================================================
    win = tk.Toplevel(parent)

    win.title("RemoteBorneManager –Professional Help")

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

    win.after(
        30,
        lambda: _center_over_parent(parent, win, 980, 760)
    )

    # ======================================================
    # SAFE CLOSE
    # ======================================================
    def _close():

        try:

            if win.winfo_exists():
                win.destroy()

        except Exception:
            pass

    win.bind("<Escape>", lambda e: _close())

    # ======================================================
    # MAIN FRAME
    # ======================================================
    main = ttk.Frame(win)

    main.pack(
        fill="both",
        expand=True,
        padx=10,
        pady=10
    )

    # ======================================================
    # TOP BAR
    # ======================================================
    top = ttk.Frame(main)

    top.pack(
        fill="x",
        pady=(0, 10)
    )

    title_lbl = ttk.Label(
        top,
        text="📘 User Guide",
        font=("Segoe UI", 16, "bold")
    )

    title_lbl.pack(side="left")

    # ======================================================
    # SEARCH BAR
    # ======================================================
    search_var = tk.StringVar()

    search_entry = ttk.Entry(
        top,
        textvariable=search_var,
        width=35
    )

    search_entry.pack(
        side="right",
        padx=(5, 0)
    )

    search_entry.focus_set()

    # ======================================================
    # TEXT AREA
    # ======================================================
    text_frame = ttk.Frame(main)

    text_frame.pack(
        fill="both",
        expand=True
    )

    text = tk.Text(
        text_frame,
        wrap="word",
        font=("Segoe UI", 10),
        padx=20,
        pady=20,
        spacing3=6,
        background="#FFFFFF",
        foreground="#1E1E1E",
        relief="flat"
    )

    scroll = ttk.Scrollbar(
        text_frame,
        orient="vertical",
        command=text.yview
    )

    text.configure(
        yscrollcommand=scroll.set
    )

    text.pack(
        side="left",
        fill="both",
        expand=True
    )

    scroll.pack(
        side="right",
        fill="y"
    )

    # ======================================================
    # TAGS / STYLES
    # ======================================================
    text.tag_configure(
        "title",
        font=("Segoe UI", 18, "bold"),
        foreground="#0F172A",
        spacing3=20
    )

    text.tag_configure(
        "section",
        font=("Segoe UI", 13, "bold"),
        foreground="#1D4ED8",
        spacing1=20,
        spacing3=10
    )

    text.tag_configure(
        "subtitle",
        font=("Segoe UI", 11, "bold"),
        foreground="#0F766E",
        spacing1=10,
        spacing3=5
    )

    text.tag_configure(
        "normal",
        font=("Segoe UI", 10),
        spacing3=4
    )

    text.tag_configure(
        "code",
        font=("Consolas", 10),
        foreground="#7C2D12",
        background="#F8FAFC"
    )

    text.tag_configure(
        "warning",
        foreground="#B91C1C",
        font=("Segoe UI", 10, "bold")
    )

    text.tag_configure(
        "highlight",
        background="#FFF59D",
        foreground="#000000"
    )

    # ======================================================
    # INSERT HELP CONTENT
    # ======================================================
    script_name = os.path.basename(sys.argv[0])

    today = datetime.date.today()

    # TITLE
    text.insert(
        "end",
        "📘 RemoteBorneManager – Professional Guide\n",
        "title"
    )

    # ======================================================
    # PRESENTATION
    # ======================================================
    text.insert(
        "end",
        "\n1. PRESENTATION\n",
        "section"
    )

    text.insert(
        "end",
        "RemoteBorneManager (RBM) est une application desktop industrielle "
        "permettant la gestion distante de bornes via SSH et SCP.\n\n",
        "normal"
    )

    text.insert(
        "end",
        "Objectifs principaux :\n",
        "subtitle"
    )

    features = [
        "Connexion SSH sécurisée",
        "Gestion distante des fichiers",
        "Upload / Download SCP",
        "Monitoring temps réel",
        "Energy Manager PRO",
        "Logs SSH industriels",
        "Reconnexion automatique",
        "Edition fichiers distante",
        "Protection anti-race-condition",
        "Architecture thread-safe",
        "Terminal SSH intégré",
        "Menu contextuel sécurisé",
        "Suppression sécurisée fichiers/dossiers",
        "Historique commandes terminal",
        "Support terminal cd persistant"
    ]

    for item in features:

        text.insert(
            "end",
            f"• {item}\n",
            "normal"
        )

    # ======================================================
    # STARTUP
    # ======================================================
    text.insert(
        "end",
        "\n2. DEMARRAGE\n",
        "section"
    )

    text.insert(
        "end",
        "Mode Python :\n",
        "subtitle"
    )

    text.insert(
        "end",
        f"python {script_name}\n\n",
        "code"
    )

    text.insert(
        "end",
        "Mode EXE portable :\n",
        "subtitle"
    )

    text.insert(
        "end",
        "Lancer RBM.exe\n\n",
        "code"
    )

    # ======================================================
    # SSH
    # ======================================================
    text.insert(
        "end",
        "3. ARCHITECTURE SSH\n",
        "section"
    )

    text.insert(
        "end",
        "RBM utilise désormais une architecture SSH centralisée robuste.\n\n",
        "normal"
    )

    ssh_features = [
        "SSHQueue centralisée",
        "Exécution séquentielle des commandes",
        "Protection anti-collision SSH",
        "Protection SCP concurrente",
        "Reconnexion automatique",
        "Monitoring sécurisé",
        "Callbacks Tkinter thread-safe",
        "Fermeture propre des threads",
        "Surveillance heartbeat"
    ]

    for item in ssh_features:

        text.insert(
            "end",
            f"• {item}\n",
            "normal"
        )

    # ======================================================
    # FILE BROWSER
    # ======================================================
    text.insert(
        "end",
        "\n4. EXPLORATEUR DE FICHIERS\n",
        "section"
    )

    browser_text = (
        "Le navigateur GridCodes permet de gérer les fichiers distants "
        "de manière sécurisée.\n\n"
        "Actions disponibles :\n"
        "• Double clic dossier → entrer\n"
        "• Double clic fichier → ouvrir\n"
        "• Upload SCP\n"
        "• Download SCP\n"
        "• Print PDF\n"
        "• Edition distante\n"
        "• Refresh sécurisé\n"
        "• Copy GridCodes\n"
        "• Menu contextuel sécurisé\n"
        "• Suppression fichiers/dossiers\n"
    )

    text.insert(
        "end",
        browser_text,
        "normal"
    )

    # ======================================================
    # SCP
    # ======================================================
    text.insert(
        "end",
        "\n5. SYSTEME SCP SECURISE\n",
        "section"
    )

    scp_text = (
        "RBM protège les transferts SCP afin d’éviter :\n"
        "• corruption fichiers\n"
        "• collisions réseau\n"
        "• conflits SSH\n"
        "• uploads simultanés\n\n"
        "Fonctionnalités :\n"
        "• SCP Lock global\n"
        "• Retry automatique\n"
        "• Vérification taille distante\n"
        "• Pause monitoring pendant transfert\n"
        "• Upload thread-safe\n"
    )

    text.insert(
        "end",
        scp_text,
        "normal"
    )

    # ======================================================
    # MONITORING
    # ======================================================
    text.insert(
        "end",
        "\n6. MONITORING INDUSTRIEL\n",
        "section"
    )

    monitor_text = (
        "RBM intègre un monitoring temps réel :\n\n"
        "• température PowerBoard\n"
        "• température MainBoard\n"
        "• SoC batterie\n"
        "• état SSH\n"
        "• reconnect automatique\n"
        "• surveillance heartbeat\n\n"
        "Le monitoring est automatiquement suspendu\n"
        "pendant certaines opérations critiques.\n"
    )

    text.insert(
        "end",
        monitor_text,
        "normal"
    )

    # ======================================================
    # TERMINAL SSH
    # ======================================================
    text.insert(
        "end",
        "\n7. TERMINAL SSH PRO\n",
        "section"
    )

    terminal_text = (
        "RBM intègre un terminal SSH sécurisé.\n\n"
        "Fonctionnalités :\n"
        "• historique commandes\n"
        "• navigation clavier ↑ ↓\n"
        "• support cd persistant\n"
        "• commandes Linux classiques\n"
        "• clear intégré\n"
        "• help intégré\n"
        "• auto-scroll output\n\n"
        "Commandes supportées :\n"
        "• ls\n"
        "• cd\n"
        "• pwd\n"
        "• cat\n"
        "• grep\n"
        "• rm\n"
        "• mv\n"
        "• cp\n"
        "• python3\n"
        "• sh\n"
        "• journalctl\n\n"
        "Commandes interactives non supportées :\n"
        "• vim\n"
        "• nano\n"
        "• top\n"
        "• htop\n"
    )

    text.insert(
        "end",
        terminal_text,
        "normal"
    )
    
    # ======================================================
    # ENERGY MANAGER
    # ======================================================
    text.insert(
        "end",
        "\n8. ENERGY MANAGER PRO\n",
        "section"
    )

    energy_text = (
        "Le module Energy Manager permet le pilotage énergétique.\n\n"
        "Modes disponibles :\n\n"
        "A. Mode P / Q\n"
        "• Active Power\n"
        "• Reactive Power\n\n"
        "B. Mode CosPhi\n"
        "• calcul automatique du Q\n"
        "• validation automatique\n\n"
        "Formule utilisée :\n"
    )

    text.insert(
        "end",
        energy_text,
        "normal"
    )

    text.insert(
        "end",
        "Q = |P| × tan(acos(CosPhi))\n",
        "code"
    )
    
    # ======================================================
    # LOGS
    # ======================================================
    text.insert(
        "end",
        "\n9. DEBUG & LOGS\n",
        "section"
    )

    logs_text = (
        "Fonctionnalités disponibles :\n\n"
        "• logs SSH temps réel\n"
        "• filtres ERROR/WARN/INFO\n"
        "• sauvegarde locale\n"
        "• monitoring live\n"
        "• callbacks thread-safe\n"
        "• fermeture sécurisée\n"
    )

    text.insert(
        "end",
        logs_text,
        "normal"
    )

    # ======================================================
    # SECURITY
    # ======================================================
    text.insert(
        "end",
        "\n10. SECURITE & STABILITE\n",
        "section"
    )

    sec_text = (
        "RBM a été conçu pour un environnement industriel local.\n\n"
        "Protections intégrées :\n"
        "• protection anti-race-condition\n"
        "• fermeture propre application\n"
        "• widgets Tkinter protégés\n"
        "• stale callbacks protection\n"
        "• monitoring sécurisé\n"
        "• reconnect intelligent\n"
    )

    text.insert(
        "end",
        sec_text,
        "normal"
    )

    text.insert(
        "end",
        "⚠️ Utilisation recommandée uniquement sur réseau industriel sécurisé.\n",
        "warning"
    )

    # ======================================================
    # ROADMAP
    # ======================================================
    text.insert(
        "end",
        "\n11. ROADMAP\n",
        "section"
    )

    roadmap = [
        "Comparaison fichiers",
        "Historique modifications",
        "Download manager async",
        "Packaging MSI",
        "Gestion clés SSH",
        "Logs structurés",
        "Plugins industriels"
    ]

    for item in roadmap:

        text.insert(
            "end",
            f"• {item}\n",
            "normal"
        )

    # ======================================================
    # VERSION
    # ======================================================
    text.insert(
        "end",
        "\n12. VERSION\n",
        "section"
    )

    version_text = (
        "RemoteBorneManager 3.1 PRO\n"
        f"Date : {today}\n\n"
        "Auteur : Nabil RAISSI\n"
    )

    text.insert(
        "end",
        version_text,
        "normal"
    )

    # ======================================================
    # READ ONLY
    # ======================================================
    text.bind(
        "<Key>",
        lambda e: "break"
    )

    # ======================================================
    # SEARCH FUNCTION
    # ======================================================
    def find_text():

        text.tag_remove(
            "highlight",
            "1.0",
            "end"
        )

        query = search_var.get().strip()

        if not query:
            return

        start = "1.0"

        while True:

            pos = text.search(
                query,
                start,
                stopindex="end",
                nocase=True
            )

            if not pos:
                break

            end = f"{pos}+{len(query)}c"

            text.tag_add(
                "highlight",
                pos,
                end
            )

            start = end

        ranges = text.tag_ranges("highlight")

        if ranges:
            text.see(ranges[0])

    # ENTER SEARCH
    search_entry.bind(
        "<Return>",
        lambda e: find_text()
    )

    # ======================================================
    # BOTTOM BAR
    # ======================================================
    bottom = ttk.Frame(main)

    bottom.pack(
        fill="x",
        pady=(10, 0)
    )

    find_btn = ttk.Button(
        bottom,
        text="Find",
        command=find_text
    )

    find_btn.pack(
        side="left"
    )

    close_btn = ttk.Button(
        bottom,
        text="Close",
        command=_close
    )

    close_btn.pack(
        side="right"
    )

    text.configure(state="disabled")
   
