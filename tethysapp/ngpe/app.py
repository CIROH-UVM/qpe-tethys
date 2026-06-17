"""NGPE Platform — Main Tethys Component App.

Provides the primary map interface for the Next-Generation QPE Platform.
Layout: left sidebar (data layer cards + workflow builder), center
(OpenLayers map), right panel (ToolPropertiesPanel for step configuration).

State architecture (refactored 2026-05-24, Pat's feedback):
  - Workflow is always active — every tool action is a workflow step.
  - No standalone tool mode — tools are added via the workflow panel.
  - WorkflowStep wraps actual Tool instances (not property copies).
  - Steps have back-references to their parent Workflow.
"""

import logging
import copy
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
from .workflow import Workflow, WorkflowStep, WorkflowEngine, WorkflowStore

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

# Registry of available tools — rendered as "Add Step" buttons in workflow panel.
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

    Renders the full application layout: left sidebar with layer cards
    and workflow builder, center OpenLayers map, and right-side tool
    properties panel for configuring the selected workflow step.
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

    # Tool property state — drives the right-side ToolPropertiesPanel.
    # Set when a workflow step is selected.
    tool_props, set_tool_props = lib.hooks.use_state(None)
    tool_values, set_tool_values = lib.hooks.use_state({})

    # Mutable ref tracking latest active_layers — avoids stale closures
    # in event handlers. Updated every render cycle.
    layers_ref = lib.hooks.use_ref({})
    layers_ref.current = active_layers

    # Stores DataLayer objects so downstream tools can access raw data.
    data_layers_ref = lib.hooks.use_ref({})

    # Status message shown after tool/workflow execution completes.
    status_msg, set_status_msg = lib.hooks.use_state(None)

    # Polygon drawing state — used by tools that support spatial extent.
    draw_mode, set_draw_mode = lib.hooks.use_state(False)
    polygon_vertices, set_polygon_vertices = lib.hooks.use_state([])
    vertices_ref = lib.hooks.use_ref([])
    vertices_ref.current = polygon_vertices

    # ====== WORKFLOW STATE ======
    # The workflow is always active — there is no standalone tool mode.
    # Engine and store are mutable singletons — use_ref (no re-render).
    workflow_engine_ref = lib.hooks.use_ref(None)
    if workflow_engine_ref.current is None:
        workflow_engine_ref.current = WorkflowEngine()
    workflow_store_ref = lib.hooks.use_ref(None)
    if workflow_store_ref.current is None:
        workflow_store_ref.current = WorkflowStore()

    # The active Workflow object — always exists.
    workflow_ref = lib.hooks.use_ref(None)
    if workflow_ref.current is None:
        workflow_ref.current = Workflow()

    # UI state for the workflow builder panel
    wf_open, set_wf_open = lib.hooks.use_state(True)
    wf_name, set_wf_name = lib.hooks.use_state('Untitled Workflow')
    wf_steps, set_wf_steps = lib.hooks.use_state([])  # list of step dicts for UI
    wf_status, set_wf_status = lib.hooks.use_state('idle')
    wf_editing_index, set_wf_editing_index = lib.hooks.use_state(-1)
    saved_workflows, set_saved_workflows = lib.hooks.use_state(
        workflow_store_ref.current.list_all()
    )

    wf_running, set_wf_running = lib.hooks.use_state(False)
    # Track which step to run (-1 = all steps, >= 0 = single step index)
    run_step_ref = lib.hooks.use_ref(-1)

    # ====== HELPERS ======

    def _ui_safe_values(props_dict):
        """Convert property values to UI-safe types (strings for HTML inputs).

        datetime objects → ISO string, None → '', everything else passthrough.
        """
        safe = {}
        for k, v in props_dict.items():
            if isinstance(v, datetime):
                safe[k] = v.isoformat()
            elif v is None:
                safe[k] = None
            else:
                safe[k] = v
        return safe

    def _sync_steps_to_ui():
        """Sync the Workflow object's steps to the UI state list."""
        wf = workflow_ref.current
        step_dicts = []
        for step in wf.steps:
            sd = step.to_dict()
            sd['tool_properties'] = step.tool.get_properties()
            step_dicts.append(sd)
        set_wf_steps(step_dicts)

    def _get_tool_props_for_step(step):
        """Get property definitions for a step's tool, with dynamic options.

        For layer_id properties, populates options with:
          1. Step references ('step:0', 'step:1', ...) for all previous
             steps in the workflow — allows building the full pipeline
             before running.
          2. Existing map layers — for referencing data loaded outside
             the current workflow.
        """
        props_list = step.tool.get_properties()
        wf = workflow_ref.current

        for prop in props_list:
            if prop['name'] != 'layer_id':
                continue

            options = []
            option_labels = {}  # value → display label

            # Previous step outputs (workflow references)
            if wf and step.workflow is wf:
                step_idx = step.step_index
                for i, prev_step in enumerate(wf.steps):
                    if i >= step_idx:
                        break  # Only reference earlier steps
                    ref_value = f"step:{i}"
                    label = f"Step {i + 1} \u2014 {prev_step.tool_name}"
                    # Add detail from properties if available
                    detail_parts = []
                    if prev_step.tool.properties.get('dataset_id'):
                        detail_parts.append(
                            prev_step.tool.properties['dataset_id']
                            .replace('_', ' ')
                        )
                    if prev_step.tool.properties.get('output_name'):
                        detail_parts.append(
                            prev_step.tool.properties['output_name']
                        )
                    if detail_parts:
                        label += f" ({', '.join(detail_parts)})"
                    options.append(ref_value)
                    option_labels[ref_value] = label

            # Only show step references when inside a workflow —
            # map layers are redundant (they come from the same steps).
            prop['options'] = options
            prop['option_labels'] = option_labels

        return props_list

    # ====== HANDLERS ======

    # ---- Polygon drawing handlers ----

    def handle_start_drawing(event):
        """Activate polygon drawing mode and clear existing vertices."""
        vertices_ref.current = []
        set_polygon_vertices([])
        set_draw_mode(True)
        set_error_msg(None)
        set_status_msg(None)

    def handle_finish_polygon(event):
        """Close the polygon and store GeoJSON extent on the selected step's tool."""
        set_draw_mode(False)
        verts = vertices_ref.current
        if len(verts) >= 3:
            ring = [[lon, lat] for lon, lat in verts]
            ring.append(ring[0])  # close
            geojson_geom = {
                'type': 'Polygon',
                'coordinates': [ring],
            }
            # Store on the selected step's tool
            wf = workflow_ref.current
            if 0 <= wf_editing_index < len(wf.steps):
                wf.steps[wf_editing_index].tool.extent = geojson_geom
                # Also update the extent property value
                wf.steps[wf_editing_index].tool.properties['extent'] = geojson_geom
                _sync_steps_to_ui()
            logger.info('Extent polygon set: %d vertices', len(verts))

    def handle_clear_polygon(event):
        """Clear the drawn polygon and reset the selected step's extent."""
        set_draw_mode(False)
        vertices_ref.current = []
        set_polygon_vertices([])
        wf = workflow_ref.current
        if 0 <= wf_editing_index < len(wf.steps):
            wf.steps[wf_editing_index].tool.extent = None
            if 'extent' in wf.steps[wf_editing_index].tool.properties:
                wf.steps[wf_editing_index].tool.properties['extent'] = None
            _sync_steps_to_ui()

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

    def handle_property_change(prop_name, new_value):
        """Callback from ToolPropertiesPanel when user changes a value.

        Updates the actual Tool instance on the selected workflow step.
        """
        set_tool_values(lambda prev: {**prev, prop_name: new_value})

        # Update the Tool object on the workflow step
        wf = workflow_ref.current
        if 0 <= wf_editing_index < len(wf.steps):
            step = wf.steps[wf_editing_index]
            step.tool.properties[prop_name] = new_value
            _sync_steps_to_ui()

    # ---- Workflow builder handlers ----

    def toggle_workflow(event):
        set_wf_open(lambda prev: not prev)

    def handle_workflow_name_change(event):
        name = event['target']['value']
        set_wf_name(name)
        workflow_ref.current.name = name

    def handle_add_step(tool_id):
        """Add a new step: create a Tool instance, wrap in WorkflowStep."""
        tool_entry = next(
            (t for t in TOOL_REGISTRY if t['id'] == tool_id), None
        )
        if tool_entry is None:
            return

        # Create a fresh Tool instance
        tool = tool_entry['class']()

        # Initialize properties with empty defaults
        props_list = tool.get_properties()
        initial_values = {
            p['name']: (None if p['type'] == 'polygon' else '')
            for p in props_list
        }
        tool.properties = initial_values

        # Add to the workflow
        wf = workflow_ref.current
        wf.add_step(tool)

        # Sync to UI and auto-select the new step
        _sync_steps_to_ui()
        new_index = len(wf.steps) - 1
        _select_step(new_index)
        set_wf_status('idle')

    def handle_remove_step(step_index):
        """Remove a step from the workflow."""
        wf = workflow_ref.current
        wf.remove_step(step_index)
        _sync_steps_to_ui()

        if wf_editing_index == step_index:
            # Clear right panel — the step we were editing is gone
            set_wf_editing_index(-1)
            set_tool_props(None)
            set_tool_values({})
        elif wf_editing_index > step_index:
            set_wf_editing_index(wf_editing_index - 1)

    def handle_move_step_up(step_index):
        """Swap step with the one above it."""
        if step_index <= 0:
            return
        wf = workflow_ref.current
        wf.move_step(step_index, step_index - 1)
        _sync_steps_to_ui()
        # Track editing index
        if wf_editing_index == step_index:
            set_wf_editing_index(step_index - 1)
        elif wf_editing_index == step_index - 1:
            set_wf_editing_index(step_index)

    def handle_move_step_down(step_index):
        """Swap step with the one below it."""
        wf = workflow_ref.current
        if step_index >= len(wf.steps) - 1:
            return
        wf.move_step(step_index, step_index + 1)
        _sync_steps_to_ui()
        if wf_editing_index == step_index:
            set_wf_editing_index(step_index + 1)
        elif wf_editing_index == step_index + 1:
            set_wf_editing_index(step_index)

    def _select_step(step_index):
        """Select a workflow step — show its properties in the right panel."""
        wf = workflow_ref.current
        if step_index < 0 or step_index >= len(wf.steps):
            return
        step = wf.steps[step_index]
        set_wf_editing_index(step_index)

        props_list = _get_tool_props_for_step(step)
        set_tool_props(props_list)
        set_tool_values(_ui_safe_values(step.tool.properties))
        set_error_msg(None)
        set_status_msg(None)

        # Clear polygon state when switching steps
        set_draw_mode(False)
        vertices_ref.current = []
        set_polygon_vertices([])

    def handle_select_step(step_index):
        """Toggle selection of a workflow step."""
        if wf_editing_index == step_index:
            # Deselect — clear right panel
            set_wf_editing_index(-1)
            set_tool_props(None)
            set_tool_values({})
            return
        _select_step(step_index)

    def handle_save_workflow(event):
        """Save the current workflow to the store."""
        wf = workflow_ref.current
        if not wf.steps:
            set_error_msg('Add steps to the workflow before saving')
            return
        wf.name = wf_name or 'Untitled Workflow'
        store = workflow_store_ref.current
        store.save(wf)
        set_saved_workflows(store.list_all())
        set_status_msg(f'Workflow saved: {wf.name}')
        logger.info('Workflow saved: %s (%d steps)', wf.name, len(wf.steps))

    def _auto_finish_polygon():
        """If polygon vertices exist, finalize them onto the selected step."""
        verts = vertices_ref.current
        wf = workflow_ref.current
        if len(verts) >= 3 and 0 <= wf_editing_index < len(wf.steps):
            ring = [[lon, lat] for lon, lat in verts]
            ring.append(ring[0])
            geojson_geom = {'type': 'Polygon', 'coordinates': [ring]}
            wf.steps[wf_editing_index].tool.extent = geojson_geom
            wf.steps[wf_editing_index].tool.properties['extent'] = geojson_geom
            set_draw_mode(False)

    def _clean_previous_layers(steps):
        """Remove map layers produced by previous runs of the given steps."""
        prev_layer_ids = set()
        for step in steps:
            if step.output_layer_id:
                prev_layer_ids.add(step.output_layer_id)
        if prev_layer_ids:
            current = layers_ref.current
            cleaned = {k: v for k, v in current.items()
                       if k not in prev_layer_ids}
            layers_ref.current = cleaned
            set_active_layers(cleaned)
            for lid in prev_layer_ids:
                data_layers_ref.current.pop(lid, None)

    def handle_run_workflow(event):
        """Execute all steps in the current workflow."""
        wf = workflow_ref.current
        if wf_running:
            return
        if not wf.steps:
            set_error_msg('Add steps to the workflow first')
            return

        _auto_finish_polygon()
        _clean_previous_layers(wf.steps)

        run_step_ref.current = -1  # -1 = run all steps
        set_wf_running(True)
        set_wf_status('running')
        _sync_steps_to_ui()
        set_error_msg(None)
        set_status_msg(None)

    def handle_run_step(step_index):
        """Execute a single workflow step (e.g., load data to see it on map)."""
        wf = workflow_ref.current
        if wf_running:
            return
        if step_index < 0 or step_index >= len(wf.steps):
            return

        _auto_finish_polygon()
        # Only clean the layer from this specific step's previous run
        _clean_previous_layers([wf.steps[step_index]])

        run_step_ref.current = step_index
        set_wf_running(True)
        set_wf_status('running')
        _sync_steps_to_ui()
        set_error_msg(None)
        set_status_msg(None)

    @lib.hooks.use_effect(dependencies=[wf_running])
    def _run_workflow():
        if not wf_running:
            return
        wf = workflow_ref.current
        if wf is None or not wf.steps:
            set_wf_running(False)
            return

        engine = workflow_engine_ref.current
        target_step = run_step_ref.current  # -1 = all, >= 0 = single step

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

        try:
            existing = list(data_layers_ref.current.values())

            if target_step >= 0:
                # Single step execution
                engine.run_single_step(
                    wf, step_index=target_step,
                    existing_layers=existing,
                    on_step_complete=on_step_done,
                )
                step_name = wf.steps[target_step].tool_name
                set_status_msg(f'Step {target_step + 1} complete: {step_name}')
            else:
                # Full workflow execution
                engine.run(wf, existing_layers=existing,
                           on_step_complete=on_step_done)
                set_status_msg(f'Workflow complete: {wf.name}')

            _sync_steps_to_ui()
            set_wf_status('done' if target_step < 0 else 'idle')
            set_wf_running(False)
            logger.info('Execution complete')

        except Exception as e:
            logger.exception('Execution failed')
            _sync_steps_to_ui()
            set_wf_status('error')
            set_error_msg(f'Error: {e}')
            set_wf_running(False)

    def handle_clear_workflow(event):
        """Clear all steps, polygon, and start a fresh workflow."""
        workflow_ref.current = Workflow(name='Untitled Workflow')
        set_wf_steps([])
        set_wf_status('idle')
        set_wf_name('Untitled Workflow')
        set_wf_editing_index(-1)
        set_tool_props(None)
        set_tool_values({})
        # Clear polygon drawing state
        set_draw_mode(False)
        vertices_ref.current = []
        set_polygon_vertices([])

    def handle_load_workflow(workflow_id):
        """Load a saved workflow from the store."""
        store = workflow_store_ref.current
        wf = store.load(workflow_id)
        if wf is None:
            set_error_msg(f'Workflow not found: {workflow_id}')
            return
        workflow_ref.current = wf
        set_wf_name(wf.name)
        _sync_steps_to_ui()
        set_wf_status(wf.status)
        set_wf_editing_index(-1)
        set_tool_props(None)
        set_tool_values({})
        set_status_msg(f'Loaded: {wf.name}')
        logger.info('Loaded workflow: %s (%d steps)', wf.name, len(wf.steps))

    def handle_delete_workflow(workflow_id):
        """Delete a saved workflow from the store."""
        store = workflow_store_ref.current
        store.delete(workflow_id)
        set_saved_workflows(store.list_all())
        wf = workflow_ref.current
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

    # Determine if selected step has polygon property (for Draw Extent button)
    wf = workflow_ref.current
    selected_step_has_polygon = False
    if 0 <= wf_editing_index < len(wf.steps):
        step_tool = wf.steps[wf_editing_index].tool
        selected_step_has_polygon = any(
            p.get('type') == 'polygon' for p in step_tool.get_properties()
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
                                'Add steps to the workflow, '
                                'configure them, then click '
                                '"Run Workflow".'
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
                            on_run_step=handle_run_step,
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
                    on_coordinate_click=handle_coordinate_click,
                    is_running=wf_running,
                    selected_basemap=selected_basemap,
                ),
                # Draw Extent button — shown when selected step has polygon prop
                *(
                    [lib.html.div(
                        style=lib.Style(
                            position='absolute', bottom='40px', right='14px',
                            display='flex', flexDirection='column', gap='6px',
                            zIndex='1000',
                        ),
                    )(
                        *(
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
                        ),
                    )]
                    if selected_step_has_polygon else []
                ),
            ),

            # ── Right: Tool Properties Panel ──
            # Shows the selected workflow step's configuration.
            ToolPropertiesPanel(
                lib,
                tool_props=tool_props,
                tool_values=tool_values,
                on_property_change=handle_property_change,
                on_run_tool=handle_run_workflow,
                status_msg=status_msg,
                error_msg=error_msg,
                is_running=wf_running,
                panel_mode='workflow_step' if wf_editing_index >= 0 else 'tool',
                step_label=(
                    f"Step {wf_editing_index + 1} \u2014 "
                    f"{wf_steps[wf_editing_index].get('tool_name', '')}"
                    if 0 <= wf_editing_index < len(wf_steps) else None
                ),
            ),
    )
