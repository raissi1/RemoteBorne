# Remote Borne Manager — Guide Utilisateur

## 1. Démarrage

1. Initialiser la config locale (une seule fois) :
```powershell
copy config\config.example.ini config\config.ini
```
2. Lancer l'application :
```bash
python src/RemoteBorneManager.py
```

## 2. Connexion

- **Connect** : démarre/reprend la connexion SSH.
- **Disconnect** : déconnexion manuelle stricte (pas de reconnexion auto immédiate).
- La version de l'app est affichée au démarrage dans les logs.

## 3. Navigation fichiers

- Double-clic dossier : entrer
- `[.] (Parent)` : remonter
- Clic droit : Open/Edit, Download, Print, Copy to GridCodes

## 4. Édition de fichier

1. Ouvrir un fichier avec **Edit**.
2. Modifier le contenu.
3. Recherche: **Ctrl+F** (ou bouton Find).
4. Save (upload automatique).

Notes:
- Les fins de lignes sont normalisées en **LF** (évite les `^M` sous vi/MobaXterm).
- `Escape` retire le surlignage Find.

## 5. Impression PDF

- Action **Print** depuis un fichier sélectionné.
- Le nom proposé est celui du fichier source (`<nom>.pdf`).
- Le texte est automatiquement wrapped pour éviter les lignes tronquées.

## 6. Energy Manager

### P/Q
- Envoi standard `--power` + `--reactive-power`.

### CosPhi
- Procédure en 2 commandes chaînées:
  1) `--grid-option "SetpointCosPhi_Pct=..."`
  2) setpoint actif `--power ... -m CentralSetpoint`

## 7. Debug logs

- Ouvrir `Debug -> Debug logs`.
- Bouton **Start** démarre le suivi `tail -f` distant.
- Plus de popup bloquante au Start ; infos affichées directement dans l'onglet.
- Sous Windows, `plink` est lancé sans fenêtre cmd visible.

## 8. Network config

- Champs validés: Host/IP, Username, Password, Port, Remote path/file, Local path.
- Port accepté: **1..65535**.
- Le dossier local est créé si nécessaire.
- Sauvegarde recharge la config et déclenche la reconnexion.

## 9. Dépannage rapide

- Si connexion instable : vérifier IP/port/réseau physique.
- Si heartbeat échoue ponctuellement : l'app n'impose la reconnexion qu'après échecs consécutifs.
- Si print vide/tronqué : re-tester après mise à jour et vérifier droits d'écriture dossier export.
