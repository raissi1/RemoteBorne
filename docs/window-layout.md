# Fenêtres compactes et résultats visibles

Les titres internes des fenêtres secondaires utilisent une police régulière de
11 points. Les boutons Migration et Energy Manager sont compacts et se
réorganisent selon la largeur disponible.

- **Migration** : seuls les réglages du haut défilent. Les chemins et le profil
  passent sur plusieurs lignes si nécessaire. Le tableau d’analyse et les détails
  du fichier sélectionné gardent une zone dédiée avec leurs propres défilements.
- **Energy Manager** : les réglages P/Q et CosPhi défilent séparément. L’historique
  des commandes et le moniteur restent visibles, avec leurs boutons accessibles.
- **Test Sequence** : le tableau, la progression, les commandes et le journal
  conservent leurs zones réservées.
- **Autres fenêtres** : titres discrets, contrôle des contrastes et des boutons
  accessibles aux tailles de texte 100 %, 150 % et 200 %.

La taille initiale respecte l’espace de travail disponible. Les cadres défilants
sont recalés après leur premier affichage pour éviter une largeur initiale
incorrecte. Les commandes SSH, les confirmations et les règles de migration
restent inchangées.

Contrôles graphiques hors connexion, avec un affichage Tk :

```text
python scripts/check_window_layout.py --theme darkly --scale 2.6667 --compact
python scripts/check_migration_energy_layout.py --scale 2.6667
python scripts/check_sequence_layout.py --scale 2.6667
```

Le contrôle Migration/Energy réalise une analyse et un export locaux dans un
dossier temporaire. Il vérifie les fichiers source et simule la réponse d’une
commande Energy ; aucune commande n’est envoyée à une borne.
