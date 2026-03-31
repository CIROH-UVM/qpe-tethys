import json
import geopandas as gpd
from django.db import models
from .base import DataLayer


# QC flag -> display colour mapping
QC_COLORS = {
    0: '#2ecc71',   # Good    -- green
    1: '#3498db',   # Suspect -- blue
    2: '#f39c12',   # Bad     -- orange
    3: '#e74c3c',   # Missing -- red
    9: '#95a5a6',   # No QC   -- grey
}
QC_LABELS = {
    0: 'Good',
    1: 'Suspect',
    2: 'Bad',
    3: 'Missing',
    9: 'No QC',
}


class PointData(DataLayer):
    """
    DataLayer backed by a GeoPandas GeoDataFrame (MADIS gauge network).

    The actual GeoDataFrame (__data) is stored in memory -- not in the DB.
    The DB row stores metadata and QC summary counts.
    """

    # DB fields -- metadata only
    network = models.CharField(max_length=100, default='MADIS')
    station_count = models.IntegerField(default=0)
    qc_summary = models.JSONField(default=dict)

    class Meta(DataLayer.Meta):
        abstract = False
        app_label = 'ngpe'

    def __init__(self, *args, data: gpd.GeoDataFrame = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.__data = data
        if data is not None:
            self.station_count = len(data)
            self._compute_qc_summary()

    def get_data(self) -> gpd.GeoDataFrame:
        return self.__data

    def _compute_qc_summary(self):
        counts = self.__data['qc_flag'].value_counts().to_dict()
        self.qc_summary = {int(k): int(v) for k, v in counts.items()}

    def to_geojson(self) -> dict:
        """Convert GeoDataFrame to GeoJSON dict with QC colours injected.

        Reprojects to EPSG:3857 (Web Mercator) because the Tethys OL wrapper's
        readFeatures() does not auto-reproject, and the map uses EPSG:3857.
        """
        gdf = self.__data.copy()
        gdf['qc_color'] = gdf['qc_flag'].map(QC_COLORS).fillna('#95a5a6')
        gdf['qc_label'] = gdf['qc_flag'].map(QC_LABELS).fillna('Unknown')
        # Reproject to EPSG:3857 to match the map projection
        if gdf.crs and gdf.crs.to_epsg() != 3857:
            gdf = gdf.to_crs(epsg=3857)
        return json.loads(gdf.to_json())

    def to_map_layer(self) -> dict:
        """Return OpenLayers VectorLayer config dict with embedded GeoJSON."""
        return {
            'type': 'Vector',
            'id': str(self.id),
            'name': self.name,
            'geojson': self.to_geojson(),
            'style': {
                'type': 'circle',
                'colorProperty': 'qc_color',
                'radius': 6,
                'strokeColor': '#ffffff',
                'strokeWidth': 1.5,
            },
        }

    def to_catalog_entry(self) -> dict:
        entry = super().to_catalog_entry()
        entry.update({
            'network': self.network,
            'station_count': self.station_count,
            'qc_summary': self.qc_summary,
        })
        return entry
