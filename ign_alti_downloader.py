# -*- coding: utf-8 -*-
"""
IGNAltiDownloader - Plugin QGIS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Téléchargement des MNT/MNS/MNH IGN (RGE ALTI 1m et LiDAR HD 50cm)

Author: Nicolas Lieutenant
Copyright (C) 2026
"""

import os
import shutil
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

from qgis.PyQt import uic
from qgis.PyQt.QtCore import Qt, QSettings, QVariant
from qgis.PyQt.QtWidgets import (
    QAction, QDialog, QFileDialog, QMessageBox, QApplication
)
from qgis.PyQt.QtGui import QIcon, QColor
from qgis.core import (
    QgsProject, QgsRasterLayer, QgsVectorLayer, QgsCoordinateReferenceSystem,
    QgsCoordinateTransform, Qgis, QgsMessageLog, QgsFeature, QgsGeometry,
    QgsRectangle, QgsField, QgsFields, QgsWkbTypes, QgsSymbol,
    QgsFillSymbol, QgsRendererCategory, QgsCategorizedSymbolRenderer,
    QgsSingleSymbolRenderer, QgsSimpleFillSymbolLayer
)
from qgis.gui import QgsMapToolEmitPoint, QgsRubberBand


# Charger le fichier UI
FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'ign_alti_dialog.ui'))


# Configuration des sources de données disponibles
DATA_SOURCES = {
    "RGE ALTI - MNT 1m": {
        "layer": "ELEVATION.ELEVATIONGRIDCOVERAGE.HIGHRES",
        "description": "MNT RGE ALTI - Résolution 1m",
        "resolution": 1,
        "prefix": "RGEALTI",
        "method": "wms"
    },
    "LiDAR HD - MNT 50cm": {
        "layer": "IGNF_LIDAR-HD_MNT_ELEVATION.ELEVATIONGRIDCOVERAGE.LAMB93",
        "description": "MNT LiDAR HD - Résolution 50cm",
        "resolution": 0.5,
        "prefix": "LHD_MNT",
        "method": "wms",
        "code": "MNT"
    },
    "LiDAR HD - MNS 50cm (surface avec végétation/bâtiments)": {
        "layer": "IGNF_LIDAR-HD_MNS_ELEVATION.ELEVATIONGRIDCOVERAGE.LAMB93",
        "description": "MNS LiDAR HD (surface avec végétation/bâtiments) - Résolution 50cm",
        "resolution": 0.5,
        "prefix": "LHD_MNS",
        "method": "wms",
        "code": "MNS"
    },
    "LiDAR HD - MNH 50cm (hauteur sursol)": {
        "layer": "IGNF_LIDAR-HD_MNH_ELEVATION.ELEVATIONGRIDCOVERAGE.LAMB93",
        "description": "MNH LiDAR HD (hauteur sursol) - Résolution 50cm",
        "resolution": 0.5,
        "prefix": "LHD_MNH",
        "method": "wms",
        "code": "MNH"
    }
}


class IGNAltiDownloader:
    """Plugin principal pour le téléchargement des dalles IGN."""

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.action = None
        self.dialog = None
        
    def initGui(self):
        """Crée les entrées de menu et les icônes de la barre d'outils."""
        icon_path = os.path.join(self.plugin_dir, 'icons', 'ign_alti.svg')
        
        self.action = QAction(
            QIcon(icon_path) if os.path.exists(icon_path) else QIcon(),
            "IGNAltiDownloader",
            self.iface.mainWindow()
        )
        self.action.setToolTip("Télécharger les données altimétriques IGN (MNT/MNS/MNH)")
        self.action.setCheckable(False)
        self.action.triggered.connect(self.run)
        
        self.iface.addPluginToRasterMenu("&IGNAltiDownloader", self.action)
        self.iface.addToolBarIcon(self.action)
        
    def unload(self):
        """Supprime l'élément de menu et l'icône du plugin."""
        if self.action:
            self.iface.removePluginRasterMenu("&IGNAltiDownloader", self.action)
            self.iface.removeToolBarIcon(self.action)
            
        if self.dialog:
            self.dialog.cleanup_grid()
            self.dialog.close()
            self.dialog = None
            
    def run(self):
        """Lance le dialogue principal."""
        if not self.dialog:
            self.dialog = RgeAltiDialog(self.iface)
        
        self.dialog.refresh_extent_from_canvas()
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()


