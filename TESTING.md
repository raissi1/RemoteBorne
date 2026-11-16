# Vérification et livraison RBM

## Lancer depuis les sources

Depuis la racine du projet dans PowerShell :

```powershell
.\.venv\Scripts\python.exe -B scripts/pre_commit_quality_gate.py
.\.venv\Scripts\python.exe .\src\RemoteBorneManager.py
```

## Vérifier les fenêtres sans contacter une borne

Le contrôle ci-dessous ouvre les fenêtres avec des transports SSH simulés,
vérifie que les boutons sont visibles ou accessibles par défilement, puis les ferme.
Il utilise uniquement des fichiers temporaires pour tester la configuration.

```powershell
.\.venv\Scripts\python.exe scripts/check_window_layout.py --scale 1.3333
.\.venv\Scripts\python.exe scripts/check_window_layout.py --scale 2
.\.venv\Scripts\python.exe scripts/check_window_layout.py --scale 2.6667 --compact
```

Ces trois échelles correspondent approximativement à 100 %, 150 % et 200 %.
`--compact` limite les fenêtres à un espace de travail de 1024 × 600 pixels.
Les commandes exigent une session graphique. Les tests Linux ne remplacent pas
la vérification de la barre de titre, des icônes et de la mise à l'échelle Windows.

## Générer une version portable sous Windows

```powershell
.\build_rbm.ps1
```

Le script utilise `.venv\Scripts\python.exe` en priorité, même sans activation.
`RBM_PYTHON` permet de sélectionner explicitement un autre interpréteur.
Utiliser Python 3.10 à 3.14 ; Python 3.12 est recommandé. Si des dépendances manquent :

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

La compilation est préparée et vérifiée dans `dist\.rbm-staging`.
Une erreur de version Python, de dépendances, de tests ou de PyInstaller arrête
le script sans supprimer la version portable précédente. Après réussite,
l'ancien dossier est conservé dans `dist\RBM-backup-<date>` et le nouveau dans
`dist\RBM`. Distribuer tout ce nouveau dossier.

La livraison contient un modèle de configuration propre ; elle n'inclut ni
`config.ini` personnel ni l'état généré par le simulateur. Au premier lancement,
configurer la borne depuis Network Configuration. Les anciens réglages restent
dans la sauvegarde de la version précédente.

PyInstaller peut régénérer `RBM.spec`. Si Git bloque une mise à jour à cause de ce
fichier généré, le sauvegarder ou le mettre de côté avec `git stash push -- RBM.spec`
avant `git pull`. Ne pas rétablir toute l'arborescence pour résoudre ce seul fichier.

## Essai manuel de la livraison

- Vérifier Save/Cancel dans Network Configuration, y compris avec une forte mise à l'échelle.
- Vérifier l'aide, l'éditeur, Energy Manager, Test Sequence, Debug Logs et les recherches.
- Démarrer le simulateur : tester P/Q, CosPhi, Pause/Reprise, logs continus, Find et export.
- Pour une migration, choisir un dossier d'export vide ; vérifier le rapport avant transfert.
- Tester le paquet copié dans un autre dossier avant livraison sur un autre PC.

## Essai de la présentation A

La branche `essai-interface-a` contient uniquement la refonte à essayer.
La branche `main` reste la version de référence. Fermer RBM avant de changer de branche.

```powershell
git stash push -m "RBM.spec avant essai A" -- RBM.spec
git fetch origin
git switch --track origin/essai-interface-a
.\.venv-build\Scripts\python.exe .\src\RemoteBorneManager.py
```

La commande `git stash` met de côté le fichier de build régénéré s'il a été modifié.
Si la branche locale existe déjà, utiliser `git switch essai-interface-a` puis
`git pull --ff-only` à la place de `git switch --track`.

Pour revenir à l'interface de référence, fermer RBM puis lancer `git switch main`.
Lancer d'abord les essais depuis les sources ; l'exécutable portable existant reste indépendant.

La présentation A conserve les actions des fichiers. Download, Edit et Upload
restent visibles ; Print, Apply Grid Code, Active properties et NetLogger logs
sont regroupés dans Actions. Le clic droit, le double-clic, les scripts et la
recherche récursive conservent leurs chemins et leurs protections. Les séparations
entre fichiers/commandes et espace de travail/logs sont ajustables à la souris.
Les valeurs SoC restent explicitement les dernières valeurs connues ; Last retrieval
indique l'heure de lecture, pas un nouvel horodatage du capteur.

Les tests natifs de cette présentation sont optionnels dans le contrôle sans écran.
Pour les exécuter sous Windows, sans contacter une borne :

```powershell
$env:RBM_UI_TESTS = "1"
.\.venv-build\Scripts\python.exe -B -m unittest discover -s tests -p "test_*.py"
Remove-Item Env:RBM_UI_TESTS
```

Ils vérifient notamment les 23 actions, la sélection des fichiers, les chemins avec
espaces, les résultats récursifs, le mode CosPhi, les verrouillages, les thèmes et
le déplacement des séparateurs. Les commandes SSH sont remplacées par des doublures.
