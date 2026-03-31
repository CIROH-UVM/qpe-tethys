from datetime import datetime, timezone

import xarray as xr
import geopandas as gpd

from ..data_layer.raster_data import RasterData
from ..data_layer.point_data import PointData
from ..data_layer.validation import validate_raster, validate_point_data
from .tool import Tool

class LoadDatasetTool(Tool):
    """
    Loads a dataset from NOAA (MRMS radar or MADIS gauges) and creates
    a DataLayer object from it.

    The Noah boundary is in _download_raster() and _download_points() only.
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

    def get_properties(self) -> dict:
        return {
            'properties': [
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
                    'type': 'str',
                    'options': self.RFC_BBOXES.keys(),
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
    #
    # Pat's spec (NGPE_technical_reference.md Section 7):
    #   _download_raster  → must return xr.DataArray
    #   _download_points  → must return gpd.GeoDataFrame
    #
    # Noah's code currently returns different formats (see adapter notes below).
    # Once Noah updates his output OR we finalize the adapter, replace the
    # raise NotImplementedError with the actual call + adapter logic.
    # =========================================================================

    def _download_raster(self, region: str, ref_datetime: datetime) -> xr.DataArray:
        """
        Download MRMS radar QPE data for the given region and datetime.

        Calls Noah's mrms module to download NOAA MRMS data from AWS S3,
        then adapts the output to match the contract required by
        validate_raster() and RasterData.

        Required output contract (Pat's spec Section 7.2):
          - xr.DataArray (NOT xr.Dataset)
          - dims: ('y', 'x')
          - values: float32, QPE precipitation in inches (0.0 to 30.0)
          - attrs['bbox']: [W, S, E, N] in EPSG:4326  -- REQUIRED
          - attrs['crs']:  'EPSG:4326'

        Noah's mrms.get_data() currently returns:
          - xr.Dataset (needs ds['variable_name'] to get DataArray)
          - dims: ('time', 'latitude', 'longitude')
          - no attrs['bbox'] or attrs['crs'] set
          - PENDING: Noah needs to confirm MRMS product (QPE vs CREF)
                     and output units (inches vs dBZ)

        Adapter steps needed:
          1. Convert region string → bbox dict using RFC_BBOXES
          2. Call Noah's mrms.get_data(start, end, bbox, data_dir)
          3. Extract DataArray from Dataset: ds['variable_name']
          4. Remove time dim if present: da.isel(time=0)
          5. Rename dims: ('latitude','longitude') → ('y','x')
          6. Set attrs['bbox'] from coordinates
          7. Set attrs['crs'] = 'EPSG:4326'
          8. Convert units if needed (depends on MRMS product)
        """
        raise NotImplementedError(
            'MRMS data download not yet connected. '
            'Waiting for Noah to confirm MRMS product (QPE vs CREF) '
            'and update output format. See adapter steps in docstring.'
        )

    def _download_points(self, region: str, ref_datetime: datetime) -> gpd.GeoDataFrame:
        """
        Download MADIS gauge observations for the given region and datetime.

        Calls Noah's madis module to download NOAA MADIS CRN data,
        then adapts the output to match the contract required by
        validate_point_data() and PointData.

        Required output contract (Pat's spec Section 7.3):
          - gpd.GeoDataFrame
          - geometry: shapely Point(lon, lat), CRS EPSG:4326
          - 'value' column:  float, precipitation in inches (0.0 to 30.0)
          - 'qc_flag' column: int, one of {0, 1, 2, 3, 9}

        Noah's madis.get_data() currently returns:
          - gpd.GeoDataFrame
          - geometry: Point, CRS EPSG:3857 (default)
          - 'precipAccum' column (not 'value'), units in mm (not inches)
          - no 'qc_flag' column
          - extra 'datetime' column (harmless, can keep)

        Adapter steps needed:
          1. Convert region string → bbox dict using RFC_BBOXES
          2. Call Noah's madis.get_data(start, end, bbox,
                                        crs_out='EPSG:4326', data_dir)
          3. Rename column: 'precipAccum' → 'value'
          4. Convert units: mm → inches (value / 25.4)
          5. Add 'qc_flag' column:
             - PENDING: Noah needs to extract QC flags from MADIS NetCDF
             - If unavailable, default to 9 (No QC) — all dots grey
        """
        raise NotImplementedError(
            'MADIS data download not yet connected. '
            'Waiting for Noah to add qc_flag extraction from MADIS NetCDF. '
            'See adapter steps in docstring.'
        )
