"""MapPanel — OpenLayers map component for NGPE.

Renders data layers (raster, vector) and polygon extent overlay
from active_layers state.

Architecture note (from qpe_builder reference app):
  OL does NOT handle child-level VDOM swaps inside a live Map.
  The map wrapper key MUST change when layers change so OL
  destroys and recreates the entire map with the new children.
"""

import json
from pyproj import Transformer

# Reusable transformer for polygon vertex display
_transformer_4326_to_3857 = Transformer.from_crs(
    'EPSG:4326', 'EPSG:3857', always_xy=True
)


def _build_polygon_geojson_3857(vertices_4326):
    """Build a GeoJSON FeatureCollection from vertices in EPSG:4326.

    Converts to EPSG:3857 for map display. Includes Point features
    (visible as blue dots with OL default style) plus LineString/Polygon.
    """
    if not vertices_4326:
        return None

    coords_3857 = []
    for lon, lat in vertices_4326:
        x, y = _transformer_4326_to_3857.transform(lon, lat)
        coords_3857.append([x, y])

    features = []

    # Each vertex as a Point (always visible as blue dot in OL default style)
    for i, coord in enumerate(coords_3857):
        features.append({
            'type': 'Feature',
            'geometry': {'type': 'Point', 'coordinates': coord},
            'properties': {'vertex': i + 1},
        })

    if len(coords_3857) >= 2:
        features.append({
            'type': 'Feature',
            'geometry': {'type': 'LineString', 'coordinates': coords_3857},
            'properties': {'type': 'outline'},
        })

    if len(coords_3857) >= 3:
        ring = coords_3857 + [coords_3857[0]]
        features.append({
            'type': 'Feature',
            'geometry': {'type': 'Polygon', 'coordinates': [ring]},
            'properties': {'type': 'polygon'},
        })

    return {'type': 'FeatureCollection', 'features': features}


def _compute_combined_extent(active_layers):
    """Compute the combined EPSG:3857 extent from all visible layers.

    Returns [center_x, center_y], zoom or None if no layers with extents.
    """
    min_x, min_y = float('inf'), float('inf')
    max_x, max_y = float('-inf'), float('-inf')
    has_extent = False

    for uid, entry in active_layers.items():
        if not entry.get('added') or not entry.get('visible', True):
            continue
        config = entry.get('config', {})
        extent = config.get('extent')
        if extent and len(extent) == 4:
            min_x = min(min_x, extent[0])
            min_y = min(min_y, extent[1])
            max_x = max(max_x, extent[2])
            max_y = max(max_y, extent[3])
            has_extent = True

    if not has_extent:
        return None

    center_x = (min_x + max_x) / 2
    center_y = (min_y + max_y) / 2

    # Estimate zoom from extent width (EPSG:3857 meters).
    # Rough mapping: world ~40M meters wide at zoom 0, halves per zoom level.
    width = max_x - min_x
    height = max_y - min_y
    span = max(width, height)
    if span <= 0:
        zoom = 8
    else:
        import math
        zoom = int(math.log2(40_000_000 / span))
        zoom = max(3, min(zoom, 14))

    return [center_x, center_y], zoom


# CONUS center in EPSG:3857 (~97.5W, 39N) and zoom level
_CONUS_CENTER = [-10850000, 4750000]
_CONUS_ZOOM = 4


