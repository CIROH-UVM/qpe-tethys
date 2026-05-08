import datetime as dt
import ftplib
import gzip
import os
import shutil
import subprocess
import tempfile as tf

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point
import xarray as xr


'''
This module provides functional tools to download and process precipitation gauge data from NOAA's
Meteorological Assimilation Data Ingest System (MADIS). Data are sourced from the Climate Reference
Network (CRN) and contain accumulated precipitation observations from ground-based gauges across the
continental United States.

MADIS HTTPS data access: https://madis-data.ncep.noaa.gov/madisPublic1/data/LDAD/crn/netCDF/
MADIS FTP server: madis-data.ncep.noaa.gov  (path: /LDAD/crn/netCDF)

NOTE: This module is currently scoped to CRN precipitation gauge data and the `precipAccum` variable.
Other MADIS data types (e.g., METAR) and variables may be added in future iterations.
'''

CONUS_BBOX = {
    'min_lon': -127.699,
    'max_lon': -65.137,
    'min_lat': 24.275,
    'max_lat': 49.840
}

MADIS_BASE_URL = 'https://madis-data.ncep.noaa.gov/madisPublic1/data/LDAD/crn/netCDF/{date}.gz'
MADIS_FTP_HOST = 'madis-data.ncep.noaa.gov'
MADIS_FTP_PATH = '/LDAD/crn/netCDF'


