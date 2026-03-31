import traceback
from datetime import datetime, timezone

from tethys_sdk.components import ComponentBase

import json
from .components.layer_card import LayerCard
from .tools.tool import LoadDatasetTool


class App(ComponentBase):
    """
    Tethys app class for NGPE Platform.
    Uses NavHeader layout (hidden via CSS) to match the reference qpe_builder
    pattern exactly. Custom FullPageLayout caused OL map rendering issues.
    """

    name = "NGPE Platform"
    description = "Next-Generation QPE Platform for NOAA River Forecast Centers"
    package = "ngpe"  # WARNING: Do not change this value
    index = "home"
    icon = f"{package}/images/icon.png"
    root_url = "ngpe"
    color = "#1565C0"
    tags = "Meteorology", "Precipitation Estimate", "Forecasts"
    enable_feedback = False
    feedback_emails = []
    exit_url = "/apps/"
    default_layout = "NavHeader"
    nav_links = "auto"


# RFC Regions for the region selector
RFC_REGIONS = [
    {'id': 'arkansas-red', 'name': 'Arkansas-Red Basin'},
    {'id': 'colorado', 'name': 'Colorado Basin'},
    {'id': 'california-nv', 'name': 'California-Nevada'},
    {'id': 'northeast', 'name': 'Northeast'},
    {'id': 'missouri', 'name': 'Missouri Basin'},
    {'id': 'north-central', 'name': 'North Central'},
    {'id': 'northwest', 'name': 'Northwest'},
    {'id': 'ohio', 'name': 'Ohio'},
    {'id': 'southeast', 'name': 'Southeast'},
    {'id': 'west-gulf', 'name': 'West Gulf'},
    {'id': 'mid-atlantic', 'name': 'Mid-Atlantic'},
    {'id': 'lower-miss', 'name': 'Lower Mississippi'},
]


# ── Page ─────────────────────────────────────────────────────────────