def MapPanel(lib, active_layers, error_msg, polygon_vertices=None,
             draw_mode=False, on_coordinate_click=None, is_running=False):
    """
    OpenLayers map panel -- renders layers from active_layers state.

    Args:
        active_layers: Dict of layer entries for map rendering.
        error_msg: Error string to display as overlay (or None).
        polygon_vertices: List of [lon, lat] in EPSG:4326 for extent drawing.
        draw_mode: If True, map clicks add polygon vertices.
        on_coordinate_click: Callback for map clicks (receives coordinate).
        is_running: True while a tool is executing (shows loading overlay).
    """

    # Build OL layers from active_layers state
    overlay_layers = []

    for uid, entry in active_layers.items():
        if not entry.get('added', False) or not entry.get('visible', True):
            continue

        config = entry.get('config', {})
        ltype = config.get('type')

        if ltype == 'ImageStatic':
            url = config['url']
            source = lib.ol.source.Image(
                options=lib.Props(
                    url=url,
                    imageExtent=config['extent'],
                )
            )
            layer = lib.olmod.layer.Image(
                options=lib.Props(title=config.get('name', 'Radar')),
            )(source)
            overlay_layers.append(layer)

        elif ltype == 'Vector':
            geojson_str = json.dumps(config['geojson'])

            source = lib.ol.source.Vector(
                options=lib.Props(
                    features=geojson_str,
                    format='GeoJSON',
                ),
            )
            layer = lib.ol.layer.Vector(
                options=lib.Props(title=config.get('name', 'Gauges')),
            )(source)
            overlay_layers.append(layer)

    # Polygon extent drawing layer
    if polygon_vertices:
        poly_geojson = _build_polygon_geojson_3857(polygon_vertices)
        if poly_geojson:
            poly_source = lib.ol.source.Vector(
                options=lib.Props(
                    features=json.dumps(poly_geojson),
                    format='GeoJSON',
                ),
            )
            poly_layer = lib.ol.layer.Vector(
                options=lib.Props(title='Extent'),
            )(poly_source)
            overlay_layers.append(poly_layer)

    # Compute view center/zoom: fit to data layers if any, else CONUS default
    fit = _compute_combined_extent(active_layers)
    if fit:
        view_center, view_zoom = fit
    else:
        view_center, view_zoom = _CONUS_CENTER, _CONUS_ZOOM

    # Build map children (matches qpe_builder reference pattern)
    map_props = {}
    if on_coordinate_click:
        map_props['onCoordinateClick'] = on_coordinate_click

    map_children = [
        lib.ol.View(
            options=lib.Props(projection='EPSG:3857'),
            center=view_center,
            zoom=view_zoom,
        ),
        lib.ol.layer.Tile()(lib.ol.source.OSM()),
        lib.ol.control.ScaleLine(),
    ]

    # Add overlay layers directly as map children.
    # lib.ol.layer.Group is NOT available in this Tethys installation
    # (only Image.js and Vector.js exist in ol-mods/layer/).
    map_children.extend(overlay_layers)

    the_map = lib.ol.Map(**map_props)(*map_children)

    # Map wrapper key MUST change when layers change so OL destroys
    # and recreates the map with new children (OL ignores prop patches).
    layer_ids = sorted(active_layers.keys())
    map_key = f"map-{'-'.join(layer_ids)}" if layer_ids else "map-empty"
    map_wrapper = lib.html.div(
        style=lib.Style(flex='1', height='100%'),
    )(lib.tethys.Display(the_map))
    map_wrapper["key"] = map_key

    # Status overlays (inside stable container)
    overlay_items = []

    if error_msg:
        err_el = lib.html.div(
            style=lib.Style(
                position='absolute', top='14px', left='50%',
                transform='translateX(-50%)',
                background='rgba(255, 245, 245, 0.95)',
                color='#c62828',
                padding='8px 20px', borderRadius='8px',
                fontSize='12px', zIndex='1000',
                border='1px solid #ef9a9a',
                fontWeight='600',
                boxShadow='0 2px 8px rgba(0,0,0,0.1)',
            ),
        )(f'Load error: {error_msg}')
        err_el["key"] = "overlay-error"
        overlay_items.append(err_el)

    if is_running:
        loading_el = lib.html.div(
            style=lib.Style(
                position='absolute', top='50%', left='50%',
                transform='translate(-50%, -50%)',
                background='rgba(21, 101, 192, 0.9)',
                color='#fff',
                padding='16px 32px', borderRadius='12px',
                fontSize='14px', zIndex='1001',
                fontWeight='700',
                letterSpacing='0.03em',
                boxShadow='0 4px 20px rgba(0,0,0,0.3)',
                pointerEvents='auto',
            ),
        )('Loading data, please wait...')
        loading_el["key"] = "overlay-loading"
        overlay_items.append(loading_el)

    if draw_mode:
        draw_el = lib.html.div(
            style=lib.Style(
                position='absolute', top='14px', right='14px',
                background='rgba(230, 81, 0, 0.9)',
                color='#fff',
                padding='6px 14px', borderRadius='8px',
                fontSize='11px', zIndex='1000',
                fontWeight='700',
                letterSpacing='0.04em',
                pointerEvents='auto',
            ),
        )('DRAWING MODE -- Click map to add vertices')
        draw_el["key"] = "overlay-draw"
        overlay_items.append(draw_el)

    overlay_container = lib.html.div(
        style=lib.Style(
            position='absolute', top='0', left='0',
            width='100%', height='100%',
            pointerEvents='none', zIndex='1000',
        ),
    )(*overlay_items)
    overlay_container["key"] = "overlay-container"

    return lib.html.div(
        style=lib.Style(position='relative', width='100%', height='100%'),
    )(
        map_wrapper,
        overlay_container,
    )
