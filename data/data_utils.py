import datetime as dt

def _parse_datetime(dt_input: str | dt.date | dt.datetime) -> dt.datetime:
    '''
    Normalizes a date/time input to a datetime object.

    Accepted formats:
    - datetime object (returned as-is)
    - date object (converted to datetime at midnight UTC)
    - string in MADIS/MRMS format: 'YYYYMMDD_HHMM' or 'YYYYMMDD-HHMMSS'
    - string in ISO 8601 format: 'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM'

    Raises ValueError if the string cannot be parsed.
    '''
    if isinstance(dt_input, dt.datetime):
        return dt_input
    if isinstance(dt_input, dt.date):
        return dt.datetime(dt_input.year, dt_input.month, dt_input.day)
    if isinstance(dt_input, str):
        for fmt in ('%Y%m%d_%H%M', '%Y%m%d-%H%M%S', '%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
            try:
                return dt.datetime.strptime(dt_input, fmt)
            except ValueError:
                continue
        raise ValueError(
            f"Could not parse datetime string: '{dt_input}'. "
            "Expected 'YYYYMMDD_HHMM', 'YYYYMMDD-HHMMSS', or ISO 8601 (e.g., '2025-11-30T00:00')."
        )
    raise TypeError(f"Expected str, date, or datetime; got {type(dt_input)}")