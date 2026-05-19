# NGPE Platform

Next-Generation Quantitative Precipitation Estimate (QPE) Platform for NOAA River Forecast Centers, built on [Tethys Platform](https://www.tethysplatform.org/) 4.4.3.

## Overview

Interactive OpenLayers map application for visualizing and processing CONUS precipitation data. Supports two data sources:

- **MRMS Radar QPE** -- Multi-Radar Multi-Sensor composite reflectivity from NOAA's AWS S3 bucket, rendered as a color-mapped PNG overlay (ImageStatic).
- **MADIS Gauge Network** -- Meteorological Assimilation Data Ingest System precipitation gauge observations from NOAA's MADIS server, rendered as GeoJSON point features (Vector).

Users can load datasets by region and datetime, visualize them on the map, and apply processing tools (e.g., Scale/Bias) within user-drawn polygon extents.

## Architecture

- Built on **Tethys Platform 4.4.3** using the `ComponentBase` pattern (ReactPy server-side components).
- The entire UI is rendered via **ReactPy-Django** -- no HTML templates, no JavaScript files, no REST endpoints.
- Map layers use `lib.ol.*` / `lib.olmod.*` wrappers around OpenLayers.
- Data download modules (`data/mrms.py`, `data/madis.py`) fetch live NOAA data via HTTPS.

### Project Structure

```
tethysapp-ngpe/
├── data/                              # NOAA data download modules
│   ├── __init__.py
│   ├── mrms.py                        # MRMS radar (GRIB2 from AWS S3)
│   └── madis.py                       # MADIS gauges (NetCDF from NOAA)
├── tethysapp/ngpe/
│   ├── app.py                         # Main page: state, handlers, 3-panel layout
│   ├── models.py                      # Django model registration
│   ├── components/
│   │   ├── map_panel.py               # OpenLayers map + overlay layers
│   │   ├── ToolPropertiesPanel.py     # Right panel: tool config form
│   │   └── layer_card.py              # Left sidebar: layer metadata cards
│   ├── data_layer/
│   │   ├── base.py                    # DataLayer abstract model (UUID, metadata)
│   │   ├── raster_data.py             # RasterData: xarray -> PNG -> ImageStatic
│   │   ├── point_data.py              # PointData: GeoDataFrame -> GeoJSON -> Vector
│   │   └── validation.py              # Raster/point data validation
│   └── tools/
│       ├── tool.py                    # Tool base class
│       ├── LoadDatasetTool.py         # Downloads MRMS/MADIS data
│       └── ScaleBiasTool.py           # Scale/bias raster values in polygon
├── pyproject.toml                     # Package metadata and dependencies
└── README.md
```

### UI Layout

| Panel | Purpose |
|-------|---------|
| **Left sidebar** | Data layer cards with visibility toggle, opacity slider, remove |
| **Center** | OpenLayers map with tool buttons (lower-right) and polygon drawing |
| **Right panel** | ToolPropertiesPanel for configuring and running the selected tool |

### Tools

- **Load Data** -- Select dataset (MRMS or MADIS), RFC region, datetime, and output name. Downloads from NOAA and adds a layer to the map.
- **Scale/Bias** -- Select a raster layer, draw a polygon extent on the map, choose operation (scale=multiply, bias=add), enter a value. Creates a new modified layer.

## Prerequisites

- **Python** 3.10+
- **Tethys Platform** 4.4.3 ([installation guide](http://docs.tethysplatform.org/en/stable/installation.html))
- **eccodes** C library (required by `cfgrib` for reading GRIB2 files)
- **curl** on PATH (used by download modules for NOAA data)

### Installing eccodes

eccodes is a C library that `cfgrib` depends on. It cannot be installed via pip alone.

**Conda (recommended):**
```bash
conda install -c conda-forge eccodes
```

**Ubuntu/Debian:**
```bash
sudo apt-get install libeccodes-dev
```

**macOS (Homebrew):**
```bash
brew install eccodes
```

**Windows:**
The easiest approach is to use conda. If using pip-only, download eccodes binaries from [ECMWF](https://confluence.ecmwf.int/display/ECC/Releases) and add to PATH.

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/CIROH-UVM/qpe-tethys.git
cd qpe-tethys
```

### 2. Activate your Tethys environment

If using conda:
```bash
conda activate tethys
```

Or if Tethys is installed in your system Python, just ensure `tethys-platform` is available:
```bash
python -c "import tethys_sdk; print('Tethys OK')"
```

### 3. Install eccodes (if not already installed)

```bash
conda install -c conda-forge eccodes
```

### 4. Install the app in development mode

```bash
cd tethysapp-ngpe
pip install -e .
```

This installs the app and all Python dependencies listed in `pyproject.toml`:
- `reactpy-django`, `numpy`, `xarray`, `geopandas`, `matplotlib`, `pyproj`, `shapely`, `netcdf4`, `cfgrib`, `pandas`

### 5. Run the development server

```bash
tethys manage start
```

The app will be available at: `http://localhost:8000/apps/ngpe/`

## Usage

1. Open the app in your browser.
2. Click **Load Data** button (lower-right on map).
3. In the right panel, select a dataset, region, datetime, and output name.
4. Click **Run Tool** -- data downloads from NOAA and appears on the map.
5. To apply Scale/Bias: click **Scale/Bias** button, select target layer, draw a polygon on the map, configure operation and value, then click **Run Tool**.

## VDOM / OpenLayers Notes (for contributors)

OpenLayers components rendered through Tethys `lib.ol.*` wrappers do **not** respond to VDOM prop patches -- only CREATE and DESTROY operations work. Key patterns:

1. **Pre-registration**: All OL components used in sub-modules must appear in the `if False:` block in `app.py` so Tethys generates the required JS modules.
2. **Map key**: The map wrapper div is keyed by layer IDs (`f"map-{'-'.join(layer_ids)}"`) so the OL Map is recreated when layers are added/removed.
3. **No Group layers**: `ol.layer.Group` is not available in Tethys ol-mods. Overlay layers are added directly as map children.
4. **Source overrides**: Use `lib.olmod.layer.Image` (not `lib.ol.layer.Image`) and `lib.ol.source.Image` with `url` + `imageExtent` (not `ImageStatic`).
5. **Projections**: Raster extents and GeoJSON features must be in EPSG:3857 (map projection). Use `pyproj.Transformer` for conversion.

## Known Limitations

- **Visibility toggle**: Toggling layer visibility does not visually update (OL ignores prop patches). Layers must be removed and re-added.
- **Colormap**: Currently uses a QPE colormap (0-5 inches) but MRMS data is CREF in dBZ (0-75). Values above 5 render as purple. Will be updated when true QPE product replaces CREF.
- **No data caching**: Every "Run Tool" downloads fresh from NOAA. A cache keyed by (dataset, region, datetime) is planned.
- **Gauge styling**: QC-colored circle styling is defined in `PointData.to_map_layer()` but not yet applied by the OL Vector layer.

## License

See [LICENSE](LICENSE) for details.
