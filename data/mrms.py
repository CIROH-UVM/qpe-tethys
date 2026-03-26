import datetime as dt
import gzip
import os
import shutil
import subprocess
import tempfile as tf

import numpy as np
import xarray as xr


'''
This module provides functional tools to download and process MRMS (Multi-Radar/Multi-Sensor System)
Composite Reflectivity (CREF) data from NOAA's public AWS S3 bucket.

MRMS AWS S3 bucket: https://noaa-mrms-pds.s3.amazonaws.com/CONUS/
Product: CREF_1HR_MAX_00.50 (1-hour maximum composite reflectivity at 0.50° tilt)

Files are distributed as hourly GRIB2 snapshots compressed as .grib2.gz. This module downloads,
decompresses, and processes them into xarray Datasets with standard EPSG:4326 coordinates.

NOTE: This module currently supports the CREF_1HR_MAX_00.50 product only. Additional MRMS products
may be added in future iterations.

Dependencies: cfgrib must be installed for xarray to open GRIB2 files.
  pip install cfgrib
  or
  conda install -c conda-forge cfgrib
'''

CONUS_BBOX = {
    'min_lon': -130.0,
    'max_lon': -60.0,
    'min_lat': 20.0,
    'max_lat': 55.0
}

MRMS_PRODUCT = 'CREF_1HR_MAX_00.50'
MRMS_BASE_URL = (
    'https://noaa-mrms-pds.s3.amazonaws.com/CONUS/CREF_1HR_MAX_00.50'
    '/{date_dir}/MRMS_CREF_1HR_MAX_00.50_{date_str}-{time_str}.grib2.gz'
)


