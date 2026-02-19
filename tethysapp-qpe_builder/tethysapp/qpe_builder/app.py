"""
QPE Builder -- Tethys Application
=================================
Interactive OpenLayers map for visualizing CONUS (Continental United States)
precipitation data.  Currently supports two data layers:

    * **MRMS Radar QPE** -- Multi-Radar Multi-Sensor reflectivity overlay
      served as a pre-rendered PNG image (ImageStatic).
    * **Gauges (MADIS)** -- Meteorological Assimilation Data Ingest System
      gauge stations served as GeoJSON point features (Vector).

Architecture
------------
* Built on **Tethys Platform 4.x** using the ``ComponentBase`` pattern,
  which replaces traditional Django views with ReactPy server-side
  components.
* The entire UI is rendered via **ReactPy-Django** -- there are no HTML
  templates, no JavaScript files, and no REST endpoints.
* Map layers use ``lib.ol.*`` wrappers around OpenLayers.

Sidebar UI
----------
The sidebar uses an **accordion layout** with collapsible sections:

* **Base Map** section -- a ``<select>`` dropdown to switch between tile
  providers (OSM, Carto Dark, ESRI Satellite, ESRI Topo).
* **Data Layers** section -- each layer from ``LAYER_CATALOG`` gets a row
  with pill-button controls:
    - ``Add``   -- adds the layer to the map (appears in ``active_layers``).
    - ``Remove`` -- removes the layer from the map entirely.
    - ``Hide``  -- keeps the layer in the list but hides it on the map.
    - ``Show``  -- makes a hidden layer visible again.

VDOM Reconciliation Notes (important for contributors)
------------------------------------------------------
OpenLayers components rendered through Tethys ``lib.ol.*`` wrappers do
**not** respond to VDOM prop patches -- only CREATE and DESTROY operations
work.  To ensure correct behavior:

1. All basemap tiles live in a Group with ``visible`` flags, matching
   Tethys's built-in ``BaseMapSuite`` pattern (``custom.py``).
2. Each data layer gets a unique VDOM ``key`` (e.g. ``data-radar``) so
   ReactPy matches children by key instead of array index.
3. The map wrapper div is keyed by the selected basemap so the entire
   OL Map is recreated on switch.  OL does not handle any form of
   child-level VDOM swap inside a live Map — full remount is required.
4. Overlay layers are iterated in ``LAYER_CATALOG`` order (not dict
   insertion order) to guarantee stable child positions.

Key modules
-----------
* ``tethys_sdk.components.ComponentBase`` -- base class that registers the
  app with Tethys and enables the ``@App.page`` ReactPy decorator.
* ``geopandas`` -- reads the GeoJSON gauge file into a DataFrame, then
  serializes it to a JSON string for the OpenLayers Vector source.
"""

from tethys_sdk.components import ComponentBase  # Tethys 4.x reactive component base
import geopandas as gpd                          # Spatial data I/O for gauge GeoJSON


# =============================================================================
# App Registration
# =============================================================================
# ``ComponentBase`` tells Tethys this app uses ReactPy pages (decorated with
# ``@App.page``) instead of traditional Django view functions.  The ``color``
# field sets the Tethys app-card accent and should match ``COLORS["primary"]``.

class App(ComponentBase):
    """Tethys app class for QPE Builder."""

    name = "Quantitative Precipitation Estimate Builder"
    description = (
        "Develop, run, and save custom workflows for generating regional "
        "Quantitative Precipitation Estimates (QPE)"
    )
    package = "qpe_builder"  # WARNING: Do not change this value
    index = "qpe_home"
    icon = f"{package}/images/CIROHLogo_200x200.png"
    root_url = "qpe-builder"
    color = "#1A5276"        # Deep hydro-blue -- matches COLORS["primary"]
    tags = "Meteorology", "Precipitation Estimate", "Forecasts", "Workflows"
    enable_feedback = False
    feedback_emails = []
    exit_url = "/apps/"
    default_layout = "NavHeader"
    nav_links = "auto"


