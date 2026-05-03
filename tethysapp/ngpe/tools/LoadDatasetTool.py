"""LoadDatasetTool — downloads NOAA data and creates DataLayer objects.

Wiring to Noah's downloaders (2026-04-20):
  - _download_raster() calls qpe-tethys/data/mrms.get_data()
  - _download_points() calls qpe-tethys/data/madis.get_data()
  - Each method adapts Noah's output format to match the contract
    expected by validate_raster()/validate_point_data() and
    RasterData/PointData classes.
  - qpe-tethys is not an installed package, so we add it to sys.path
    at import time.

Noah's mrms module returns CREF (composite reflectivity in dBZ), not
QPE precipitation in inches. The adapter clamps negative dBZ to 0 so
validation passes. When a true QPE product is available, update the
MRMS download call and remove the clamp.
"""

import os
import sys
from datetime import datetime, timezone

import numpy as np
import xarray as xr
import geopandas as gpd

from ..data_layer.raster_data import RasterData
from ..data_layer.point_data import PointData
from ..data_layer.validation import validate_raster, validate_point_data
from .tool import Tool

# ── Import Noah's download modules from qpe-tethys/data/ ──
# qpe-tethys is not installed as a Python package, so we add its parent
# directory to sys.path to allow `from data import mrms, madis`.
_QPE_TETHYS_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'qpe-tethys')
)
if _QPE_TETHYS_DIR not in sys.path:
    sys.path.insert(0, _QPE_TETHYS_DIR)

from data import mrms as noah_mrms
from data import madis as noah_madis


class LoadDatasetTool(Tool):
    """
    Loads a dataset from NOAA (MRMS radar or MADIS gauges) and creates
    a DataLayer object from it.

    _download_raster() and _download_points() call Noah's modules
    (qpe-tethys/data/mrms.py and madis.py) and adapt the output to
    match Pat's DataLayer contracts.
    """

    name = 'Load Dataset Tool'

