# Un seul dossier d’export portable

Le dossier par défaut est `export`, à côté de `RBM.exe` ou à la racine du projet
pour un lancement Python. Les captures restent dans `export/incident` ; les
migrations et autres exports utilisent également cette racine.

Les anciennes valeurs `exports` et les chemins vers l’ancien dossier `exports`
de cette application sont normalisés vers `export`. Un dossier externe choisi
explicitement dans Network Configuration reste respecté.

Au lancement de l’application, si `exports` existe encore :

- si `export` n’existe pas, l’ancien dossier est renommé ;
- si les deux existent, tout l’ancien dossier est conservé dans
  `export/legacy_exports_DATE_HEURE_identifiant`, sans écraser les exports récents.

En cas de fichier verrouillé ou d’échec du déplacement, les données restent à
leur emplacement et un message apparaît dans les logs. Fermer l’ancienne
instance puis relancer permet de réessayer. Aucun fichier n’est supprimé.
