"""LoadDatasetTool — downloads NOAA data and creates DataLayer objects.

Integrates with the MRMS and MADIS download modules (qpe-tethys/data/)
to fetch radar and gauge data. Each download method adapts the raw output
to match the contracts expected by RasterData and PointData.

Note: The MRMS module currently returns CREF (composite reflectivity in
dBZ), not QPE precipitation in inches. Negative dBZ values are clamped
to 0 for validation. Update this when a true QPE product is available.
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

# Import download modules from the data/ directory at the repo root.
# Not installed as a package, so we add the repo root to sys.path.
_REPO_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), '..', '..', '..')
)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from data import mrms as noah_mrms
from data import madis as noah_madis


class LoadDatasetTool(Tool):
    """Download a NOAA dataset (MRMS radar or MADIS gauges) and create
    a validated DataLayer from the result."""

    name = 'Load Dataset Tool'

    # Dataset catalog — descriptions shown in the dropdown UI
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
        """Return property definitions for the ToolPropertiesPanel UI."""
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
                # TODO: Remove value_max override when true QPE product is available.
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

            # DataLayer objects are kept in-memory (no DB persistence yet).
            self.status = 'done'
            self._result = layer
            return layer

        except Exception:
            self.status = 'error'
            raise

    # =========================================================================
    # Data download adapters
    #
    # Each method calls the corresponding download module and adapts the
    # output to match the contracts expected by the DataLayer classes.
    # =========================================================================

    def _region_to_bbox_dict(self, region: str) -> dict:
        """Convert region name to bbox dict for the download API.

        Returns: {'min_lon', 'max_lon', 'min_lat', 'max_lat'}
        """
        bbox_list = self.RFC_BBOXES.get(region, self.DEFAULT_BBOX)
        return {
            'min_lon': bbox_list[0],
            'min_lat': bbox_list[1],
            'max_lon': bbox_list[2],
            'max_lat': bbox_list[3],
        }

    def _download_raster(self, region: str, ref_datetime: datetime) -> xr.DataArray:
        """Download MRMS raster data and adapt to the DataLayer contract.

        Fetches data via mrms.get_data(), extracts the CREF variable,
        normalizes dimensions to (y, x), and sets bbox/crs attributes.

        Returns:
            xr.DataArray with dims ('y', 'x'), float32,
            attrs['bbox'] = [W, S, E, N] in EPSG:4326,
            attrs['crs'] = 'EPSG:4326'.
        """
        bbox = self._region_to_bbox_dict(region)

        # Fetch single hour of data (start == end)
        ds = noah_mrms.get_data(
            start_datetime=ref_datetime,
            end_datetime=ref_datetime,
            bbox=bbox,
        )

        # Extract the CREF variable (composite reflectivity)
        if 'cref' in ds.data_vars:
            da = ds['cref']
        else:
            # Fallback to first available data variable
            var_name = list(ds.data_vars)[0]
            da = ds[var_name]

        # Remove time dimension (single timestep)
        if 'time' in da.dims:
            da = da.isel(time=0)

        # Rename dims to match DataLayer contract: (y, x)
        rename_map = {}
        if 'latitude' in da.dims:
            rename_map['latitude'] = 'y'
        if 'longitude' in da.dims:
            rename_map['longitude'] = 'x'
        if rename_map:
            da = da.rename(rename_map)

        # Set bbox from actual coordinate bounds
        if 'x' in da.coords and 'y' in da.coords:
            W = float(da.coords['x'].min())
            E = float(da.coords['x'].max())
            S = float(da.coords['y'].min())
            N = float(da.coords['y'].max())
        else:
            # Fallback to configured region bbox
            bbox_list = self.RFC_BBOXES.get(region, self.DEFAULT_BBOX)
            W, S, E, N = bbox_list
        da.attrs['bbox'] = [W, S, E, N]

        # Set CRS attribute
        da.attrs['crs'] = 'EPSG:4326'

        # Replace MRMS sentinel values (e.g., -99) with NaN for transparent
        # rendering. Actual radar returns range from ~0 to 75 dBZ.
        # TODO: Update colormap range when true QPE product replaces CREF.
        da = da.where(da >= 0, np.nan).astype(np.float32)

        return da

    def _download_points(self, region: str, ref_datetime: datetime) -> gpd.GeoDataFrame:
        """Download MADIS gauge data and adapt to the DataLayer contract.

        Fetches data via madis.get_data(), renames columns, converts
        precipitation from mm to inches, and adds QC flags.

        Returns:
            gpd.GeoDataFrame in EPSG:4326 with 'value' (inches)
            and 'qc_flag' (int: 0/1/2/3/9) columns.
        """
        bbox = self._region_to_bbox_dict(region)

        # Fetch single hour of gauge data in EPSG:4326
        gdf = noah_madis.get_data(
            start_datetime=ref_datetime,
            end_datetime=ref_datetime,
            bbox=bbox,
            crs_out='EPSG:4326',
        )

        # Validate non-empty result
        if gdf.empty:
            raise ValueError(
                f'No MADIS gauge data found for region={region}, '
                f'datetime={ref_datetime}. The NOAA server may not '
                f'have data for this time.'
            )

        # Rename precipitation column to standard name
        if 'precipAccum' in gdf.columns:
            gdf = gdf.rename(columns={'precipAccum': 'value'})
        elif 'value' not in gdf.columns:
            raise ValueError(
                f"MADIS data missing precipitation column. "
                f"Available columns: {list(gdf.columns)}"
            )

        # Convert mm to inches
        gdf['value'] = gdf['value'] / 25.4

        # Add QC flag column (default 9 = No QC applied).
        # TODO: Read actual QC flags when extraction is implemented.
        if 'qc_flag' not in gdf.columns:
            gdf['qc_flag'] = 9

        # Clamp negative values to 0
        gdf['value'] = gdf['value'].clip(lower=0.0)

        # Convert Timestamp to string for JSON serialization
        if 'datetime' in gdf.columns:
            gdf['datetime'] = gdf['datetime'].astype(str)

        return gdf
