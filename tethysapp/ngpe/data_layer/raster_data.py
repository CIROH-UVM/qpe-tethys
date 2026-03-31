import io
import base64
import math
import numpy as np
import xarray as xr
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from django.db import models
from .base import DataLayer


def _bbox_4326_to_3857(bbox):
    """Convert [W, S, E, N] from EPSG:4326 to EPSG:3857.

    OL's ImageStatic imageExtent must be in the map's projection (EPSG:3857).
    The reference qpe_builder app confirms this -- its imageExtent uses
    Web Mercator coordinates, not lat/lon.
    """
    w, s, e, n = bbox
    x_min = w * 20037508.34 / 180.0
    x_max = e * 20037508.34 / 180.0
    y_min = math.log(math.tan((90.0 + s) * math.pi / 360.0)) * 20037508.34 / math.pi
    y_max = math.log(math.tan((90.0 + n) * math.pi / 360.0)) * 20037508.34 / math.pi
    return [x_min, y_min, x_max, y_max]


# Radar colour ramp — standard NWS reflectivity (dBZ) scale
# Used for CREF product; will also work for QPE once available
# (value_fraction, (R, G, B, Alpha)) — fraction is 0.0-1.0 of RASTER_VMAX
RADAR_COLORMAP_NODES = [
    (0.000, (0.00, 0.00, 0.00, 0.00)),  #  0 dBZ -- transparent (no echo)
    (0.067, (0.00, 0.93, 0.93, 1.00)),  #  5 dBZ -- cyan (very light)
    (0.200, (0.00, 0.80, 0.00, 1.00)),  # 15 dBZ -- green
    (0.333, (0.00, 0.55, 0.00, 1.00)),  # 25 dBZ -- dark green
    (0.467, (1.00, 1.00, 0.00, 1.00)),  # 35 dBZ -- yellow
    (0.600, (1.00, 0.55, 0.00, 1.00)),  # 45 dBZ -- orange
    (0.733, (0.80, 0.00, 0.00, 1.00)),  # 55 dBZ -- red
    (0.867, (0.60, 0.00, 0.80, 1.00)),  # 65 dBZ -- purple
    (1.000, (1.00, 1.00, 1.00, 1.00)),  # 75 dBZ -- white (extreme)
]
RADAR_CMAP = mcolors.LinearSegmentedColormap.from_list(
    'Radar',
    [(v, c) for v, c in RADAR_COLORMAP_NODES]
)
RASTER_VMAX = 75.0   # dBZ for CREF; change to 5.0 (inches) when QPE is available


class RasterData(DataLayer):
    """
    DataLayer backed by an xarray.DataArray (MRMS radar QPE).

    The actual DataArray (__data) is stored in memory -- not in the DB.
    The DB row stores metadata and the path to the rendered PNG.
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

    # Max pixel dimensions for the base64 PNG sent via ReactPy websocket.
    # Real NOAA grids can be 700x1200+; base64 must stay under ~40KB to avoid
    # overwhelming ReactPy's VDOM diffing and websocket. Stubs at 100x100 worked;
    # keep real data around that size too.
    MAX_RENDER_PIXELS = 150

    def _render_png(self):
        """Render xarray grid to colour-coded RGBA PNG as base64 data URI.

        Downsamples large grids to MAX_RENDER_PIXELS on the longest side
        to keep the base64 string small enough for ReactPy's websocket.
        """
        arr = self.__data.values.astype(np.float32)

        # Downsample if needed — use simple slicing (nearest-neighbor)
        rows, cols = arr.shape
        max_dim = max(rows, cols)
        if max_dim > self.MAX_RENDER_PIXELS:
            factor = max(1, max_dim // self.MAX_RENDER_PIXELS)
            arr = arr[::factor, ::factor]
            print(f'[NGPE] Downsampled raster from {rows}x{cols} to {arr.shape[0]}x{arr.shape[1]} (factor={factor})')

        norm = mcolors.Normalize(vmin=0, vmax=RASTER_VMAX)
        rgba = RADAR_CMAP(norm(arr))

        # Make nodata and sub-threshold pixels fully transparent
        rgba[~np.isfinite(arr)] = [0, 0, 0, 0]
        rgba[arr <= 0] = [0, 0, 0, 0]

        buf = io.BytesIO()
        plt.imsave(buf, rgba, format='png')
        buf.seek(0)
        b64 = base64.b64encode(buf.read()).decode('ascii')
        self._png_url = f'data:image/png;base64,{b64}'
        print(f'[NGPE] PNG rendered as data URI ({len(b64)} chars, {arr.shape[0]}x{arr.shape[1]})')

    def png_url(self) -> str:
        """Return the static file URL for the rendered PNG."""
        return self._png_url

    def to_map_layer(self) -> dict:
        """Return OpenLayers ImageStatic config dict.

        The imageExtent is converted to EPSG:3857 to match the map projection.
        This matches the reference qpe_builder app pattern -- OL requires the
        extent in the map's native projection when no projection prop is set.
        """
        extent = _bbox_4326_to_3857(self.bbox)
        print(f'[NGPE] RasterData.to_map_layer: url={self.png_url()}, extent={extent}')
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
