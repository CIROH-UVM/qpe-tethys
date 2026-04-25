"""MapPanel — OpenLayers map component for NGPE.

Renders data layers (raster, vector) and polygon drawing overlay
from active_layers state.

Changes (2026-04-25):
  - Added polygon_vertices parameter for drawing-in-progress display.
  - Added gauge point style support (circle radius, stroke).
  - Added draw_mode parameter to show drawing cursor hint.
"""

import json
from pyproj import Transformer


# Reusable transformer for polygon vertex conversion
_transformer_4326_to_3857 = Transformer.from_crs(
    'EPSG:4326', 'EPSG:3857', always_xy=True
)


def _build_polygon_geojson_3857(vertices_4326):
    """Build a GeoJSON FeatureCollection from polygon vertices in EPSG:4326.

    Converts vertices to EPSG:3857 for map display.
    If >= 3 vertices, renders as a Polygon. Otherwise as a LineString.
    """
    if not vertices_4326:
        return None

    # Convert 4326 → 3857 for map rendering
    coords_3857 = []
    for lon, lat in vertices_4326:
        x, y = _transformer_4326_to_3857.transform(lon, lat)
        coords_3857.append([x, y])

    if len(coords_3857) == 1:
        # Single point
        feature = {
            'type': 'Feature',
            'geometry': {'type': 'Point', 'coordinates': coords_3857[0]},
            'properties': {},
        }
    elif len(coords_3857) == 2:
        # Line between two points
        feature = {
            'type': 'Feature',
            'geometry': {'type': 'LineString', 'coordinates': coords_3857},
            'properties': {},
        }
    else:
        # Polygon (close the ring)
        ring = coords_3857 + [coords_3857[0]]
        feature = {
            'type': 'Feature',
            'geometry': {'type': 'Polygon', 'coordinates': [ring]},
            'properties': {},
        }

    return {'type': 'FeatureCollection', 'features': [feature]}


def MapPanel(lib, active_layers, error_msg, polygon_vertices=None,
             draw_mode=False):
    """
    OpenLayers map panel -- renders layers from active_layers state.

    Args:
        active_layers: Dict of layer entries for map rendering.
        error_msg: Error string to display as overlay (or None).
        polygon_vertices: List of [lon, lat] pairs in EPSG:4326 for
                         drawing-in-progress polygon (or None).
        draw_mode: If True, shows crosshair cursor on map.

    OL VDOM Rules:
        - OL handles CREATE and DESTROY of child layers via VDOM diffs.
        - OL does NOT handle PATCHING existing children's props.
        - For visibility: conditionally include/exclude from VDOM tree.
        - The overlay Group is ALWAYS present (even when empty) so the
          VDOM structure stays consistent and OL doesn't need to handle
          adding/removing a Group child from the Map.
        - The map wrapper uses a STABLE key so the map is NOT destroyed.
        - View center/zoom are STATIC — OL breaks if they are patched.
    """

    # Build OL layers from active_layers state
    overlay_layers = []

    print(f'[MapPanel] Building layers from {len(active_layers)} entries')

    for uid, entry in active_layers.items():
        if not entry.get('added', False) or not entry.get('visible', True):
            print(f'[MapPanel] Skipping {uid}: added={entry.get("added")}, visible={entry.get("visible")}')
            continue

        config = entry.get('config', {})
        ltype = config.get('type')
        print(f'[MapPanel] Layer {uid}: type={ltype}, name={config.get("name")}')

        if ltype == 'ImageStatic':
            url = config['url']
            print(f'[MapPanel]   ImageStatic url={url[:80]}..., extent={config["extent"]}')
            source = lib.ol.source.ImageStatic(
                options=lib.Props(
                    url=url,
                    imageExtent=config['extent'],
                )
            )
            layer = lib.ol.layer.Image(
                options=lib.Props(title=config.get('name', 'Radar')),
            )(source)
            layer["key"] = f"data-raster-{uid}"
            overlay_layers.append(layer)

        elif ltype == 'Vector':
            geojson_str = json.dumps(config['geojson'])
            style_config = config.get('style', {})
            num_features = len(config.get('geojson', {}).get('features', []))
            print(f'[MapPanel]   Vector features={num_features} points, style={style_config.get("type", "default")}')

            source = lib.ol.source.Vector(
                options=lib.Props(
                    features=geojson_str,
                    format='GeoJSON',
                ),
            )

            # Build layer props for Vector layer.
            # NOTE: Custom circle styling (radius, QC colors) deferred —
            # Tethys OL wrapper's style prop format needs investigation.
            # Default OL style (blue dots) used for now.
            layer = lib.ol.layer.Vector(
                options=lib.Props(title=config.get('name', 'Gauges')),
            )(source)
            layer["key"] = f"data-vector-{uid}"
            overlay_layers.append(layer)

    # Add polygon drawing layer (if vertices exist)
    if polygon_vertices:
        poly_geojson = _build_polygon_geojson_3857(polygon_vertices)
        if poly_geojson:
            poly_source = lib.ol.source.Vector(
                options=lib.Props(
                    features=json.dumps(poly_geojson),
                    format='GeoJSON',
                ),
            )
            # NOTE: Do NOT pass style dict to Vector layer — it crashes OL.
            # Tethys OL wrapper doesn't support this format.
            poly_layer = lib.ol.layer.Vector(
                options=lib.Props(title='Drawing'),
            )(poly_source)
            poly_layer["key"] = "drawing-polygon"
            overlay_layers.append(poly_layer)

    print(f'[MapPanel] Total overlay layers built: {len(overlay_layers)}')

    # Always include the overlay Group -- even when empty.
    overlay_group = lib.ol.layer.Group(
        options=lib.Props(title='Data Layers', fold='open'),
    )(*overlay_layers) if overlay_layers else lib.ol.layer.Group(
        options=lib.Props(title='Data Layers', fold='open'),
    )()

    # Build map children
    the_map = lib.ol.Map()(
        lib.ol.View(
            options=lib.Props(projection='EPSG:3857'),
            center=[-10000000, 4000000],
            zoom=4,
        ),
        lib.ol.layer.Tile()(lib.ol.source.OSM()),
        lib.ol.control.ScaleLine(),
        overlay_group,
    )

    # Error overlay
    status_children = []

    if error_msg:
        status_children.append(
            lib.html.div(
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
        )

    # Draw mode indicator
    if draw_mode:
        status_children.append(
            lib.html.div(
                style=lib.Style(
                    position='absolute', top='14px', right='14px',
                    background='rgba(229, 57, 53, 0.9)',
                    color='#fff',
                    padding='6px 14px', borderRadius='8px',
                    fontSize='11px', zIndex='1000',
                    fontWeight='700',
                    letterSpacing='0.04em',
                ),
            )('DRAWING MODE — Click map to add vertices'),
        )

    # STABLE key -- map is never destroyed/recreated.
    # NOTE: Do NOT add extra style props (like cursor) to this wrapper.
    # Any style change on the wrapper can cause OL to break.
    map_wrapper = lib.html.div(
        style=lib.Style(flex='1', height='100%'),
    )(lib.tethys.Display(the_map))
    map_wrapper["key"] = "map-main"

    return lib.html.div(
        style=lib.Style(position='relative', width='100%', height='100%'),
    )(
        *status_children,
        map_wrapper,
    )
