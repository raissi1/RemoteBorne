# PVAL - Plan de revalidation post-correctifs

## Objectif

Ce document sert de guide rapide pour rejouer les points sensibles après les correctifs majeurs apportés à RBM.

## 1. Points déjà traités côté code

- blocages UI sur `refresh`, `download`, `print`, `upload`, `editor`
- sérialisation des commandes critiques via `SSHQueue`
- timeouts SCP explicites
- restauration du terminal SSH intégré
- restauration du menu contextuel GridCodes complet
- correction de la fenêtre `Energy Manager PRO`
- redémarrage propre après modification IP / SSH dans `Network config`

## 2. Priorités de revalidation

1. stabilité SSH / reconnexion
2. édition / upload / print
3. Energy Manager PRO
4. terminal SSH intégré
5. monitoring température / SoC

## 3. Cas à rejouer en priorité

### T13 - Reconnexion automatique

- Préconditions : session SSH active
- Étapes :
  1. provoquer une coupure réseau
  2. rétablir le réseau
- Attendu :
  - tentatives de reconnexion visibles
  - retour en état connecté si la cible redevient accessible

### T14 - Changement IP runtime

- Étapes :
  1. ouvrir `Network config`
  2. modifier l’IP ou les paramètres SSH
  3. enregistrer
- Attendu :
  - sauvegarde de la configuration
  - redémarrage propre de l’application
  - reconnexion possible sur la nouvelle cible après relance

### T30 - Édition et sauvegarde

- Étapes :
  1. ouvrir un fichier distant
  2. modifier son contenu
  3. lancer `Save`
- Attendu :
  - contenu uploadé sans blocage UI
  - fins de lignes normalisées

### T31 / T31B - Download / Upload

- Attendu :
  - transfert sans freeze UI
  - réussite du transfert
  - vérification taille distante pour l’upload

### T32 - Impression PDF

- Attendu :
  - PDF généré localement
  - texte lisible
  - nom proposé cohérent avec le fichier source

### T40 / T42 - Energy Manager

- Attendu :
  - envoi P/Q fonctionnel
  - envoi CosPhi fonctionnel
  - logs courts et lisibles

### T60 - Debug logs

- Attendu :
  - ouverture de la fenêtre
  - suivi sans popup bloquante inutile

### T61 / T62 - Température / SoC

- Attendu :
  - rafraîchissement manuel via `↻`
  - température visible
  - SoC visible

### T79 - Terminal SSH GUI

- Étapes :
  1. ouvrir `Terminal -> Open Terminal`
  2. tester `ls`, `pwd`, `cd`
  3. tester l’historique `↑/↓`
- Attendu :
  - exécution correcte
  - `cd` persistant
  - pas de freeze UI

### T89 - Commandes interactives interdites

- Étapes :
  1. ouvrir le terminal
  2. taper `vim`
  3. taper `nano`
- Attendu :
  - message d’erreur propre
  - aucune ouverture interactive
  - pas de blocage de l’application

## 4. Points encore à surveiller

- précision fonctionnelle du `SoC` par rapport à la valeur véhicule
- comportement longue durée sur plusieurs heures
- cas multi-actions rapides avec éditeur déjà ouvert

## 5. Critères de sortie

- aucun blocage UI sur les scénarios critiques
- terminal et help cohérents avec les fonctions visibles
- trois runs consécutifs sans régression majeure sur les cas prioritaires
