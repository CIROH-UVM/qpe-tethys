import sys
import os
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any

import numpy as np
import xarray as xr
import geopandas as gpd

from ..data_layer.raster_data import RasterData
from ..data_layer.point_data import PointData
from ..data_layer.validation import validate_raster, validate_point_data

# Add Noah's data package to the import path
# Noah's code lives at qpe-tethys/data/ alongside the tethysapp-ngpe directory
_NOAH_DATA_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'qpe-tethys', 'data')
)
if os.path.isdir(_NOAH_DATA_DIR) and _NOAH_DATA_DIR not in sys.path:
    sys.path.insert(0, _NOAH_DATA_DIR)


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


class Tool:
    """Abstract base class for all NGPE processing tools."""

    name: str = 'Tool'
    status: str = 'idle'

    def __init__(self, inputs: list = None, prop_defaults: dict = None):
        self.inputs = inputs or []
        self.properties = prop_defaults or {}
        self.extent = None
        self._result = None

    def get_schema(self) -> Dict[str, Any]:
        raise NotImplementedError(f'{self.__class__.__name__} must implement get_schema()')

    def validate_inputs(self) -> List[str]:
        return []

    def run(self):
        raise NotImplementedError(f'{self.__class__.__name__} must implement run()')

    def to_dict(self) -> dict:
        return {
            'tool': self.name,
            'properties': self.properties,
            'status': self.status,
        }


# Region-specific bounding boxes [W, S, E, N] in EPSG:4326
# Used to crop NOAA full-CONUS downloads to the selected RFC region
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


