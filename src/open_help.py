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
    win.title("RemoteBorneManager - Professional Help")
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

    title_lbl = ttk.Label(
        top,
        text="RemoteBorneManager - User Guide",
        font=("Segoe UI", 16, "bold"),
    )
    title_lbl.pack(side="left")

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

    text.tag_configure(
        "title",
        font=("Segoe UI", 18, "bold"),
        foreground="#0F172A",
        spacing3=20,
    )
    text.tag_configure(
        "section",
        font=("Segoe UI", 13, "bold"),
        foreground="#1D4ED8",
        spacing1=20,
        spacing3=10,
    )
    text.tag_configure(
        "subtitle",
        font=("Segoe UI", 11, "bold"),
        foreground="#0F766E",
        spacing1=10,
        spacing3=5,
    )
    text.tag_configure("normal", font=("Segoe UI", 10), spacing3=4)
    text.tag_configure(
        "code",
        font=("Consolas", 10),
        foreground="#7C2D12",
        background="#F8FAFC",
    )
    text.tag_configure(
        "warning",
        foreground="#B91C1C",
        font=("Segoe UI", 10, "bold"),
    )
    text.tag_configure(
        "highlight",
        background="#FFF59D",
        foreground="#000000",
    )

    script_name = os.path.basename(sys.argv[0])
    today = datetime.date.today()

    def add_block(title, body, tag="normal"):
        text.insert("end", title, "subtitle")
        text.insert("end", body + "\n", tag)

    text.insert("end", "RemoteBorneManager - Professional Guide\n", "title")

    text.insert("end", "\n1. PRESENTATION\n", "section")
    text.insert(
        "end",
        "RemoteBorneManager (RBM) est une application desktop industrielle pour la gestion distante de bornes via SSH et SCP.\n\n",
        "normal",
    )
    text.insert("end", "Fonctions principales :\n", "subtitle")
    for item in [
        "connexion SSH et surveillance de session",
        "navigateur GridCodes avec menu contextuel complet",
        "édition distante, upload, download et impression PDF",
        "Energy Manager PRO en modes P/Q et CosPhi",
        "Restart services, Reboot device et Debug logs",
        "Network config avec redémarrage propre si paramètres SSH changent",
        "monitoring Température / SoC",
        "terminal SSH intégré avec historique et cd persistant",
    ]:
        text.insert("end", f"- {item}\n", "normal")

    text.insert("end", "\n2. DEMARRAGE\n", "section")
    add_block("Mode Python\n", f"python {script_name}\n", "code")
    add_block("Mode exécutable\n", "Lancer RBM.exe\n", "code")

    text.insert("end", "\n3. CONNEXION ET RESEAU\n", "section")
    text.insert(
        "end",
        "Le bouton Connect ouvre la session SSH et initialise l’interface distante. Disconnect coupe la session et évite une reconnexion automatique immédiate.\n\n"
        "Quand l’IP, le port ou les identifiants sont modifiés dans Network config, l’application enregistre les paramètres puis redémarre proprement. Ce comportement remplace l’ancienne reconnexion à chaud.\n",
        "normal",
    )

    text.insert("end", "\n4. GRIDCODES BROWSER\n", "section")
    text.insert(
        "end",
        "Le navigateur distant permet :\n"
        "- double-clic dossier : entrer\n"
        "- double-clic [.] (Parent) : revenir au parent\n"
        "- rafraîchissement de la liste distante\n"
        "- mise à jour du champ Path\n\n"
        "Menu contextuel fichier :\n"
        "- Edit\n"
        "- Download\n"
        "- Print\n"
        "- Copy to GridCodes.properties\n"
        "- Delete\n\n"
        "Menu contextuel dossier :\n"
        "- Delete\n",
        "normal",
    )

    text.insert("end", "\n5. EDITION, UPLOAD, DOWNLOAD, PRINT\n", "section")
    text.insert(
        "end",
        "Edition distante :\n"
        "- Find dans l’éditeur\n"
        "- Save et Save As disponibles\n"
        "- normalisation LF des fins de lignes\n\n"
        "Download / Print / ouverture d’éditeur utilisent des traitements de fond pour éviter les gels d’interface.\n\n"
        "Upload : vérification de taille distante après transfert.\n",
        "normal",
    )

    text.insert("end", "\n6. MONITORING TEMPERATURE / SOC\n", "section")
    text.insert(
        "end",
        "Le panneau Temperature / Derating affiche la température et le SoC batterie.\n"
        "Le bouton ↻ déclenche un rafraîchissement manuel immédiat de ces deux valeurs.\n",
        "normal",
    )

    text.insert("end", "\n7. ENERGY MANAGER PRO\n", "section")
    text.insert(
        "end",
        "Le module Energy Manager PRO permet le pilotage énergétique via une fenêtre dédiée.\n\n"
        "Mode P/Q :\n"
        "- Active Power P\n"
        "- Reactive Power Q\n"
        "- Send P/Q\n\n"
        "Mode CosPhi :\n"
        "- Active Power P\n"
        "- CosPhi\n"
        "- Calculate Q\n"
        "- Send CosPhi\n\n",
        "normal",
    )
    text.insert("end", "Q = |P| * tan(acos(CosPhi))\n", "code")

    text.insert("end", "\n8. TERMINAL SSH INTEGRE\n", "section")
    text.insert(
        "end",
        "Ouvrir via Terminal -> Open Terminal.\n\n"
        "Fonctions :\n"
        "- historique Up / Down\n"
        "- cd persistant\n"
        "- clear\n"
        "- help\n"
        "- exécution de commandes shell simples\n"
        "- exécution de scripts Python et shell\n\n"
        "Commandes interactives bloquées :\n"
        "- vim\n"
        "- vi\n"
        "- nano\n"
        "- top\n"
        "- htop\n"
        "- less\n"
        "- more\n\n"
        "Pour sécurité et cohérence UI, rm / mv / cp sont forcées avec -f.\n",
        "normal",
    )

    text.insert("end", "\n9. DEBUG LOGS ET MAINTENANCE\n", "section")
    text.insert(
        "end",
        "Le menu Debug logs ouvre la fenêtre de suivi des logs distants.\n\n"
        "Maintenance disponible :\n"
        "- Restart services\n"
        "- Reboot device\n"
        "- Debug logs\n",
        "normal",
    )

    text.insert("end", "\n10. ARCHITECTURE ET STABILITE\n", "section")
    text.insert(
        "end",
        "RBM s’appuie sur une architecture centralisée avec SSHQueue pour les commandes critiques, des timeouts SCP explicites, des callbacks Tkinter protégés et une gestion plus propre des pertes de transport.\n",
        "normal",
    )
    text.insert(
        "end",
        "Utilisation recommandée sur réseau industriel local maîtrisé.\n",
        "warning",
    )

    text.insert("end", "\n11. LIMITES CONNUES\n", "section")
    text.insert(
        "end",
        "- Save et Save As passent encore par un flux de nommage distant proche\n"
        "- la précision exacte du SoC reste à revalider sur borne\n"
        "- certains scénarios longue durée et multi-actions doivent encore être rejoués terrain\n",
        "normal",
    )

    text.insert("end", "\n12. VERSION\n", "section")
    text.insert(
        "end",
        f"RemoteBorneManager 3.x PRO\nDate : {today}\n\nAuteur : Nabil RAISSI\n",
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

    find_btn = ttk.Button(bottom, text="Find", command=find_text)
    find_btn.pack(side="left")

    close_btn = ttk.Button(bottom, text="Close", command=_close)
    close_btn.pack(side="right")

    text.configure(state="disabled")
