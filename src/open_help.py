import os
import sys
import tkinter as tk
from tkinter import ttk
import datetime

def _center_over_parent(parent, win, w=900, h=700):
    """Centre la fenêtre d'aide sur la fenêtre parente."""
    if parent is not None:
        parent.update_idletasks()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        x = px + (pw - w) // 2
        y = py + (ph - h) // 2
    else:
        win.update_idletasks()
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
    win.geometry(f"{w}x{h}+{max(x, 0)}+{max(y, 0)}")


def open_help(parent=None):
    """
    Fenêtre d’aide utilisateur détaillée pour RemoteBorneManager (Version PRO Ultimate).

    Couvre les modules :
      - RemoteBorneManager.py (interface principale)
      - ssh_manager.py / plink_backend.py (SSH)
      - debug_logs.py (Debug logs ultimate)
      - energy_manager.py (Energy Manager PRO ultimate)
      - network_config.py (config réseau)
      - log_manager.py, open_help.py
    """
    win = tk.Toplevel(parent)
    win.title("RemoteBorneManager – Help")
    win.geometry("900x700")
    if parent is not None:
        win.transient(parent)
        win.grab_set()
        win.focus_force()
        win.lift()
    _center_over_parent(parent, win, 900, 700)

    # ----- zone texte scrollable -----
    frame = ttk.Frame(win)
    frame.pack(fill="both", expand=True, padx=10, pady=10)

    text = tk.Text(
        frame,
        wrap="word",
        font=("Segoe UI", 10),
        spacing1=3,
        spacing2=2,
        spacing3=3,
    )
    scroll = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
    text.configure(yscrollcommand=scroll.set)
    text.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")

    script_name = os.path.basename(sys.argv[0]) if sys.argv else "RemoteBorneManager.py"

    # ATTENTION : pas d'accolades { } non échappées dans cette f-string
    help_content = f"""
📘 RemoteBorneManager – Guide Utilisateur
================================================================

1. OBJECTIF DU LOGICIEL
-----------------------

RemoteBorneManager est une application Windows permettant de piloter et
superviser à distance une borne de charge (ou équipement embarqué) via SSH.

Fonctions principales :

  • Connexion SSH stable (Plink) avec reconnexion automatique.
  • Navigation dans les GridCodes (/etc/iotecha/configs/GridCodes).
  • Copie d'un fichier vers GridCodes.properties (fichier actif).
  • Téléchargement, impression PDF et édition de fichiers distants.
  • Energy Manager PRO :
        - commandes P / Q (power / reactive power)
        - mode CosPhi avec calcul automatique de Q
        - historique des commandes + export CSV
        - monitor et restart du service S91energy-manager
  • Debug Logs Ultimate :
        - tail -f des logs distants
        - filtres type "grep -i" sur les messages
        - filtres par niveau (ERROR / WARN / INFO)
        - pause / reprise du flux live
        - sauvegarde de la vue filtrée
  • Fenêtre de configuration réseau (config.ini).
  • Mode portable (.exe) sans installation Python sur les postes utilisateurs.


================================================================
2. DEMARRAGE DE L’APPLICATION
================================================================

Pour lancer l'application en mode Python :

    python {script_name}

ou en double-cliquant sur l'exécutable Portable (RemoteBorneManager.exe)
si une version PyInstaller a été fournie.

Pré-requis dans le dossier du projet :

  • RemoteBorneManager.py
  • ssh_manager.py, plink_backend.py
  • debug_logs.py, energy_manager.py, log_manager.py
  • network_config.py, open_help.py
  • plink.exe, pscp.exe (ou présents dans le PATH Windows)
  • dossier config/ contenant config.ini (créé automatiquement à la première exécution)


================================================================
3. PREMIERE CONFIGURATION (NETWORK CONFIGURATION)
================================================================

Menu  Network  →  Network Configuration

La fenêtre permet de configurer :

  • IP Address
  • Username (ex : root)
  • Password
  • Remote Path  : répertoire des GridCodes (ex : /etc/iotecha/configs/GridCodes)
  • Remote File  : nom du fichier GridCodes actif (ex : GridCodes.properties)
  • Local Path   : dossier local pour les téléchargements

Boutons :

  • [Browse]  : choisir un répertoire local.
  • [Save]    : enregistre les paramètres dans config/config.ini,
                relance la connexion SSH et actualise la liste de fichiers.
  • [Cancel]  : ferme la fenêtre sans enregistrer.

Après validation, la nouvelle configuration est prise en compte. En cas de problème,
vérifiez les logs (zone "Logs" en bas de la fenêtre principale).


================================================================
4. CONNEXION SSH & ETAT
================================================================

Menu  File  →  Connect
-----------------------

  • Ouvre une session SSH vers la borne via Plink, en utilisant :
        - IP, user, password, port : issus de config.ini.
  • Si la clé d'hôte (host key) n'est pas encore connue, l'appli tente
    de l'accepter automatiquement (mode batch) et la stocke chez Windows.

Indications visuelles :

  • LED rouge = Disconnected
  • LED orange = Reconnecting...
  • LED verte = Connected

Menu  File  →  Disconnect
-------------------------

  • Ferme la session SSH proprement.
  • Désactive les boutons nécessitant une connexion (Download, Edit, Energy Manager, etc.).
  • La liste des fichiers reste visible mais non interactive (lecture seule).

Menu  File  →  Exit
-------------------

  • Ferme complètement l’application et stoppe les threads internes.

Reconnexion automatique
-----------------------

  • ssh_manager maintient une tâche de reconnect avec backoff (2s, 4s, 6s, ...),
    jusqu’à un nombre de tentatives maximum.
  • En cas de succès : message [SSH] Reconnect SUCCESS et LED verte.
  • En cas d’échec : message [SSH] Unable to reconnect after max attempts.


================================================================
5. NAVIGATION DANS LES GRIDCODES
================================================================

Zone "Remote GridCodes Files" (côté gauche de la fenêtre principale) :

Champ Path :
    • Affiche le répertoire distant courant.
    • Bouton [Go]   : tente de se déplacer vers le chemin saisi.
    • Bouton [Root] : revient au dossier GridCodes par défaut (config.ini).

Liste de fichiers :
    • Double-clic sur un dossier : on y entre.
    • Double-clic sur ".."       : remonte d'un niveau.
    • Double-clic sur un fichier : ouvre l’éditeur (Edit) si l’option est active.

Boutons sous la liste :

  • [Refresh]
      Recharge la liste du répertoire courant en exécutant "ls" via SSH.

  • [Copy to GridCodes]
      Copie le fichier sélectionné vers le fichier GridCodes.properties
      défini dans config.ini.
      Un message de confirmation s’affiche avant l’écrasement.
      Après la copie, une question peut proposer de redémarrer les services.

  • [Edit]
      Télécharge le fichier sélectionné dans un fichier temporaire, ouvre un
      éditeur texte interne (fenêtre modale) puis, en cas de sauvegarde, renvoie
      le fichier modifié sur la borne via SCP.

  • [Download]
      Télécharge le fichier sélectionné vers le chemin local indiqué
      dans config.ini (ou un chemin choisi par l’utilisateur).

  • [Print]
      Lit le fichier distant et génère un PDF (via reportlab) pour impression
      ou archivage.


================================================================
6. ENERGY MANAGER PRO (P/Q & COSPHI ULTIMATE)
================================================================

Menu  Energy  →  Energy Manager PRO

Ouvre une fenêtre dédiée, en plein écran, avec :

  • Bloc Mode P/Q
  • Bloc Mode CosPhi
  • Bloc Historique des commandes
  • Bloc Monitor (status + restart du service S91energy-manager)

Validation des champs
---------------------

Les champs P, Q et CosPhi n’acceptent que des valeurs numériques :
  • Exemples valides  : 1000, -500, 2300.5
  • Exemples invalides : abc, 12a3, 3,14 (virgule), etc.
En cas de valeur incorrecte, une popup claire s’affiche (toujours devant la fenêtre).

A. Mode P/Q
-----------

Champs :

  • Active Power P (W)
  • Reactive Power Q (VAR)

Bouton [Send P/Q] :

  • Envoie la commande suivante :

        cd /var/aux/EnergyManager &&
        export LD_LIBRARY_PATH=/usr/local/lib &&
        /usr/local/bin/EnergyManagerTestingTool -S -s ocpp -a \
            --power P --reactive-power Q -m CentralSetpoint

  • Le résultat (OK ou erreur) est affiché dans une popup + enregistré
    dans l’historique.

B. Mode CosPhi
--------------

Champs :

  • Active Power P (W)
  • CosPhi (-1 → 1]
  • Reactive Power Q (auto) : calculé, en lecture seule

Bouton [Calculate Q] :

  • Calcule :

        Q = |P| * tan(acos(CosPhi))

  • Affiche la valeur entière arrondie dans "Reactive Power Q (auto)".

Bouton [Send CosPhi] :

  • Réutilise P, CosPhi et Q calculé pour envoyer la même commande
    EnergyManagerTestingTool qu’en mode P/Q.

C. Historique des commandes
---------------------------

Tableau avec :

  • Timestamp
  • Mode (P/Q ou CosPhi)
  • Commande exécutée
  • Statut (OK / ERR: ...)

Bouton [Exporter CSV] :

  • Exporte l’historique complet dans un fichier CSV pour analyse.

D. Monitor Energy Manager
-------------------------

Zone de texte montrant :

  • Résultat de "/etc/init.d/S91energy-manager status"
  • Liste des processus liés à l’énergie via "ps | grep -i energy"

Boutons :

  • [Refresh status]
      Rafraîchit les informations de status.

  • [Restart S91energy-manager]
      Exécute "/etc/init.d/S91energy-manager restart" et affiche le résultat.


================================================================
7. DEBUG LOGS ULTIMATE
================================================================

Menu  Debug  →  Service Logs
----------------------------

Ouvre une fenêtre avec 3 onglets :

  • EnergyManager.log
  • ChargerApp.log
  • iotc-meter-dispatcher.log

Pour chaque onglet :

  • [Start]        : démarre un "tail -f" sur le log distant via plink.
  • [Stop]         : arrête la lecture en continu.
  • [Clear view]   : efface la vue (sans supprimer le fichier distant).
  • [Save view]    : enregistre uniquement les lignes visibles (filtrées)
                     dans un fichier .log local (équivalent tail -f | grep > file).
  • [Pause live]   : met en pause l’affichage temps réel tout en continuant
                     à stocker les lignes dans un buffer mémoire.
  • [Auto-scroll]  : si coché, la vue suit automatiquement la dernière ligne.

Filtres type "tail -f | grep -i"
--------------------------------

Barre de filtre par onglet :

  • Champ "grep:"     : saisie d’un mot ou expression simple.
  • Case "-i"         : ignore la casse (grep -i).
  • Cases "ERROR", "WARN", "INFO" :
        - permettent de ne montrer que certaines lignes de niveau donné.
        - si aucune case n’est cochée → tous les niveaux sont acceptés.
  • Bouton [Apply]    : applique le filtre sur tout l’historique en mémoire.
  • Bouton [Clear]    : réinitialise le filtre et affiche toutes les lignes.

Comportement :

  • Chaque ligne reçue via tail -f est :
        1) stockée en mémoire (buffer limité en taille),
        2) affichée uniquement si elle matche le filtre courant.
  • Le comportement est équivalent à :
        tail -f fichier.log | grep -i "mot" | grep "ERROR|WARN|INFO"


================================================================
8. JOURNAL D’APPLICATION (LOGS PRINCIPAUX)
================================================================

En bas de la fenêtre principale :

  • Zone "Logs" avec tout l’historique local des événements.
  • Messages typiques :

        [INFO] Application started...
        [SSH] Connecting to ...
        [SSH] Reconnect SUCCESS.
        [FILES] Listing /etc/iotecha/configs/GridCodes
        [EDIT] Downloading ...
        [ERROR] Command failed: ...

C’est le premier endroit à regarder en cas de souci de connexion ou de transfert.


================================================================
9. STRUCTURE DU PROJET & PORTABLE
================================================================

Arborescence recommandée :

  remote_borne_manager/
    ├─ config/
    │    └─ config.ini
    ├─ documents/
    ├─ logs/
    ├─ tools/
    │    ├─ plink.exe
    │    └─ pscp.exe
    ├─ imgs/
    ├─ exports/
    └─ src/
         ├─ RemoteBorneManager.py
         ├─ ssh_manager.py
         ├─ plink_backend.py
         ├─ debug_logs.py
         ├─ energy_manager.py
         ├─ network_config.py
         ├─ log_manager.py
         └─ open_help.py

Version portable (.exe) :

  • Construite avec PyInstaller (spec déjà préparé).
  • Le .exe est autonome, les bibliothèques Python sont intégrées.
  • L’utilisateur n’a rien à installer (pas besoin de droits admin).
  • Les dossiers config, logs, tools, etc. restent au même niveau.


================================================================
10. RESOLUTION DE PROBLEMES (TROUBLESHOOTING)
================================================================

Impossible de se connecter (timeout) :
  • Vérifier l’IP dans config.ini (Network config).
  • Vérifier que la borne répond au ping.
  • Tester la commande manuelle :
        plink -ssh -P 22 -l USER -pw "PASS" IP "echo connected"

Mot de passe incorrect :
  • Message "Access denied" dans la zone Logs.
  • Corriger le mot de passe dans Network Configuration.

Host key / clé d’hôte SSH :
  • Si la clé change (nouvelle borne, firmware, etc.), plink peut refuser
    la connexion en mode batch.
  • Dans ce cas, lancer une fois plink manuellement, accepter la clé,
    puis relancer RemoteBorneManager.

Téléchargement / SCP ne fonctionne pas :
  • Vérifier la présence de pscp.exe dans le dossier tools ou dans le PATH.
  • Vérifier les droits en écriture sur le dossier local choisi.

EnergyManagerTestingTool introuvable :
  • Chemin différent ou binaire absent sur la borne.
  • Contacter l’équipe intégration pour corriger le chemin ou installer l’outil.

systemctl not found :
  • Certaines bornes n’utilisent pas systemd.
  • La version Ultimate utilise /etc/init.d/S91energy-manager + ps
    pour assurer la compatibilité.


================================================================
11. SECURITE & BONNES PRATIQUES
================================================================

  • Changer régulièrement les mots de passe SSH.
  • Eviter de diffuser un config.ini contenant des identifiants de production.
  • Restreindre l’accès réseau aux IP des bornes.
  • Garder plink.exe et pscp.exe à jour.
  • Eviter d’utiliser des réseaux Wi-Fi publics pour se connecter aux bornes.


================================================================
12. SUPPORT & EVOLUTIONS
================================================================

Pour toute évolution future possible :

  • Support d’authentification par clé SSH.
  • Gestion multi-bornes dans une même interface.
  • Graphiques temps réel (courbes de puissance, etc.).
  • Intégration OCPP plus poussée.
  
================================================================
13. SIGNATURE
================================================================
Version : 3.0.0
Date    : {datetime.date.today()}

Responsable Logiciel :
   A. RAISSI Nabil – Ingénieur Logiciel

Support :
   nabil.raissi@avl.com
----------------------------------------------------------------

Fin du document.
================================================================
"""

    text.insert("1.0", help_content)
    text.configure(state="disabled")

    btn = ttk.Button(win, text="Close", command=win.destroy)
    btn.pack(pady=5)
