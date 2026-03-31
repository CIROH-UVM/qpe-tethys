import json


def MapPanel(lib, active_layers, error_msg):
    """
    OpenLayers map panel -- renders layers from active_layers state.

    OL VDOM Rules:
        - OL handles CREATE and DESTROY of child layers via VDOM diffs.
        - OL does NOT handle PATCHING existing children's props.
        - For visibility: conditionally include/exclude from VDOM tree.
        - The overlay Group is ALWAYS present (even when empty) so the
          VDOM structure stays consistent and OL doesn't need to handle
          adding/removing a Group child from the Map.
        - The map wrapper uses a STABLE key so the map is NOT destroyed.
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
            print(f'[MapPanel]   Vector features={len(config.get("geojson", {}).get("features", []))} points')
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

    print(f'[MapPanel] Total overlay layers built: {len(overlay_layers)}')

    # Always include the overlay Group -- even when empty.
    # This keeps the VDOM structure consistent so the Map never needs
    # to handle adding/removing a Group child (only the Group's children change).
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

    # STABLE key -- map is never destroyed/recreated.
    # The overlay Group is always present; only its children change.
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
