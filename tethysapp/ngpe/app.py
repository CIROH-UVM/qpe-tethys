"""NGPE Platform — Main Tethys Component App.

Provides the primary map interface for the Next-Generation QPE Platform.
Layout: left sidebar (data layer cards), center (OpenLayers map with tool
buttons), right panel (ToolPropertiesPanel for tool configuration).

State architecture:
  - tool_ref (use_ref): mutable Tool instance, no re-render on change.
  - tool_props / tool_values (use_state): drive the ToolPropertiesPanel UI.
  - active_layers (use_state): dict of layer entries for map + sidebar cards.
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

from pyproj import Transformer
from tethys_sdk.components import ComponentBase

# Coordinate transformer: EPSG:3857 (Web Mercator) → EPSG:4326 (lat/lon).
# Map click coordinates arrive in 3857; Tool.extent uses 4326.
_transformer_3857_to_4326 = Transformer.from_crs(
    'EPSG:3857', 'EPSG:4326', always_xy=True
)

from .components.layer_card import LayerCard
from .components.map_panel import MapPanel
from .components.ToolPropertiesPanel import ToolPropertiesPanel
from .tools.LoadDatasetTool import LoadDatasetTool
from .tools.ScaleBiasTool import ScaleBiasTool

# Registry of available tools — rendered as buttons on the map (lower-right).
TOOL_REGISTRY = [
    {'id': 'load_dataset', 'name': 'Load Data', 'icon': '\u2B07',
     'class': LoadDatasetTool},
    {'id': 'scale_bias', 'name': 'Scale/Bias', 'icon': '\u2702',
     'class': ScaleBiasTool},
]


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
    default_layout = "NavHeader"
    nav_links = "auto"


# ── Page ─────────────────────────────────────────────────────────────

@App.page
def home(lib):
    """Main NGPE map page.

    Renders the full application layout: left sidebar with layer cards,
    center OpenLayers map with tool buttons, and right-side tool
    properties panel.
    """

    # Pre-register OL components for JS module generation.
    # Tethys scans this function's source for lib.X.Y( patterns but strips
    # docstrings/comments first. Sub-modules (map_panel.py) are NOT scanned.
    # This block never executes but the source scanner sees the patterns.
    if False:
        lib.ol.Map()
        lib.ol.View()
        lib.ol.layer.Tile()
        lib.ol.source.OSM()
        lib.ol.control.ScaleLine()
        lib.tethys.Display()
        lib.ol.source.Image()
        lib.olmod.layer.Image()
        lib.ol.source.Vector()
        lib.ol.layer.Vector()

    # ====== STATE ======
    # Separate use_state hooks — each hook independently manages its own
    # value, avoiding stale-state issues with single-object updaters.
    active_layers, set_active_layers = lib.hooks.use_state({})
    error_msg, set_error_msg = lib.hooks.use_state(None)
    layers_open, set_layers_open = lib.hooks.use_state(True)

    # Map view center/zoom are not in state — OL does not support
    # patching View props on a live map. Users zoom/pan manually.

    # Tool state: use_ref for mutable Tool instance (no re-render),
    # use_state for property definitions and values (drives panel UI).
    tool_ref = lib.hooks.use_ref(None)
    tool_props, set_tool_props = lib.hooks.use_state(None)
    tool_values, set_tool_values = lib.hooks.use_state({})

    # Mutable ref tracking latest active_layers — avoids stale closures
    # in event handlers. Updated every render cycle.
    layers_ref = lib.hooks.use_ref({})
    layers_ref.current = active_layers

    # Stores DataLayer objects so downstream tools can access raw data.
    data_layers_ref = lib.hooks.use_ref({})

    # Status message shown after tool execution completes.
    status_msg, set_status_msg = lib.hooks.use_state(None)

    # Loading flag — triggers use_effect to execute tool after render.
    is_running, set_is_running = lib.hooks.use_state(False)

    # Pending tool work (set by button click, consumed by use_effect).
    pending_tool_ref = lib.hooks.use_ref(None)

    # Polygon drawing state — used by tools that support spatial extent.
    draw_mode, set_draw_mode = lib.hooks.use_state(False)
    polygon_vertices, set_polygon_vertices = lib.hooks.use_state([])
    vertices_ref = lib.hooks.use_ref([])
    vertices_ref.current = polygon_vertices

    # ====== HANDLERS ======

    def make_tool_select_handler(tool_id):
        """Create a click handler for a tool button on the map."""
        def handler(event):
            tool_entry = next(
                (t for t in TOOL_REGISTRY if t['id'] == tool_id), None
            )
            if tool_entry is None:
                set_error_msg(f'Unknown tool: {tool_id}')
                return

            tool = tool_entry['class']()
            tool_ref.current = tool

            props_list = tool.get_properties()

            # Dynamically populate layer_id options from active layers
            for prop in props_list:
                if prop['name'] == 'layer_id' and not prop.get('options'):
                    current_layers = layers_ref.current
                    prop['options'] = [
                        f"{v['config'].get('name', k)} ({v['config'].get('type', '?')})"
                        for k, v in current_layers.items()
                        if v.get('added')
                    ]

            set_tool_props(props_list)

            # Initialize values dict — empty strings for UI props,
            # None for polygon (filled by map drawing).
            initial_values = {
                p['name']: (None if p['type'] == 'polygon' else '')
                for p in props_list
            }
            set_tool_values(initial_values)
            set_error_msg(None)
            set_status_msg(None)
            set_is_running(False)

            # Clear polygon when switching tools
            set_draw_mode(False)
            vertices_ref.current = []
            set_polygon_vertices([])
            if tool_ref.current is not None:
                tool_ref.current.extent = None
        return handler

    def handle_property_change(prop_name, new_value):
        """Callback from ToolPropertiesPanel when user changes a value."""
        set_tool_values(lambda prev: {**prev, prop_name: new_value})

    # ---- Polygon drawing handlers ----

    def handle_start_drawing(event):
        """Activate polygon drawing mode and clear existing vertices."""
        vertices_ref.current = []
        set_polygon_vertices([])
        set_draw_mode(True)
        set_error_msg(None)
        set_status_msg(None)

    def handle_finish_polygon(event):
        """Close the polygon and store GeoJSON extent on the active tool."""
        set_draw_mode(False)
        verts = vertices_ref.current
        if len(verts) >= 3:
            ring = [[lon, lat] for lon, lat in verts]
            ring.append(ring[0])  # close
            geojson_geom = {
                'type': 'Polygon',
                'coordinates': [ring],
            }
            # Store on the active tool's extent property
            if tool_ref.current is not None:
                tool_ref.current.extent = geojson_geom
            logger.info('Extent polygon set: %d vertices', len(verts))

    def handle_clear_polygon(event):
        """Clear the drawn polygon and reset the tool's extent."""
        set_draw_mode(False)
        vertices_ref.current = []
        set_polygon_vertices([])
        if tool_ref.current is not None:
            tool_ref.current.extent = None

    def handle_coordinate_click(event):
        """Append a vertex to the polygon on map click (drawing mode only)."""
        if not draw_mode:
            return
        coord = event.get('coordinate', None)
        if not coord or len(coord) < 2:
            return
        lon, lat = _transformer_3857_to_4326.transform(coord[0], coord[1])
        logger.debug('Polygon vertex: [%.4f, %.4f]', lon, lat)
        new_verts = vertices_ref.current + [[lon, lat]]
        vertices_ref.current = new_verts
        set_polygon_vertices(new_verts)

    def handle_run_tool(event):
        """Prepare the tool for execution and trigger the loading state.

        Sets is_running=True so the UI shows a loading indicator. The
        use_effect hook then picks up the pending tool and executes it.
        """
        if tool_ref.current is None:
            set_error_msg('No tool selected. Click a tool button on the map.')
            return

        if is_running:
            return  # Prevent double-click

        # Create a fresh Tool instance and configure it
        tool = tool_ref.current.__class__()
        tool.inputs = list(data_layers_ref.current.values())

        # Parse datetime string if present (HTML input returns ISO string).
        props_for_tool = dict(tool_values)
        dt_str = props_for_tool.get('ref_datetime', '')
        if dt_str:
            try:
                props_for_tool['ref_datetime'] = datetime.fromisoformat(dt_str)
            except (ValueError, TypeError):
                props_for_tool['ref_datetime'] = datetime.now(timezone.utc)
        else:
            props_for_tool['ref_datetime'] = datetime.now(timezone.utc)

        # Auto-finish polygon if vertices exist but user didn't click Finish.
        verts = vertices_ref.current
        extent_geojson = None
        if len(verts) >= 3:
            ring = [[lon, lat] for lon, lat in verts]
            ring.append(ring[0])
            extent_geojson = {'type': 'Polygon', 'coordinates': [ring]}
            tool.extent = extent_geojson
            set_draw_mode(False)
        elif tool_ref.current is not None and tool_ref.current.extent is not None:
            extent_geojson = tool_ref.current.extent
            tool.extent = extent_geojson

        # Pass extent GeoJSON as a property for tools that use it
        if extent_geojson and 'extent' in props_for_tool:
            props_for_tool['extent'] = extent_geojson

        tool.properties = props_for_tool

        # Queue tool for execution by the use_effect hook
        pending_tool_ref.current = tool

        # Trigger loading UI — use_effect will execute the tool after render
        set_error_msg(None)
        set_status_msg(None)
        set_is_running(True)

    # Effect hook: executes the queued tool after the loading UI renders.
    @lib.hooks.use_effect(dependencies=[is_running])
    def _run_pending_tool():
        if not is_running:
            return
        tool = pending_tool_ref.current
        if tool is None:
            set_is_running(False)
            return
        pending_tool_ref.current = None

        try:
            logger.info('Running tool...')
            layer = tool.run()
            layer_config = layer.to_map_layer()
            layer_entry = {
                str(layer.id): {
                    'added': True,
                    'visible': True,
                    'opacity': 0.75,
                    'config': layer_config,
                    'metadata': layer.to_catalog_entry(),
                },
            }

            new_layers = {**layers_ref.current, **layer_entry}
            layers_ref.current = new_layers
            set_active_layers(new_layers)

            data_layers_ref.current[str(layer.id)] = layer

            meta = layer.to_catalog_entry()
            lname = meta.get('name', 'Layer')
            set_status_msg(f'Data loaded: {lname}')
            set_error_msg(None)
            set_is_running(False)
            logger.info('Tool complete: %s', lname)

        except Exception as e:
            logger.exception('Tool execution failed')
            set_error_msg(str(e))
            set_status_msg(None)
            set_is_running(False)

    # ---- Layer visibility/opacity/remove handlers ----
    # Use layers_ref for reads and set_active_layers for writes
    # to avoid stale closure issues.

    def make_toggle_handler(key):
        def handler(event):
            current = layers_ref.current
            new_layers = {
                k: ({**v, 'visible': not v['visible']} if k == key else v)
                for k, v in current.items()
            }
            layers_ref.current = new_layers
            set_active_layers(new_layers)
        return handler

    def make_opacity_handler(key):
        def handler(event):
            new_val = int(event['target']['value']) / 100
            current = layers_ref.current
            new_layers = {
                k: ({**v, 'opacity': new_val} if k == key else v)
                for k, v in current.items()
            }
            layers_ref.current = new_layers
            set_active_layers(new_layers)
        return handler

    def make_remove_handler(key):
        def handler(event):
            current = layers_ref.current
            new_layers = {k: v for k, v in current.items() if k != key}
            layers_ref.current = new_layers
            set_active_layers(new_layers)
        return handler

    def toggle_layers(event):
        set_layers_open(lambda prev: not prev)

    def handle_remove_all(event):
        """Remove all layers from the map."""
        layers_ref.current = {}
        set_active_layers({})

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
    # NavHeader provides the Tethys header bar (56px). Our content fills
    # the remaining viewport height below it.
    return lib.html.div(
        style=lib.Style(
            display='flex',
            height='calc(100vh - 56px)', width='100%',
            background='#f5f7fa',
            fontFamily="'Segoe UI', system-ui, -apple-system, sans-serif",
            overflow='hidden',
        ),
    )(
            # ── Left Sidebar — Data Layers ──
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
                # Data Layers header (collapsible) with count
                lib.html.div(
                    style=lib.Style(
                        display='flex', alignItems='center', gap='8px',
                        padding='8px 0', cursor='pointer', userSelect='none',
                    ),
                    onClick=toggle_layers,
                )(
                    lib.html.span(
                        style=lib.Style(
                            fontSize='9px', color='#667085', width='12px',
                        ),
                    )('\u25BC' if layers_open else '\u25B6'),
                    lib.html.span(
                        style=lib.Style(
                            fontSize='11px', fontWeight='700',
                            letterSpacing='0.06em', color='#667085',
                            textTransform='uppercase', flex='1',
                        ),
                    )(f'Data Layers ({len(layer_cards)})' if layer_cards
                      else 'Data Layers'),
                ),

                # "Clear All" button — outside the header to avoid
                # click propagation conflicts with toggle.
                *(
                    [lib.html.div(
                        style=lib.Style(
                            display='flex', justifyContent='flex-end',
                            padding='0 0 4px 0',
                        ),
                    )(
                        lib.html.button(
                            style=lib.Style(
                                background='none', border='1px solid #ef9a9a',
                                cursor='pointer', fontSize='10px',
                                color='#c62828', fontWeight='600',
                                padding='2px 8px', borderRadius='4px',
                            ),
                            onClick=handle_remove_all,
                            title='Remove all layers',
                        )('Clear All'),
                    )]
                    if layer_cards and layers_open else []
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
                            )(
                                'Click a tool button on the map, '
                                'configure it on the right panel, '
                                'then click "Run Tool".'
                            ),
                        ]
                    ) if layers_open else []
                ),
            ),

            # ── Center: Map + Tool Buttons ──
            lib.html.div(
                style=lib.Style(flex='1', position='relative'),
            )(
                MapPanel(
                    lib,
                    active_layers=active_layers,
                    error_msg=error_msg,
                    polygon_vertices=polygon_vertices,
                    draw_mode=draw_mode,
                    on_coordinate_click=handle_coordinate_click,
                    is_running=is_running,
                ),
                # Tool buttons + Draw Extent — lower-right corner of map
                lib.html.div(
                    style=lib.Style(
                        position='absolute', bottom='40px', right='14px',
                        display='flex', flexDirection='column', gap='6px',
                        zIndex='1000',
                    ),
                )(
                    *[
                        lib.html.button(
                            style=lib.Style(
                                background='#1565C0', color='#fff',
                                border='none', borderRadius='8px',
                                padding='8px 14px', fontSize='12px',
                                fontWeight='700', cursor='pointer',
                                boxShadow='0 2px 8px rgba(0,0,0,0.2)',
                                letterSpacing='0.02em',
                                whiteSpace='nowrap',
                            ),
                            onClick=make_tool_select_handler(t['id']),
                            title=f'Open {t["name"]} tool',
                        )(f'{t["icon"]} {t["name"]}')
                        for t in TOOL_REGISTRY
                    ],
                    # Draw Extent button — only shown for tools with a
                    # 'polygon' property (e.g., ScaleBiasTool).
                    *(
                        (
                            # Drawing active — show Finish + Cancel buttons
                            [
                                lib.html.button(
                                    style=lib.Style(
                                        background='#2e7d32' if len(polygon_vertices) >= 3 else '#78909c',
                                        color='#fff',
                                        border='none', borderRadius='8px',
                                        padding='8px 14px', fontSize='12px',
                                        fontWeight='700', cursor='pointer',
                                        boxShadow='0 2px 8px rgba(0,0,0,0.2)',
                                        whiteSpace='nowrap',
                                    ),
                                    onClick=handle_finish_polygon,
                                    title='Finish drawing polygon',
                                )(f'Finish ({len(polygon_vertices)} pts)'),
                                lib.html.button(
                                    style=lib.Style(
                                        background='#c62828', color='#fff',
                                        border='none', borderRadius='8px',
                                        padding='8px 14px', fontSize='12px',
                                        fontWeight='700', cursor='pointer',
                                        boxShadow='0 2px 8px rgba(0,0,0,0.2)',
                                        whiteSpace='nowrap',
                                    ),
                                    onClick=handle_clear_polygon,
                                    title='Cancel drawing',
                                )('Cancel'),
                            ] if draw_mode else
                            # Not drawing: show Draw Extent button
                            [
                                lib.html.button(
                                    style=lib.Style(
                                        background='#e65100', color='#fff',
                                        border='none', borderRadius='8px',
                                        padding='8px 14px', fontSize='12px',
                                        fontWeight='700', cursor='pointer',
                                        boxShadow='0 2px 8px rgba(0,0,0,0.2)',
                                        letterSpacing='0.02em',
                                        whiteSpace='nowrap',
                                    ),
                                    onClick=handle_start_drawing,
                                    title='Draw extent polygon on map',
                                )(
                                    'Draw Extent'
                                    + (f' ({len(polygon_vertices)} pts)'
                                       if polygon_vertices else '')
                                ),
                            ]
                        )
                        if tool_props and any(p.get('type') == 'polygon' for p in tool_props)
                        else []
                    ),
                ),
            ),

            # ── Right: Tool Properties Panel ──
            ToolPropertiesPanel(
                lib,
                tool_props=tool_props,
                tool_values=tool_values,
                on_property_change=handle_property_change,
                on_run_tool=handle_run_tool,
                status_msg=status_msg,
                error_msg=error_msg,
                is_running=is_running,
            ),
    )
