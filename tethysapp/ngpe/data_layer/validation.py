from typing import List
import numpy as np
import xarray as xr
import geopandas as gpd

# Constants
# CREF values are in dBZ (0-75 range); QPE values are in inches (0-30 range).
# Using a permissive max to support both products until QPE is available.
RASTER_VALUE_MIN = -10.0   # dBZ can be slightly negative for weak returns
RASTER_VALUE_MAX = 80.0    # dBZ max ~75; inches max ~30; 80 covers both
QPE_VALUE_MIN = 0.0        # precipitation min for gauge data (inches)
QPE_VALUE_MAX = 30.0       # precipitation max for gauge data (inches)
VALID_QC_FLAGS = {0, 1, 2, 3, 9}


def validate_raster(da: xr.DataArray) -> List[str]:
    """
    Validate an xarray.DataArray from Noah's MRMSDownloader.

    Returns:
        List of error strings. Empty list = valid.
    """
    errors = []

    if da is None or da.size == 0:
        errors.append('DataArray is empty or None')
        return errors

    if da.ndim < 2:
        errors.append(f'Expected 2D array, got {da.ndim}D')

    finite_vals = da.values[np.isfinite(da.values)]

    if len(finite_vals) == 0:
        errors.append('DataArray contains no finite values (all NaN/Inf)')
    else:
        if float(np.min(finite_vals)) < RASTER_VALUE_MIN:
            errors.append(
                f'Min value {np.min(finite_vals):.3f} is below {RASTER_VALUE_MIN}'
            )
        if float(np.max(finite_vals)) > RASTER_VALUE_MAX:
            errors.append(
                f'Max value {np.max(finite_vals):.3f} exceeds {RASTER_VALUE_MAX}'
            )

    # Check bbox is present and valid
    bbox = da.attrs.get('bbox', None)
    if bbox is None:
        errors.append(
            "Missing attrs['bbox'] -- Noah's MRMSDownloader must set "
            "da.attrs['bbox'] = [W, S, E, N] in EPSG:4326"
        )
    elif len(bbox) == 4:
        W, S, E, N = bbox
        if not (-180 <= W < E <= 180):
            errors.append(f'Invalid longitude bounds in bbox: W={W}, E={E}')
        if not (-90 <= S < N <= 90):
            errors.append(f'Invalid latitude bounds in bbox: S={S}, N={N}')

    return errors


def validate_point_data(gdf: gpd.GeoDataFrame) -> List[str]:
    """
    Validate a GeoDataFrame from Noah's MADISDownloader.

    Returns:
        List of error strings. Empty list = valid.
    """
    errors = []

    if gdf is None or len(gdf) == 0:
        errors.append('GeoDataFrame is empty or None')
        return errors

    # Check geometry type
    if not all(gdf.geometry.geom_type == 'Point'):
        bad_types = gdf.geometry.geom_type.unique().tolist()
        errors.append(f'All geometries must be Points. Found: {bad_types}')

    # Check required columns
    if 'value' not in gdf.columns:
        errors.append("Missing required column: 'value' (precipitation in inches)")
    else:
        if float(gdf['value'].min()) < QPE_VALUE_MIN:
            errors.append(f"Column 'value' has values below {QPE_VALUE_MIN} inches")
        if float(gdf['value'].max()) > QPE_VALUE_MAX:
            errors.append(f"Column 'value' has values above {QPE_VALUE_MAX} inches")

    if 'qc_flag' not in gdf.columns:
        errors.append("Missing required column: 'qc_flag' (int: 0/1/2/3/9)")
    else:
        bad_flags = set(gdf['qc_flag'].unique()) - VALID_QC_FLAGS
        if bad_flags:
            errors.append(
                f"Invalid qc_flag values found: {bad_flags}. "
                f"Valid values are: {VALID_QC_FLAGS}"
            )

    return errors
