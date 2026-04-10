import os
import sys
import tkinter as tk
from tkinter import ttk
import datetime

try:
    from .utils_ui import center_window
except ImportError:
    from utils_ui import center_window

def open_help(parent=None):
    win = tk.Toplevel(parent)
    win.title("RemoteBorneManager – Help")

    if parent:
        win.transient(parent)
        win.grab_set()

    win.geometry("900x700")
    center_window(parent, win, 900, 700)

    # ----- UI -----
    frame = ttk.Frame(win)
    frame.pack(fill="both", expand=True, padx=10, pady=10)

    text = tk.Text(frame, wrap="word", font=("Segoe UI", 10))
    scroll = ttk.Scrollbar(frame, command=text.yview)
    text.configure(yscrollcommand=scroll.set)

    text.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")

    script_name = os.path.basename(sys.argv[0])

    help_content = f"""
📘 RemoteBorneManager – Guide Utilisateur
===========================================================

🧭 1. PRESENTATION
------------------
RemoteBorneManager est une application permettant de gérer à distance une borne via SSH.

Fonctionnalités principales :
• Connexion SSH sécurisée (plink)
• Navigation et gestion des fichiers distants
• Edition directe des fichiers
• Terminal SSH intégré
• Energy Manager (P / Q / CosPhi)
• Debug logs en temps réel
• Configuration réseau

-----------------------------------------------------------

🚀 2. DEMARRAGE
---------------
Mode Python :
    python {script_name}

Mode EXE :
    lancer RBM.exe

-----------------------------------------------------------

🔐 3. CONNEXION SSH
-------------------
Menu : File → Connect

Statuts :
🔴 Disconnected
🟠 Reconnecting
🟢 Connected

Fonctionnement :
• reconnexion automatique
• gestion des erreurs réseau
• timeout configurable

-----------------------------------------------------------

📂 4. EXPLORATEUR DE FICHIERS
-----------------------------
Interface principale (gauche)

Actions :
• Double clic dossier → entrer
• Double clic fichier → ouvrir
• ".." → remonter

Fonctions :
• Refresh → rafraîchir
• Copy to GridCodes
• Download fichier
• Print (PDF)
• Edit fichier

-----------------------------------------------------------

✏️ 5. EDITEUR DE FICHIERS
-------------------------
• ouverture d’un fichier distant
• modification locale
• sauvegarde → upload automatique

Options :
• Restart service après save
• Recherche (Find)

⚠️ Attention :
les modifications sont envoyées directement sur la borne

-----------------------------------------------------------

⚡ 6. ENERGY MANAGER
--------------------

Modes disponibles :

A. Mode P / Q
-------------
• Active Power (P en W)
• Reactive Power (Q en VAR)

B. Mode CosPhi
--------------
• calcul automatique de Q
• formule utilisée :

    Q = |P| × tan(acos(CosPhi))

Fonctions :
• validation des valeurs
• historique
• export CSV

-----------------------------------------------------------

🖥️ 7. TERMINAL SSH (IMPORTANT)
------------------------------
Terminal intégré dans l'application

Permet :
• exécuter des commandes Linux
• naviguer dans le système
• lancer scripts
• debug avancé

Exemples :
    ls
    cd /var/aux
    cat fichier.txt
    python script.py

⚠️ Conseil :
éviter les commandes critiques en production

-----------------------------------------------------------

📜 8. DEBUG LOGS
----------------
Fonctionnalités :
• lecture logs en temps réel (tail -f)
• filtres :
    ERROR
    WARN
    INFO

Options :
• pause / reprise
• sauvegarde locale

-----------------------------------------------------------

🌐 9. CONFIGURATION RESEAU
--------------------------
Menu Network :

Paramètres :
• IP borne
• utilisateur SSH
• mot de passe
• chemins système

Fonction :
• sauvegarde automatique
• reconnexion après modification

-----------------------------------------------------------

📁 10. STRUCTURE DU PROJET
--------------------------
config/      → configuration
tools/       → plink, outils SSH
logs/        → logs locaux
exports/     → fichiers exportés
src/         → code source

-----------------------------------------------------------

⚠️ 11. PROBLEMES COURANTS
-------------------------

❌ Impossible de se connecter
→ vérifier IP / réseau / firewall

❌ plink.exe introuvable
→ vérifier dossier tools/

❌ fichier non modifiable
→ vérifier permissions

❌ logs vides
→ vérifier chemin logs distant

-----------------------------------------------------------

🔒 12. BONNES PRATIQUES
-----------------------
• utiliser des clés SSH (recommandé)
• éviter mot de passe en clair
• sauvegarder avant modification
• limiter accès réseau

-----------------------------------------------------------

📦 13. VERSION
--------------
Version : 3.0 PRO
Date : {datetime.date.today()}

Auteur :
Nabil RAISSI

-----------------------------------------------------------
"""

    text.insert("1.0", help_content)
    text.configure(state="disabled")

    ttk.Button(win, text="Close", command=win.destroy).pack(pady=8)