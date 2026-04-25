"""ToolPropertiesPanel — right-side panel for tool configuration and execution.

Architecture (agreed with team 2026-04-20):
  - ZERO hooks inside this component. All state lives in app.py.
  - Receives tool_props (list of property dicts from get_properties()),
    tool_values (dict of current values from use_state in app.py),
    on_property_change callback, and on_run_tool callback.
  - Renders controls for each property type: 'list', 'str', 'datetime'.
  - "Run Tool" button calls on_run_tool which is handled in app.py.

This builds on Pat's original ToolPropertiesPanel structure and styling.
Key changes from Pat's version:
  - Removed use_state hooks (broke ReactPy due to inconsistent hook count).
  - State lifted to app.py; panel is now a pure render function.
  - Added 'str' and 'datetime' property type implementations.
  - Added "Run Tool" button at bottom of panel.
  - Property values come from tool_values dict, changes go through callback.
"""


def ToolPropertiesPanel(lib, tool_props, tool_values, on_property_change,
                        on_run_tool, on_start_drawing=None,
                        on_finish_polygon=None, on_clear_polygon=None,
                        draw_mode=False):
    """Render the tool properties panel.

    Args:
        lib: Tethys component library.
        tool_props: List of property dicts from Tool.get_properties().
                    Each has: name, type, label, and optionally options.
                    None if no tool is selected.
        tool_values: Dict of {prop_name: current_value} from use_state
                     in app.py. Drives the displayed values.
        on_property_change: Callback(prop_name, new_value) to update
                           tool_values in app.py (triggers re-render).
        on_run_tool: Callback(event) to execute the tool from app.py.
        on_start_drawing: Callback to start polygon drawing mode.
        on_finish_polygon: Callback to finish/close the polygon.
        on_clear_polygon: Callback to clear polygon vertices.
        draw_mode: Whether polygon drawing is currently active.

    Returns:
        VDOM element for the right-side panel.
    """

    # ── Panel container (matches Pat's original styling) ──
    panel_style = lib.Style(
        width='280px', minWidth='280px', flexShrink='0',
        background='#f5f7fa',
        borderLeft='1px solid #e0e4ea',
        overflowY='auto',
        padding='14px 16px',
        boxSizing='border-box',
    )

    # No tool selected — show empty panel with hint
    if not tool_props:
        return lib.html.div(style=panel_style)(
            lib.html.div(
                style=lib.Style(
                    fontSize='12px', color='#98a2b3',
                    padding='12px 0', textAlign='center',
                    lineHeight='1.6',
                ),
            )('Click "Load Data" to configure a tool.'),
        )

    # ── Build a control for each property ──
    controls = []

    for prop in tool_props:
        prop_name = prop['name']
        prop_type = prop['type']
        prop_label = prop['label']
        current_value = tool_values.get(prop_name, '')

        # Factory: create a change handler bound to this property's name.
        # Using default arg (bound_name=prop_name) to capture the current
        # value in the closure — same pattern Pat used with cur_prop.
        def make_change_handler(bound_name=prop_name):
            def handler(event):
                on_property_change(bound_name, event['target']['value'])
            return handler

        # ── Shared styles (from Pat's original) ──
        label_style = lib.Style(
            fontSize='11px', color='#667085', fontWeight='600',
        )
        input_style = lib.Style(
            width='100%', padding='7px 10px',
            fontSize='13px', fontWeight='600',
            border='1.5px solid #d0d5dd', borderRadius='8px',
            backgroundColor='#fff', color='#333',
            outline='none', boxSizing='border-box',
        )
        control_wrapper_style = lib.Style(
            display='flex', flexDirection='column', gap='4px',
            marginBottom='12px', paddingLeft='20px',
        )

        # ── Render by property type ──
        if prop_type == 'list':
            # Dropdown select — Pat's original implementation, now with
            # value driven by tool_values and changes via callback.
            options = prop.get('options', [])
            control = lib.html.select(
                style=lib.Style(
                    width='100%', padding='7px 10px',
                    fontSize='13px', fontWeight='600',
                    border='1.5px solid #d0d5dd', borderRadius='8px',
                    backgroundColor='#fff', color='#333',
                    cursor='pointer', outline='none',
                ),
                value=current_value,
                onChange=make_change_handler(),
            )(
                lib.html.option(value='')(f'Select {prop_label}...'),
                *[
                    lib.html.option(value=opt)(opt)
                    for opt in options
                ],
            )

        elif prop_type == 'str':
            # Text input — was "Not yet implemented" in Pat's version.
            control = lib.html.input(
                type='text',
                value=current_value,
                onChange=make_change_handler(),
                placeholder=f'Enter {prop_label.lower()}...',
                style=input_style,
            )

        elif prop_type == 'datetime':
            # Datetime picker — was "Not yet implemented" in Pat's version.
            control = lib.html.input(
                type='datetime-local',
                value=current_value,
                onChange=make_change_handler(),
                style=input_style,
            )

        elif prop_type == 'polygon':
            # Polygon drawing — Start/Finish/Clear buttons + vertex count.
            # The actual polygon data is stored as GeoJSON in tool_values.
            vertex_count = 0
            if current_value and isinstance(current_value, dict):
                coords = current_value.get('coordinates', [[]])
                vertex_count = max(0, len(coords[0]) - 1)  # -1 for closing vertex

            if draw_mode:
                # Drawing active — show Finish and Clear buttons
                control = lib.html.div(
                    style=lib.Style(display='flex', gap='6px'),
                )(
                    lib.html.button(
                        style=lib.Style(
                            background='#2e7d32', color='#fff',
                            border='none', borderRadius='6px',
                            padding='6px 12px', fontSize='12px',
                            fontWeight='600', cursor='pointer',
                        ),
                        onClick=on_finish_polygon,
                    )('Finish'),
                    lib.html.button(
                        style=lib.Style(
                            background='#c62828', color='#fff',
                            border='none', borderRadius='6px',
                            padding='6px 12px', fontSize='12px',
                            fontWeight='600', cursor='pointer',
                        ),
                        onClick=on_clear_polygon,
                    )('Clear'),
                )
            else:
                # Not drawing — show Start button (or vertex summary)
                start_label = 'Draw Polygon' if vertex_count == 0 else f'Redraw ({vertex_count} vertices)'
                control = lib.html.div(
                    style=lib.Style(display='flex', flexDirection='column', gap='4px'),
                )(
                    lib.html.button(
                        style=lib.Style(
                            background='#e53935', color='#fff',
                            border='none', borderRadius='6px',
                            padding='6px 12px', fontSize='12px',
                            fontWeight='600', cursor='pointer',
                        ),
                        onClick=on_start_drawing,
                    )(start_label),
                    *(
                        [lib.html.span(
                            style=lib.Style(
                                fontSize='10px', color='#2e7d32',
                                fontWeight='600',
                            ),
                        )(f'Polygon set ({vertex_count} vertices)')]
                        if vertex_count > 0 else []
                    ),
                )

        else:
            # Fallback for unknown property types
            control = lib.html.span(
                style=lib.Style(fontSize='12px', color='#d32f2f'),
            )(f'Unknown type: {prop_type}')

        controls.append(
            lib.html.div(style=control_wrapper_style)(
                lib.html.label(style=label_style)(prop_label),
                control,
            )
        )

    # ── "Run Tool" button at bottom of panel ──
    # Team agreed: button lives in panel, calls on_run_tool callback
    # which is handled by app.py (sets props on tool_ref, runs, adds layer).
    run_button = lib.html.div(
        style=lib.Style(paddingLeft='20px', marginTop='8px'),
    )(
        lib.html.button(
            style=lib.Style(
                background='#1565C0', color='#fff',
                border='none', borderRadius='8px',
                padding='9px 0', fontSize='13px', fontWeight='700',
                cursor='pointer', letterSpacing='0.02em', width='100%',
            ),
            onClick=on_run_tool,
        )('Run Tool'),
    )

    # ── Assemble panel ──
    return lib.html.div(style=panel_style)(
        # Panel header
        lib.html.div(
            style=lib.Style(
                fontSize='11px', fontWeight='700',
                letterSpacing='0.06em', color='#667085',
                textTransform='uppercase', padding='8px 0',
            ),
        )('Tool Properties'),

        # Divider
        lib.html.div(
            style=lib.Style(
                height='1px', background='#e0e4ea', margin='0 0 12px 0',
            ),
        )(),

        # Property controls
        *controls,

        # Run button
        run_button,
    )
