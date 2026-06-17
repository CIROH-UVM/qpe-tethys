"""ScaleBiasTool — apply scale (multiply) or bias (add) to raster values
within a user-drawn polygon.

Creates a new DataLayer with modified values, preserving the original.
Currently supports raster layers only.
"""

import numpy as np
from shapely.geometry import shape as shapely_shape
from matplotlib.path import Path

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

    def validate_inputs(self):
        """Validate required fields before running."""
        errors = []
        if not self.properties.get('layer_id'):
            errors.append('Select a target layer')
        if not self.properties.get('operation'):
            errors.append('Select an operation (scale or bias)')
        val_str = self.properties.get('value', '')
        if not val_str:
            errors.append('Enter a numeric value')
        else:
            try:
                float(val_str)
            except (ValueError, TypeError):
                errors.append('Value must be a number (e.g., 1.5)')
        extent = self.properties.get('extent', None) or self.extent
        if not extent or not isinstance(extent, dict):
            errors.append('Draw a polygon on the map first')
        return errors

    def run(self):
        """Execute scale/bias on the target layer within the polygon extent.

        Reads the target layer's DataArray, applies the operation inside
        the polygon, and returns a new RasterData layer.
        """
        errors = self.validate_inputs()
        if errors:
            raise ValueError('; '.join(errors))

        layer_id = self.properties.get('layer_id', '')
        operation = self.properties.get('operation', 'scale')
        output_name = self.properties.get('output_name', f'{operation}_result')
        extent_geojson = self.properties.get('extent', None) or self.extent
        op_value = float(self.properties.get('value', '1.0'))

        # Resolve target layer from the display string (e.g., "radar_data (ImageStatic)")
        # Use startswith to avoid false substring matches with short names.
        target_layer = None
        for inp in self.inputs:
            if layer_id.startswith(f"{inp.name} (") or layer_id == inp.name:
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

            # Get coordinate arrays
            if 'x' in result_da.coords and 'y' in result_da.coords:
                x_coords = result_da.coords['x'].values
                y_coords = result_da.coords['y'].values
            else:
                raise ValueError('DataArray must have x and y coordinates')

            # Create mask using vectorized matplotlib Path (fast)
            # instead of per-pixel shapely contains (slow)
            polygon_coords = list(shapely_shape(extent_geojson).exterior.coords)
            poly_path = Path(polygon_coords)
            xx, yy = np.meshgrid(x_coords, y_coords)
            points = np.column_stack([xx.ravel(), yy.ravel()])
            mask = poly_path.contains_points(points).reshape(result_da.shape)

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
