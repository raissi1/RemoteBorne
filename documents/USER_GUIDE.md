# Remote Borne Manager - Guide utilisateur

## 1. Démarrage

Lancer l’application :

```bash
python src/RemoteBorneManager.py
```

Ou utiliser l’exécutable packagé s’il est déjà généré.

## 2. Connexion SSH

- `Connect` : ouvre la session SSH et initialise l’interface distante
- `Disconnect` : coupe la session et bloque la reconnexion automatique immédiate
- les états principaux sont visibles dans les logs et via l’indicateur de connexion

En cas de perte réseau, l’application peut tenter une reconnexion automatique. En cas de changement d’IP ou de paramètres SSH depuis `Network config`, l’application redémarre proprement.

## 3. Navigateur GridCodes

Le navigateur principal permet de parcourir le dossier distant configuré dans `PATHS.remote_path`.

Navigation :

- double-clic sur un dossier : entrer dans le dossier
- double-clic sur `[.] (Parent)` : revenir au parent
- champ `Path` : reflète le chemin courant
- `Refresh` : recharge la liste distante

## 4. Menu contextuel GridCodes

Le clic droit sur un fichier propose :

- `Edit`
- `Download`
- `Print`
- `Copy to GridCodes.properties`
- `Delete`

Le clic droit sur un dossier propose :

- `Delete`

Remarques :

- la suppression demande toujours confirmation
- `Copy to GridCodes.properties` peut proposer un `Restart services` ensuite

## 5. Édition de fichier distant

Depuis `Edit` :

- `Find` ouvre une recherche locale dans l’éditeur
- `Save` envoie le contenu vers un nom distant
- `Save As` passe par le même flux avec saisie du nom distant
- les fins de lignes sont normalisées en `LF`

Raccourcis utiles :

- `Ctrl+F` : rechercher
- `Escape` : retirer le surlignage
- `Ctrl+W` : fermer l’éditeur

## 6. Download, Upload, Print

### Download

- récupère le fichier distant vers un emplacement local
- le transfert est lancé en arrière-plan

### Upload

- permet d’envoyer un fichier local vers le dossier courant
- une vérification finale de taille distante est effectuée

### Print

- récupère le fichier distant
- génère un PDF local lisible
- le nom proposé reprend celui du fichier source

## 7. Energy Manager PRO

Ouvrir :

- `Energy Manager` -> `Energy Manager PRO`

Fonctions :

- mode `P/Q`
- mode `CosPhi`
- historique des commandes
- zone `Monitor Energy Manager`

### Mode P/Q

- renseigner `Active Power P`
- renseigner `Reactive Power Q`
- cliquer `Send P/Q`

### Mode CosPhi

- renseigner `Active Power P`
- renseigner `CosPhi`
- utiliser `Calculate Q` si besoin
- cliquer `Send CosPhi`

## 8. Maintenance

Depuis le menu ou les boutons :

- `Restart services`
- `Reboot device`
- `Debug logs`

### Restart services

- relance les services cibles côté borne
- utilise un timeout plus large côté SSH

### Reboot device

- demande confirmation
- envoie la commande de reboot distante

### Debug logs

- ouvre la fenêtre de logs distante
- permet de suivre les sorties sans popup bloquante inutile

## 9. Monitoring température / SoC

Le panneau `Temperature / Derating` affiche :

- température carte
- SoC batterie

Le bouton `↻` force un rafraîchissement manuel immédiat.

## 10. Network config

Le menu `Network config` permet de modifier :

- host / IP
- username
- password
- port
- `remote_path`
- `remote_file`
- `local_path`

Comportement actuel :

- si seuls les chemins changent, ils sont rechargés
- si l’IP, le port ou les identifiants changent, l’application redémarre après sauvegarde

## 11. Terminal SSH intégré

Ouvrir :

- `Terminal` -> `Open Terminal`

Fonctions :

- historique `Up/Down`
- `cd` persistant
- `clear`
- `help`
- exécution de commandes simples
- exécution de scripts shell et Python

Commandes typiques :

```bash
ls
pwd
cd /var/aux/EnergyManager
cat fichier.txt
python3 script.py
sh restart.sh
```

Commandes interactives non supportées :

- `vim`
- `vi`
- `nano`
- `top`
- `htop`
- `less`
- `more`

Pour sécurité et cohérence UI :

- `rm`, `mv` et `cp` sont forcées avec `-f`

## 12. Dépannage rapide

### Host key / Plink

Si `plink` affiche une erreur de host key en batch mode :

- vérifier que la borne visée est bien la bonne
- nettoyer au besoin la clé PuTTY en cache pour l’IP concernée

### Température ou SoC non mis à jour

- vérifier que la session SSH est active
- utiliser le bouton `↻`
- contrôler les logs applicatifs

### Changement IP

- enregistrer dans `Network config`
- laisser l’application redémarrer
- relancer la connexion sur la nouvelle IP

### Energy Manager PRO

- si un bouton semble masqué, vérifier que la version courante du code inclut le correctif de taille de fenêtre

## 13. Points connus

- `Save` et `Save As` ne sont pas encore séparés fonctionnellement
- le `SoC` doit encore être revalidé face à la valeur réellement lue sur le véhicule
- certains tests longue durée restent à rejouer sur borne réelle
