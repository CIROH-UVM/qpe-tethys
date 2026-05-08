"""ToolPropertiesPanel — right-side panel for tool configuration and execution.

A stateless component that renders UI controls for tool properties and
delegates all state management to the parent (app.py) via callbacks.
Supports property types: 'list', 'str', 'datetime', 'polygon'.
"""


def ToolPropertiesPanel(lib, tool_props, tool_values, on_property_change,
                        on_run_tool, status_msg=None, error_msg=None,
                        is_running=False):
    """Render the tool properties panel.

    Args:
        lib: Tethys component library.
        tool_props: List of property dicts from Tool.get_properties().
                    None if no tool is selected.
        tool_values: Dict of {prop_name: current_value}.
        on_property_change: Callback(prop_name, new_value).
        on_run_tool: Callback(event) to execute the tool.
        status_msg: Success message string (or None).
        error_msg: Error message string (or None).
        is_running: True while tool is executing.
    """

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
            )('Click a tool button on the map to get started.'),
        )

    # ── Build a control for each property ──
    controls = []

    for prop in tool_props:
        prop_name = prop['name']
        prop_type = prop['type']
        prop_label = prop['label']
        current_value = tool_values.get(prop_name, '')

        def make_change_handler(bound_name=prop_name):
            def handler(event):
                on_property_change(bound_name, event['target']['value'])
            return handler

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

        if prop_type == 'list':
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
            control = lib.html.input(
                type='text',
                value=current_value,
                onChange=make_change_handler(),
                placeholder=f'Enter {prop_label.lower()}...',
                style=input_style,
            )

        elif prop_type == 'datetime':
            control = lib.html.input(
                type='datetime-local',
                value=current_value,
                onChange=make_change_handler(),
                style=input_style,
            )

        elif prop_type == 'polygon':
            # Polygon type is handled by the map's Draw Extent button.
            # Show a hint label in the panel.
            control = lib.html.div(
                style=lib.Style(
                    fontSize='12px', color='#546e7a',
                    fontStyle='italic', padding='6px 0',
                ),
            )('Use "Draw Extent" button on the map to define area.')

        else:
            control = lib.html.span(
                style=lib.Style(fontSize='12px', color='#d32f2f'),
            )(f'Unknown type: {prop_type}')

        controls.append(
            lib.html.div(style=control_wrapper_style)(
                lib.html.label(style=label_style)(prop_label),
                control,
            )
        )

    # ── "Run Tool" button ──
    btn_label = 'Running... Please wait' if is_running else 'Run Tool'
    btn_bg = '#78909c' if is_running else '#1565C0'
    run_button = lib.html.div(
        style=lib.Style(paddingLeft='20px', marginTop='8px'),
    )(
        lib.html.button(
            style=lib.Style(
                background=btn_bg, color='#fff',
                border='none', borderRadius='8px',
                padding='9px 0', fontSize='13px', fontWeight='700',
                cursor='pointer' if not is_running else 'not-allowed',
                letterSpacing='0.02em', width='100%',
                opacity='0.7' if is_running else '1',
            ),
            onClick=on_run_tool,
        )(btn_label),
    )

    # ── Feedback (success / error / loading) ──
    feedback_items = []

    if is_running:
        feedback_items.append(
            lib.html.div(
                style=lib.Style(
                    marginTop='10px', padding='10px 12px',
                    background='#e3f2fd', borderRadius='8px',
                    border='1px solid #90caf9',
                    textAlign='center',
                ),
            )(
                lib.html.div(
                    style=lib.Style(
                        fontSize='13px', fontWeight='700',
                        color='#1565C0',
                    ),
                )('Downloading data from NOAA, this may take a moment...'),
            ),
        )

    if status_msg and not is_running:
        feedback_items.append(
            lib.html.div(
                style=lib.Style(
                    marginTop='10px', padding='10px 12px',
                    background='#e8f5e9', borderRadius='8px',
                    border='1px solid #a5d6a7',
                    textAlign='center',
                ),
            )(
                lib.html.div(
                    style=lib.Style(
                        fontSize='13px', fontWeight='700',
                        color='#2e7d32',
                    ),
                )(status_msg),
            ),
        )

    if error_msg and not is_running:
        feedback_items.append(
            lib.html.div(
                style=lib.Style(
                    marginTop='10px', padding='10px 12px',
                    background='#fce4ec', borderRadius='8px',
                    border='1px solid #ef9a9a',
                    textAlign='center',
                ),
            )(
                lib.html.div(
                    style=lib.Style(
                        fontSize='13px', fontWeight='700',
                        color='#c62828',
                    ),
                )(f'Error: {error_msg}'),
            ),
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

        # Feedback (success/error) — appears after tool completes
        *feedback_items,
    )
