import json


def MapPanel(lib, active_layers, error_msg):
    """
    OpenLayers map panel -- renders layers from active_layers state.

    The map container uses absolute positioning to guarantee it fills
    the parent div regardless of flex nesting. OL requires an explicit
    pixel size on its container to initialize.
    """

    # Build OL layers from active_layers state
    overlay_layers = []

    for uid, entry in active_layers.items():
        if not entry.get('added', False) or not entry.get('visible', True):
            continue

        config = entry.get('config', {})
        ltype = config.get('type')

        if ltype == 'ImageStatic':
            source = lib.ol.source.ImageStatic(
                options=lib.Props(
                    url=config['url'],
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
            source = lib.ol.source.Vector(
                options=lib.Props(
                    features=geojson_str,
                    format='GeoJSON',
                ),
            )
            layer = lib.ol.layer.Vector(
                options=lib.Props(title=config.get('name', 'Gauges')),
            )(source)
            layer["key"] = f"data-vector-{uid}"
            overlay_layers.append(layer)

    # Always include the overlay Group -- even when empty.
    overlay_group = lib.ol.layer.Group(
        options=lib.Props(title='Data Layers', fold='open'),
    )(*overlay_layers) if overlay_layers else lib.ol.layer.Group(
        options=lib.Props(title='Data Layers', fold='open'),
    )()

    # Build map
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

    # Use absolute positioning so OL gets explicit pixel dimensions.
    # height:100% in nested flex can resolve to 0px; absolute avoids that.
    map_display = lib.html.div(
        style=lib.Style(
            position='absolute',
            top='0', left='0', right='0', bottom='0',
        ),
    )(lib.tethys.Display(the_map))
    map_display["key"] = "map-main"

    return lib.html.div(
        style=lib.Style(
            position='relative',
            width='100%', height='100%',
            minHeight='0',
        ),
    )(
        map_display,
        *status_children,
    )
