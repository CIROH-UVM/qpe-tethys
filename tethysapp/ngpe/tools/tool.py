"""Tool base class for NGPE processing tools.

Architecture (agreed with team 2026-04-20):
  - Tool instance stored in use_ref in app.py (mutable, no re-render).
  - get_properties() returns a plain list of property dicts that drive
    the ToolPropertiesPanel UI.
  - The panel calls on_property_change(name, value) to update a
    use_state dict in app.py, which triggers re-render.
  - handle_run_tool() in app.py creates a fresh Tool, sets properties,
    calls run(), and adds the resulting DataLayer to active_layers.

Property types supported by ToolPropertiesPanel:
  - 'list'     : dropdown select (requires 'options' key)
  - 'str'      : text input
  - 'datetime' : datetime-local picker
  - 'polygon'  : map drawing tool (future)

Output → Input flow (layer workflow sequence):
  - Tool.inputs is a list of DataLayer objects from previous tools.
  - Tool.run() can read inputs to chain processing steps.
  - Tool._result holds the output DataLayer after run().
"""

from typing import List, Dict, Any


class Tool:
    """Abstract base class for all NGPE processing tools."""

    name: str = 'Tool'
    status: str = 'idle'

    def __init__(self, inputs: list = None, prop_defaults: dict = None):
        """Initialize a Tool.

        Args:
            inputs: List of DataLayer objects from previous tools in the
                    workflow. Allows chaining tool outputs as inputs.
            prop_defaults: Default property values (overridden by UI).
        """
        self.inputs = inputs or []
        self.properties = prop_defaults or {}
        self.extent = None
        self._result = None

    def get_properties(self) -> List[Dict[str, Any]]:
        """Return a list of property dicts that describe the UI controls.

        Each dict has keys: name, type, label, and optionally 'options'.
        Supported types: 'list', 'str', 'datetime', 'polygon'.
        """
        raise NotImplementedError(
            f'{self.__class__.__name__} must implement get_properties()'
        )

    def validate_inputs(self) -> List[str]:
        """Validate inputs before running. Returns list of error strings."""
        return []

    def run(self):
        """Execute the tool. Returns a DataLayer (or list of DataLayers)."""
        raise NotImplementedError(
            f'{self.__class__.__name__} must implement run()'
        )

    @property
    def result(self):
        """The output DataLayer from the last run()."""
        return self._result

    def to_dict(self) -> dict:
        """Serialize tool state for debugging/logging."""
        return {
            'tool': self.name,
            'properties': self.properties,
            'status': self.status,
            'has_result': self._result is not None,
            'num_inputs': len(self.inputs),
        }
