# Remote Borne Manager — Guide Utilisateur

## 1. Introduction

Remote Borne Manager permet de gérer des bornes IOTECHA à distance via SSH.
L’application simplifie :
- la gestion des fichiers GridCodes
- le contrôle de puissance
- le debug en temps réel
- le redémarrage des services

## 2. Démarrage

0. Initialiser la config locale (une seule fois) :
```
copy config\\config.example.ini config\\config.ini
```

1. Ouvrir PowerShell
2. Aller dans le dossier src :
```
cd remote_borne_manager/src
```
3. Lancer l'app :
```
python RemoteBorneManager_v3.py
```

## 3. Connexion

Cliquer sur **Connect**.

Si succès :
- LED verte
- Liste des fichiers affichée

Si erreur :
- Messages dans logs
- Tentative de reconnexion

## 4. Navigation fichiers

- Double-clic dossier → entrer
- Double-clic `[.] (Parent)` → remonter
- Double-clic fichier → ouvrir

Menu clic droit :
- Open/Edit
- Download
- Print
- Copy to GridCodes

## 5. Modifier un fichier

1. Double-clic fichier
2. Modifier
3. Rechercher dans le texte avec **Ctrl+F** (Find)
3. Save
4. Upload

Si GridCodes.properties :
- Proposition de redémarrer les services

## 6. Télécharger un fichier

Clic droit → Download  
Choisir emplacement

## 7. Imprimer (PDF)

Clic droit → Print  
Conversion automatique en PDF (avec retour à la ligne des longues lignes)  
Choisir emplacement

## 8. Energy Manager

### Mode P/Q

- Active power (W)
- Reactive power (VAR)
- Send

### Mode CosPhi

- Active power (W)
- CosPhi
- Send

## 9. Services

- Restart services
- Reboot device

## 10. Logs

Zone en bas :
- Horodatée
- Séquentielle
- Auto-scroll

## 11. Debug logs

Menu : Debug → Debug logs

Fonctionnalités :
- multi-onglet
- stream temps réel
- save
- clear
- pause

## 12. Problèmes courants

### Connexion impossible

- Vérifier IP
- Vérifier mot de passe
- Vérifier le port SSH (Menu Network config)
- Vérifier réseau

### Erreur de sauvegarde de configuration réseau

- Vérifier que l’IP/hostname est valide
- Vérifier que le port est entre 1 et 65535
- Vérifier que le dossier local configuré est accessible

### PDF vide

- Fichier source vide

### Upload échoue

- Permissions
- Fichier verrouillé

## 13. Bonnes pratiques

- Sauvegarder avant modification
- Ne pas reboot en boucle
- Redémarrer services après changement de GridCodes

## 14. Sécurité

Le mot de passe n'est pas chiffré.  
Ne pas distribuer config.ini publiquement.
