from typing import List, Dict, Any
class Tool:
    """Abstract base class for all NGPE processing tools."""

    name: str = 'Tool'
    status: str = 'idle'

    def __init__(self, inputs: list = None, prop_defaults: dict = None):
        self.inputs = inputs or []
        self.properties = prop_defaults or {}
        self.extent = None
        self._result = None

    def get_properties(self) -> Dict[str, Any]:
        raise NotImplementedError(f'{self.__class__.__name__} must implement get_properties()')

    def validate_inputs(self) -> List[str]:
        return []

    def run(self):
        raise NotImplementedError(f'{self.__class__.__name__} must implement run()')

    def to_dict(self) -> dict:
        return {
            'tool': self.name,
            'properties': self.properties,
            'status': self.status,
        }