class RgeAltiDialog(QDialog, FORM_CLASS):
    """Dialogue principal du plugin IGN Alti Downloader."""
    
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.iface = iface
        self.canvas = iface.mapCanvas()
        
        # Configuration
        self.settings = QSettings()
        self.download_dir = self.settings.value(
            "ign_alti_downloader/download_dir",
            os.path.join(Path.home(), "IGN_ALTI_Cache")
        )
        
        # Paramètres WMS IGN
        self.wms_base_url = "https://data.geopf.fr/wms-r"
        
        # Source sélectionnée
        self.current_source = None
        
        # Fichiers téléchargés
        self.downloaded_files = []
        
        # Couche de grille
        self.grid_layer = None
        self.grid_layer_id = None
        
        # Dalles sélectionnées manuellement
        self.selected_tiles = set()
        
        # Initialisation de l'interface
        self._setup_ui()
        self._connect_signals()
        
    def _setup_ui(self):
        """Configure l'interface utilisateur."""
        # Remplir la liste des sources
        self.sourceComboBox.clear()
        self.sourceComboBox.addItem("Sélectionner une source")
        for name in DATA_SOURCES.keys():
            self.sourceComboBox.addItem(name)
        
        # Pas de source sélectionnée par défaut
        self.current_source = None
        self.downloadButton.setEnabled(False)
        
        # Désactiver le bouton sélection au départ
        self.useSelectionButton.setEnabled(False)
        
        # Dossier de cache
        self.cacheDirLineEdit.setText(self.download_dir)
        self._update_cache_size()
        
        # Emprise initiale
        self.refresh_extent_from_canvas()
        
    def _connect_signals(self):
        """Connecte les signaux aux slots."""
        # Source de données
        self.sourceComboBox.currentIndexChanged.connect(self._on_source_changed)
        
        # Boutons d'emprise
        self.useCurrentExtentButton.clicked.connect(self.refresh_extent_from_canvas)
        self.useLayerExtentButton.clicked.connect(self.use_layer_extent)
        self.useSelectionButton.clicked.connect(self.use_selected_tiles)
        
        # SpinBox pour mise à jour du compteur de dalles
        self.xminSpinBox.valueChanged.connect(self._update_dalles_count)
        self.xmaxSpinBox.valueChanged.connect(self._update_dalles_count)
        self.yminSpinBox.valueChanged.connect(self._update_dalles_count)
        self.ymaxSpinBox.valueChanged.connect(self._update_dalles_count)
        
        # Grille
        self.showGridCheckBox.toggled.connect(self._on_grid_toggled)
        
        # Options de fusion
        self.createVrtCheckBox.toggled.connect(self._on_VRT_toggled)
        self.smoothMntCheckBox.toggled.connect(self._on_smooth_toggled)

        # Pente
        self.calculateSlopeCheckBox.toggled.connect(self._on_slope_toggled)
        
        # Cache
        self.browseCacheButton.clicked.connect(self._browse_cache_dir)
        
        # Boutons principaux
        self.downloadButton.clicked.connect(self.start_download)
    
    def _on_slope_toggled(self, checked):
        """Active/désactive l'option pourcentage selon l'état de calculer la pente."""
        self.slopePercentCheckBox.setEnabled(checked)
    
    def _on_VRT_toggled(self, checked):
        """Gère l'interaction entre lissage et VRT."""
        if checked:
            # Le VRT produit un fichier brut fusionné, donc on décoche le lissage
            self.smoothMntCheckBox.setChecked(False)
            self.smoothMntCheckBox.setEnabled(False)
        else:
            self.smoothMntCheckBox.setEnabled(True)
    
    def _on_smooth_toggled(self, checked):
        """Gère l'interaction entre lissage et VRT."""
        if checked:
            # Le lissage produit un GeoTIFF fusionné, donc on décoche le VRT
            self.createVrtCheckBox.setChecked(False)
            self.createVrtCheckBox.setEnabled(False)
        else:
            self.createVrtCheckBox.setEnabled(True)
    
    def _on_grid_toggled(self, checked):
        """Affiche ou masque la grille de mosaïquage."""
        if checked:
            self._create_grid()
        else:
            self._remove_grid()
    
    def _on_source_changed(self, index):
        """Met à jour quand la source change."""
        source_name = self.sourceComboBox.currentText()
        if source_name in DATA_SOURCES:
            self.current_source = DATA_SOURCES[source_name]
            self.downloadButton.setEnabled(True)
            self._update_dalles_count()
            
            # Activer la section pente uniquement pour les MNT
            is_mnt = "MNT" in source_name
            self.slopeGroupBox.setEnabled(is_mnt)
            if not is_mnt:
                self.calculateSlopeCheckBox.setChecked(False)
                self.slopePercentCheckBox.setChecked(False)
            
            # Recréer la grille si affichée
            if self.showGridCheckBox.isChecked():
                self._create_grid()
        else:
            # Option par défaut sélectionnée
            self.current_source = None
            self.downloadButton.setEnabled(False)
            self.slopeGroupBox.setEnabled(False)
            self._remove_grid()
    
    def _create_grid(self):
        """Crée la couche de grille de mosaïquage."""
        if not self.current_source:
            return
        
        # Supprimer l'ancienne grille
        self._remove_grid()
        
        # Récupérer l'emprise de la vue en Lambert 93
        canvas_extent = self.canvas.extent()
        canvas_crs = self.canvas.mapSettings().destinationCrs()
        lambert93 = QgsCoordinateReferenceSystem("EPSG:2154")
        
        if canvas_crs != lambert93:
            transform = QgsCoordinateTransform(canvas_crs, lambert93, QgsProject.instance())
            canvas_extent = transform.transformBoundingBox(canvas_extent)
        
        # Arrondir aux kilomètres
        xmin = int(canvas_extent.xMinimum() / 1000) * 1000
        xmax = (int(canvas_extent.xMaximum() / 1000) + 1) * 1000
        ymin = int(canvas_extent.yMinimum() / 1000) * 1000
        ymax = (int(canvas_extent.yMaximum() / 1000) + 1) * 1000
        
        # Limiter le nombre de dalles
        nx = (xmax - xmin) // 1000
        ny = (ymax - ymin) // 1000
        if nx * ny > 2500:
            QMessageBox.warning(
                self, "Attention",
                f"Trop de dalles à afficher ({nx * ny}). Zoomez pour réduire l'emprise."
            )
            return
        
        # Créer la couche mémoire
        prefix = self.current_source["prefix"]
        self.grid_layer = QgsVectorLayer(
            "Polygon?crs=EPSG:2154",
            f"Grille {prefix}",
            "memory"
        )
        
        provider = self.grid_layer.dataProvider()
        
        # Ajouter les champs
        fields = QgsFields()
        fields.append(QgsField("id", QVariant.String))
        fields.append(QgsField("x_km", QVariant.Int))
        fields.append(QgsField("y_km", QVariant.Int))
        fields.append(QgsField("en_cache", QVariant.Int))
        provider.addAttributes(fields)
        self.grid_layer.updateFields()
        
        # Créer les dalles
        features = []
        for x in range(xmin, xmax, 1000):
            for y in range(ymin, ymax, 1000):
                x_km = x // 1000
                y_km = (y + 1000) // 1000
                
                # Vérifier si en cache
                if "LHD" in prefix:
                    code = self.current_source.get("code", "MNT")
                    filename = f"LHD_FXX_{x_km:04d}_{y_km:04d}_{code}_O_0M50_LAMB93_IGN69.tif"
                else:
                    filename = f"RGEALTI_FXX_{x_km:04d}_{y_km:04d}_MNT_LAMB93_IGN69.tif"
                
                cache_path = os.path.join(self.download_dir, filename)
                en_cache = 1 if os.path.exists(cache_path) else 0
                
                # Créer le polygone
                rect = QgsRectangle(x, y, x + 1000, y + 1000)
                geom = QgsGeometry.fromRect(rect)
                
                feat = QgsFeature()
                feat.setGeometry(geom)
                feat.setAttributes([
                    f"{x_km:04d}_{y_km:04d}",
                    x_km,
                    y_km,
                    en_cache
                ])
                features.append(feat)
        
        provider.addFeatures(features)
        
        # Style catégorisé (en cache = vert, à télécharger = rouge transparent)
        categories = []
        
        # En cache (vert)
        symbol_cache = QgsFillSymbol.createSimple({
            'color': '39,174,96,100',
            'outline_color': '39,174,96,255',
            'outline_width': '0.5'
        })
        categories.append(QgsRendererCategory(1, symbol_cache, "En cache"))
        
        # À télécharger (rouge)
        symbol_download = QgsFillSymbol.createSimple({
            'color': '231,76,60,50',
            'outline_color': '231,76,60,255',
            'outline_width': '0.5'
        })
        categories.append(QgsRendererCategory(0, symbol_download, "À télécharger"))
        
        renderer = QgsCategorizedSymbolRenderer("en_cache", categories)
        self.grid_layer.setRenderer(renderer)
        
        # Ajouter au projet
        QgsProject.instance().addMapLayer(self.grid_layer)
        self.grid_layer_id = self.grid_layer.id()
        
        # Connecter le signal de sélection
        self.grid_layer.selectionChanged.connect(self._on_grid_selection_changed)
        
        self.canvas.refresh()
    
    def _remove_grid(self):
        """Supprime la couche de grille."""
        if self.grid_layer_id:
            layer = QgsProject.instance().mapLayer(self.grid_layer_id)
            if layer:
                QgsProject.instance().removeMapLayer(self.grid_layer_id)
        self.grid_layer = None
        self.grid_layer_id = None
        self.selected_tiles.clear()
        self.useSelectionButton.setEnabled(False)
    
    def cleanup_grid(self):
        """Nettoie la grille lors de la fermeture."""
        self._remove_grid()
    
    def _on_grid_selection_changed(self):
        """Met à jour quand la sélection de dalles change."""
        if not self.grid_layer:
            return
        
        selected = self.grid_layer.selectedFeatures()
        self.selected_tiles.clear()
        
        for feat in selected:
            x_km = feat["x_km"]
            y_km = feat["y_km"]
            self.selected_tiles.add((x_km, y_km))
        
        # Activer le bouton si des dalles sont sélectionnées
        self.useSelectionButton.setEnabled(len(self.selected_tiles) > 0)
        
        # Mettre à jour le label
        if self.selected_tiles:
            self.dallesInfoLabel.setText(f"Sélection : {len(self.selected_tiles)} dalles")
            self.dallesInfoLabel.setStyleSheet("QLabel { color: #9b59b6; font-weight: bold; }")
    
    def use_selected_tiles(self):
        """Utilise les dalles sélectionnées pour définir l'emprise."""
        if not self.selected_tiles:
            QMessageBox.warning(self, "Aucune sélection", 
                "Sélectionnez des dalles sur la grille d'abord.")
            return
        
        # Calculer l'emprise des dalles sélectionnées
        x_coords = [t[0] for t in self.selected_tiles]
        y_coords = [t[1] for t in self.selected_tiles]
        
        xmin = min(x_coords) * 1000
        xmax = (max(x_coords) + 1) * 1000
        ymin = (min(y_coords) - 1) * 1000
        ymax = max(y_coords) * 1000
        
        self.xminSpinBox.setValue(xmin)
        self.xmaxSpinBox.setValue(xmax)
        self.yminSpinBox.setValue(ymin)
        self.ymaxSpinBox.setValue(ymax)
        
        self._update_dalles_count()
    
    def closeEvent(self, event):
        """Nettoie à la fermeture."""
        self.cleanup_grid()
        super().closeEvent(event)

    def refresh_extent_from_canvas(self):
        """Utilise l'emprise de la vue courante."""
        canvas = self.iface.mapCanvas()
        extent = canvas.extent()
        
        # Transformer en Lambert 93
        canvas_crs = canvas.mapSettings().destinationCrs()
        lambert93 = QgsCoordinateReferenceSystem("EPSG:2154")
        
        if canvas_crs != lambert93:
            transform = QgsCoordinateTransform(canvas_crs, lambert93, QgsProject.instance())
            extent = transform.transformBoundingBox(extent)
        
        # Arrondir aux kilomètres
        self.xminSpinBox.setValue(int(extent.xMinimum() / 1000) * 1000)
        self.xmaxSpinBox.setValue((int(extent.xMaximum() / 1000) + 1) * 1000)
        self.yminSpinBox.setValue(int(extent.yMinimum() / 1000) * 1000)
        self.ymaxSpinBox.setValue((int(extent.yMaximum() / 1000) + 1) * 1000)
        
    def use_layer_extent(self):
        """Ouvre un dialogue pour choisir une couche et utilise son emprise."""
        from qgis.PyQt.QtWidgets import QInputDialog
        
        layers = QgsProject.instance().mapLayers().values()
        layer_names = [layer.name() for layer in layers if layer.id() != self.grid_layer_id]
        
        if not layer_names:
            QMessageBox.warning(self, "Aucune couche", "Aucune couche disponible dans le projet.")
            return
        
        name, ok = QInputDialog.getItem(
            self, "Choisir une couche", "Couche :", layer_names, 0, False
        )
        
        if ok and name:
            layer = QgsProject.instance().mapLayersByName(name)[0]
            extent = layer.extent()
            
            layer_crs = layer.crs()
            lambert93 = QgsCoordinateReferenceSystem("EPSG:2154")
            
            if layer_crs != lambert93:
                transform = QgsCoordinateTransform(layer_crs, lambert93, QgsProject.instance())
                extent = transform.transformBoundingBox(extent)
            
            self.xminSpinBox.setValue(int(extent.xMinimum() / 1000) * 1000)
            self.xmaxSpinBox.setValue((int(extent.xMaximum() / 1000) + 1) * 1000)
            self.yminSpinBox.setValue(int(extent.yMinimum() / 1000) * 1000)
            self.ymaxSpinBox.setValue((int(extent.yMaximum() / 1000) + 1) * 1000)
    
    def _update_dalles_count(self):
        """Met à jour le compteur de dalles."""
        xmin = self.xminSpinBox.value()
        xmax = self.xmaxSpinBox.value()
        ymin = self.yminSpinBox.value()
        ymax = self.ymaxSpinBox.value()
        
        if xmax <= xmin or ymax <= ymin:
            self.dallesInfoLabel.setText("Emprise invalide")
            self.dallesInfoLabel.setStyleSheet("QLabel { color: #e74c3c; font-weight: bold; }")
            return
        
        nx = (xmax - xmin) // 1000
        ny = (ymax - ymin) // 1000
        total = nx * ny
        
        self.dallesInfoLabel.setText(f"Dalles : {total} ({nx} x {ny})")
        
        if total > 100:
            self.dallesInfoLabel.setStyleSheet("QLabel { color: #e74c3c; font-weight: bold; }")
        elif total > 25:
            self.dallesInfoLabel.setStyleSheet("QLabel { color: #e67e22; font-weight: bold; }")
        else:
            self.dallesInfoLabel.setStyleSheet("QLabel { color: #27ae60; font-weight: bold; }")
    
    def _browse_cache_dir(self):
        """Ouvre un dialogue pour choisir le dossier de cache."""
        dir_path = QFileDialog.getExistingDirectory(
            self,
            "Choisir le dossier de cache",
            self.download_dir
        )
        if dir_path:
            self.download_dir = dir_path
            self.cacheDirLineEdit.setText(dir_path)
            self.settings.setValue("ign_alti_downloader/download_dir", dir_path)
            self._update_cache_size()
            
            # Rafraîchir la grille si affichée
            if self.showGridCheckBox.isChecked():
                self._create_grid()
    
    def _update_cache_size(self):
        """Calcule et affiche la taille du cache."""
        if not os.path.exists(self.download_dir):
            self.cacheSizeLabel.setText(
                '<span style="font-size:9pt; font-style:italic; color:#7f8c8d;">'
                'Taille du cache : 0 MB (dossier non créé)</span>'
            )
            return
        
        total = 0
        count = 0
        for f in os.listdir(self.download_dir):
            fp = os.path.join(self.download_dir, f)
            if os.path.isfile(fp) and f.endswith(('.tif', '.vrt')):
                total += os.path.getsize(fp)
                count += 1
        
        if total < 1024 * 1024:
            size_str = f"{total / 1024:.1f} KB"
        elif total < 1024 * 1024 * 1024:
            size_str = f"{total / (1024 * 1024):.1f} MB"
        else:
            size_str = f"{total / (1024 * 1024 * 1024):.2f} GB"
        
        self.cacheSizeLabel.setText(
            f'<span style="font-size:9pt; font-style:italic; color:#7f8c8d;">'
            f'Taille du cache : {size_str} ({count} dalles)</span>'
        )
    
    def start_download(self):
        """Lance le téléchargement des dalles."""
        if not self.current_source:
            QMessageBox.warning(self, "Erreur", "Aucune source sélectionnée")
            return
        
        xmin = self.xminSpinBox.value()
        xmax = self.xmaxSpinBox.value()
        ymin = self.yminSpinBox.value()
        ymax = self.ymaxSpinBox.value()
        
        if xmax <= xmin or ymax <= ymin:
            QMessageBox.warning(self, "Erreur", "Emprise invalide")
            return
        
        nx = (xmax - xmin) // 1000
        ny = (ymax - ymin) // 1000
        total = nx * ny
        
        if total > 500:
            reply = QMessageBox.question(
                self,
                "Confirmation",
                f"Vous allez télécharger {total} dalles.\n"
                "Cela peut prendre beaucoup de temps.\nContinuer ?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
        
        # Désactiver le bouton
        self.downloadButton.setEnabled(False)
        self.downloadButton.setText("Téléchargement en cours...")
        
        # Créer le dossier si nécessaire
        os.makedirs(self.download_dir, exist_ok=True)
        
        self.progressBar.setMaximum(total)
        self.progressBar.setValue(0)
        self.downloaded_files = []
        
        skip_cache = self.skipCacheCheckBox.isChecked()
        downloaded = 0
        skipped = 0
        errors = 0
        
        prefix = self.current_source["prefix"]
        resolution = self.current_source["resolution"]
        pixels = int(1000 / resolution)
        
        is_lidar = "LHD" in prefix
        
        for x in range(xmin, xmax, 1000):
            for y in range(ymin, ymax, 1000):
                x_km = x // 1000
                y_km = (y + 1000) // 1000
                dalle_id = f"{x_km:04d}_{y_km:04d}"
                
                if is_lidar:
                    code = self.current_source.get("code", "MNT")
                    nom_fichier = f"LHD_FXX_{x_km:04d}_{y_km:04d}_{code}_O_0M50_LAMB93_IGN69.tif"
                else:
                    nom_fichier = f"RGEALTI_FXX_{x_km:04d}_{y_km:04d}_MNT_LAMB93_IGN69.tif"
                
                cache_path = os.path.join(self.download_dir, nom_fichier)
                
                if skip_cache and os.path.exists(cache_path):
                    self.statusLabel.setText(f"Cache : {dalle_id}")
                    self.downloaded_files.append(cache_path)
                    skipped += 1
                else:
                    self.statusLabel.setText(f"Téléchargement : {dalle_id}")
                    
                    if is_lidar:
                        bbox_xmin = x - 0.25
                        bbox_ymin = y + 0.25
                        bbox_xmax = x + 1000 - 0.25
                        bbox_ymax = y + 1000 + 0.25
                    else:
                        bbox_xmin = x
                        bbox_ymin = y
                        bbox_xmax = x + 1000
                        bbox_ymax = y + 1000
                    
                    success = self._download_tile(
                        bbox_xmin, bbox_ymin, bbox_xmax, bbox_ymax,
                        cache_path, pixels
                    )
                    
                    if success:
                        downloaded += 1
                        self.downloaded_files.append(cache_path)
                    else:
                        errors += 1
                
                self.progressBar.setValue(self.progressBar.value() + 1)
                QApplication.processEvents()
        
        # Fusionner si demandé (VRT ou GeoTIFF lissé)
        merged_file = None
        if self.downloaded_files:
            if self.smoothMntCheckBox.isChecked():
                # Fusion avec lissage → GeoTIFF
                self.statusLabel.setText("Fusion et lissage du MNT...")
                QApplication.processEvents()
                
                tiff_path = os.path.join(
                    self.download_dir,
                    f"{prefix}_{xmin}_{ymin}_{xmax}_{ymax}_smooth.tif"
                )
                if self._create_smoothed_tiff(self.downloaded_files, tiff_path):
                    merged_file = tiff_path
                    self.downloaded_files = [tiff_path]
                    
            elif self.createVrtCheckBox.isChecked():
                # Fusion simple → VRT
                vrt_path = os.path.join(
                    self.download_dir,
                    f"{prefix}_{xmin}_{ymin}_{xmax}_{ymax}.vrt"
                )
                self._create_vrt(self.downloaded_files, vrt_path)
                merged_file = vrt_path
                self.downloaded_files = [vrt_path]

        # Calculer la pente si demandé
        slope_files = []
        if self.calculateSlopeCheckBox.isChecked() and self.downloaded_files:
            self.statusLabel.setText("Calcul des pentes...")
            QApplication.processEvents()
            
            for i, mnt_path in enumerate(self.downloaded_files):
                self.progressBar.setValue(int((i + 1) / len(self.downloaded_files) * 100))
                slope_path = self._calculate_slope(mnt_path)
                if slope_path:
                    slope_files.append(slope_path)
                QApplication.processEvents()
            # Créer un VRT des pentes si plusieurs fichiers
            if len(slope_files) > 1:
                slope_vrt_path = os.path.join(
                    self.download_dir,
                    f"{prefix}_{xmin}_{ymin}_{xmax}_{ymax}_pente.vrt"
                )
                self._create_vrt(slope_files, slope_vrt_path)
                slope_files = [slope_vrt_path]
        
        # Charger dans QGIS si demandé
        if self.loadAfterCheckBox.isChecked():
            for path in self.downloaded_files:
                self._load_raster(path)
            for path in slope_files:
                self._load_raster(path)
        
        # Rafraîchir la grille
        if self.showGridCheckBox.isChecked():
            self._create_grid()
        
        # Mise à jour finale
        self._update_cache_size()
        
        status = f"✅ Terminé : {downloaded} nouvelles"
        if skipped > 0:
            status += f", {skipped} en cache"
        if errors > 0:
            status += f", {errors} erreurs"
        self.statusLabel.setText(status)
        self.statusLabel.setStyleSheet("QLabel { color: #27ae60; font-weight: bold; }")
        
        self.downloadButton.setEnabled(True)
        self.downloadButton.setText("Télécharger les dalles")
    
    def _download_tile(self, xmin, ymin, xmax, ymax, output_path, pixels=1000):
        """Télécharge une dalle via WMS."""
        params = {
            "SERVICE": "WMS",
            "VERSION": "1.3.0",
            "REQUEST": "GetMap",
            "LAYERS": self.current_source["layer"],
            "STYLES": "",
            "CRS": "EPSG:2154",
            "BBOX": f"{xmin},{ymin},{xmax},{ymax}",
            "WIDTH": str(pixels),
            "HEIGHT": str(pixels),
            "FORMAT": "image/geotiff"
        }
        
        url = self.wms_base_url + "?" + "&".join(f"{k}={v}" for k, v in params.items())
        
        try:
            req = Request(url)
            req.add_header('User-Agent', 'QGIS IGN Alti Downloader Plugin')
            
            with urlopen(req, timeout=60) as response:
                content_type = response.headers.get('Content-Type', '')
                
                if 'xml' in content_type.lower() or 'html' in content_type.lower():
                    return False
                
                temp_path = output_path + ".tmp"
                with open(temp_path, 'wb') as f:
                    f.write(response.read())
                
                self._fix_georeferencing(temp_path, output_path, xmin, ymin, xmax, ymax)
                
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                
                return True
                
        except Exception as e:
            QgsMessageLog.logMessage(f"Erreur: {str(e)}", "IGN Alti", Qgis.Warning)
            return False
    
    def _fix_georeferencing(self, input_path, output_path, xmin, ymin, xmax, ymax):
        """Corrige le géoréférencement du fichier téléchargé."""
        try:
            from osgeo import gdal, osr
            
            src_ds = gdal.Open(input_path)
            if src_ds is None:
                shutil.copy(input_path, output_path)
                return
            
            driver = gdal.GetDriverByName('GTiff')
            dst_ds = driver.CreateCopy(output_path, src_ds, 0)
            
            if dst_ds:
                width = src_ds.RasterXSize
                height = src_ds.RasterYSize
                pixel_width = (xmax - xmin) / float(width)
                pixel_height = (ymax - ymin) / float(height)
                geotransform = (xmin, pixel_width, 0, ymax, 0, -pixel_height)
                dst_ds.SetGeoTransform(geotransform)
                
                srs = osr.SpatialReference()
                srs.ImportFromEPSG(2154)
                dst_ds.SetProjection(srs.ExportToWkt())
            
            src_ds = None
            dst_ds = None
            
        except Exception as e:
            shutil.copy(input_path, output_path)
            QgsMessageLog.logMessage(f"Géoref fallback: {str(e)}", "IGN Alti", Qgis.Info)
    
    def _create_vrt(self, files, output_path):
        """Crée un fichier VRT à partir des dalles."""
        try:
            from osgeo import gdal
            vrt = gdal.BuildVRT(output_path, files)
            vrt = None
            QgsMessageLog.logMessage(f"VRT créé : {output_path}", "IGN Alti", Qgis.Info)
        except Exception as e:
            QgsMessageLog.logMessage(f"Erreur VRT: {str(e)}", "IGN Alti", Qgis.Warning)
    
    def _create_smoothed_tiff(self, files, output_path):
        """Crée un GeoTIFF fusionné et lissé par filtre gaussien."""
        QgsMessageLog.logMessage(f"=== DEBUT LISSAGE GAUSSIEN ===", "IGN Alti", Qgis.Info)
        
        try:
            from osgeo import gdal
            import numpy as np
            
            # Créer un VRT temporaire pour fusionner
            temp_vrt = output_path.replace('.tif', '_temp.vrt')
            vrt_ds = gdal.BuildVRT(temp_vrt, files)
            
            if vrt_ds is None:
                QgsMessageLog.logMessage("ERREUR: VRT temporaire est None", "IGN Alti", Qgis.Warning)
                return False
            
            # Lire les données
            band = vrt_ds.GetRasterBand(1)
            data = band.ReadAsArray().astype(np.float32)
            nodata = band.GetNoDataValue()
            geotransform = vrt_ds.GetGeoTransform()
            projection = vrt_ds.GetProjection()
            width = vrt_ds.RasterXSize
            height = vrt_ds.RasterYSize
            
            QgsMessageLog.logMessage(f"Dimensions : {width} x {height}, NoData : {nodata}", "IGN Alti", Qgis.Info)
            
            vrt_ds = None
            
            # Appliquer un filtre gaussien
            sigma = 2.0
            
            # Créer un masque pour les valeurs valides
            if nodata is not None:
                mask = ~np.isclose(data, nodata)
                data_work = np.where(mask, data, np.nan)
            else:
                mask = np.ones_like(data, dtype=bool)
                data_work = data.copy()
            
            # Filtre gaussien manuel (sans scipy)
            def gaussian_kernel(size, sigma):
                """Crée un kernel gaussien 2D."""
                x = np.arange(size) - size // 2
                kernel_1d = np.exp(-x**2 / (2 * sigma**2))
                kernel_2d = np.outer(kernel_1d, kernel_1d)
                return kernel_2d / kernel_2d.sum()
            
            def apply_gaussian_filter(data, sigma):
                """Applique un filtre gaussien avec gestion des NaN."""
                kernel_size = int(6 * sigma + 1)
                if kernel_size % 2 == 0:
                    kernel_size += 1
                
                kernel = gaussian_kernel(kernel_size, sigma)
                pad = kernel_size // 2
                
                # Remplacer les NaN par 0 pour la convolution
                data_filled = np.nan_to_num(data, nan=0.0)
                valid_mask = ~np.isnan(data)
                
                # Convolution manuelle avec padding
                padded_data = np.pad(data_filled, pad, mode='reflect')
                padded_mask = np.pad(valid_mask.astype(float), pad, mode='reflect')
                
                result = np.zeros_like(data)
                weight_sum = np.zeros_like(data)
                
                for i in range(kernel_size):
                    for j in range(kernel_size):
                        result += kernel[i, j] * padded_data[i:i+data.shape[0], j:j+data.shape[1]]
                        weight_sum += kernel[i, j] * padded_mask[i:i+data.shape[0], j:j+data.shape[1]]
                
                # Normaliser par les poids valides
                weight_sum = np.maximum(weight_sum, 1e-10)
                result = result / weight_sum
                
                return result
            
            QgsMessageLog.logMessage(f"Application filtre gaussien sigma={sigma}...", "IGN Alti", Qgis.Info)
            smoothed = apply_gaussian_filter(data_work, sigma)
            
            # Restaurer les nodata
            if nodata is not None:
                smoothed = np.where(mask, smoothed, nodata)
            
            # Écrire le résultat
            driver = gdal.GetDriverByName('GTiff')
            out_ds = driver.Create(
                output_path,
                width,
                height,
                1,
                gdal.GDT_Float32,
                ['COMPRESS=LZW', 'TILED=YES', 'BIGTIFF=IF_SAFER']
            )
            
            out_ds.SetGeoTransform(geotransform)
            out_ds.SetProjection(projection)
            
            out_band = out_ds.GetRasterBand(1)
            if nodata is not None:
                out_band.SetNoDataValue(nodata)
            out_band.WriteArray(smoothed)
            
            out_ds = None
            
            # Nettoyer
            if os.path.exists(temp_vrt):
                os.remove(temp_vrt)
            
            if os.path.exists(output_path):
                QgsMessageLog.logMessage(f"GeoTIFF lissé créé : {output_path}", "IGN Alti", Qgis.Info)
                return True
            
            return False
            
        except Exception as e:
            QgsMessageLog.logMessage(f"EXCEPTION lissage: {str(e)}", "IGN Alti", Qgis.Warning)
            import traceback
            QgsMessageLog.logMessage(f"Traceback: {traceback.format_exc()}", "IGN Alti", Qgis.Warning)
            return False

    def _load_raster(self, path):
        """Charge un raster dans QGIS."""
        name = os.path.splitext(os.path.basename(path))[0]
        layer = QgsRasterLayer(path, name)
        
        if layer.isValid():
            QgsProject.instance().addMapLayer(layer)
    
    def _calculate_slope(self, input_path):
        """Calcule la pente d'un MNT avec GDAL."""
        try:
            from osgeo import gdal
            
            base_name = os.path.splitext(input_path)[0]
            output_path = f"{base_name}_pente.tif"
            
            use_percent = self.slopePercentCheckBox.isChecked()
            
            src_ds = gdal.Open(input_path)
            if src_ds is None:
                QgsMessageLog.logMessage(f"Impossible d'ouvrir {input_path}", "IGN Alti", Qgis.Warning)
                return None
            
            options = gdal.DEMProcessingOptions(
                format='GTiff',
                slopeFormat='percent' if use_percent else 'degree'
            )
            
            result = gdal.DEMProcessing(
                output_path,
                src_ds,
                'slope',
                options=options
            )
            
            src_ds = None
            result = None
            
            if os.path.exists(output_path):
                QgsMessageLog.logMessage(f"Pente calculée : {output_path}", "IGN Alti", Qgis.Info)
                return output_path
            else:
                return None
                
        except Exception as e:
            QgsMessageLog.logMessage(f"Erreur calcul pente: {str(e)}", "IGN Alti", Qgis.Warning)
            return None
