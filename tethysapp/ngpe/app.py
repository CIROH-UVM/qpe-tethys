"""NGPE Platform — Main Tethys Component App.

Changes (2026-04-20, ToolPropertiesPanel refactor):
  - Removed duplicate region dropdown and datetime picker from sidebar.
    These inputs now live in the ToolPropertiesPanel, driven by
    LoadDatasetTool.get_properties().
  - Added tool_ref (use_ref) to hold the Tool instance without triggering
    re-renders. Added tool_props/tool_values (use_state) to drive panel UI.
  - Added handle_property_change() callback — panel calls this when user
    changes a value; updates tool_values dict which triggers re-render.
  - Added handle_run_tool() — panel calls this on "Run Tool" click;
    sets properties on tool_ref, calls tool.run(), adds resulting
    DataLayer to active_layers via handle_tool_complete pattern.
  - Removed handle_load_data() — replaced by panel-driven flow.
  - Sidebar now has: "Load Data" button → Data Layers section.

Original architecture by Pat. Refactored per team feedback (2026-04-20).
"""

import traceback
from datetime import datetime, timezone

from pyproj import Transformer
from tethys_sdk.components import ComponentBase

# Reusable transformer: EPSG:3857 (Web Mercator) -> EPSG:4326 (lat/lon).
# Map click coordinates arrive in 3857; Tool.extent stores 4326.
_transformer_3857_to_4326 = Transformer.from_crs(
    'EPSG:3857', 'EPSG:4326', always_xy=True
)

from .components.layer_card import LayerCard
from .components.map_panel import MapPanel
from .components.ToolPropertiesPanel import ToolPropertiesPanel
from .tools.LoadDatasetTool import LoadDatasetTool
from .tools.ScaleBiasTool import ScaleBiasTool

# Registry of available tools — map buttons on the map (lower-right).
# Per Pat's feedback: each tool gets a button on the map, not a sidebar dropdown.
TOOL_REGISTRY = [
    {'id': 'load_dataset', 'name': 'Load Data', 'icon': '\u2B07',
     'class': LoadDatasetTool},
    {'id': 'scale_bias', 'name': 'Scale/Bias', 'icon': '\u2702',
     'class': ScaleBiasTool},
]


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


# ── Page ─────────────────────────────────────────────────────────────

