from ..tools.tool import Tool

def ToolProperitesPanel(lib, selected_tool):

    panel = lib.html.div(
        style=lib.Style(
            width='280px', minWidth='280px', flexShrink='0',
            background='#f5f7fa',
            borderRight='1px solid #e0e4ea',
            overflowY='auto',
            padding='14px 16px',
            boxSizing='border-box',
        ),
    )
    
    if selected_tool == None:
        return panel

    hook_vars = {}
    hook_setters = {}

    def handle_value_change(event, hook_setter, property):
        hook_setter(event['target']['value'])
        property['value'] = event['target']['value']

    for prop in selected_tool.get_properties():
        if prop['type'] == 'list':
            hook_vars[prop['name']], hook_setters[prop['name']] = lib.hooks.use_state('')
            
            control_inside = lib.html.select(
                style=lib.Style(
                    width='100%', padding='7px 10px',
                    fontSize='13px', fontWeight='600',
                    border='1.5px solid #d0d5dd', borderRadius='8px',
                    backgroundColor='#fff', color='#333',
                    cursor='pointer', outline='none',
                ),
                value=hook_vars[prop['name']],
                onChange=lambda e: handle_value_change(e, hook_setters[prop['name']], prop),
            )(
                lib.html.option(value='')('Select Region...'),
                *[
                    lib.html.option(value=r['id'])(r['name'])
                    for r in prop['options']
                ],
            )
        
        elif prop['type'] == 'str':
            pass
        ## String input box
        elif prop['type'] == 'datetime':
            pass
        ## Datetime input

        control = lib.html.div(
            style=lib.Style(
                display='flex', flexDirection='column', gap='4px',
                marginBottom='12px', paddingLeft='20px',
            ),
        )(
            lib.html.label(
                style=lib.Style(
                    fontSize='11px', color='#667085', fontWeight='600',
                ),
            )(prop['label']),
            control_inside,
        ),
        panel.append(control)
    
    return panel