def _parse_datetime(dt_input: str | dt.date | dt.datetime) -> dt.datetime:
    '''
    Normalizes a date/time input to a datetime object.

    Accepted formats:
    - datetime object (returned as-is)
    - date object (converted to datetime at midnight UTC)
    - string in MADIS/MRMS format: 'YYYYMMDD_HHMM' or 'YYYYMMDD-HHMMSS'
    - string in ISO 8601 format: 'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM'

    Raises ValueError if the string cannot be parsed.
    '''
    if isinstance(dt_input, dt.datetime):
        return dt_input
    if isinstance(dt_input, dt.date):
        return dt.datetime(dt_input.year, dt_input.month, dt_input.day)
    if isinstance(dt_input, str):
        for fmt in ('%Y%m%d_%H%M', '%Y%m%d-%H%M%S', '%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
            try:
                return dt.datetime.strptime(dt_input, fmt)
            except ValueError:
                continue
        raise ValueError(
            f"Could not parse datetime string: '{dt_input}'. "
            "Expected 'YYYYMMDD_HHMM', 'YYYYMMDD-HHMMSS', or ISO 8601."
        )
    raise TypeError(f"Expected str, date, or datetime; got {type(dt_input)}")


def _build_mrms_url(date: dt.datetime) -> str:
    '''Constructs the AWS S3 download URL for a given datetime.'''
    date_dir = date.strftime('%Y%m%d')
    date_str = date.strftime('%Y%m%d')
    time_str = date.strftime('%H%M%S')
    return MRMS_BASE_URL.format(date_dir=date_dir, date_str=date_str, time_str=time_str)


def _build_local_filename(date: dt.datetime) -> str:
    '''Constructs the local .grib2 filename for a given datetime.'''
    date_str = date.strftime('%Y%m%d')
    time_str = date.strftime('%H%M%S')
    return f'MRMS_CREF_1HR_MAX_00.50_{date_str}-{time_str}.grib2'


def download_mrms(
    date: str | dt.date | dt.datetime,
    data_dir: str,
    force_download: bool = False
) -> str:
    '''
    Downloads and decompresses a single MRMS CREF GRIB2 file for the given date/time.

    Args:
    -- date: Target date and time for which to download MRMS CREF data.
    -- data_dir: Directory in which to save the decompressed .grib2 file.
    -- force_download: If True, re-download the file even if it already exists locally. Default: False.

    Returns:
    str: Path to the decompressed .grib2 file.
    '''
    date = _parse_datetime(date)
    fname = _build_local_filename(date)
    grib_path = os.path.join(data_dir, fname)
    gz_path = grib_path + '.gz'

    if os.path.exists(grib_path) and not force_download:
        print(f'Skipping download; {fname} found at: {grib_path}')
        return grib_path

    url = _build_mrms_url(date)
    date_str = date.strftime('%Y%m%d')
    time_str = date.strftime('%H%M%S')
    print(f'TASK INITIATED: Download MRMS CREF {date_str}-{time_str}...')
    os.makedirs(data_dir, exist_ok=True)

    subprocess.run(['curl', '-k', '-o', gz_path, url], check=True)

    with gzip.open(gz_path, 'rb') as f_in:
        with open(grib_path, 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)

    os.remove(gz_path)
    print('TASK COMPLETE: MRMS CREF Download')
    return grib_path


def process_mrms(
    grib_file: str,
    bbox: dict | None = None
) -> xr.Dataset:
    '''
    Opens a MRMS CREF GRIB2 file, normalizes coordinates to EPSG:4326, applies a bounding box
    filter, and returns an xarray Dataset.

    Args:
    -- grib_file: Path to the decompressed .grib2 file.
    -- bbox: Bounding box dict with keys 'min_lon', 'max_lon', 'min_lat', 'max_lat' (degrees,
             -180 to 180 longitude convention). Defaults to CONUS.

    Returns:
    xr.Dataset with variable 'cref' and dims (latitude, longitude) in EPSG:4326.
    '''
    if not os.path.exists(grib_file):
        raise FileNotFoundError(f'GRIB2 file not found: {grib_file}')

    if bbox is None:
        bbox = CONUS_BBOX
    else:
        required_keys = {'min_lon', 'max_lon', 'min_lat', 'max_lat'}
        if not isinstance(bbox, dict) or not required_keys.issubset(bbox):
            raise TypeError(f"'bbox' must be a dict with keys: {required_keys}. Got: {bbox}")

    print(f'TASK INITIATED: Process MRMS CREF {os.path.basename(grib_file)}...')

    ds = xr.open_dataset(grib_file, engine='cfgrib')

    # cfgrib may name the CREF variable 'unknown' when the GRIB parameter table entry is missing
    data_vars = list(ds.data_vars)
    if len(data_vars) == 1:
        ds = ds.rename({data_vars[0]: 'cref'})
    elif 'unknown' in data_vars:
        ds = ds.rename({'unknown': 'cref'})

    # convert longitude from 0–360 to -180–180 if needed, then sort ascending
    if ds.longitude.values.max() > 180:
        ds = ds.assign_coords(longitude=(ds.longitude - 360))
        ds = ds.sortby('longitude')

    # latitude may be descending (north-first); sort ascending for consistent slicing
    if ds.latitude.values[0] > ds.latitude.values[-1]:
        ds = ds.sortby('latitude')

    # apply bounding box via coordinate selection
    ds = ds.sel(
        latitude=slice(bbox['min_lat'], bbox['max_lat']),
        longitude=slice(bbox['min_lon'], bbox['max_lon'])
    )

    shape = ds['cref'].shape
    print(f'Grid shape after bbox filter: {shape}')
    print('TASK COMPLETE: Process MRMS CREF')
    return ds


def get_data(
    start_datetime: str | dt.date | dt.datetime,
    end_datetime: str | dt.date | dt.datetime,
    bbox: dict | None = None,
    data_dir: str | None = None,
    force_download: bool = False
) -> xr.Dataset:
    '''
    High-level function to download and process MRMS CREF data for a given time range. Iterates
    over hourly timesteps between start and end (inclusive), downloading and processing each file,
    and returns a single xarray Dataset concatenated along the time dimension.

    Args:
    -- start_datetime: Start of the time range (inclusive).
    -- end_datetime: End of the time range (inclusive).
    -- bbox: Bounding box dict with keys 'min_lon', 'max_lon', 'min_lat', 'max_lat' (degrees).
             Defaults to CONUS.
    -- data_dir: Directory for storing downloaded .grib2 files. Defaults to the OS temp directory.
    -- force_download: If True, re-download files even if they already exist locally. Default: False.

    Returns:
    xr.Dataset with variable 'cref' and dims (time, latitude, longitude) in EPSG:4326.
    '''
    start_datetime = _parse_datetime(start_datetime)
    end_datetime = _parse_datetime(end_datetime)

    if end_datetime < start_datetime:
        raise ValueError(
            f"'end_datetime' ({end_datetime}) must be >= 'start_datetime' ({start_datetime})."
        )

    if data_dir is None:
        data_dir = tf.mkdtemp()

    # generate hourly timesteps between start and end (inclusive)
    timesteps = []
    current = start_datetime
    while current <= end_datetime:
        timesteps.append(current)
        current += dt.timedelta(hours=1)

    datasets = []
    for ts in timesteps:
        grib_file = download_mrms(ts, data_dir, force_download=force_download)
        ds = process_mrms(grib_file, bbox=bbox)
        ds = ds.expand_dims(time=[np.datetime64(ts)])
        datasets.append(ds)

    result = xr.concat(datasets, dim='time')
    return result
