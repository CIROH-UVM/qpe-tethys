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

from tethys_sdk.components import ComponentBase

from .components.layer_card import LayerCard
from .components.map_panel import MapPanel
from .components.ToolPropertiesPanel import ToolPropertiesPanel
from .tools.LoadDatasetTool import LoadDatasetTool


# Registry of available tools — add new tools here as they are created.
# Each entry: {'id': str, 'name': str (display), 'class': Tool subclass}
TOOL_REGISTRY = [
    {'id': 'load_dataset', 'name': 'Load Dataset', 'class': LoadDatasetTool},
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

    # ====== STATE ======
    # Separate use_state hooks — matches reference qpe_builder pattern.
    # See MEMORY.md "ReactPy State Management" for why single-object failed.
    active_layers, set_active_layers = lib.hooks.use_state({})
    error_msg, set_error_msg = lib.hooks.use_state(None)
    controls_open, set_controls_open = lib.hooks.use_state(True)
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

    # Polygon drawing state — for tools with 'polygon' property type.
    draw_mode, set_draw_mode = lib.hooks.use_state(False)
    polygon_vertices, set_polygon_vertices = lib.hooks.use_state([])

    # ====== HANDLERS ======

    def handle_tool_select(event):
        """Create the selected Tool and populate the ToolPropertiesPanel.

        Reads the tool ID from the dropdown, looks it up in TOOL_REGISTRY,
        creates an instance, stores in use_ref, and populates tool_props
        and tool_values for the panel.
        """
        tool_id = event['target']['value']
        if not tool_id:
            tool_ref.current = None
            set_tool_props(None)
            set_tool_values({})
            return

        # Find the tool class from registry
        tool_entry = next(
            (t for t in TOOL_REGISTRY if t['id'] == tool_id), None
        )
        if tool_entry is None:
            set_error_msg(f'Unknown tool: {tool_id}')
            return

        tool = tool_entry['class']()
        tool_ref.current = tool

        props_list = tool.get_properties()
        set_tool_props(props_list)

        # Initialize values dict with empty strings for each property
        initial_values = {p['name']: '' for p in props_list}
        set_tool_values(initial_values)
        set_error_msg(None)

    def handle_property_change(prop_name, new_value):
        """Callback from ToolPropertiesPanel when user changes a value.

        Updates tool_values dict in use_state, triggering re-render so
        the panel shows the updated value. Uses functional updater to
        safely merge new value into existing dict.
        """
        set_tool_values(lambda prev: {**prev, prop_name: new_value})

    # ---- Polygon drawing handlers ----

    def handle_start_drawing(event):
        """Start polygon drawing mode. Clears existing vertices."""
        set_polygon_vertices([])
        set_draw_mode(True)

    def handle_finish_polygon(event):
        """Finish polygon drawing. Store as GeoJSON Polygon in tool_values."""
        set_draw_mode(False)
        verts = polygon_vertices
        if len(verts) >= 3:
            # Close the ring and build GeoJSON Polygon geometry
            ring = [[lon, lat] for lon, lat in verts]
            ring.append(ring[0])  # close
            geojson_geom = {
                'type': 'Polygon',
                'coordinates': [ring],
            }
            # Find the polygon property name and update tool_values
            if tool_props:
                for p in tool_props:
                    if p.get('type') == 'polygon':
                        set_tool_values(
                            lambda prev: {**prev, p['name']: geojson_geom}
                        )
                        break

    def handle_clear_polygon(event):
        """Clear polygon vertices and exit drawing mode."""
        set_draw_mode(False)
        set_polygon_vertices([])
        # Clear the polygon property value in tool_values
        if tool_props:
            for p in tool_props:
                if p.get('type') == 'polygon':
                    set_tool_values(
                        lambda prev: {**prev, p['name']: ''}
                    )
                    break

    def handle_run_tool(event):
        """Callback from ToolPropertiesPanel "Run Tool" button.

        Creates a FRESH Tool instance each run to avoid stale state,
        sets the collected tool_values as properties, runs the tool,
        and adds resulting DataLayer(s) to active_layers.

        Uses layers_ref (not functional updater) to read current layers
        and direct set_active_layers to avoid ReactPy stale-prev issues.
        """
        if tool_ref.current is None:
            set_error_msg('No tool selected. Click "Load Data" first.')
            return

        # Create a fresh Tool instance each run to avoid stale status/_result.
        # The tool type comes from the ref; we create a new instance of the
        # same class so run() starts clean.
        tool = tool_ref.current.__class__()

        # Copy user-entered values onto the Tool's properties dict.
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

        tool.properties = props_for_tool

        try:
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

            # Use layers_ref for current state (avoids stale functional updater).
            # Direct set — not lambda prev — to bypass ReactPy chaining issues.
            new_layers = {**layers_ref.current, **layer_entry}
            layers_ref.current = new_layers
            set_active_layers(new_layers)
            set_error_msg(None)

        except Exception as e:
            traceback.print_exc()
            set_error_msg(str(e))

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

        # ── MAIN: SIDEBAR + MAP + TOOL PANEL ──
        lib.html.div(
            style=lib.Style(display='flex', flex='1', overflow='hidden'),
        )(
            # ── Left Sidebar ──
            # Simplified: "Load Data" button + Data Layers.
            # Region/datetime pickers removed — now in ToolPropertiesPanel
            # driven by LoadDatasetTool.get_properties().
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
                        style=lib.Style(
                            fontSize='9px', color='#667085', width='12px',
                        ),
                    )('\u25BC' if controls_open else '\u25B6'),
                    lib.html.span(
                        style=lib.Style(
                            fontSize='11px', fontWeight='700',
                            letterSpacing='0.06em', color='#667085',
                            textTransform='uppercase', flex='1',
                        ),
                    )('Controls'),
                ),

                # Tool selector dropdown — select a tool to configure and run.
                # When a tool is selected, its get_properties() populates
                # the ToolPropertiesPanel on the right side.
                *(
                    [
                        lib.html.div(
                            style=lib.Style(
                                display='flex', flexDirection='column',
                                gap='4px', marginBottom='12px',
                                paddingLeft='20px',
                            ),
                        )(
                            lib.html.label(
                                style=lib.Style(
                                    fontSize='11px', color='#667085',
                                    fontWeight='600',
                                ),
                            )('Select Tool'),
                            lib.html.select(
                                style=lib.Style(
                                    width='100%', padding='7px 10px',
                                    fontSize='13px', fontWeight='600',
                                    border='1.5px solid #d0d5dd',
                                    borderRadius='8px',
                                    backgroundColor='#fff', color='#333',
                                    cursor='pointer', outline='none',
                                ),
                                onChange=handle_tool_select,
                            )(
                                lib.html.option(value='')(
                                    'Choose a tool...'
                                ),
                                *[
                                    lib.html.option(value=t['id'])(
                                        t['name']
                                    )
                                    for t in TOOL_REGISTRY
                                ],
                            ),
                        ),
                    ] if controls_open else []
                ),

                # Divider
                lib.html.div(
                    style=lib.Style(
                        height='1px', background='#e0e4ea', margin='6px 0',
                    ),
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
                            )(
                                'Click "Load Data" above, configure the '
                                'tool on the right, then click "Run Tool".'
                            ),
                        ]
                    ) if layers_open else []
                ),
            ),

            # ── Center: Map ──
            lib.html.div(
                style=lib.Style(flex='1', position='relative'),
            )(
                MapPanel(
                    lib,
                    active_layers=active_layers,
                    error_msg=error_msg,
                    polygon_vertices=polygon_vertices,
                    draw_mode=draw_mode,
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
                on_start_drawing=handle_start_drawing,
                on_finish_polygon=handle_finish_polygon,
                on_clear_polygon=handle_clear_polygon,
                draw_mode=draw_mode,
            ),
        ),
    )
