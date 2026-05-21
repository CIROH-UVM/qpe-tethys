"""WorkflowPanel — sidebar builder for creating and managing workflow steps.

User clicks a step → the right-side ToolPropertiesPanel shows that step's
configuration. This panel only handles step list, reorder, add, and actions.

User experience:
  1. Name the workflow
  2. Click "+ Add Step" to pick a tool
  3. Click a step card → right panel shows its properties for editing
  4. Reorder or remove steps with arrows and X
  5. Click "Run Workflow" to execute all steps in sequence
  6. Save / Load / Clear workflows
"""


def _step_detail_text(step):
    """Build a short summary string from step properties."""
    props = step.get('properties', {})
    parts = []
    if props.get('dataset_id'):
        parts.append(props['dataset_id'].replace('_', ' '))
    if props.get('operation'):
        val = props.get('value', '')
        parts.append(f"{props['operation']}({val})")
    if props.get('region'):
        parts.append(props['region'].replace('-', ' ').title())
    return ' \u2022 '.join(parts)


def _status_icon(status):
    """Return (icon, color) for a step status."""
    return {
        'done':    ('\u2705', '#2e7d32'),
        'running': ('\u23F3', '#1565C0'),
        'error':   ('\u274C', '#c62828'),
        'pending': ('\u25CB', '#bdbdbd'),
    }.get(status, ('\u25CB', '#bdbdbd'))


