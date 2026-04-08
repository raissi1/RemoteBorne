# PVAL – Plan de revalidation (post-correctifs)

## 1) Synthèse rapide des points déjà traités

- **T02 / T11 / T13 (IP/password/reconnect runtime)** : corrigés côté flux de reconnexion (`update_target` + reconnect contrôlé, annulation des reconnects obsolètes, queue reconnect).
- **T30 (`^M` dans GridCodes.properties)** : sauvegarde normalisée en LF (`\n`) avec nettoyage explicite CRLF/CR.
- **T30 (recherche éditeur)** : `Ctrl+F` + bouton Find + surlignage.
- **T32 (texte tronqué en PDF)** : wrapping basé sur largeur réelle (`pdfmetrics`) + nom PDF par défaut = nom du fichier source.
- **T42 (procédure CosPhiSetPoint)** : envoi via 2 commandes chaînées (`SetpointCosPhi_Pct` puis `CentralSetpoint`).
- **T60 (fenêtre cmd + popup bloquante)** : lancement plink masqué sous Windows + suppression popup bloquante au Start.

> Important: statut réel = à confirmer par re-PVAL terrain.

## 2) Points à revalider en priorité (risque le plus élevé)

1. **T02 / T11 / T13** (stabilité réseau SSH)
2. **T42** (nouvelle procédure CosPhi)
3. **T30 / T32** (édition et impression)
4. **T60** (debug logs UX)

## 3) Tests complémentaires recommandés à ajouter au PVAL

### T72 – Reconnexion sur faux-positif heartbeat
- **Préconditions**: connecté.
- **Étapes**:
  1. Introduire une latence ponctuelle (ou micro-coupure <30s).
  2. Observer les logs heartbeat.
- **Résultat attendu**:
  - Logs `Heartbeat failed (1/3)` possibles,
  - pas de tempête de reconnect immédiate,
  - reconnexion forcée uniquement après 3 échecs consécutifs.

### T73 – Disconnect manuel strict
- **Étapes**:
  1. Connecter,
  2. cliquer **Disconnect**.
- **Résultat attendu**:
  - état reste `Disconnected`,
  - pas de reconnect auto,
  - liste des fichiers vide.

### T74 – Changement IP pendant reconnexion en cours
- **Étapes**:
  1. Provoquer une reconnexion (IP invalide),
  2. ouvrir Network config et mettre une nouvelle IP valide,
  3. Save.
- **Résultat attendu**:
  - abandon des tentatives obsolètes,
  - reprise de connexion vers la nouvelle IP sans redémarrage application.

### T75 – CosPhi envoi rapide (UX)
- **Étapes**:
  1. Envoyer CosPhi plusieurs fois de suite,
  2. mesurer ressenti UI / latence click->retour.
- **Résultat attendu**:
  - envoi quasi immédiat côté UI,
  - pas de blocage visible de fenêtre.

### T76 – Print nom de fichier par défaut
- **Étapes**:
  1. Sélectionner `MyFile.properties`,
  2. Print.
- **Résultat attendu**:
  - nom proposé automatiquement: `MyFile.pdf`.

### T77 – Debug logs Start sans popup bloquante
- **Étapes**:
  1. Ouvrir Debug logs,
  2. cliquer Start.
- **Résultat attendu**:
  - pas de fenêtre cmd visible,
  - pas de popup `Info` bloquante,
  - lignes log affichées directement.

## 4) Critères de sortie PVAL

- Tous les **Fail/Warning historiques** (T02, T11, T13, T30, T32, T42, T60, T71) rejoués.
- Aucun blocage UI sur actions critiques (Connect/Disconnect/Edit/Print/Start logs).
- Reproductibilité: 3 runs consécutifs sans régression sur les cas critiques.
