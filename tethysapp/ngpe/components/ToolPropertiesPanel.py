from ..tools.tool import Tool

def ToolPropertiesPanel(lib, selected_props):

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

    props = selected_props

    # Here is ok
    # if selected_props != None:
    # for prop in [1,2]:
    #     active_value, set_active_value = lib.hooks.use_state('')

    if selected_props == None:
        print("No selected tool")
        return panel

    # Here is not
    # active_value, set_active_value = lib.hooks.use_state('')

    hook_vars = {}
    hook_setters = {}
    controls = []

    # Here is not... hmmm
    #active_value, set_active_value = lib.hooks.use_state('')

#    def handle_value_change(event, hook_setter, property):
    def handle_value_change(event, property):
        print("Generic Handle Value Change Called...")
        print(event)
        # hook_setter(event['target']['value'])
        property['value'] = event['target']['value']
        print(selected_props)

    for prop in selected_props:
        print(prop)
        prop['value'] = ''
        if prop['type'] == 'list':
            # hook_vars[prop['name']], hook_setters[prop['name']] = lib.hooks.use_state('')

            print(hook_vars)
            print(hook_setters)
            cur_prop = prop

            control_inside = lib.html.select(
                style=lib.Style(
                    width='100%', padding='7px 10px',
                    fontSize='13px', fontWeight='600',
                    border='1.5px solid #d0d5dd', borderRadius='8px',
                    backgroundColor='#fff', color='#333',
                    cursor='pointer', outline='none',
                ),
                value=prop['value'],
                # # onChange=lambda e: handle_value_change(e, hook_setters[prop['name']], prop),
                #onChange=handle_value_change,
                onChange=lambda e: handle_value_change(e, cur_prop),
            )(
                lib.html.option(value='')('Select Region...'),
                *[
#                    lib.html.option(value=r['id'])(r['name'])
                    lib.html.option(value=r)(r)
                    for r in prop['options']
                ],
            )
        
        elif prop['type'] == 'str':
            control_inside = lib.html.label()("Not yet implemented")
        ## String input box
        elif prop['type'] == 'datetime':
            control_inside = lib.html.label()("Not yet implemented")
        ## Datetime input

        controls.append(lib.html.div(
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
        ))
        # TODO: https://www.google.com/search?q=concate+reactpy+html+fragments
        # TODO: Use a list
        print(controls)
        
    panel = panel(*controls)
    
    print("Exiting Panel Code...")
    return panel
    
    return lib.html.div(
        style=lib.Style(
            width='280px', minWidth='280px', flexShrink='0',
            background='#f5f7fa',
            borderRight='1px solid #e0e4ea',
            overflowY='auto',
            padding='14px 16px',
            boxSizing='border-box',
        ),
    )(
        lib.html.label(
            style=lib.Style(
                fontSize='11px', color='#667085', fontWeight='600',
            ),
        )('Clicked')
    )

