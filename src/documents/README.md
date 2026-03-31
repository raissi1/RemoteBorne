
# 📘 **README – Remote Borne Manager (RBM)**

Version : **3.0 PRO**
Auteur : **RAISSI Nabil – 2025**
Licence : Usage interne

---

## 📝 **1. Introduction**

Remote Borne Manager (RBM) est un outil autonome, portable, permettant d’administrer à distance des bornes de charge via SSH.
Il offre une interface graphique moderne et simple permettant :

* La connexion sécurisée SSH (via PuTTY / Plink intégré)
* La navigation dans les fichiers distants
* L’édition des configurations GridCodes
* Le téléchargement et l’impression de fichiers
* La gestion énergétique avancée (P/Q & CosPhi)
* Le redémarrage de services et du système
* La consultation des logs temps réel

RBM s’utilise sans installation, fonctionne sur toutes les machines Windows, et ne nécessite **aucun privilège administrateur**.

---

## 📦 **2. Architecture du projet**

```
remote_borne_manager/
│
├── src/
│   ├── RemoteBorneManager.py     → Programme principal (UI + logique)
│   ├── ssh_manager.py            → Gestion SSH (connexion, reconnexion, threads)
│   ├── plink_backend.py          → Backend Plink / PSCP
│   ├── network_config.py         → Fenêtre de configuration réseau
│   ├── open_help.py              → Ouverture du manuel HTML
│   ├── debug_logs.py             → Fenêtre debug logs
│   ├── energy_manager.py         → Fenêtre Energy Manager PRO
│   └── log_manager.py            → Gestion des logs internes
│
├── config/
│   └── config.ini                → Configuration SSH & chemins distants
│
├── tools/
│   ├── plink.exe                 → SSH portable
│   └── pscp.exe                  → SCP portable
│
├── assets/
│   └── imgs/
│       ├── renault.png           → Logo gauche
│       └── avl.png               → Logo droite
│
├── documents/
├── exports/
├── logs/
└── README.md
```

---

## ⚙️ **3. Fonctionnalités principales**

### 🔐 SSH & Navigation

* Connexion SSH automatique avec auto-acceptation du host key
* Reconnexion intelligente avec délais progressifs
* Navigation dans les répertoires (ls)
* Double-clic : entrer dossier / ouvrir fichier
* Actions bloquées tant que la connexion n’est pas établie

---

### 📑 Gestion fichiers

* Liste dynamique des fichiers distants
* Téléchargement (SCP)
* Impression locale automatique
* Édition dans un éditeur intégré
* Comparaison (dans les versions futures)

---

### ⚡ Energy Manager PRO

Deux modes :

#### **1. Mode P/Q classique**

* Active Power (W)
* Reactive Power (Q) avec valeur par défaut **0**
* Commande envoyée via EnergyManagerTestingTool

#### **2. Mode CosPhi**

* Calcul automatique du Q
* Validation de plage (-1, 1]
* Blocage automatique du mode P/Q

---

### 🔧 Maintenance

* Restart Services (OCPP, EM, etc.)
* Reboot machine distante
* Debug logs temps réel

---

## 📂 **4. Fichiers de configuration**

### **config.ini**

Modifiable via **Menu → Network Config**.

Contient :

```
[SSH]
host = 192.168.1.xxx
username = root
password = ********
port = 22

[PATHS]
remote_path = /etc/iotecha/configs/GridCodes
remote_file = GridCodes.properties
local_path = exports/GridCodes.properties
```

Toute modification nécessite un **redémarrage de l’application**.

---

## 🚀 **5. Version Portable (EXE)**

Une fois générée avec PyInstaller, la distribution contient :

✔️ `RemoteBorneManager.exe`
✔️ `tools/` avec plink.exe & pscp.exe
✔️ `config/` avec config.ini
✔️ `assets/imgs/`
✔️ Tous les répertoires nécessaires

L'utilisateur :

❌ n’a **pas** besoin d’installer Python
❌ n’a **pas** besoin d’installer PuTTY
❌ n’a **pas** besoin d’être administrateur

---

## 🔒 **6. Sécurité**

* Pas d’accès root sans mot de passe
* Aucun stockage Internet
* Pas de dépendances externes
* Logs stockés uniquement en local
* Host key automatiquement acceptée → utile pour bornes internes

> ⚠️ Pour usage réseau local uniquement.
> Ne jamais utiliser pour des serveurs publics.

---

## 🛠️ **7. Dépendances techniques**

RBM utilise :

* Python 3.10+
* Tkinter (GUI)
* PuTTY tools (plink.exe + pscp.exe)
* PyInstaller (pour version portable)

Aucune installation supplémentaire n'est requise.

---

## 📘 **8. Manuel utilisateur**

Le manuel complet est fourni dans un fichier séparé sous forme DOCX ou HTML.

---

# 📗 **MANUEL UTILISATEUR – Remote Borne Manager**

## 🎯 1. Objectif

Ce manuel décrit toutes les étapes pour utiliser RBM afin d’administrer une borne IOTECHA / AVL.

---

## 🟢 2. Lancement

### ▶️ **Mode Python**

```
python RemoteBorneManager.py
```

### ▶️ **Mode Portable**

Double-cliquer :
`RemoteBorneManager.exe`

---

## 🔐 3. Configuration Réseau

Menu : **Network → Configuration réseau**

Renseignez :

* Adresse IP de la borne
* Identifiant SSH (root)
* Mot de passe
* Chemin distant des GridCodes

Cliquez **Save**, puis redémarrez l’application.

---

## 🔌 4. Connexion SSH

### ➤ Pour se connecter

Bouton **Connect** (désactivé si déjà connecté).

### ➤ Pour se déconnecter

Bouton **Disconnect**.

### Indicateurs :

* ⭐ *Connected* → toutes les fonctionnalités activées
* ❌ *Disconnected* → liste fichiers désactivée

---

## 📁 5. Navigation des fichiers

* Le panneau central affiche le contenu du chemin distant (GridCodes).
* **Double-clic** sur un dossier → entrer
* **Double-clic** sur un fichier → ouvrir dans l’éditeur

---

## ✏️ 6. Édition de fichiers

1. Sélectionner un fichier
2. Double-clic → téléchargement temporaire
3. Modification dans la fenêtre d’édition
4. Sauvegarde → upload automatique dans la borne

RBM gère le SCP entièrement.

---

## ⬇️ 7. Téléchargement & Impression

### Télécharger

**Menu → File → Download**

### Imprimer

**Menu → File → Print**
Le fichier est téléchargé puis envoyé à l'imprimante par défaut.

---

## ⚡ 8. Energy Manager PRO

### Mode standard P/Q

* Entrer Active (W)
* Entrer Reactive (var) → **par défaut = 0**
* Envoyer via "Send Power"

### Mode CosPhi

* Cocher "Use CosPhi mode"
* Entrer Active (W)
* Entrer CosPhi (-1 à 1)
* Q est calculé automatiquement

---

## 🔧 9. Maintenance

### Redémarrer services

**Menu → File → Restart services**

### Redémarrer système distant

**Menu → File → Reboot device**

---

## 📜 10. Debug & Logs

### Debug Logs

Affiche en temps réel les logs SSH.

### Application Logs

Stockés dans :
`logs/app.log`

---

## 🛑 11. Fermeture

Bouton **Exit**
→ fermeture propre du SSH Manager et des threads.
