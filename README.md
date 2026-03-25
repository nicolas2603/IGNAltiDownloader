# IGN Alti Downloader

Plugin QGIS pour télécharger les données altimétriques de l'IGN (RGE ALTI et LiDAR HD).

![QGIS](https://img.shields.io/badge/QGIS-3.16+-green.svg)
![License](https://img.shields.io/badge/license-GPL--3.0-blue.svg)

## Pourquoi ce plugin ?

Télécharger des dalles altimétriques, c'est un processus qui peut s'optimiser. Identifier les tuiles, les récupérer une par une, les assembler... Ce plugin automatise tout ça directement depuis QGIS.

## Sources disponibles

| Source | Résolution | Usage type |
|--------|------------|------------|
| RGE ALTI MNT | 1m | Calculs de pente, analyse du relief |
| LiDAR HD MNT | 50cm | Études topographiques fines |
| LiDAR HD MNS | 50cm | Calculs de visibilité, études d'impact paysager |
| LiDAR HD MNH | 50cm | Caractérisation de la végétation, analyse du bâti |

## Fonctionnalités

- Téléchargement par emprise : vue courante, couche, ou sélection manuelle sur la grille
- Affichage de la grille de mosaïquage IGN avec visualisation du cache
- Cache local pour éviter les téléchargements inutiles
- Fusion des dalles en VRT ou GeoTIFF
- Lissage gaussien pour atténuer les artefacts des données brutes
- Calcul de pente intégré (degrés ou pourcentage)
- Fonctionne quel que soit le système de coordonnées du projet

## Installation

1. Télécharger le ZIP depuis les [releases](https://github.com/nicolas2603/IGNAltiDownloader/releases)
2. Dans QGIS : Extensions > Installer/Gérer les extensions > Installer depuis un ZIP
3. Activer le plugin dans la liste des extensions

Ou copier le dossier `IGNAltiDownloader` dans :
- Windows : `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\`
- Linux : `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`
- macOS : `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/`

## Utilisation

1. Cliquer sur l'icône dans la barre d'outils ou menu Raster > IGNAltiDownloader
2. Sélectionner une source de données
3. Définir l'emprise à télécharger
4. Cocher les options souhaitées (fusion, lissage, pente)
5. Lancer le téléchargement

### Astuce : la grille de mosaïquage

Cocher "Afficher la grille de mosaïquage" permet de visualiser les dalles sur la carte :
- Vert = déjà en cache
- Rouge = à télécharger

On peut sélectionner les dalles à la main avec l'outil de sélection QGIS, puis cliquer sur "Sélection" pour définir l'emprise.

## Dépendances

- QGIS 3.16+
- GDAL (inclus avec QGIS)
- NumPy (inclus avec QGIS)

## Limitations

- Couverture LiDAR HD partielle (programme IGN 2021-2026 en cours)
- Les données proviennent du WMS IGN, légèrement dégradées par rapport aux fichiers ASC originaux

## Licence

GPL-3.0 - Voir [LICENSE](LICENSE)

## Auteur

Nicolas Lieutenant

---

*Ce plugin utilise les services WMS de l'IGN via data.geopf.fr*