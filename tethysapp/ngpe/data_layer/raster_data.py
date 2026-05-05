import logging
import os
import numpy as np
import xarray as xr
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from pyproj import Transformer
from django.db import models
from .base import DataLayer

logger = logging.getLogger(__name__)

# Directory for rendered raster PNGs, served at /static/ngpe/data/rasters/.
_APP_PUBLIC = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'public')
_RASTER_DIR = os.path.join(_APP_PUBLIC, 'data', 'rasters')
os.makedirs(_RASTER_DIR, exist_ok=True)


# Reusable transformer: EPSG:4326 (lat/lon) → EPSG:3857 (Web Mercator).
# always_xy=True ensures (lon, lat) order, not (lat, lon).
_transformer_4326_to_3857 = Transformer.from_crs(
    'EPSG:4326', 'EPSG:3857', always_xy=True
)


def _bbox_4326_to_3857(bbox):
    """Convert [W, S, E, N] from EPSG:4326 to EPSG:3857 using pyproj.

    OL's ImageStatic imageExtent must be in the map's projection (EPSG:3857).
    Uses pyproj for accurate coordinate transformation (replaces manual math).
    """
    w, s, e, n = bbox
    x_min, y_min = _transformer_4326_to_3857.transform(w, s)
    x_max, y_max = _transformer_4326_to_3857.transform(e, n)
    return [x_min, y_min, x_max, y_max]


# QPE colour ramp definition
# (value_fraction, (R, G, B, Alpha)) -- fraction is 0.0-1.0 of vmax=5.0 inches
QPE_COLORMAP_NODES = [
    (0.000, (0.00, 0.00, 0.00, 0.00)),  # 0.0 in -- fully transparent
    (0.005, (0.64, 0.96, 0.64, 1.00)),  # trace  -- light green
    (0.100, (0.13, 0.55, 0.13, 1.00)),  # 0.5 in -- green
    (0.200, (1.00, 1.00, 0.00, 1.00)),  # 1.0 in -- yellow
    (0.400, (1.00, 0.55, 0.00, 1.00)),  # 2.0 in -- orange
    (0.600, (0.80, 0.00, 0.00, 1.00)),  # 3.0 in -- red
    (1.000, (0.60, 0.00, 0.80, 1.00)),  # 5.0 in -- purple
]
QPE_CMAP = mcolors.LinearSegmentedColormap.from_list(
    'QPE',
    [(v, c) for v, c in QPE_COLORMAP_NODES]
)
QPE_VMAX = 5.0   # inches


class RasterData(DataLayer):
    """DataLayer backed by an xarray.DataArray (MRMS radar QPE).

    Data is stored in memory; the DB row holds metadata only.
    """

    # DB fields -- metadata only
    bbox = models.JSONField(default=list)
    resolution = models.FloatField(default=0.01)
    crs = models.CharField(max_length=50, default='EPSG:4326')
    stats = models.JSONField(default=dict)

    class Meta(DataLayer.Meta):
        abstract = False
        app_label = 'ngpe'

    def __init__(self, *args, data: xr.DataArray = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.__data = data
        self._png_url = None
        if data is not None:
            self._read_bbox_from_data()
            self._compute_stats()
            self._render_png()

    def get_data(self) -> xr.DataArray:
        return self.__data

    def _read_bbox_from_data(self):
        self.bbox = self.__data.attrs.get('bbox', [-180, -90, 180, 90])
        self.crs = self.__data.attrs.get('crs', 'EPSG:4326')

    def _compute_stats(self):
        arr = self.__data.values
        finite = arr[np.isfinite(arr)]
        if len(finite) == 0:
            self.stats = {'min': 0, 'max': 0, 'mean': 0, 'nodata_pct': 100.0}
        else:
            self.stats = {
                'min': float(np.min(finite)),
                'max': float(np.max(finite)),
                'mean': float(np.mean(finite)),
                'nodata_pct': float(np.sum(~np.isfinite(arr)) / arr.size * 100),
            }

    def _render_png(self):
        """Render xarray grid to QPE colour-coded RGBA PNG file.

        Writes the PNG to public/data/rasters/ for static serving.
        Uses a file URL instead of data URI to keep VDOM payloads small.
        """
        arr = self.__data.values.astype(np.float32)
        norm = mcolors.Normalize(vmin=0, vmax=QPE_VMAX)
        rgba = QPE_CMAP(norm(arr))

        # Make nodata and zero-rain pixels fully transparent
        rgba[~np.isfinite(arr)] = [0, 0, 0, 0]
        rgba[arr == 0] = [0, 0, 0, 0]

        # Write to file in public/data/rasters/ for static serving
        filename = f'raster_{self.id}.png'
        filepath = os.path.join(_RASTER_DIR, filename)
        plt.imsave(filepath, rgba, format='png')
        file_kb = os.path.getsize(filepath) / 1024
        logger.info('PNG saved to %s (%.0f KB)', filepath, file_kb)

        # Static URL served by Django dev server from app's public/ dir
        self._png_url = f'/static/ngpe/data/rasters/{filename}'

    def png_url(self) -> str:
        """Return the static file URL for the rendered PNG."""
        return self._png_url

    def to_map_layer(self) -> dict:
        """Return OpenLayers ImageStatic config dict.

        The imageExtent is converted to EPSG:3857 to match the map projection.
        """
        extent = _bbox_4326_to_3857(self.bbox)
        logger.debug('RasterData.to_map_layer: url=%s, extent=%s', self.png_url(), extent)
        return {
            'type': 'ImageStatic',
            'id': str(self.id),
            'name': self.name,
            'url': self.png_url(),
            'extent': extent,
            'opacity': 0.75,
        }

    def to_catalog_entry(self) -> dict:
        entry = super().to_catalog_entry()
        entry.update({
            'bbox': self.bbox,
            'resolution': self.resolution,
            'stats': self.stats,
            'layer_type': 'RasterData',
        })
        return entry
