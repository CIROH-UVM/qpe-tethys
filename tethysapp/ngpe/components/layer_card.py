"""LayerCard — data layer card for the left sidebar.

Displays layer metadata (name, type, region, timestamp) with controls
for visibility toggle, opacity slider, and layer removal.
"""


def LayerCard(lib, layer_id, entry, on_toggle_visibility,
              on_opacity_change, on_remove):
    """Render a data layer card with metadata, visibility, and opacity controls."""

    metadata = entry.get('metadata', {})
    name = metadata.get('name', 'Unknown Layer')
    visible = entry.get('visible', True)
    opacity = entry.get('opacity', 1.0)
    ltype = metadata.get('layer_type', '')
    region = metadata.get('region', '')
    ref_dt = metadata.get('ref_datetime', '')

    # Layer type styling
    is_raster = ltype == 'RasterData'
    accent = '#00ACC1' if is_raster else '#7B1FA2'
    type_label = 'RADAR' if is_raster else 'GAUGE'
    type_bg = '#E0F7FA' if is_raster else '#F3E5F5'

    # Extra info for point data
    station_count = metadata.get('station_count', None)

    # Format datetime for display (trim seconds/microseconds)
    display_dt = ''
    if ref_dt:
        display_dt = str(ref_dt)[:16]  # "2026-04-24T16:00"
        display_dt = display_dt.replace('T', ' ')

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
        # Header row: name + type badge + eye + remove
        lib.html.div(
            style=lib.Style(
                display='flex', alignItems='center',
                padding='8px 10px', gap='6px',
                borderLeft=f'3px solid {accent if visible else "#ccc"}',
            ),
        )(
            # Layer name
            lib.html.span(
                style=lib.Style(
                    fontSize='12.5px', fontWeight='600',
                    color=accent if visible else '#999', flex='1',
                    overflow='hidden', textOverflow='ellipsis',
                    whiteSpace='nowrap',
                ),
                title=name,
            )(name),
            # Type badge
            lib.html.span(
                style=lib.Style(
                    fontSize='9px', fontWeight='700',
                    color=accent, background=type_bg,
                    padding='1px 5px', borderRadius='4px',
                    letterSpacing='0.04em',
                    flexShrink='0',
                ),
            )(type_label),
            # Visibility toggle
            lib.html.button(
                style=lib.Style(
                    background='none', border='none', cursor='pointer',
                    padding='0 4px', fontSize='14px', lineHeight='1',
                    color=accent if visible else '#ccc',
                    flexShrink='0',
                ),
                onClick=on_toggle_visibility,
                title='Hide layer' if visible else 'Show layer',
            )('\u25C9' if visible else '\u25CB'),
            # Remove button
            lib.html.button(
                style=lib.Style(
                    background='none', border='none', cursor='pointer',
                    padding='0 2px', fontSize='11px', lineHeight='1',
                    color='#ccc', flexShrink='0',
                ),
                onClick=on_remove,
                title='Remove layer',
            )('\u2715'),
        ),

        # Info row: region + timestamp (only when visible)
        *(
            [lib.html.div(
                style=lib.Style(
                    display='flex', alignItems='center', gap='8px',
                    padding='2px 10px 4px 16px',
                    fontSize='10px', color='#8896a6',
                ),
            )(
                # Region
                *(
                    [lib.html.span(
                        style=lib.Style(fontWeight='600'),
                    )(region.replace('-', ' ').title())]
                    if region else []
                ),
                # Separator
                *(
                    [lib.html.span(
                        style=lib.Style(color='#d0d5dd'),
                    )('|')]
                    if region and display_dt else []
                ),
                # Timestamp
                *(
                    [lib.html.span()(display_dt)]
                    if display_dt else []
                ),
                # Station count (for gauge layers)
                *(
                    [lib.html.span(
                        style=lib.Style(color='#d0d5dd'),
                    )('|'),
                     lib.html.span()(f'{station_count} stations')]
                    if station_count is not None else []
                ),
            )]
            if visible and (region or display_dt) else []
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