def _parse_datetime(dt_input: str | dt.date | dt.datetime) -> dt.datetime:
    '''
    Normalizes a date/time input to a datetime object.

    Accepted formats:
    - datetime object (returned as-is)
    - date object (converted to datetime at midnight)
    - string in MADIS format: 'YYYYMMDD_HHMM'
    - string in ISO 8601 format: 'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM'

    Raises ValueError if the string cannot be parsed.
    '''
    if isinstance(dt_input, dt.datetime):
        return dt_input
    if isinstance(dt_input, dt.date):
        return dt.datetime(dt_input.year, dt_input.month, dt_input.day)
    if isinstance(dt_input, str):
        for fmt in ('%Y%m%d_%H%M', '%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
            try:
                return dt.datetime.strptime(dt_input, fmt)
            except ValueError:
                continue
        raise ValueError(
            f"Could not parse datetime string: '{dt_input}'. "
            "Expected format 'YYYYMMDD_HHMM' or ISO 8601 (e.g., '2025-11-30T00:00')."
        )
    raise TypeError(f"Expected str, date, or datetime; got {type(dt_input)}")


def _date_to_madis_str(date: dt.datetime) -> str:
    '''Converts a datetime to the MADIS filename format: YYYYMMDD_HHMM.'''
    return date.strftime('%Y%m%d_%H%M')


def download_madis(
    date: str | dt.date | dt.datetime,
    data_dir: str,
    data_source: str = 'https',
    force_download: bool = False
) -> str:
    '''
    Downloads and decompresses a single MADIS CRN NetCDF file for the given date/time.

    Args:
    -- date: Target date and time for which to download MADIS data.
    -- data_dir: Directory in which to save the decompressed .nc file.
    -- data_source: Download method — 'https' (default) or 'ftp'.
    -- force_download: If True, re-download the file even if it already exists locally. Default: False.

    Returns:
    str: Path to the decompressed .nc file.
    '''
    if data_source not in ('https', 'ftp'):
        raise TypeError(f"'data_source' must be 'https' or 'ftp'; got '{data_source}'")

    date = _parse_datetime(date)
    date_str = _date_to_madis_str(date)

    gz_path = os.path.join(data_dir, f'{date_str}.gz')
    nc_path = os.path.join(data_dir, f'{date_str}.nc')

    if os.path.exists(nc_path) and not force_download:
        print(f'Skipping download; {date_str}.nc found at: {nc_path}')
        return nc_path

    print(f'TASK INITIATED: Download MADIS CRN {date_str}...')
    os.makedirs(data_dir, exist_ok=True)

    if data_source == 'https':
        url = MADIS_BASE_URL.format(date=date_str)
        subprocess.run(['curl', '-k', '-o', gz_path, url], check=True)
    else:
        remote_file = f'{date_str}.gz'
        with ftplib.FTP(MADIS_FTP_HOST, 'anonymous', 'anonymous') as ftp:
            ftp.cwd(MADIS_FTP_PATH)
            with open(gz_path, 'wb') as f:
                ftp.retrbinary(f'RETR {remote_file}', f.write)

    with gzip.open(gz_path, 'rb') as f_in:
        with open(nc_path, 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)

    os.remove(gz_path)
    print(f'TASK COMPLETE: MADIS CRN Download')
    return nc_path


def process_madis(
    nc_file: str,
    bbox: dict | None = None,
    crs_out: str = 'EPSG:3857'
) -> gpd.GeoDataFrame:
    '''
    Loads a MADIS CRN NetCDF file and returns a spatially filtered, reprojected GeoDataFrame
    of accumulated precipitation gauge observations (precipAccum).

    Args:
    -- nc_file: Path to the decompressed MADIS .nc file.
    -- bbox: Bounding box dict with keys 'min_lon', 'max_lon', 'min_lat', 'max_lat' (in degrees).
             Defaults to the continental United States (CONUS).
    -- crs_out: Output coordinate reference system. Default: 'EPSG:3857' (Web Mercator).

    Returns:
    gpd.GeoDataFrame: GeoDataFrame with Point geometries and a 'precipAccum' column,
                      filtered to the given bounding box and reprojected to crs_out.
    '''
    if not os.path.exists(nc_file):
        raise FileNotFoundError(f'NetCDF file not found: {nc_file}')

    if bbox is None:
        bbox = CONUS_BBOX
    else:
        required_keys = {'min_lon', 'max_lon', 'min_lat', 'max_lat'}
        if not isinstance(bbox, dict) or not required_keys.issubset(bbox):
            raise TypeError(
                f"'bbox' must be a dict with keys: {required_keys}. Got: {bbox}"
            )

    print(f'TASK INITIATED: Process MADIS CRN {os.path.basename(nc_file)}...')
    print(f'Filtering to bounding box: {bbox}')

    ds = xr.open_dataset(nc_file, engine='netcdf4', decode_cf=True)

    # Find the best precipitation variable available in this CRN file
    precip_candidates = [
        'precipAccum', 'archivePrecipAccum1h', 'precipAccum24h', 'precip5min',
    ]
    precip_var = None
    for candidate in precip_candidates:
        if candidate in ds.data_vars:
            precip_var = candidate
            break
    if precip_var is None:
        raise KeyError(
            f"No precipitation variable found in {nc_file}. "
            f"Available: {list(ds.data_vars)}"
        )

    df = pd.DataFrame({
        'precipAccum': ds[precip_var].values,
        'latitude': ds['latitude'].values,
        'longitude': ds['longitude'].values
    }).dropna(subset=['precipAccum'])

    geometry = [Point(lon, lat) for lon, lat in zip(df['longitude'], df['latitude'])]
    gdf = gpd.GeoDataFrame(df, crs='EPSG:4326', geometry=geometry)

    gdf = gdf.cx[bbox['min_lon']:bbox['max_lon'], bbox['min_lat']:bbox['max_lat']]
    gdf = gdf.to_crs(crs_out)

    print(f'{len(gdf)} stations found within bounding box.')
    print('TASK COMPLETE: Process MADIS CRN')
    return gdf


def get_data(
    start_datetime: str | dt.date | dt.datetime,
    end_datetime: str | dt.date | dt.datetime,
    bbox: dict | None = None,
    crs_out: str = 'EPSG:3857',
    data_dir: str | None = None,
    data_source: str = 'https',
    export_path: str | None = None,
    force_download: bool = False
) -> gpd.GeoDataFrame:
    '''
    High-level function to download and process MADIS CRN precipitation gauge data for a given
    time range. Iterates over hourly timesteps between start and end (inclusive), downloading and
    processing each file, and returns a single merged GeoDataFrame with a 'datetime' column.

    Args:
    -- start_datetime: Start of the time range (inclusive).
    -- end_datetime: End of the time range (inclusive).
    -- bbox: Bounding box dict with keys 'min_lon', 'max_lon', 'min_lat', 'max_lat' (in degrees).
             Defaults to CONUS.
    -- crs_out: Output coordinate reference system. Default: 'EPSG:3857' (Web Mercator).
    -- data_dir: Directory for storing downloaded .nc files. Defaults to the OS temp directory.
    -- data_source: Download method — 'https' (default) or 'ftp'.
    -- export_path: If provided, saves the merged GeoDataFrame to this path as a GeoJSON file.
    -- force_download: If True, re-download files even if they already exist locally. Default: False.

    Returns:
    gpd.GeoDataFrame: Merged GeoDataFrame with columns 'geometry', 'precipAccum', and 'datetime',
                      containing all stations within the bounding box across all requested timesteps.
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

    frames = []
    for ts in timesteps:
        nc_file = download_madis(ts, data_dir, data_source=data_source, force_download=force_download)
        gdf = process_madis(nc_file, bbox=bbox, crs_out=crs_out)
        if gdf.empty:
            print(f'No stations found for {_date_to_madis_str(ts)}; skipping.')
            continue
        gdf['datetime'] = ts
        frames.append(gdf)

    if not frames:
        print('No data found for the specified time range and bounding box.')
        return gpd.GeoDataFrame(columns=['geometry', 'precipAccum', 'datetime'], crs=crs_out)

    merged = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=crs_out)

    if export_path is not None:
        merged.to_file(export_path, driver='GeoJSON')
        print(f'GeoJSON saved to: {export_path}')

    return merged
