# Remote Borne Manager (RBM)

Remote Borne Manager est une application Windows en Python pour piloter à distance des bornes IOTECHA via SSH et SCP avec `plink.exe` et `pscp.exe`.

## Fonctions principales

- Connexion SSH avec surveillance et tentative de reconnexion
- Navigateur `GridCodes` avec navigation dossiers/fichiers
- Édition distante avec `Find`, `Save` et `Save As`
- Upload / Download SCP durcis avec timeout explicite
- Impression PDF depuis un fichier distant
- Copie vers `GridCodes.properties` avec confirmation
- Energy Manager PRO : mode `P/Q` et mode `CosPhi`
- `Restart services` et `Reboot device`
- Fenêtre `Debug logs`
- Fenêtre `Network config`
- Terminal SSH intégré avec historique et `cd` persistant
- Monitoring `Température / SoC`
- Menu contextuel complet sur les fichiers GridCodes

## Arborescence utile

```text
RemoteBorne/
├── config/
├── documents/
├── exports/
├── logs/
├── src/
│   ├── RemoteBorneManager.py
│   ├── ssh_manager.py
│   ├── ssh_queue.py
│   ├── energy_manager.py
│   ├── debug_logs.py
│   ├── network_config.py
│   └── open_help.py
├── tools/
│   ├── plink.exe
│   └── pscp.exe
└── imgs/
```

## Prérequis

- Windows 10 ou 11
- Python 3.10+
- `plink.exe` et `pscp.exe` présents dans `tools/`

Installation :

```bash
pip install -r documents/requirements.txt
```

## Configuration

Le fichier `config/config.ini` contient notamment :

```ini
[SSH]
host = 192.168.1.100
username = root
password = monPass
port = 22
```

Et les chemins applicatifs :

```ini
[PATHS]
remote_path = /etc/iotecha/configs/GridCodes
remote_file = GridCodes.properties
local_path = exports/GridCodes.properties
```

Modification possible depuis l’application :

- `Network` -> `Network config`

Note importante :

- si l’IP ou les paramètres SSH changent, l’application enregistre la config puis redémarre proprement pour repartir sur une base saine

## Lancement

```bash
python src/RemoteBorneManager.py
```

## Comportement actuel important

### SSH et stabilité

- `SSHQueue` sérialise les commandes critiques
- les transferts SCP utilisent un verrou dédié
- les logs `SSH QUEUE` sont raccourcis avec des labels lisibles
- les pertes de transport marquent correctement la session comme déconnectée

### GridCodes

Le clic droit sur un fichier propose :

- `Edit`
- `Download`
- `Print`
- `Copy to GridCodes.properties`
- `Delete`

Sur un dossier :

- `Delete`

### Monitoring

Le bloc `Temperature / Derating` affiche :

- température
- SoC batterie

Le bouton `↻` force un rafraîchissement manuel de ces deux valeurs.

### Terminal intégré

Disponible dans :

- `Terminal` -> `Open Terminal`

Fonctions :

- historique `Up/Down`
- `cd` persistant
- `clear`
- `help`
- `rm`, `mv`, `cp` forcés avec `-f`

Commandes interactives volontairement bloquées :

- `vim`
- `vi`
- `nano`
- `top`
- `htop`
- `less`
- `more`

## Limites connues

- `Save` et `Save As` partagent encore le même flux de saisie de nom distant
- la précision exacte du `SoC` reste à revalider sur borne
- le changement IP à chaud ne tente plus une simple reconnexion : il redémarre l’application

## Documentation associée

- `documents/USER_GUIDE.md`
- `documents/PVAL_TEST_PLAN.md`
- `documents/PV_RBM_V8_Init.docx`

## Usage

Usage interne professionnel.
