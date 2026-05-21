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
import uuid as _uuid
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
from .components.workflow_panel import WorkflowPanel
from .tools.LoadDatasetTool import LoadDatasetTool
from .tools.ScaleBiasTool import ScaleBiasTool
from .workflow import WorkflowEngine, WorkflowStore

# =============================================================================
# Design Tokens
# =============================================================================
# Centralized color palette. Every UI element references these tokens so a
# single change here propagates everywhere.

COLORS = {
    # -- Brand / accent --------------------------------------------------------
    "primary":        "#1A5276",   # deep hydro-blue -- section accents, badges
    "primary_light":  "#e8f1f5",   # tinted blue -- active-layer row highlight

    # -- Sidebar chrome --------------------------------------------------------
    "sidebar_bg":     "#f5f7fa",   # light neutral sidebar background
    "sidebar_border": "#dce1e8",   # right-edge separator

    # -- Typography ------------------------------------------------------------
    "text_dark":      "#1a1a2e",   # primary text
    "text_muted":     "#6b7280",   # secondary / subtitle text
    "text_section":   "#374151",   # accordion section header labels

    # -- Borders & dots --------------------------------------------------------
    "border_light":   "#e5e7eb",   # general light borders
    "success_dot":    "#22c55e",   # layer-visible indicator dot
    "dot_off":        "#d1d5db",   # layer-hidden / removed indicator dot
    "white":          "#ffffff",
}

SIDEBAR_WIDTH = "280px"

# =============================================================================
# Basemap Options
# =============================================================================
# Each dict defines a tile provider the user can select in the sidebar.
#   key   -- unique identifier stored in selected_basemap state
#   label -- human-readable name shown in the <select> dropdown
#   url   -- XYZ tile URL template; None uses the built-in OSM source