# =============================================================================
# Design Tokens
# =============================================================================
# Centralized color palette and spacing constants.  Every UI element
# references these tokens so a single change here propagates everywhere.
#
# The ``primary`` color is a deep hydro-blue chosen to evoke
# precipitation / weather radar imagery while maintaining readability
# against light backgrounds.

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

# Fixed sidebar width -- keeps the layer-manager panel compact while
# leaving the majority of horizontal space for the map.
SIDEBAR_WIDTH = "280px"


# =============================================================================
# Basemap Options
# =============================================================================
# Each dict defines a tile provider the user can select in the sidebar.
#
#   key   -- unique identifier stored in ``selected_basemap`` state
#   label -- human-readable name shown in the ``<select>`` dropdown
#   url   -- XYZ tile URL template; ``None`` uses the built-in OSM source

BASEMAP_OPTIONS = [
    {"key": "osm",          "label": "Street (OSM)",       "url": None},
    {"key": "carto_dark",   "label": "Dark (Carto)",       "url": "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png"},
    {"key": "esri_imagery", "label": "Satellite (ESRI)",   "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"},
    {"key": "esri_topo",    "label": "Topographic (ESRI)", "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}"},
]


# =============================================================================
# Data Layer Catalog
# =============================================================================
# Static metadata for every data layer the app can display.  The sidebar
# accordion iterates over this list (in order) to render layer rows.
# Adding a new layer here automatically gives it a sidebar entry; you
# must also add a corresponding branch in ``build_data_layer()`` below.
#
#   key         -- identifier stored in ``active_layers`` state dict
#   name        -- display label shown in the sidebar row
#   description -- short subtitle shown below the name
#   color       -- accent color for the status dot and left-border stripe

LAYER_CATALOG = [
    {
        "key": "radar",
        "name": "MRMS Radar QPE",
        "description": "Radar reflectivity overlay",
        "color": "#1565C0",       # material blue -- radar theme
    },
    {
        "key": "gauges",
        "name": "Gauges (MADIS)",
        "description": "Precipitation gauge stations",
        "color": "#2E7D32",       # material green -- gauge theme
    },
]


# =============================================================================
# Layer Builders
# =============================================================================
# Pure functions that translate state into OpenLayers VDOM nodes.  They are
# called on every render cycle and must remain side-effect-free.

def build_basemap_group(selected_key, lib):
    """
    Return an OL layer Group containing ALL basemap tiles.

    This mirrors the pattern used by Tethys's built-in ``BaseMapSuite``
    (see ``tethys_components/custom.py``).  Every tile in BASEMAP_OPTIONS
    is created inside the Group, but only the selected one has
    ``visible=True``.  OL respects ``visible`` at creation time (CREATE)
    even though it ignores later VDOM prop patches (UPDATE).

    The returned Group is keyed by ``selected_key`` so that switching
    basemaps forces ReactPy to destroy the old Group and create a fresh
    one with the correct ``visible`` flags.

    Parameters
    ----------
    selected_key : str
        One of the ``key`` values from ``BASEMAP_OPTIONS``.
    lib : object
        Tethys component library namespace (injected by ``@App.page``).
    """
    tiles = []
    for opt in BASEMAP_OPTIONS:
        url = opt["url"]

        # OSM has its own dedicated source class; every other provider
        # uses the generic XYZ tile source with a URL template.
        source = (
            lib.ol.source.OSM()
            if url is None
            else lib.ol.source.XYZ(options=lib.Props(url=url))
        )

        tile = lib.ol.layer.Tile(
            options=lib.Props(
                title=opt["label"],
                type="base",
                visible=(opt["key"] == selected_key),
            ),
        )(source)
        tiles.append(tile)

    group = lib.ol.layer.Group(
        options=lib.Props(title="Basemap", fold="close"),
    )(*tiles)

    # Key forces full Group remount on switch -- all tiles are freshly
    # created with the correct ``visible`` flag.
    group["key"] = f"basemap-group-{selected_key}"
    return group


