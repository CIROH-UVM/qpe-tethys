import traceback
from datetime import datetime, timezone

from tethys_sdk.components import ComponentBase

from .components.layer_card import LayerCard
from .components.map_panel import MapPanel
from .tools.tool import LoadDatasetTool


def FullPageLayout(lib, app, user, nav_links=None, content=None):
    """Custom layout that renders content full-page with no Tethys header.

    Replaces NavHeader layout to avoid the double-header problem.
    The NavHeader layout adds a 56px Tethys header bar + paddingTop.
    This layout skips that entirely — our component has its own header.
    """
    content = content or []
    if not isinstance(content, list):
        content = [content]
    return lib.html.div(style=lib.Style(height="100vh", width="100%"))(
        *content
    )


class App(ComponentBase):
    """
    Tethys app class for NGPE Platform.
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
    default_layout = FullPageLayout
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

            print(f'[NGPE] Loaded {len(new_layers)} layers for {region}')
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

    # ====== RENDER ======
    return lib.html.div(
        style=lib.Style(
            display='flex', flexDirection='column',
            height='100%', width='100%',
            background='#f5f7fa',
            fontFamily="'Segoe UI', system-ui, -apple-system, sans-serif",
        ),
    )(
        # ── HEADER ──
        lib.html.div(
            style=lib.Style(
                display='flex', alignItems='center', gap='14px',
                padding='0 20px', height='52px',
                background='#1565C0', flexShrink='0',
                boxShadow='0 1px 4px rgba(0,0,0,0.15)',
            ),
        )(
            lib.html.span(
                style=lib.Style(
                    fontWeight='700', fontSize='20px', color='#fff',
                    letterSpacing='0.02em',
                ),
            )('NGPE Platform'),
            lib.html.div(style=lib.Style(flex='1'))(),
            lib.html.a(
                href='/apps/',
                style=lib.Style(
                    fontSize='12px', color='rgba(255,255,255,0.8)',
                    textDecoration='none', fontWeight='600',
                    padding='4px 12px',
                    border='1px solid rgba(255,255,255,0.3)',
                    borderRadius='6px',
                ),
            )('Exit'),
        ),

        # ── MAIN: SIDEBAR + MAP ──
        lib.html.div(
            style=lib.Style(display='flex', flex='1', overflow='hidden'),
        )(
            # Sidebar
            lib.html.div(
                style=lib.Style(
                    width='280px', minWidth='280px', flexShrink='0',
                    background='#f5f7fa',
                    borderRight='1px solid #e0e4ea',
                    overflowY='auto',
                    padding='14px 16px',
                    boxSizing='border-box',
                ),
            )(
                # Controls header (collapsible)
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

                # Controls content (shown when open)
                *(
                    [
                        # Region dropdown
                        lib.html.div(
                            style=lib.Style(
                                display='flex', flexDirection='column', gap='4px',
                                marginBottom='12px', paddingLeft='20px',
                            ),
                        )(
                            lib.html.label(
                                style=lib.Style(
                                    fontSize='11px', color='#667085', fontWeight='600',
                                ),
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
                                *[
                                    lib.html.option(value=r['id'])(r['name'])
                                    for r in RFC_REGIONS
                                ],
                            ),
                        ),

                        # Datetime picker
                        lib.html.div(
                            style=lib.Style(
                                display='flex', flexDirection='column', gap='4px',
                                marginBottom='12px', paddingLeft='20px',
                            ),
                        )(
                            lib.html.label(
                                style=lib.Style(
                                    fontSize='11px', color='#667085', fontWeight='600',
                                ),
                            )('Reference Time (UTC)'),
                            lib.html.input(
                                type='datetime-local',
                                value=selected_datetime,
                                onChange=handle_datetime_change,
                                style=lib.Style(
                                    width='100%', padding='7px 10px',
                                    fontSize='13px', border='1.5px solid #d0d5dd',
                                    borderRadius='8px', backgroundColor='#fff',
                                    color='#333', outline='none',
                                    boxSizing='border-box',
                                ),
                            ),
                        ),

                        # Load Data button
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

                # Data Layers header (collapsible)
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

                # Data Layers content (shown when open)
                *(
                    (
                        layer_cards if layer_cards else [
                            lib.html.div(
                                style=lib.Style(
                                    fontSize='12px', color='#98a2b3',
                                    padding='12px 0', textAlign='center',
                                    lineHeight='1.6',
                                ),
                            )(
                                'Select a region and time above, '
                                'then click "Load Data".'
                            ),
                        ]
                    ) if layers_open else []
                ),
            ),

            # Map
            lib.html.div(
                style=lib.Style(flex='1', position='relative'),
            )(
                MapPanel(
                    lib,
                    active_layers=active_layers,
                    error_msg=error_msg,
                ),
            ),
        ),
    )