@App.page
def home(lib):
    """
    Main NGPE map page — Pat's spec Sections 6.1–6.4.

    UI: sidebar with "Load Data" button and layer cards,
    OpenLayers map in center, ToolPropertiesPanel on right.

    State architecture (team agreement 2026-04-20):
      - tool_ref (use_ref): holds mutable Tool instance, no re-render.
      - tool_props (use_state): list from get_properties(), drives panel UI.
      - tool_values (use_state): dict of {prop_name: value}, updated by
        on_property_change callback from panel.
      - active_layers (use_state): dict of layer entries for map + cards.

    """

    # Pre-register OL components for JS module generation.
    # Tethys scans this function's source for lib.X.Y( patterns but strips
    # docstrings/comments first. Sub-modules (map_panel.py) are NOT scanned.
    # This block never executes but the source scanner sees the patterns.
    if False:
        lib.ol.source.Image()
        lib.olmod.layer.Image()
        lib.ol.source.Vector()
        lib.ol.layer.Vector()

    # ====== STATE ======
    # Separate use_state hooks — matches reference qpe_builder pattern.
    # See MEMORY.md "ReactPy State Management" for why single-object failed.
    active_layers, set_active_layers = lib.hooks.use_state({})
    error_msg, set_error_msg = lib.hooks.use_state(None)
    layers_open, set_layers_open = lib.hooks.use_state(True)

    # NOTE: Map view center/zoom are NOT in state. OL does NOT handle
    # patching View props on an existing map — changing them destroys
    # the map render entirely. The reference qpe_builder app also uses
    # a static view. Users must zoom/pan manually for now.

    # Tool state: ref for mutable Tool object, use_state for UI-driving data.
    # use_ref does not trigger re-render when .current changes (correct for
    # holding a Tool with methods and internal state).
    tool_ref = lib.hooks.use_ref(None)
    tool_props, set_tool_props = lib.hooks.use_state(None)
    tool_values, set_tool_values = lib.hooks.use_state({})

    # Mutable ref to track latest active_layers state.
    # Avoids ReactPy functional updater issues where `prev` can be stale.
    # Updated every render from the use_state value.
    layers_ref = lib.hooks.use_ref({})
    layers_ref.current = active_layers

    # Stores actual DataLayer objects (not just configs) so tools like
    # ScaleBiasTool can access the raw data for processing.
    data_layers_ref = lib.hooks.use_ref({})

    # Status message — shown after tool.run() completes (success or info).
    status_msg, set_status_msg = lib.hooks.use_state(None)

    # Loading flag — triggers use_effect to run tool after UI renders loading state.
    is_running, set_is_running = lib.hooks.use_state(False)

    # Ref to hold pending tool work (set by button click, consumed by use_effect).
    pending_tool_ref = lib.hooks.use_ref(None)

    # Polygon drawing state — base Tool.extent feature (Pat's spec).
    # Any tool can use self.extent for spatial bounds.
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

    # ---- Polygon drawing handlers (base Tool.extent) ----

    def handle_start_drawing(event):
        """Start polygon drawing mode. Clears existing vertices."""
        vertices_ref.current = []
        set_polygon_vertices([])
        set_draw_mode(True)

    def handle_finish_polygon(event):
        """Finish polygon. Builds GeoJSON and stores on tool_ref.extent."""
        set_draw_mode(False)
        verts = vertices_ref.current
        if len(verts) >= 3:
            ring = [[lon, lat] for lon, lat in verts]
            ring.append(ring[0])  # close
            geojson_geom = {
                'type': 'Polygon',
                'coordinates': [ring],
            }
            # Store on the base Tool.extent (Pat's spec)
            if tool_ref.current is not None:
                tool_ref.current.extent = geojson_geom
            print(f'[NGPE] Extent polygon set: {len(verts)} vertices')

    def handle_clear_polygon(event):
        """Clear polygon and tool extent."""
        set_draw_mode(False)
        vertices_ref.current = []
        set_polygon_vertices([])
        if tool_ref.current is not None:
            tool_ref.current.extent = None

    def handle_coordinate_click(event):
        """Handle map click during drawing mode. Appends vertex."""
        if not draw_mode:
            return
        coord = event.get('coordinate', None)
        if not coord or len(coord) < 2:
            return
        lon, lat = _transformer_3857_to_4326.transform(coord[0], coord[1])
        print(f'[NGPE] Polygon vertex: [{lon:.4f}, {lat:.4f}]')
        new_verts = vertices_ref.current + [[lon, lat]]
        vertices_ref.current = new_verts
        set_polygon_vertices(new_verts)

    def handle_run_tool(event):
        """Callback from ToolPropertiesPanel "Run Tool" button.

        Phase 1: Prepares the tool and sets is_running=True.
        ReactPy renders the loading UI, then use_effect (Phase 2)
        picks up the pending tool and runs it.
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

        # Copy extent from the current tool ref (base Tool.extent).
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

        # For ScaleBiasTool: pass extent GeoJSON as a property
        if extent_geojson and 'extent' in props_for_tool:
            props_for_tool['extent'] = extent_geojson

        tool.properties = props_for_tool

        # Store tool in ref for use_effect to pick up after render
        pending_tool_ref.current = tool

        # Phase 1: set loading state — ReactPy renders loading UI
        set_error_msg(None)
        set_status_msg(None)
        set_is_running(True)

    # Phase 2: use_effect runs AFTER ReactPy renders the loading UI.
    # When is_running becomes True, this effect executes the tool.
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
            print('[NGPE] Running tool...')
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
            print(f'[NGPE] Tool complete: {lname}')

        except Exception as e:
            traceback.print_exc()
            set_error_msg(str(e))
            set_status_msg(None)
            set_is_running(False)

    # ---- Layer handlers (factory pattern like reference qpe_builder) ----

    # Layer handlers use layers_ref to read current state and direct
    # set_active_layers to write — avoids ReactPy functional updater issues.

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

        # ── MAIN: SIDEBAR + MAP + TOOL PANEL ──
        lib.html.div(
            style=lib.Style(display='flex', flex='1', overflow='hidden'),
        )(
            # ── Left Sidebar — Data Layers only ──
            # Tool selector moved to map buttons (Pat's feedback).
            # Sidebar now only shows the Data Layers section.
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

                # "Clear All" button — OUTSIDE the header div to prevent
                # click propagation triggering both toggle and remove.
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
                    # Draw Extent button — only shown when active tool
                    # has a 'polygon' property (e.g. ScaleBiasTool).
                    # Pat: "polygon doesn't make sense for data loader"
                    *(
                        (
                            # Drawing active: show Finish + Cancel
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
            # Receives tool_props (property definitions), tool_values
            # (current user-entered values), and callbacks.
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
        ),
    )