def build_data_layer(key, lib, geojson=None):
    """
    Return an OpenLayers overlay node for the given catalog key.

    Parameters
    ----------
    key : str
        Layer identifier (must match a ``LAYER_CATALOG`` entry).
    lib : object
        Tethys component library namespace.
    geojson : str or None
        Serialized GeoJSON string; required when ``key == "gauges"``.

    Returns
    -------
    dict or None
        A VDOM dict representing the OL layer, or ``None`` for unknown
        keys so callers can safely skip.
    """
    if key == "radar":
        # MRMS radar is a pre-rendered PNG covering the CONUS extent.
        # The imageExtent coordinates are in EPSG:3857 (Web Mercator).
        return lib.ol.layer.Image(
            options=lib.Props(title="MRMS Radar QPE"),
        )(
            lib.ol.source.ImageStatic(
                options=lib.Props(
                    url="/static/qpe_builder/data/radar_overlay.png",
                    imageExtent=[
                        -14470977.205671597, 2273623.3735015886,
                        -6679726.267689361,  7360895.77546744,
                    ],
                )
            )
        )

    elif key == "gauges":
        # MADIS gauge stations loaded from a local GeoJSON file.
        return lib.ol.layer.Vector(
            options=lib.Props(title="Gauges (MADIS)"),
        )(
            lib.ol.source.Vector(
                options=lib.Props(features=geojson, format="GeoJSON"),
            )
        )

    return None


# =============================================================================
# Page Component
# =============================================================================
# ``@App.page`` registers this function as a ReactPy page endpoint.
# Tethys injects ``lib`` -- a namespace providing access to:
#
#   lib.html.*           -- HTML element wrappers (div, span, button, ...)
#   lib.hooks.*          -- React-style hooks (use_state, use_memo, ...)
#   lib.ol.*             -- OpenLayers component wrappers
#   lib.tethys.*         -- Tethys-specific components (Map, Display, ...)
#   lib.Props / lib.Style -- helper constructors for component props & CSS

