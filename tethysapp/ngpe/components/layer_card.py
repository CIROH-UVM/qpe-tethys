def LayerCard(lib, layer_id, entry, on_toggle_visibility, on_opacity_change, on_remove):
    """
    Data layer card — Pat's spec Section 6.3.

    Renders:
      - Layer name with coloured accent (cyan for RasterData, purple for PointData)
      - Eye icon button (toggle visibility)
      - Remove button
      - Opacity range slider (0-100%)
    """
    name = entry.get('metadata', {}).get('name', 'Unknown Layer')
    visible = entry.get('visible', True)
    opacity = entry.get('opacity', 1.0)
    ltype = entry.get('metadata', {}).get('layer_type', '')

    is_raster = ltype == 'RasterData'
    accent = '#00ACC1' if is_raster else '#7B1FA2'

    return lib.html.div(
        style=lib.Style(
            background='#fff' if visible else '#fafbfc',
            border='1px solid #e2e6ea',
            borderRadius='8px',
            marginBottom='8px',
            overflow='hidden',
            opacity='1' if visible else '0.55',
        ),
    )(
        # Name + eye icon + remove button
        lib.html.div(
            style=lib.Style(
                display='flex', alignItems='center',
                padding='8px 10px', gap='8px',
                borderLeft=f'3px solid {accent if visible else "#ccc"}',
            ),
        )(
            lib.html.span(
                style=lib.Style(
                    fontSize='12.5px', fontWeight='600',
                    color=accent if visible else '#999', flex='1',
                ),
            )(name),
            lib.html.button(
                style=lib.Style(
                    background='none', border='none', cursor='pointer',
                    padding='0 4px', fontSize='14px', lineHeight='1',
                    color=accent if visible else '#ccc',
                ),
                onClick=on_toggle_visibility,
                title='Hide layer' if visible else 'Show layer',
            )('\u25C9' if visible else '\u25CB'),
            lib.html.button(
                style=lib.Style(
                    background='none', border='none', cursor='pointer',
                    padding='0 2px', fontSize='11px', lineHeight='1',
                    color='#ccc',
                ),
                onClick=on_remove,
                title='Remove layer',
            )('\u2715'),
        ),

        # Opacity slider (only when visible)
        *(
            [lib.html.div(
                style=lib.Style(
                    display='flex', alignItems='center', gap='6px',
                    padding='4px 10px 8px 10px',
                ),
            )(
                lib.html.span(style=lib.Style(
                    fontSize='10px', color='#8896a6',
                ))('Opacity'),
                lib.html.input(
                    type='range', min='0', max='100',
                    value=str(int(opacity * 100)),
                    onChange=on_opacity_change,
                    style=lib.Style(flex='1', cursor='pointer', height='4px'),
                ),
                lib.html.span(style=lib.Style(
                    fontSize='10px', color='#444',
                    minWidth='28px', textAlign='right', fontWeight='600',
                ))(f'{int(opacity * 100)}%'),
            )]
            if visible else []
        ),
    )