BASEMAP_OPTIONS = [
    {"key": "osm",          "label": "Street (OSM)",       "url": None},
    {"key": "carto_dark",   "label": "Dark (Carto)",       "url": "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png"},
    {"key": "esri_imagery", "label": "Satellite (ESRI)",   "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"},
    {"key": "esri_topo",    "label": "Topographic (ESRI)", "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}"},
]

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
    color = "#1A5276"
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
        lib.ol.source.XYZ()
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
    selected_basemap, set_selected_basemap = lib.hooks.use_state("osm")
    basemap_open, set_basemap_open = lib.hooks.use_state(True)
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

    # ====== WORKFLOW STATE ======
    # Engine and store are mutable singletons — use_ref (no re-render).
    workflow_engine_ref = lib.hooks.use_ref(None)
    if workflow_engine_ref.current is None:
        workflow_engine_ref.current = WorkflowEngine()
    workflow_store_ref = lib.hooks.use_ref(None)
    if workflow_store_ref.current is None:
        workflow_store_ref.current = WorkflowStore()

    # UI state for the workflow builder panel
    wf_open, set_wf_open = lib.hooks.use_state(True)
    wf_name, set_wf_name = lib.hooks.use_state('Untitled Workflow')
    wf_steps, set_wf_steps = lib.hooks.use_state([])  # list of step dicts
    wf_status, set_wf_status = lib.hooks.use_state('idle')
    wf_editing_index, set_wf_editing_index = lib.hooks.use_state(-1)
    wf_editing_values, set_wf_editing_values = lib.hooks.use_state({})
    saved_workflows, set_saved_workflows = lib.hooks.use_state(
        workflow_store_ref.current.list_all()
    )

    # Ref to track the current Workflow object for execution
    replay_wf_ref = lib.hooks.use_ref(None)
    wf_running, set_wf_running = lib.hooks.use_state(False)

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

            # Deselect any workflow step — we're now in standalone tool mode
            set_wf_editing_index(-1)
            set_wf_editing_values({})

            # Clear polygon when switching tools
            set_draw_mode(False)
            vertices_ref.current = []
            set_polygon_vertices([])
            if tool_ref.current is not None:
                tool_ref.current.extent = None
        return handler

    def handle_property_change(prop_name, new_value):
        """Callback from ToolPropertiesPanel when user changes a value.

        Routes to the workflow step if one is being edited.
        """
        set_tool_values(lambda prev: {**prev, prop_name: new_value})
        # If editing a workflow step, also update the step's properties
        if wf_editing_index >= 0 and wf_editing_index < len(wf_steps):
            handle_step_property_change(wf_editing_index, prop_name, new_value)

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

    # ---- Workflow builder handlers ----

    def toggle_workflow(event):
        set_wf_open(lambda prev: not prev)

    def handle_workflow_name_change(event):
        set_wf_name(event['target']['value'])

    def _get_tool_properties(tool_id):
        """Get property definitions for a tool by its registry ID."""
        tool_entry = next(
            (t for t in TOOL_REGISTRY if t['id'] == tool_id), None
        )
        if tool_entry is None:
            return []
        tool = tool_entry['class']()
        return tool.get_properties()

    def _rebuild_workflow_from_steps(steps_list):
        """Build a Workflow object from the UI step dicts."""
        from .workflow import Workflow
        wf = Workflow(name=wf_name or 'Untitled Workflow')
        for step_dict in steps_list:
            wf.add_step(
                tool_id=step_dict['tool_id'],
                tool_name=step_dict['tool_name'],
                properties=step_dict.get('properties', {}),
                extent=step_dict.get('extent'),
            )
        return wf

    def handle_add_step(tool_id):
        """Add a new step for the given tool to the workflow."""
        tool_entry = next(
            (t for t in TOOL_REGISTRY if t['id'] == tool_id), None
        )
        if tool_entry is None:
            return
        tool_props = _get_tool_properties(tool_id)
        initial_values = {
            p['name']: (None if p['type'] == 'polygon' else '')
            for p in tool_props
        }
        new_step = {
            'id': str(_uuid.uuid4()),
            'tool_id': tool_id,
            'tool_name': tool_entry['name'],
            'properties': initial_values,
            'extent': None,
            'step_order': len(wf_steps),
            'status': 'pending',
            'error_msg': None,
            'tool_properties': tool_props,
        }
        updated = wf_steps + [new_step]
        set_wf_steps(updated)
        # Auto-expand the new step for editing
        set_wf_editing_index(len(updated) - 1)
        set_wf_editing_values(initial_values)
        set_wf_status('idle')

    def handle_remove_step(step_index):
        """Remove a step and re-number the rest."""
        updated = [s for i, s in enumerate(wf_steps) if i != step_index]
        for i, s in enumerate(updated):
            s['step_order'] = i
        set_wf_steps(updated)
        if wf_editing_index == step_index:
            # Clear right panel — the step we were editing is gone
            set_wf_editing_index(-1)
            set_wf_editing_values({})
            set_tool_props(None)
            set_tool_values({})
        elif wf_editing_index > step_index:
            set_wf_editing_index(wf_editing_index - 1)

    def handle_move_step_up(step_index):
        """Swap step with the one above it."""
        if step_index <= 0:
            return
        updated = list(wf_steps)
        updated[step_index], updated[step_index - 1] = updated[step_index - 1], updated[step_index]
        for i, s in enumerate(updated):
            s['step_order'] = i
        set_wf_steps(updated)
        # Track editing index
        if wf_editing_index == step_index:
            set_wf_editing_index(step_index - 1)
        elif wf_editing_index == step_index - 1:
            set_wf_editing_index(step_index)

    def handle_move_step_down(step_index):
        """Swap step with the one below it."""
        if step_index >= len(wf_steps) - 1:
            return
        updated = list(wf_steps)
        updated[step_index], updated[step_index + 1] = updated[step_index + 1], updated[step_index]
        for i, s in enumerate(updated):
            s['step_order'] = i
        set_wf_steps(updated)
        if wf_editing_index == step_index:
            set_wf_editing_index(step_index + 1)
        elif wf_editing_index == step_index + 1:
            set_wf_editing_index(step_index)

    def handle_select_step(step_index):
        """Select a workflow step — show its properties in the right panel."""
        if wf_editing_index == step_index:
            # Deselect — clear right panel back to empty
            set_wf_editing_index(-1)
            set_wf_editing_values({})
            set_tool_props(None)
            set_tool_values({})
            return

        step = wf_steps[step_index]
        set_wf_editing_index(step_index)

        # Populate the right-side ToolPropertiesPanel with this step's config
        props_list = step.get('tool_properties', [])
        if not props_list:
            props_list = _get_tool_properties(step['tool_id'])

        # Dynamically populate layer_id options for Scale/Bias steps
        for prop in props_list:
            if prop['name'] == 'layer_id' and not prop.get('options'):
                current_layers = layers_ref.current
                prop['options'] = [
                    f"{v['config'].get('name', k)} ({v['config'].get('type', '?')})"
                    for k, v in current_layers.items()
                    if v.get('added')
                ]

        set_tool_props(props_list)
        set_tool_values(dict(step.get('properties', {})))
        set_wf_editing_values(dict(step.get('properties', {})))

    def handle_step_property_change(step_index, prop_name, value):
        """Update a property value on a specific step."""
        updated = list(wf_steps)
        step = dict(updated[step_index])
        step['properties'] = {**step.get('properties', {}), prop_name: value}
        updated[step_index] = step
        set_wf_steps(updated)
        if wf_editing_index == step_index:
            set_wf_editing_values(lambda prev: {**prev, prop_name: value})
            # Keep tool_values in sync so the right panel reflects changes
            set_tool_values(lambda prev: {**prev, prop_name: value})

    def handle_save_workflow(event):
        if not wf_steps:
            set_error_msg('Add steps to the workflow before saving')
            return
        store = workflow_store_ref.current
        wf = _rebuild_workflow_from_steps(wf_steps)
        # Preserve existing workflow ID if loaded from store
        existing_wf = replay_wf_ref.current
        if existing_wf:
            wf.id = existing_wf.id
        store.save(wf)
        replay_wf_ref.current = wf
        set_saved_workflows(store.list_all())
        set_status_msg(f'Workflow saved: {wf.name}')
        logger.info('Workflow saved: %s (%d steps)', wf.name, len(wf.steps))

    def handle_run_workflow(event):
        """Build a Workflow from the current steps and execute it."""
        if wf_running or is_running:
            return
        if not wf_steps:
            set_error_msg('Add steps to the workflow first')
            return
        wf = _rebuild_workflow_from_steps(wf_steps)
        replay_wf_ref.current = wf
        set_wf_running(True)
        set_wf_status('running')
        # Mark all steps as pending in UI
        updated = [{**s, 'status': 'pending', 'error_msg': None} for s in wf_steps]
        set_wf_steps(updated)
        set_error_msg(None)
        set_status_msg(None)

    @lib.hooks.use_effect(dependencies=[wf_running])
    def _run_workflow():
        if not wf_running:
            return
        wf = replay_wf_ref.current
        if wf is None:
            set_wf_running(False)
            return

        engine = workflow_engine_ref.current
        try:
            existing = list(data_layers_ref.current.values())

            def on_step_done(idx, step, layer):
                # Add each produced layer to the map
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

            engine.run(wf, existing_layers=existing,
                       on_step_complete=on_step_done)

            set_wf_steps([s.to_dict() for s in wf.steps])
            set_wf_status('done')
            set_status_msg(f'Workflow complete: {wf.name}')
            set_wf_running(False)
            logger.info('Workflow complete: %s', wf.name)

        except Exception as e:
            logger.exception('Workflow execution failed')
            set_wf_steps([s.to_dict() for s in wf.steps])
            set_wf_status('error')
            set_error_msg(f'Workflow error: {e}')
            set_wf_running(False)

    def handle_clear_workflow(event):
        set_wf_steps([])
        set_wf_status('idle')
        set_wf_name('Untitled Workflow')
        set_wf_editing_index(-1)
        set_wf_editing_values({})
        set_tool_props(None)
        set_tool_values({})
        replay_wf_ref.current = None

    def handle_load_workflow(workflow_id):
        store = workflow_store_ref.current
        wf = store.load(workflow_id)
        if wf is None:
            set_error_msg(f'Workflow not found: {workflow_id}')
            return
        replay_wf_ref.current = wf
        set_wf_name(wf.name)
        # Enrich steps with tool_properties for inline editing
        enriched_steps = []
        for s in wf.steps:
            sd = s.to_dict()
            sd['tool_properties'] = _get_tool_properties(sd['tool_id'])
            enriched_steps.append(sd)
        set_wf_steps(enriched_steps)
        set_wf_status(wf.status)
        set_wf_editing_index(-1)
        set_wf_editing_values({})
        set_status_msg(f'Loaded: {wf.name}')
        logger.info('Loaded workflow: %s (%d steps)', wf.name, len(wf.steps))

    def handle_delete_workflow(workflow_id):
        store = workflow_store_ref.current
        store.delete(workflow_id)
        set_saved_workflows(store.list_all())
        wf = replay_wf_ref.current
        if wf and wf.id == workflow_id:
            handle_clear_workflow(None)

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

    def toggle_basemap(event):
        set_basemap_open(lambda prev: not prev)

    def handle_basemap_change(event):
        set_selected_basemap(event['target']['value'])

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
            card = LayerCard(
                lib, layer_id=uid, entry=entry,
                on_toggle_visibility=make_toggle_handler(uid),
                on_opacity_change=make_opacity_handler(uid),
                on_remove=make_remove_handler(uid),
            )
            card["key"] = f"layer-{uid}"
            layer_cards.append(card)

    # ====== RENDER ======
    # NavHeader provides the Tethys header bar (56px). Our content fills
    # the remaining viewport height below it.

    # Section header style (reused for Base Map and Data Layers)
    section_hdr_style = lib.Style(
        display='flex', alignItems='center', gap='8px',
        padding='8px 0', cursor='pointer', userSelect='none',
    )
    section_label_style = lib.Style(
        fontSize='11px', fontWeight='700',
        letterSpacing='0.06em', color=COLORS['text_muted'],
        textTransform='uppercase', flex='1',
    )
    chevron_style = lib.Style(
        fontSize='9px', color=COLORS['text_muted'], width='12px',
    )

    return lib.html.div(
        style=lib.Style(
            display='flex',
            height='calc(100vh - 56px)', width='100%',
            background=COLORS['sidebar_bg'],
            fontFamily="'Segoe UI', system-ui, -apple-system, sans-serif",
            overflow='hidden',
        ),
    )(
            # ── Left Sidebar ──
            lib.html.div(
                style=lib.Style(
                    width=SIDEBAR_WIDTH, minWidth=SIDEBAR_WIDTH, flexShrink='0',
                    background=COLORS['sidebar_bg'],
                    borderRight=f"1px solid {COLORS['sidebar_border']}",
                    overflowY='auto',
                    padding='14px 16px',
                    boxSizing='border-box',
                ),
            )(
                # ── Base Map section (collapsible) ──
                lib.html.div(
                    style=section_hdr_style,
                    onClick=toggle_basemap,
                )(
                    lib.html.span(style=chevron_style)(
                        '\u25BC' if basemap_open else '\u25B6'
                    ),
                    lib.html.span(style=section_label_style)('Base Map'),
                ),
                *(
                    [lib.html.select(
                        style=lib.Style(
                            width='100%', padding='8px 12px',
                            fontSize='13px', fontWeight='600',
                            border=f"1.5px solid {COLORS['border_light']}",
                            borderRadius='8px',
                            backgroundColor=COLORS['white'],
                            color=COLORS['text_dark'],
                            cursor='pointer',
                            marginBottom='16px',
                            outline='none',
                        ),
                        value=selected_basemap,
                        onChange=handle_basemap_change,
                    )(
                        *[
                            lib.html.option(value=opt['key'])(opt['label'])
                            for opt in BASEMAP_OPTIONS
                        ],
                    )]
                    if basemap_open else []
                ),

                # ── Data Layers section (collapsible) ──
                lib.html.div(
                    style=section_hdr_style,
                    onClick=toggle_layers,
                )(
                    lib.html.span(style=chevron_style)(
                        '\u25BC' if layers_open else '\u25B6'
                    ),
                    lib.html.span(style=section_label_style)(
                        f'Data Layers ({len(layer_cards)})' if layer_cards
                        else 'Data Layers'
                    ),
                ),

                # "Clear All" button
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
                                    fontSize='12px', color=COLORS['text_muted'],
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

                # ── Workflow section (collapsible) ──
                lib.html.div(
                    style=lib.Style(
                        borderTop=f"1px solid {COLORS['border_light']}",
                        marginTop='8px', paddingTop='4px',
                    ),
                )(
                    lib.html.div(
                        style=section_hdr_style,
                        onClick=toggle_workflow,
                    )(
                        lib.html.span(style=chevron_style)(
                            '\u25BC' if wf_open else '\u25B6'
                        ),
                        lib.html.span(style=section_label_style)(
                            'Workflow'
                            + (f' ({len(wf_steps)})' if wf_steps else '')
                        ),
                        *(
                            [lib.html.span(
                                style=lib.Style(
                                    fontSize='8px', color='#1565C0',
                                    fontWeight='700', letterSpacing='0.04em',
                                ),
                            )('\u25B6 RUNNING')]
                            if wf_running else []
                        ),
                    ),
                    *(
                        [WorkflowPanel(
                            lib,
                            workflow_steps=wf_steps,
                            workflow_name=wf_name,
                            saved_workflows=saved_workflows,
                            workflow_status=wf_status,
                            available_tools=[
                                {'id': t['id'], 'name': t['name'], 'icon': t['icon']}
                                for t in TOOL_REGISTRY
                            ],
                            editing_step_index=wf_editing_index,
                            on_workflow_name_change=handle_workflow_name_change,
                            on_add_step=handle_add_step,
                            on_remove_step=handle_remove_step,
                            on_move_step_up=handle_move_step_up,
                            on_move_step_down=handle_move_step_down,
                            on_select_step=handle_select_step,
                            on_save_workflow=handle_save_workflow,
                            on_run_workflow=handle_run_workflow,
                            on_clear_workflow=handle_clear_workflow,
                            on_load_workflow=handle_load_workflow,
                            on_delete_workflow=handle_delete_workflow,
                            is_running=wf_running,
                        )]
                        if wf_open else []
                    ),
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
                    selected_basemap=selected_basemap,
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
                                background=COLORS['primary'], color='#fff',
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
            # Shows workflow step config when a step is selected,
            # otherwise shows standalone tool config.
            ToolPropertiesPanel(
                lib,
                tool_props=tool_props,
                tool_values=tool_values,
                on_property_change=handle_property_change,
                on_run_tool=handle_run_tool,
                status_msg=status_msg,
                error_msg=error_msg,
                is_running=is_running,
                panel_mode=(
                    'workflow_step' if wf_editing_index >= 0 else 'tool'
                ),
                step_label=(
                    f"Step {wf_editing_index + 1} \u2014 "
                    f"{wf_steps[wf_editing_index].get('tool_name', '')}"
                    if 0 <= wf_editing_index < len(wf_steps) else None
                ),
            ),
    )