@App.page
def qpe_home(lib):
    """Main page component -- renders the sidebar + map layout."""

    resources = lib.hooks.use_resources()

    # =========================================================================
    # State
    # =========================================================================
    #
    # selected_basemap (str)
    #     Key of the active basemap from BASEMAP_OPTIONS.  Changing it
    #     re-keys the map wrapper, forcing a full OL Map remount with
    #     the new basemap Group (all tiles freshly created).
    #
    # active_layers (dict)
    #     Tracks which data layers are added and whether they are visible.
    #     Shape: { "radar": {"visible": True}, "gauges": {"visible": True} }
    #     - Key present  --> layer is "added" (shown in sidebar with
    #       Hide/Remove buttons).
    #     - Key absent   --> layer is "removed" (shown with an Add button).
    #     - visible=True --> layer is rendered on the map.
    #     - visible=False--> layer stays in the list but is hidden on the map.
    #     All updaters use the functional form (lambda prev: ...) to avoid
    #     stale-closure bugs.
    #
    # basemap_open / layers_open (bool)
    #     Whether each accordion section in the sidebar is expanded.

    selected_basemap, set_selected_basemap = lib.hooks.use_state("osm")

    active_layers, set_active_layers = lib.hooks.use_state(
        {"radar": {"visible": True}, "gauges": {"visible": True}}
    )

    basemap_open, set_basemap_open = lib.hooks.use_state(True)
    layers_open, set_layers_open   = lib.hooks.use_state(True)

    # =========================================================================
    # Data Loading
    # =========================================================================
    # ``use_memo`` ensures the GeoJSON file is read only once (on first
    # render).  GeoPandas reads it into a GeoDataFrame; ``.to_json()``
    # serializes it to a GeoJSON string that OpenLayers can parse natively.

    geojson_path = (
        resources.path.parent / "public" / "data" / "precip_gauges.geojson"
    )
    geojson = lib.hooks.use_memo(lambda: gpd.read_file(geojson_path).to_json())

    # =========================================================================
    # Build OL Layers from State
    # =========================================================================
    # IMPORTANT: We iterate over LAYER_CATALOG (not active_layers.items())
    # so that child order in the OL Group is always stable.  Dict insertion
    # order can shift after remove-then-add, which would cause ReactPy to
    # match children by the wrong array index and issue PATCH ops that OL
    # silently ignores.
    #
    # Each layer also gets a unique VDOM ``key`` injected (same pattern as
    # basemap tiles) so ReactPy's reconciler can match by key instead of
    # position.

    basemap_group = build_basemap_group(selected_basemap, lib)

    overlay_layers = []
    for entry in LAYER_CATALOG:
        lkey = entry["key"]
        info = active_layers.get(lkey)
        if info and info.get("visible", False):
            layer = build_data_layer(
                lkey, lib, geojson=geojson if lkey == "gauges" else None,
            )
            if layer:
                layer["key"] = f"data-{lkey}"   # force key-based reconciliation
                overlay_layers.append(layer)

    # =========================================================================
    # Event Handlers
    # =========================================================================
    # Factory functions (make_*) return closures that capture the layer key
    # by parameter -- avoiding the common Python loop-variable gotcha where
    # every closure would share the last value of the loop variable.

    def handle_basemap_change(event):
        """Native ``<select>`` onChange -- update the selected basemap."""
        set_selected_basemap(event["target"]["value"])

    def make_add_handler(key):
        """Return a click handler that adds ``key`` to active_layers."""
        def handler(event):
            set_active_layers(lambda prev: {**prev, key: {"visible": True}})
        return handler

    def make_remove_handler(key):
        """Return a click handler that removes ``key`` from active_layers."""
        def handler(event):
            set_active_layers(
                lambda prev: {k: v for k, v in prev.items() if k != key}
            )
        return handler

    def make_toggle_visibility_handler(key):
        """Return a click handler that toggles the ``visible`` flag for ``key``."""
        def handler(event):
            set_active_layers(
                lambda prev: {
                    k: ({**v, "visible": not v["visible"]} if k == key else v)
                    for k, v in prev.items()
                }
            )
        return handler

    # =========================================================================
    # UI Helpers
    # =========================================================================

    # ---- Accordion Section Header -------------------------------------------
    # Renders a clickable row: [chevron + TITLE]  [optional badge]
    # Clicking anywhere on the row toggles the section open/closed.

    def accordion_section(title, is_open, on_toggle, badge_text=None):
        """
        Build a collapsible section header for the sidebar.

        Parameters
        ----------
        title : str
            Section label (rendered uppercase).
        is_open : bool
            Current expanded state -- determines chevron direction.
        on_toggle : callable
            Click handler to flip the open/closed state.
        badge_text : str or None
            Optional badge shown on the right (e.g. "2 active").
        """
        chevron = "\u25BC" if is_open else "\u25B6"   # ▼ or ▶

        # Left side: chevron + title
        left = lib.html.div(
            style=lib.Style(display="flex", alignItems="center"),
        )(
            lib.html.span(
                style=lib.Style(
                    fontSize="10px",
                    color=COLORS["text_muted"],
                    marginRight="8px",
                    display="inline-block",
                    width="10px",
                ),
            )(chevron),
            lib.html.span(
                style=lib.Style(
                    fontWeight="700",
                    textTransform="uppercase",
                    letterSpacing="1.2px",
                    fontSize="10px",
                    color=COLORS["text_section"],
                ),
            )(title),
        )

        # Right side: optional count badge
        right_children = []
        if badge_text is not None:
            right_children.append(
                lib.html.span(
                    style=lib.Style(
                        backgroundColor=COLORS["primary"],
                        color=COLORS["white"],
                        borderRadius="10px",
                        padding="2px 10px",
                        fontSize="10px",
                        fontWeight="700",
                        lineHeight="1.4",
                    ),
                )(badge_text),
            )

        return lib.html.div(
            style=lib.Style(
                display="flex",
                justifyContent="space-between",
                alignItems="center",
                marginBottom="6px",
                paddingBottom="8px",
                borderBottom=f"2px solid {COLORS['primary']}",
                cursor="pointer",
                userSelect="none",
            ),
            onClick=on_toggle,
        )(left, *right_children)

    # ---- Pill Button --------------------------------------------------------
    # Small rounded button used for Add / Remove / Hide / Show actions.
    # ``filled=True`` renders a solid background (used for primary actions
    # like Add and Show) so they stand out from secondary actions.

    def pill_button(label, on_click, color=COLORS["text_muted"], filled=False):
        """
        Render a small pill-shaped action button.

        Parameters
        ----------
        label : str
            Button text ("Add", "Remove", "Hide", or "Show").
        on_click : callable
            Click handler.
        color : str
            Border (and text or fill) color.
        filled : bool
            If True, the button has a solid background with white text.
        """
        return lib.html.button(
            style=lib.Style(
                border=f"1px solid {color}",
                borderRadius="12px",
                padding="2px 10px",
                fontSize="10px",
                fontWeight="600",
                color=COLORS["white"] if filled else color,
                backgroundColor=color if filled else "transparent",
                cursor="pointer",
                marginLeft="4px",
                lineHeight="1.6",
            ),
            onClick=on_click,
        )(label)

    # =========================================================================
    # Sidebar: Base Map Section
    # =========================================================================
    # A collapsible accordion section containing a native ``<select>``
    # dropdown.  Selecting an option updates ``selected_basemap``, which
    # re-keys the map wrapper and forces a full OL Map remount with the
    # correct basemap tiles.

    def toggle_basemap_open(event):
        set_basemap_open(lambda prev: not prev)

    basemap_header = accordion_section(
        "Base Map", basemap_open, toggle_basemap_open,
    )

    basemap_content = []
    if basemap_open:
        basemap_content.append(
            lib.html.select(
                style=lib.Style(
                    width="100%",
                    padding="8px 12px",
                    fontSize="13px",
                    fontWeight="600",
                    border=f"1.5px solid {COLORS['border_light']}",
                    borderRadius="8px",
                    backgroundColor=COLORS["white"],
                    color=COLORS["text_dark"],
                    cursor="pointer",
                    marginBottom="16px",
                    outline="none",
                ),
                value=selected_basemap,
                onChange=handle_basemap_change,
            )(
                *[
                    lib.html.option(value=opt["key"])(opt["label"])
                    for opt in BASEMAP_OPTIONS
                ],
            )
        )

    # =========================================================================
    # Sidebar: Data Layers Section
    # =========================================================================
    # A collapsible accordion section that lists every entry in
    # LAYER_CATALOG.  Each row shows:
    #   - A colored status dot (catalog color when visible, grey otherwise)
    #   - Layer name + description
    #   - Pill buttons for the available actions
    #
    # The badge on the header shows how many layers are currently visible
    # on the map (not just added).

    visible_count = sum(
        1 for v in active_layers.values() if v.get("visible", False)
    )

    def toggle_layers_open(event):
        set_layers_open(lambda prev: not prev)

    layers_header = accordion_section(
        "Data Layers", layers_open, toggle_layers_open,
        badge_text=f"{visible_count} active",
    )

    # -- Build one row per catalog entry --------------------------------------
    layer_rows = []
    if layers_open:
        for entry in LAYER_CATALOG:
            key = entry["key"]
            is_added   = key in active_layers
            is_visible = is_added and active_layers[key].get("visible", False)

            # Status dot -- uses the layer's own catalog color when visible,
            # grey when hidden or removed.  A subtle glow (box-shadow)
            # reinforces the "active" state visually.
            dot_color = entry["color"] if is_visible else COLORS["dot_off"]
            dot = lib.html.span(
                style=lib.Style(
                    display="inline-block",
                    width="9px",
                    height="9px",
                    borderRadius="50%",
                    backgroundColor=dot_color,
                    marginRight="10px",
                    flexShrink="0",
                    boxShadow=f"0 0 4px {dot_color}" if is_visible else "none",
                ),
            )()

            # Layer name (bold when visible) + description subtitle
            name_el = lib.html.div(
                style=lib.Style(flex="1", minWidth="0"),
            )(
                lib.html.div(
                    style=lib.Style(
                        fontSize="12.5px",
                        fontWeight="600" if is_visible else "500",
                        color=COLORS["text_dark"] if is_added else COLORS["text_muted"],
                        lineHeight="1.3",
                    ),
                )(entry["name"]),
                lib.html.div(
                    style=lib.Style(
                        fontSize="10px",
                        color=COLORS["text_muted"],
                        lineHeight="1.3",
                    ),
                )(entry["description"]),
            )

            # Pill-button controls
            # - Added + visible  --> [Hide] [Remove]
            # - Added + hidden   --> [Show (filled)] [Remove]
            # - Not added        --> [Add (filled)]
            buttons = []
            if is_added:
                if is_visible:
                    buttons.append(pill_button(
                        "Hide",
                        make_toggle_visibility_handler(key),
                        COLORS["text_muted"],
                    ))
                else:
                    buttons.append(pill_button(
                        "Show",
                        make_toggle_visibility_handler(key),
                        COLORS["success_dot"],
                        filled=True,
                    ))
                buttons.append(pill_button(
                    "Remove",
                    make_remove_handler(key),
                    "#dc2626",          # red accent for destructive action
                ))
            else:
                buttons.append(pill_button(
                    "Add",
                    make_add_handler(key),
                    COLORS["primary"],
                    filled=True,
                ))

            # Assemble the row.
            # - Tinted background when the layer is visible on the map.
            # - Colored left border stripe when the layer is added.
            row_bg = COLORS["primary_light"] if is_visible else "transparent"
            row = lib.html.div(
                style=lib.Style(
                    display="flex",
                    alignItems="center",
                    padding="8px 6px",
                    marginBottom="4px",
                    borderRadius="6px",
                    backgroundColor=row_bg,
                    borderLeft=(
                        f"3px solid {entry['color']}" if is_added
                        else "3px solid transparent"
                    ),
                ),
            )(dot, name_el, *buttons)

            layer_rows.append(row)

    # =========================================================================
    # Sidebar Assembly
    # =========================================================================

    sidebar_title = lib.html.div(
        style=lib.Style(
            fontSize="15px",
            fontWeight="700",
            color=COLORS["text_dark"],
            marginBottom="20px",
            paddingBottom="10px",
            borderBottom=f"1px solid {COLORS['border_light']}",
            letterSpacing="0.3px",
        ),
    )("QPE Layers")

    # Visual separator between the two accordion sections
    section_spacer = lib.html.div(style=lib.Style(height="16px"))()

    sidebar = lib.html.div(
        style=lib.Style(
            width=SIDEBAR_WIDTH,
            minWidth=SIDEBAR_WIDTH,
            backgroundColor=COLORS["sidebar_bg"],
            borderRight=f"1px solid {COLORS['sidebar_border']}",
            overflowY="auto",
            padding="18px 16px",
            boxSizing="border-box",
        ),
    )(
        sidebar_title,
        basemap_header,
        *basemap_content,
        section_spacer,
        layers_header,
        *layer_rows,
    )

    # =========================================================================
    # OpenLayers Map
    # =========================================================================
    # Map children define the projection, view center, tile layers,
    # controls, and data overlays.
    #
    #   - View       : EPSG:3857 (Web Mercator), centered on CONUS
    #   - basemap    : Group of all basemap tiles (see build_basemap_group)
    #   - ScaleLine  : distance-scale control in the bottom-left corner
    #   - Overlays   : visible data layers wrapped in an OL Group

    map_children = [
        lib.ol.View(
            options=lib.Props(projection="EPSG:3857"),
            center=[-10997148, 4569099],     # approximate center of CONUS
            zoom=4,
        ),
        basemap_group,
        lib.ol.control.ScaleLine(),
    ]

    # Only add the overlay Group when there are visible layers; otherwise
    # the empty Group node is unnecessary.
    if overlay_layers:
        map_children.append(
            lib.ol.layer.Group(
                options=lib.Props(title="Overlays", fold="open"),
            )(*overlay_layers)
        )

    the_map = lib.ol.Map()(*map_children)

    # =========================================================================
    # Layout: Sidebar + Map
    # =========================================================================
    # The map wrapper is keyed by the selected basemap so that switching
    # basemaps destroys and recreates the entire OL Map.  This is the
    # only reliable approach — OL does not handle child-level VDOM swaps
    # (neither individual tiles nor keyed Groups) inside a live Map.

    map_wrapper = lib.html.div(
        style=lib.Style(flex="1", height="100%"),
    )(lib.tethys.Display(the_map))
    map_wrapper["key"] = f"map-{selected_basemap}"

    return lib.html.div(
        style=lib.Style(display="flex", height="100%", width="100%"),
    )(
        sidebar,
        map_wrapper,
    )
