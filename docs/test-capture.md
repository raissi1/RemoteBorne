# Capture d’un test

L’interface principale reste inchangée. Dans **Debug Logs → Live diagnosis → Capture** :

1. Choisir **Start test capture**. Les quatre flux sont démarrés si nécessaire.
2. Reproduire le problème avec les commandes habituelles de RBM.
3. Choisir **Finish test capture**, puis **Open last capture folder** après sauvegarde.

Le dossier contient les logs reçus pendant l’enregistrement, les messages de RBM,
une chronologie CSV/JSONL des commandes SSH et transferts avec leurs résultats,
et une copie de la configuration GridCodes active si sa lecture réussit.
Le fichier `manifest.json` indique les flux sans données, les commandes encore
inachevées, les éventuelles pertes, erreurs ou troncatures. `README.txt` explique
les fichiers. Le dossier est enregistré dans le répertoire utilisateur des
captures d’incident de RBM, sans envoi automatique.

La pause, les filtres et l’effacement de l’affichage ne filtrent pas cette capture.
Les flux déjà actifs restent ouverts après **Finish** ; seuls ceux démarrés par
la capture sont arrêtés. Fermer Debug Logs, se déconnecter ou quitter RBM termine
également l’enregistrement. **Capture incident (snapshot)** conserve la capture
instantanée ZIP existante.

Les dates indiquent l’ordre d’arrivée local. Un flux nouvellement démarré peut
recevoir quelques anciennes lignes via `tail -f`. Les commandes commencées avant
la capture ne sont pas tracées. La lecture GridCodes passe par la file SSH
habituelle : sa date réelle de réception figure dans la chronologie.

L’écriture est asynchrone avec une file bornée. Les champs de plus de 65 536
caractères sont signalés comme tronqués ; une configuration tronquée n’est pas
présentée comme une copie valide. Les arguments PuTTY contenant le mot de passe
SSH et le fichier `config.ini` ne sont pas collectés. Le contenu des commandes,
logs et GridCodes reste celui de la borne.
