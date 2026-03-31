# Remote Borne Manager (RNA)

Remote Borne Manager (RNA) est une application Windows développée en Python permettant de gérer à distance les bornes de recharge IOTECHA via SSH, en utilisant plink.exe et pscp.exe.

## Fonctionnalités principales

- Connexion SSH avec reconnexion automatique
- Navigation des fichiers GridCodes
- Édition distante des fichiers
- Téléchargement de fichiers (Download)
- Impression PDF (Print)
- Copie vers GridCodes.properties avec confirmation
- Commandes EnergyManager (P/Q et CosPhi)
- Redémarrage des services et reboot de la borne
- Fenêtre Debug logs (suivi en temps réel)
- Fenêtre Network config (édition de config.ini)
- Thèmes clair / sombre
- Architecture portable pour déploiement terrain

## Structure du projet

remote_borne_manager/
├─ README.md
├─ USER_GUIDE.md
├─ requirements.txt
├─ src/
│   ├─ RemoteBorneManager_v3.py
│   ├─ ssh_manager.py
│   ├─ plink_backend.py
│   ├─ debug_logs.py
│   ├─ energy_manager.py
│   ├─ network_config.py
│   ├─ open_help.py
│   ├─ log_manager.py
│   └─ ...
├─ config/
│   └─ config.ini
├─ documents/
├─ logs/
├─ tools/
│   ├─ plink.exe
│   └─ pscp.exe
└─ imgs/
    ├─ renault.png
    └─ avl.png

## Installation

### Prérequis

- Windows 10/11
- Python 3.10+
- plink.exe / pscp.exe dans tools/

Installation des dépendances :

```
pip install -r requirements.txt
```

## Configuration initiale (config.ini)

```
[SSH]
host = 192.168.1.100
username = root
password = monPass
port = 22
```

Tu peux modifier ces valeurs via :

**Menu → Network → Network config**

## Lancement

```
cd src
python RemoteBorneManager_v3.py
```

## Modules principaux

### ssh_manager.py

Gestion de :
- état de la connexion
- reconnexion automatique
- callback UI

### plink_backend.py

Backend plink/pscp :
- exécution de commandes
- upload/download
- détection auto du chemin exe

### network_config.py

- Modification de config.ini
- Recharge automatique
- Mise à jour des champs UI

### debug_logs.py

- Logs temps réel
- Multi onglets
- Save, Clear, Auto-scroll

### energy_manager.py

- Mode P/Q
- Mode CosPhi
- Envoi de commandes formatées

## Packaging (.exe)

```
pip install pyinstaller
cd src
pyinstaller --noconsole --onefile RemoteBorneManager_v3.py
```

## Licence

Usage interne professionnel.

