from ..tools.tool import Tool

def ToolProperitesPanel(lib, tool):

	header = lib.html.div(
		style=lib.Style(
			width='280px', minWidth='280px', flexShrink='0',
			background='#f5f7fa',
			borderRight='1px solid #e0e4ea',
			overflowY='auto',
			padding='14px 16px',
			boxSizing='border-box',
		),
    )
	for prop in tool.get_properties():
        # Region dropdown

			  
            if prop['type'] == 'list':
			    control_inside = lib.html.select(
                    style=lib.Style(
                        width='100%', padding='7px 10px',
                        fontSize='13px', fontWeight='600',
                        border='1.5px solid #d0d5dd', borderRadius='8px',
                        backgroundColor='#fff', color='#333',
                        cursor='pointer', outline='none',
                    ),
                    value=selected_region,
                    onChange=handle_region_change,
                    )(
                        lib.html.option(value='')('Select Region...'),
                        ## Here, instead, we need to import the list of options from prop
                        *[
                            lib.html.option(value=r['id'])(r['name'])
                            for r in RFC_REGIONS
                        ],
                    ),
			
			elif prop['type'] == 'str':
			## String input box
			elif prop['type'] == 'datetime':
			## 
	
            control = lib.html.div(
            style=lib.Style(
                display='flex', flexDirection='column', gap='4px',
                marginBottom='12px', paddingLeft='20px',
            ),
        )
			(
            lib.html.label(
                style=lib.Style(
                    fontSize='11px', color='#667085', fontWeight='600',
                ),
            )('prop['label']),


	return header