def WorkflowPanel(lib, workflow_steps, workflow_name, saved_workflows,
                  workflow_status, available_tools, editing_step_index,
                  on_workflow_name_change, on_add_step,
                  on_remove_step, on_move_step_up, on_move_step_down,
                  on_select_step,
                  on_save_workflow, on_run_workflow, on_clear_workflow,
                  on_load_workflow, on_delete_workflow,
                  is_running=False):
    """Render the workflow builder panel (left sidebar).

    Step property editing happens in the right-side ToolPropertiesPanel,
    not inline here. Clicking a step calls on_select_step to populate
    the right panel.
    """

    items = []

    # ── 1. Workflow name ──
    items.append(
        lib.html.input(
            type='text',
            value=workflow_name,
            onChange=on_workflow_name_change,
            placeholder='Name your workflow...',
            style=lib.Style(
                width='100%', padding='6px 10px',
                fontSize='12px', fontWeight='600',
                border='1.5px solid #d0d5dd', borderRadius='8px',
                outline='none', boxSizing='border-box',
                marginBottom='10px', color='#333',
            ),
        ),
    )

    # ── 2. Step list ──
    if workflow_steps:
        step_els = []
        for i, step in enumerate(workflow_steps):
            status = step.get('status', 'pending')
            icon, icon_color = _status_icon(status)
            tool_name = step.get('tool_name', 'Unknown')
            detail = _step_detail_text(step)
            is_selected = (editing_step_index == i)

            def make_select(idx=i):
                def handler(event):
                    on_select_step(idx)
                return handler

            def make_remove(idx=i):
                def handler(event):
                    on_remove_step(idx)
                return handler

            def make_move_up(idx=i):
                def handler(event):
                    on_move_step_up(idx)
                return handler

            def make_move_down(idx=i):
                def handler(event):
                    on_move_step_down(idx)
                return handler

            # Step card — clickable to select for editing in right panel
            card_border = '1.5px solid #1565C0' if is_selected else '1px solid #e5e7eb'
            card_bg = '#edf4fc' if is_selected else ('#fff' if status != 'error' else '#fff5f5')

            header_children = [
                # Status icon
                lib.html.span(
                    style=lib.Style(fontSize='13px', flexShrink='0'),
                )(icon),
                # Step number
                lib.html.span(
                    style=lib.Style(
                        fontWeight='700', color=icon_color,
                        fontSize='11px', flexShrink='0', minWidth='14px',
                    ),
                )(f'{i + 1}'),
                # Tool name (click to select)
                lib.html.span(
                    style=lib.Style(
                        fontWeight='600',
                        color='#1565C0' if is_selected else '#333',
                        fontSize='12px',
                        flex='1', overflow='hidden', textOverflow='ellipsis',
                        whiteSpace='nowrap', cursor='pointer',
                    ),
                    onClick=make_select(),
                    title='Click to configure this step in the right panel',
                )(tool_name),
            ]

            # Reorder arrows
            if i > 0:
                header_children.append(
                    lib.html.button(
                        style=lib.Style(
                            background='none', border='none', cursor='pointer',
                            padding='0 2px', fontSize='10px', color='#9e9e9e',
                            flexShrink='0',
                        ),
                        onClick=make_move_up(),
                        title='Move up',
                    )('\u25B2'),
                )
            if i < len(workflow_steps) - 1:
                header_children.append(
                    lib.html.button(
                        style=lib.Style(
                            background='none', border='none', cursor='pointer',
                            padding='0 2px', fontSize='10px', color='#9e9e9e',
                            flexShrink='0',
                        ),
                        onClick=make_move_down(),
                        title='Move down',
                    )('\u25BC'),
                )

            # Remove
            header_children.append(
                lib.html.button(
                    style=lib.Style(
                        background='none', border='none', cursor='pointer',
                        padding='0 3px', fontSize='11px', color='#ccc',
                        flexShrink='0',
                    ),
                    onClick=make_remove(),
                    title='Remove step',
                )('\u2715'),
            )

            card_children = [
                lib.html.div(
                    style=lib.Style(
                        display='flex', alignItems='center', gap='5px',
                        padding='6px 8px',
                    ),
                )(*header_children),
            ]

            # Detail line below the header
            if detail:
                card_children.append(
                    lib.html.div(
                        style=lib.Style(
                            fontSize='10px', color='#8896a6',
                            padding='0 8px 4px 30px',
                            overflow='hidden', textOverflow='ellipsis',
                            whiteSpace='nowrap',
                        ),
                    )(detail),
                )

            # Error message
            if status == 'error' and step.get('error_msg'):
                card_children.append(
                    lib.html.div(
                        style=lib.Style(
                            fontSize='10px', color='#c62828',
                            padding='0 8px 4px 30px', fontWeight='600',
                        ),
                    )(step.get('error_msg')),
                )

            # Selected hint
            if is_selected:
                card_children.append(
                    lib.html.div(
                        style=lib.Style(
                            fontSize='9px', color='#1565C0', fontWeight='600',
                            padding='0 8px 5px 30px',
                            letterSpacing='0.03em',
                        ),
                    )('\u2190 Editing in right panel'),
                )

            step_el = lib.html.div(
                style=lib.Style(
                    background=card_bg,
                    border=card_border,
                    borderRadius='8px',
                    marginBottom='4px',
                    cursor='pointer',
                    transition='border-color 0.15s',
                ),
                onClick=make_select(),
            )(*card_children)
            step_el["key"] = f"wf-step-{step.get('id', i)}"
            step_els.append(step_el)

        items.append(
            lib.html.div(
                style=lib.Style(marginBottom='8px'),
            )(*step_els),
        )

    # ── 3. "+ Add Step" ──
    def make_add_handler(tool_id):
        def handler(event):
            on_add_step(tool_id)
        return handler

    add_btns = []
    for tool in available_tools:
        add_btns.append(
            lib.html.button(
                style=lib.Style(
                    background='#fff', border='1.5px dashed #b0bec5',
                    borderRadius='6px', padding='5px 10px',
                    fontSize='11px', fontWeight='600', color='#546e7a',
                    cursor='pointer', display='flex', alignItems='center',
                    gap='4px', whiteSpace='nowrap',
                ),
                onClick=make_add_handler(tool['id']),
                title=f'Add {tool["name"]} step',
            )(
                lib.html.span(style=lib.Style(fontSize='13px'))(tool.get('icon', '+')),
                tool['name'],
            ),
        )

    items.append(
        lib.html.div(
            style=lib.Style(
                display='flex', gap='6px', flexWrap='wrap',
                marginBottom='10px', padding='2px 0',
            ),
        )(
            lib.html.span(
                style=lib.Style(
                    fontSize='10px', fontWeight='700', color='#9e9e9e',
                    textTransform='uppercase', letterSpacing='0.04em',
                    alignSelf='center', marginRight='2px',
                ),
            )('+'),
            *add_btns,
        ),
    )

    # ── 4. Action buttons ──
    if workflow_steps:
        action_btns = []

        # Run Workflow — primary action
        run_label = '\u23F3 Running...' if is_running else '\u25B6 Run Workflow'
        action_btns.append(
            lib.html.button(
                style=lib.Style(
                    background='#2e7d32' if not is_running else '#9e9e9e',
                    color='#fff',
                    border='none', borderRadius='6px',
                    padding='7px 0', fontSize='12px',
                    fontWeight='700',
                    cursor='pointer' if not is_running else 'not-allowed',
                    flex='1',
                ),
                onClick=on_run_workflow,
                title='Execute all steps in order',
            )(run_label),
        )

        # Save
        action_btns.append(
            lib.html.button(
                style=lib.Style(
                    background='#1565C0', color='#fff',
                    border='none', borderRadius='6px',
                    padding='7px 12px', fontSize='11px',
                    fontWeight='700', cursor='pointer',
                ),
                onClick=on_save_workflow,
                title='Save workflow',
            )('Save'),
        )

        # Clear
        action_btns.append(
            lib.html.button(
                style=lib.Style(
                    background='none', border='1px solid #bdbdbd',
                    color='#757575', borderRadius='6px',
                    padding='6px 10px', fontSize='11px',
                    fontWeight='600', cursor='pointer',
                ),
                onClick=on_clear_workflow,
                title='Clear all steps',
            )('Clear'),
        )

        items.append(
            lib.html.div(
                style=lib.Style(
                    display='flex', gap='6px',
                    marginBottom='10px',
                ),
            )(*action_btns),
        )

        # Status feedback
        if workflow_status == 'done' and not is_running:
            items.append(
                lib.html.div(
                    style=lib.Style(
                        fontSize='11px', fontWeight='600',
                        color='#2e7d32', padding='6px 10px',
                        background='#e8f5e9', borderRadius='6px',
                        marginBottom='8px', textAlign='center',
                    ),
                )('\u2705 All steps completed successfully'),
            )
        elif workflow_status == 'error':
            items.append(
                lib.html.div(
                    style=lib.Style(
                        fontSize='11px', fontWeight='600',
                        color='#c62828', padding='6px 10px',
                        background='#fce4ec', borderRadius='6px',
                        marginBottom='8px', textAlign='center',
                    ),
                )('\u274C Workflow stopped — check the failed step'),
            )

    # ── 5. Saved workflows ──
    if saved_workflows:
        items.append(
            lib.html.div(
                style=lib.Style(
                    height='1px', background='#e0e4ea',
                    margin='4px 0 8px 0',
                ),
            )(),
        )
        items.append(
            lib.html.div(
                style=lib.Style(
                    fontSize='10px', fontWeight='700', color='#9e9e9e',
                    textTransform='uppercase', letterSpacing='0.05em',
                    marginBottom='6px',
                ),
            )('Saved Workflows'),
        )

        for wf_summary in saved_workflows:
            wf_id = wf_summary['id']
            wf_name_display = wf_summary.get('name', 'Untitled')
            step_count = wf_summary.get('step_count', 0)

            def make_load_handler(bound_id=wf_id):
                def handler(event):
                    on_load_workflow(bound_id)
                return handler

            def make_delete_handler(bound_id=wf_id):
                def handler(event):
                    on_delete_workflow(bound_id)
                return handler

            saved_el = lib.html.div(
                style=lib.Style(
                    display='flex', alignItems='center', gap='4px',
                    padding='5px 8px', fontSize='11px',
                    background='#fff', borderRadius='6px',
                    border='1px solid #e5e7eb',
                    marginBottom='4px',
                ),
            )(
                lib.html.span(
                    style=lib.Style(
                        flex='1', fontWeight='600', color='#333',
                        overflow='hidden', textOverflow='ellipsis',
                        whiteSpace='nowrap',
                    ),
                    title=wf_name_display,
                )(wf_name_display),
                lib.html.span(
                    style=lib.Style(
                        fontSize='9px', color='#9e9e9e', flexShrink='0',
                    ),
                )(f'{step_count} steps'),
                lib.html.button(
                    style=lib.Style(
                        background='#e3f2fd', border='1px solid #90caf9',
                        color='#1565C0', borderRadius='4px',
                        padding='2px 8px', fontSize='10px',
                        fontWeight='700', cursor='pointer', flexShrink='0',
                    ),
                    onClick=make_load_handler(),
                    title='Load workflow',
                )('Load'),
                lib.html.button(
                    style=lib.Style(
                        background='none', border='1px solid #ef9a9a',
                        color='#c62828', borderRadius='4px',
                        padding='2px 6px', fontSize='10px',
                        fontWeight='600', cursor='pointer', flexShrink='0',
                    ),
                    onClick=make_delete_handler(),
                    title='Delete workflow',
                )('\u2715'),
            )
            saved_el["key"] = f"saved-wf-{wf_id}"
            items.append(saved_el)

    # ── Empty state ──
    if not workflow_steps and not saved_workflows:
        items.append(
            lib.html.div(
                style=lib.Style(
                    fontSize='11px', color='#9e9e9e',
                    padding='6px 0', lineHeight='1.6',
                    textAlign='center',
                ),
            )('Add steps above to build a workflow.'),
        )

    return lib.html.div(
        style=lib.Style(marginTop='0'),
    )(*items)
