"""ScaleBiasTool — apply scale (multiply) or bias (add) to raster values
within a user-drawn polygon.

Creates a new DataLayer with modified values, preserving the original.
Currently supports raster layers only.
"""

import numpy as np
from shapely.geometry import shape, Point

from ..data_layer.raster_data import RasterData
from .tool import Tool


class ScaleBiasTool(Tool):
    """Apply scale (multiply) or bias (add) to raster values inside a polygon."""

    name = 'Scale / Bias Tool'

    def get_properties(self) -> list:
        """Return property definitions for the ToolPropertiesPanel UI.

        The 'layer_id' options list is populated dynamically from
        active layers before rendering.
        """
        return [
            {
                'name': 'layer_id',
                'type': 'list',
                'options': [],  # Populated dynamically by app.py
                'label': 'Target Layer',
            },
            {
                'name': 'extent',
                'type': 'polygon',
                'label': 'Processing Area',
            },
            {
                'name': 'operation',
                'type': 'list',
                'options': ['scale', 'bias'],
                'label': 'Operation (scale=multiply, bias=add)',
            },
            {
                'name': 'value',
                'type': 'str',
                'label': 'Numeric value (e.g. 1.5 or -0.5)',
            },
            {
                'name': 'output_name',
                'type': 'str',
                'label': 'Output layer name',
            },
        ]

    def run(self):
        """Execute scale/bias on the target layer within the polygon extent.

        Reads the target layer's DataArray, applies the operation inside
        the polygon, and returns a new RasterData layer.
        """
        layer_id = self.properties.get('layer_id', '')
        operation = self.properties.get('operation', 'scale')
        output_name = self.properties.get('output_name', f'{operation}_result')
        extent_geojson = self.properties.get('extent', None) or self.extent

        # Parse value
        try:
            op_value = float(self.properties.get('value', '1.0'))
        except (ValueError, TypeError):
            raise ValueError(
                'Invalid value — enter a number (e.g., 1.5 for scale, 0.5 for bias)'
            )

        # Validate inputs
        if not layer_id:
            raise ValueError('Select a target layer')
        if not extent_geojson or not isinstance(extent_geojson, dict):
            raise ValueError('Draw a polygon on the map first')

        # Resolve target layer from the display string (e.g., "radar_data (RasterData)")
        target_layer = None
        for inp in self.inputs:
            if inp.name in layer_id:
                target_layer = inp
                break

        if target_layer is None:
            raise ValueError(
                f'Target layer not found: {layer_id}. '
                f'Available: {[l.name for l in self.inputs]}'
            )

        if not isinstance(target_layer, RasterData):
            raise ValueError(
                'Scale/Bias currently only works on raster (radar) layers'
            )

        self.status = 'running'

        try:
            # Get the original data
            original_da = target_layer.get_data()
            if original_da is None:
                raise ValueError('Target layer has no data')

            # Copy the data
            result_da = original_da.copy(deep=True)

            # Build polygon from GeoJSON
            polygon = shape(extent_geojson)

            # Get coordinate arrays
            if 'x' in result_da.coords and 'y' in result_da.coords:
                x_coords = result_da.coords['x'].values
                y_coords = result_da.coords['y'].values
            else:
                raise ValueError('DataArray must have x and y coordinates')

            # Create mask: True where point is inside polygon
            # Coordinates are in EPSG:4326 (lon/lat)
            mask = np.zeros(result_da.shape, dtype=bool)
            for iy, y in enumerate(y_coords):
                for ix, x in enumerate(x_coords):
                    if polygon.contains(Point(x, y)):
                        mask[iy, ix] = True

            # Apply operation inside polygon
            values = result_da.values
            if operation == 'scale':
                values[mask] = values[mask] * op_value
            elif operation == 'bias':
                values[mask] = values[mask] + op_value
            else:
                raise ValueError(f'Unknown operation: {operation}')

            result_da.values = values

            # Preserve attrs from original
            result_da.attrs = dict(original_da.attrs)

            # Create new RasterData layer
            layer = RasterData(
                name=output_name,
                description=f'{operation} ({op_value}) applied to {target_layer.name}',
                region=target_layer.region,
                ref_datetime=target_layer.ref_datetime,
                creator_tool=self.name,
                data=result_da,
            )

            self.status = 'done'
            self._result = layer
            return layer

        except Exception:
            self.status = 'error'
            raise