@App.page
def home(lib):
    """
    Main NGPE map page — Pat's spec Sections 6.1–6.4.

    UI: region dropdown, datetime picker, Load Data button,
    layer cards (name + eye + remove + opacity), OpenLayers map.
    """

    # ====== STATE ======
    selected_region, set_selected_region = lib.hooks.use_state('')
    selected_datetime, set_selected_datetime = lib.hooks.use_state('')
    active_layers, set_active_layers = lib.hooks.use_state({})
    error_msg, set_error_msg = lib.hooks.use_state(None)
    controls_open, set_controls_open = lib.hooks.use_state(True)
    layers_open, set_layers_open = lib.hooks.use_state(True)

    print(f'[NGPE] Render: region={selected_region}, layers={len(active_layers)}')

    # ====== HANDLERS ======

    def handle_region_change(event):
        set_selected_region(event['target']['value'])

    def handle_datetime_change(event):
        set_selected_datetime(event['target']['value'])

    def handle_load_data(event):
        region = selected_region
        dt_str = selected_datetime
        print(f'[NGPE] Load Data: region={region}, dt={dt_str}')

        if not region:
            set_error_msg('Please select an RFC Region first.')
            return

        try:
            ref_dt = datetime.now(timezone.utc)
            if dt_str:
                try:
                    ref_dt = datetime.fromisoformat(dt_str)
                except (ValueError, TypeError):
                    ref_dt = datetime.now(timezone.utc)

            raster_tool = LoadDatasetTool(prop_defaults={
                'dataset_id': 'mrms_qpe_01h',
                'output_name': 'MRMS Radar QPE',
                'ref_datetime': ref_dt,
                'region': region,
            })
            raster_layer = raster_tool.run()
            raster_config = raster_layer.to_map_layer()

            point_tool = LoadDatasetTool(prop_defaults={
                'dataset_id': 'madis_gauges',
                'output_name': 'MADIS Gauges',
                'ref_datetime': ref_dt,
                'region': region,
            })
            point_layer = point_tool.run()

            new_layers = {
                str(raster_layer.id): {
                    'added': True,
                    'visible': True,
                    'opacity': 0.75,
                    'config': raster_config,
                    'metadata': raster_layer.to_catalog_entry(),
                },
                str(point_layer.id): {
                    'added': True,
                    'visible': True,
                    'opacity': 1.0,
                    'config': point_layer.to_map_layer(),
                    'metadata': point_layer.to_catalog_entry(),
                },
            }

            # Log sizes to debug VDOM payload
            raster_url_len = len(raster_config.get('url', ''))
            print(f'[NGPE] Loaded {len(new_layers)} layers for {region} '
                  f'(raster base64: {raster_url_len} chars)')
            set_active_layers(new_layers)
            set_error_msg(None)

        except Exception as e:
            print(f'[NGPE] Load error: {e}')
            traceback.print_exc()
            set_error_msg(str(e))

    # ---- Layer handlers (factory pattern like reference) ----

    def make_toggle_handler(key):
        def handler(event):
            set_active_layers(
                lambda prev: {
                    k: ({**v, 'visible': not v['visible']} if k == key else v)
                    for k, v in prev.items()
                }
            )
        return handler

    def make_opacity_handler(key):
        def handler(event):
            new_val = int(event['target']['value']) / 100
            set_active_layers(
                lambda prev: {
                    k: ({**v, 'opacity': new_val} if k == key else v)
                    for k, v in prev.items()
                }
            )
        return handler

    def make_remove_handler(key):
        def handler(event):
            set_active_layers(
                lambda prev: {k: v for k, v in prev.items() if k != key}
            )
        return handler

    def toggle_controls(event):
        set_controls_open(lambda prev: not prev)

    def toggle_layers(event):
        set_layers_open(lambda prev: not prev)

    # ====== BUILD LAYER CARDS ======
    layer_cards = []
    for uid, entry in active_layers.items():
        if entry.get('added', False):
            layer_cards.append(
                LayerCard(
                    lib, layer_id=uid, entry=entry,
                    on_toggle_visibility=make_toggle_handler(uid),
                    on_opacity_change=make_opacity_handler(uid),
                    on_remove=make_remove_handler(uid),
                )
            )

    # ====== BUILD OL MAP (inline, matching reference qpe_builder pattern) ======
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

    # Overlay Group — ALWAYS present, even when empty.
    # This keeps the VDOM structure consistent (always 4 map children).
    # If the Group is only added when layers exist, OL breaks when the
    # Map goes from 3→4 children (structural VDOM change it can't handle).
    overlay_group = lib.ol.layer.Group(
        options=lib.Props(title='Data Layers', fold='open'),
    )(*overlay_layers) if overlay_layers else lib.ol.layer.Group(
        options=lib.Props(title='Data Layers', fold='open'),
    )()

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

    # Map wrapper — direct child of the flex container, same as reference app
    map_wrapper = lib.html.div(
        style=lib.Style(flex='1', height='100%'),
    )(lib.tethys.Display(the_map))
    map_wrapper["key"] = "map-main"

    # ====== SIDEBAR ======
    sidebar = lib.html.div(
        style=lib.Style(
            width='280px', minWidth='280px', flexShrink='0',
            background='#f5f7fa',
            borderRight='1px solid #e0e4ea',
            overflowY='auto',
            padding='14px 16px',
            boxSizing='border-box',
        ),
    )(
        # Controls header
        lib.html.div(
            style=lib.Style(
                display='flex', alignItems='center', gap='8px',
                padding='8px 0', cursor='pointer', userSelect='none',
            ),
            onClick=toggle_controls,
        )(
            lib.html.span(
                style=lib.Style(fontSize='9px', color='#667085', width='12px'),
            )('\u25BC' if controls_open else '\u25B6'),
            lib.html.span(
                style=lib.Style(
                    fontSize='11px', fontWeight='700',
                    letterSpacing='0.06em', color='#667085',
                    textTransform='uppercase', flex='1',
                ),
            )('Controls'),
        ),

        # Controls content
        *(
            [
                lib.html.div(
                    style=lib.Style(
                        display='flex', flexDirection='column', gap='4px',
                        marginBottom='12px', paddingLeft='20px',
                    ),
                )(
                    lib.html.label(
                        style=lib.Style(fontSize='11px', color='#667085', fontWeight='600'),
                    )('RFC Region'),
                    lib.html.select(
                        style=lib.Style(
                            width='100%', padding='7px 10px',
                            fontSize='13px', fontWeight='600',
                            border='1.5px solid #d0d5dd', borderRadius='8px',
                            backgroundColor='#fff', color='#333',
                            cursor='pointer', outline='none',
                        ),
                        value=selected_region,
                        onChange=handle_region_change,
                    )(
                        lib.html.option(value='')('Select Region...'),
                        *[lib.html.option(value=r['id'])(r['name']) for r in RFC_REGIONS],
                    ),
                ),

                lib.html.div(
                    style=lib.Style(
                        display='flex', flexDirection='column', gap='4px',
                        marginBottom='12px', paddingLeft='20px',
                    ),
                )(
                    lib.html.label(
                        style=lib.Style(fontSize='11px', color='#667085', fontWeight='600'),
                    )('Reference Time (UTC)'),
                    lib.html.input(
                        type='datetime-local',
                        value=selected_datetime,
                        onChange=handle_datetime_change,
                        style=lib.Style(
                            width='100%', padding='7px 10px',
                            fontSize='13px', border='1.5px solid #d0d5dd',
                            borderRadius='8px', backgroundColor='#fff',
                            color='#333', outline='none', boxSizing='border-box',
                        ),
                    ),
                ),

                lib.html.div(
                    style=lib.Style(paddingLeft='20px', marginBottom='12px'),
                )(
                    lib.html.button(
                        style=lib.Style(
                            background='#1565C0' if selected_region else '#b0bec5',
                            color='#fff', border='none', borderRadius='8px',
                            padding='9px 0', fontSize='13px', fontWeight='700',
                            cursor='pointer' if selected_region else 'not-allowed',
                            letterSpacing='0.02em', width='100%',
                        ),
                        onClick=handle_load_data,
                    )('Load Data'),
                ),
            ] if controls_open else []
        ),

        # Divider
        lib.html.div(
            style=lib.Style(height='1px', background='#e0e4ea', margin='6px 0'),
        )(),

        # Data Layers header
        lib.html.div(
            style=lib.Style(
                display='flex', alignItems='center', gap='8px',
                padding='8px 0', cursor='pointer', userSelect='none',
            ),
            onClick=toggle_layers,
        )(
            lib.html.span(
                style=lib.Style(fontSize='9px', color='#667085', width='12px'),
            )('\u25BC' if layers_open else '\u25B6'),
            lib.html.span(
                style=lib.Style(
                    fontSize='11px', fontWeight='700',
                    letterSpacing='0.06em', color='#667085',
                    textTransform='uppercase', flex='1',
                ),
            )('Data Layers'),
        ),

        # Data Layers content
        *(
            (
                layer_cards if layer_cards else [
                    lib.html.div(
                        style=lib.Style(
                            fontSize='12px', color='#98a2b3',
                            padding='12px 0', textAlign='center',
                            lineHeight='1.6',
                        ),
                    )('Select a region and time above, then click "Load Data".'),
                ]
            ) if layers_open else []
        ),
    )

    # ====== RENDER — exact reference pattern: flex container with sidebar + map_wrapper ======
    return lib.html.div(
        style=lib.Style(
            display='flex', height='100%', width='100%',
            background='#f5f7fa',
            fontFamily="'Segoe UI', system-ui, -apple-system, sans-serif",
        ),
    )(
        sidebar,
        map_wrapper,
    )