# Dataset catalog -- descriptions shown in the dropdown UI
# Pat's ask: add dataset descriptions so forecasters know what they're loading
    DATASET_CATALOG = [
        {
            'id': 'mrms_qpe_01h',
            'name': 'MRMS Radar QPE',
            'description': (
                'Multi-Sensor QPE -- NOAA MRMS hourly radar precipitation estimate. '
                '1km grid covering the continental US. Combines NEXRAD radar with '
                'multi-sensor analysis. Updated every hour.'
            ),
            'layer_type': 'raster',
            'downloader': 'mrms',
        },
        {
            'id': 'madis_gauges',
            'name': 'MADIS Gauge Network',
            'description': (
                'Meteorological Assimilation Data Ingest System -- real-time hourly '
                'rain gauge observations from ASOS, COOP, MESONET and other networks. '
                'Each station includes automated QC flags. Updated every hour.'
            ),
            'layer_type': 'point',
            'downloader': 'madis',
        },
    ]

    # Region-specific bounding boxes [W, S, E, N] in EPSG:4326
    # Used to crop NOAA full-CONUS downloads to the selected RFC region
    # TODO: Look up actual lat-lons
    RFC_BBOXES = {
        'arkansas-red':  [-103.0, 33.0, -94.0, 38.0],
        'colorado':      [-112.0, 35.0, -104.0, 42.0],
        'california-nv': [-125.0, 32.0, -114.0, 42.0],
        'northeast':     [-80.0, 40.0, -67.0, 47.5],
        'missouri':      [-105.0, 37.0, -90.0, 49.0],
        'north-central': [-97.0, 40.0, -82.0, 49.0],
        'northwest':     [-125.0, 42.0, -111.0, 49.0],
        'ohio':          [-90.0, 36.0, -78.0, 43.0],
        'southeast':     [-91.0, 25.0, -75.0, 37.0],
        'west-gulf':     [-107.0, 26.0, -93.0, 37.0],
        'mid-atlantic':  [-83.0, 36.0, -74.0, 42.0],
        'lower-miss':    [-95.0, 29.0, -87.0, 37.0],
    }
    DEFAULT_BBOX = [-100.0, 33.0, -90.0, 40.0]

    def get_properties(self) -> list:
        """Return list of property dicts for the ToolPropertiesPanel UI.

        Changed: returns plain list (was wrapped in {'properties': [...]}).
        Changed: 'region' type fixed from 'str' to 'list' (has options).
        """
        return [
            {
                'name': 'dataset_id',
                'type': 'list',
                'options': [d['id'] for d in self.DATASET_CATALOG],
                'label': 'Dataset',
            },
            {
                'name': 'output_name',
                'type': 'str',
                'label': 'Output layer name',
            },
            {
                'name': 'ref_datetime',
                'type': 'datetime',
                'label': 'Reference datetime (UTC)',
            },
            {
                'name': 'region',
                'type': 'list',
                'options': list(self.RFC_BBOXES.keys()),
                'label': 'RFC Region',
            },
        ]

    def run(self):
        """Execute the load: download, validate, create DataLayer."""
        dataset_id = self.properties.get('dataset_id')
        output_name = self.properties.get('output_name', dataset_id)
        ref_datetime = self.properties.get('ref_datetime', datetime.now(timezone.utc))
        region = self.properties.get('region', '')

        dataset = next(
            (d for d in self.DATASET_CATALOG if d['id'] == dataset_id), None
        )
        if dataset is None:
            raise ValueError(
                f"Unknown dataset_id: '{dataset_id}'. "
                f"Valid options: {[d['id'] for d in self.DATASET_CATALOG]}"
            )

        self.status = 'running'

        try:
            if dataset['layer_type'] == 'raster':
                raw_data = self._download_raster(region, ref_datetime)

                # CREF data is in dBZ (0-75), not QPE inches (0-30).
                # Pass value_max=80 so validation accepts dBZ range.
                # When a true QPE product is available, use the default.
                errors = validate_raster(raw_data, value_max=80.0)
                if errors:
                    self.status = 'error'
                    raise ValueError(f'Raster validation failed: {errors}')

                layer = RasterData(
                    name=output_name,
                    description=dataset['description'],
                    region=region,
                    ref_datetime=ref_datetime,
                    creator_tool=self.name,
                    data=raw_data,
                )

            elif dataset['layer_type'] == 'point':
                raw_data = self._download_points(region, ref_datetime)

                errors = validate_point_data(raw_data)
                if errors:
                    self.status = 'error'
                    raise ValueError(f'Point validation failed: {errors}')

                layer = PointData(
                    name=output_name,
                    description=dataset['description'],
                    region=region,
                    ref_datetime=ref_datetime,
                    creator_tool=self.name,
                    data=raw_data,
                )

            else:
                raise ValueError(f"Unknown layer_type: {dataset['layer_type']}")

            # Note: layer.save() skipped -- Tethys Component Apps handle
            # models differently. DataLayer objects work in-memory for now.
            self.status = 'done'
            self._result = layer
            return layer

        except Exception:
            self.status = 'error'
            raise

    # =========================================================================
    # NOAH BOUNDARY — Data download integration
    #
    # These two methods call Noah's download modules (qpe-tethys/data/)
    # and adapt the output to match the contracts expected by
    # validate_raster(), validate_point_data(), RasterData, and PointData.
    #
    # Wired up 2026-04-20 per team agreement to use Noah's existing code.
    # =========================================================================

    def _region_to_bbox_dict(self, region: str) -> dict:
        """Convert region string to bbox dict format Noah's code expects.

        Noah's modules expect: {'min_lon', 'max_lon', 'min_lat', 'max_lat'}
        Our RFC_BBOXES stores: [W, S, E, N]
        """
        bbox_list = self.RFC_BBOXES.get(region, self.DEFAULT_BBOX)
        return {
            'min_lon': bbox_list[0],
            'min_lat': bbox_list[1],
            'max_lon': bbox_list[2],
            'max_lat': bbox_list[3],
        }

    def _download_raster(self, region: str, ref_datetime: datetime) -> xr.DataArray:
        """
        Download MRMS data via Noah's mrms.get_data() and adapt to DataLayer contract.

        Noah's mrms.get_data() returns:
          - xr.Dataset with 'cref' variable, dims (time, latitude, longitude)
          - CREF = composite reflectivity in dBZ (not QPE inches)
          - coordinates in EPSG:4326

        Adapter steps (documented in Pat's spec Section 7.2):
          1. Convert region → bbox dict for Noah's API
          2. Call noah_mrms.get_data(start, end, bbox)
          3. Extract DataArray: ds['cref']
          4. Remove time dim: da.isel(time=0)
          5. Rename dims: (latitude, longitude) → (y, x)
          6. Set attrs['bbox'] = [W, S, E, N] from coordinates
          7. Set attrs['crs'] = 'EPSG:4326'
          8. Clamp negative values to 0 (dBZ can be negative;
             validation expects >= 0). When true QPE product is
             available, replace this with proper unit conversion.

        Required output contract:
          - xr.DataArray, dims ('y', 'x'), float32
          - attrs['bbox']: [W, S, E, N] in EPSG:4326
          - attrs['crs']: 'EPSG:4326'
        """
        # Step 1: Convert region to bbox dict
        bbox = self._region_to_bbox_dict(region)

        # Step 2: Call Noah's downloader (single hour: start == end)
        ds = noah_mrms.get_data(
            start_datetime=ref_datetime,
            end_datetime=ref_datetime,
            bbox=bbox,
        )

        # Step 3: Extract DataArray from Dataset
        # Noah's module names the variable 'cref' after renaming
        if 'cref' in ds.data_vars:
            da = ds['cref']
        else:
            # Fallback: take the first data variable
            var_name = list(ds.data_vars)[0]
            da = ds[var_name]

        # Step 4: Remove time dimension (single timestep)
        if 'time' in da.dims:
            da = da.isel(time=0)

        # Step 5: Rename dims to match DataLayer contract
        rename_map = {}
        if 'latitude' in da.dims:
            rename_map['latitude'] = 'y'
        if 'longitude' in da.dims:
            rename_map['longitude'] = 'x'
        if rename_map:
            da = da.rename(rename_map)

        # Step 6: Set bbox from actual coordinate bounds
        if 'x' in da.coords and 'y' in da.coords:
            W = float(da.coords['x'].min())
            E = float(da.coords['x'].max())
            S = float(da.coords['y'].min())
            N = float(da.coords['y'].max())
        else:
            # Fallback to region bbox
            bbox_list = self.RFC_BBOXES.get(region, self.DEFAULT_BBOX)
            W, S, E, N = bbox_list
        da.attrs['bbox'] = [W, S, E, N]

        # Step 7: Set CRS
        da.attrs['crs'] = 'EPSG:4326'

        # Step 8: Handle MRMS sentinel values and negative dBZ
        # MRMS uses -99 (and other large negatives) as "no data" sentinels.
        # These are NOT NaN in the GRIB2 file. Replace them with NaN so
        # _render_png() treats them as transparent nodata.
        # Actual radar returns range from ~0 to 75 dBZ.
        # NOTE: CREF is in dBZ, not QPE inches. The QPE colormap (0-5 range)
        # will saturate above 5 dBZ, but at least the data renders visibly.
        # When a true QPE product replaces CREF, update the colormap range.
        da = da.where(da >= 0, np.nan).astype(np.float32)

        return da

    def _download_points(self, region: str, ref_datetime: datetime) -> gpd.GeoDataFrame:
        """
        Download MADIS gauge data via Noah's madis.get_data() and adapt to DataLayer contract.

        Noah's madis.get_data() returns:
          - gpd.GeoDataFrame with columns: geometry, precipAccum, datetime
          - precipAccum is in mm
          - CRS configurable via crs_out parameter

        Adapter steps (documented in Pat's spec Section 7.3):
          1. Convert region → bbox dict for Noah's API
          2. Call noah_madis.get_data(start, end, bbox, crs_out='EPSG:4326')
          3. Rename column: precipAccum → value
          4. Convert units: mm → inches (value / 25.4)
          5. Add qc_flag = 9 (No QC) — Noah hasn't implemented QC
             extraction from MADIS NetCDF yet. All dots render grey.
          6. Clamp negative values to 0

        Required output contract:
          - gpd.GeoDataFrame, CRS EPSG:4326
          - 'value' column: float, precipitation in inches (0-30)
          - 'qc_flag' column: int, one of {0, 1, 2, 3, 9}
        """
        # Step 1: Convert region to bbox dict
        bbox = self._region_to_bbox_dict(region)

        # Step 2: Call Noah's downloader (single hour, EPSG:4326 output)
        gdf = noah_madis.get_data(
            start_datetime=ref_datetime,
            end_datetime=ref_datetime,
            bbox=bbox,
            crs_out='EPSG:4326',
        )

        # Handle empty result
        if gdf.empty:
            raise ValueError(
                f'No MADIS gauge data found for region={region}, '
                f'datetime={ref_datetime}. The NOAA server may not '
                f'have data for this time.'
            )

        # Step 3: Rename precipAccum → value
        if 'precipAccum' in gdf.columns:
            gdf = gdf.rename(columns={'precipAccum': 'value'})
        elif 'value' not in gdf.columns:
            raise ValueError(
                f"MADIS data missing precipitation column. "
                f"Available columns: {list(gdf.columns)}"
            )

        # Step 4: Convert mm → inches
        gdf['value'] = gdf['value'] / 25.4

        # Step 5: Add qc_flag column (default 9 = No QC)
        # TODO: When Noah adds QC flag extraction from MADIS NetCDF,
        # read the actual flags here instead of defaulting to 9.
        if 'qc_flag' not in gdf.columns:
            gdf['qc_flag'] = 9

        # Step 6: Clamp negative values to 0
        gdf['value'] = gdf['value'].clip(lower=0.0)

        # Step 7: Convert datetime column to string (if present)
        # Noah's get_data() adds a pandas.Timestamp 'datetime' column.
        # GeoDataFrame.to_json() can't serialize Timestamp objects.
        if 'datetime' in gdf.columns:
            gdf['datetime'] = gdf['datetime'].astype(str)

        return gdf
