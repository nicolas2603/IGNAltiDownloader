# -*- coding: utf-8 -*-
"""
IGNAltiDownloader - Plugin QGIS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Téléchargement des MNT/MNS/MNH IGN (RGE ALTI 1m et LiDAR HD 50cm)

Author: Nicolas Lieutenant
Copyright (C) 2026
"""


def classFactory(iface):
    """Fonction d'entrée du plugin QGIS."""
    from .ign_alti_downloader import IGNAltiDownloader
    return IGNAltiDownloader(iface)