class LoadDatasetTool(Tool):
    """
    Loads a dataset from NOAA (MRMS radar or MADIS gauges) and creates
    a DataLayer object from it.

    The Noah boundary is in _download_raster() and _download_points() only.
    """

    name = 'LoadDatasetTool'

    def get_schema(self) -> dict:
        return {
            'properties': [
                {
                    'name': 'dataset_id',
                    'type': 'list',
                    'options': [d['id'] for d in DATASET_CATALOG],
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
                    'type': 'str',
                    'label': 'RFC region ID',
                },
            ]
        }

    def run(self):
        """Execute the load: download, validate, create DataLayer."""
        dataset_id = self.properties.get('dataset_id')
        output_name = self.properties.get('output_name', dataset_id)
        ref_datetime = self.properties.get('ref_datetime', datetime.now(timezone.utc))
        region = self.properties.get('region', '')

        dataset = next(
            (d for d in DATASET_CATALOG if d['id'] == dataset_id), None
        )
        if dataset is None:
            raise ValueError(
                f"Unknown dataset_id: '{dataset_id}'. "
                f"Valid options: {[d['id'] for d in DATASET_CATALOG]}"
            )

        self.status = 'running'

        try:
            if dataset['layer_type'] == 'raster':
                raw_data = self._download_raster(region, ref_datetime)

                errors = validate_raster(raw_data)
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
    # Noah's modules: qpe-tethys/data/mrms.py and qpe-tethys/data/madis.py
    #
    # These two methods call Noah's download code and adapt the output
    # to match the contract expected by validate_raster(), validate_point_data(),
    # RasterData, and PointData.
    # =========================================================================

    @staticmethod
    def _bbox_list_to_dict(bbox_list):
        """Convert [W, S, E, N] list to Noah's bbox dict format."""
        w, s, e, n = bbox_list
        return {
            'min_lon': w, 'max_lon': e,
            'min_lat': s, 'max_lat': n,
        }

    def _download_raster(self, region: str, ref_datetime: datetime) -> xr.DataArray:
        """
        Download MRMS CREF data via Noah's mrms module and adapt to DataLayer contract.

        Noah returns: xr.Dataset, variable 'cref', dims (time, latitude, longitude)
        We return:    xr.DataArray, dims ('y', 'x'), attrs['bbox'], attrs['crs']
        """
        import mrms  # Noah's module

        bbox_list = RFC_BBOXES.get(region, DEFAULT_BBOX)
        bbox_dict = self._bbox_list_to_dict(bbox_list)

        # Noah expects start and end datetimes for a time range
        start_dt = ref_datetime
        end_dt = ref_datetime + timedelta(hours=1)

        print(f'[LoadDatasetTool] Calling mrms.get_data({start_dt}, {end_dt}, bbox={bbox_dict})')
        ds = mrms.get_data(
            start_datetime=start_dt,
            end_datetime=end_dt,
            bbox=bbox_dict,
        )

        # Adapt: Dataset → DataArray
        # Noah's variable is 'cref'; find the first data variable if different
        var_name = 'cref'
        if var_name not in ds.data_vars:
            var_name = list(ds.data_vars)[0]
            print(f'[LoadDatasetTool] MRMS variable "cref" not found, using "{var_name}"')

        da = ds[var_name]

        # Remove time dimension if present (take first timestep)
        if 'time' in da.dims:
            da = da.isel(time=0)

        # Rename dims to ('y', 'x')
        dim_map = {}
        for d in da.dims:
            if 'lat' in d.lower():
                dim_map[d] = 'y'
            elif 'lon' in d.lower():
                dim_map[d] = 'x'
        if dim_map:
            da = da.rename(dim_map)

        # Ensure float32; replace MRMS nodata sentinel (-99) with NaN
        da = da.astype(np.float32)
        da = da.where(da > -90)  # -99 and similar sentinels → NaN

        # Set bbox from coordinates or fall back to region bbox
        if 'y' in da.coords and 'x' in da.coords:
            y_vals = da.coords['y'].values
            x_vals = da.coords['x'].values
            computed_bbox = [
                float(np.min(x_vals)), float(np.min(y_vals)),
                float(np.max(x_vals)), float(np.max(y_vals)),
            ]
            da.attrs['bbox'] = computed_bbox
        else:
            da.attrs['bbox'] = bbox_list

        da.attrs['crs'] = 'EPSG:4326'

        print(f'[LoadDatasetTool] MRMS adapted: shape={da.shape}, bbox={da.attrs["bbox"]}')
        return da

    def _download_points(self, region: str, ref_datetime: datetime) -> gpd.GeoDataFrame:
        """
        Download MADIS gauge data via Noah's madis module and adapt to DataLayer contract.

        Noah returns: GeoDataFrame with 'precipAccum' (mm), CRS EPSG:3857
        We return:    GeoDataFrame with 'value' (inches), 'qc_flag', CRS EPSG:4326
        """
        import madis  # Noah's module

        bbox_list = RFC_BBOXES.get(region, DEFAULT_BBOX)
        bbox_dict = self._bbox_list_to_dict(bbox_list)

        start_dt = ref_datetime
        end_dt = ref_datetime + timedelta(hours=1)

        print(f'[LoadDatasetTool] Calling madis.get_data({start_dt}, {end_dt}, bbox={bbox_dict})')
        gdf = madis.get_data(
            start_datetime=start_dt,
            end_datetime=end_dt,
            bbox=bbox_dict,
            crs_out='EPSG:4326',  # request WGS84 directly
        )

        if gdf is None or len(gdf) == 0:
            raise ValueError(f'No MADIS stations found for region={region} at {ref_datetime}')

        # Adapt: find precipitation column, rename to 'value', convert mm → inches
        # Noah's CRN data may have different column names depending on product
        precip_col = None
        for candidate in ['precipAccum', 'precipAccum24h', 'archivePrecipAccum1h',
                          'precip5min', 'rawPrecipAccumTipBuck']:
            if candidate in gdf.columns:
                precip_col = candidate
                break

        if precip_col:
            print(f'[LoadDatasetTool] Using precipitation column: {precip_col}')
            gdf = gdf.rename(columns={precip_col: 'value'})
            gdf['value'] = gdf['value'] / 25.4  # mm to inches
        elif 'value' not in gdf.columns:
            raise ValueError(
                f"MADIS data missing precipitation column. "
                f"Columns found: {list(gdf.columns)}"
            )

        # Clamp negative values to 0 (sensor noise)
        gdf['value'] = gdf['value'].clip(lower=0.0)

        # Add qc_flag — Noah doesn't extract QC yet, default to 9 (No QC)
        if 'qc_flag' not in gdf.columns:
            gdf['qc_flag'] = 9

        # Ensure CRS is EPSG:4326
        if gdf.crs and gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(epsg=4326)

        print(f'[LoadDatasetTool] MADIS adapted: {len(gdf)} stations, crs={gdf.crs}')
        return gdf
