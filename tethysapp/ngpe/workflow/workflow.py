"""Workflow and WorkflowStep — define replayable processing pipelines.

A Workflow is an ordered sequence of WorkflowSteps. Each step records
which Tool was used, what properties were set, and optionally a spatial
extent. Workflows can be serialized to/from dicts for saving to JSON
and replayed via WorkflowEngine.

Usage:
    wf = Workflow(name='Morning correction')
    wf.add_step(LoadDatasetTool, {'dataset_id': 'mrms_qpe_01h', ...})
    wf.add_step(ScaleBiasTool, {'operation': 'bias', 'value': '0.5', ...}, extent=geojson)
    saved = wf.to_dict()          # persist as JSON
    wf2 = Workflow.from_dict(saved)  # reload later
"""

import uuid
import copy
from datetime import datetime, timezone


class WorkflowStep:
    """One step in a workflow — records a Tool invocation with its config.

    Attributes:
        id: Unique step identifier.
        tool_id: Registry key identifying the Tool class (e.g. 'load_dataset').
        tool_name: Human-readable tool name (e.g. 'Load Data').
        properties: Dict of {prop_name: value} as configured by the user.
        extent: GeoJSON polygon dict or None (for spatial tools).
        step_order: Position in the workflow (0-based).
        status: 'pending' | 'running' | 'done' | 'error' | 'skipped'.
        output_layer_id: UUID string of the DataLayer produced (set after run).
        error_msg: Error message if status == 'error'.
        started_at: Timestamp when step execution began.
        completed_at: Timestamp when step execution finished.
    """

    def __init__(self, tool_id, tool_name, properties, extent=None, step_order=0):
        self.id = str(uuid.uuid4())
        self.tool_id = tool_id
        self.tool_name = tool_name
        self.properties = dict(properties)
        self.extent = copy.deepcopy(extent) if extent else None
        self.step_order = step_order

        # Execution state
        self.status = 'pending'
        self.output_layer_id = None
        self.error_msg = None
        self.started_at = None
        self.completed_at = None

    def reset(self):
        """Reset execution state for replay."""
        self.status = 'pending'
        self.output_layer_id = None
        self.error_msg = None
        self.started_at = None
        self.completed_at = None

    def to_dict(self):
        """Serialize step to a JSON-safe dict for saving."""
        d = {
            'id': self.id,
            'tool_id': self.tool_id,
            'tool_name': self.tool_name,
            'properties': self.properties,
            'extent': self.extent,
            'step_order': self.step_order,
            'status': self.status,
            'output_layer_id': self.output_layer_id,
            'error_msg': self.error_msg,
        }
        if self.started_at:
            d['started_at'] = self.started_at.isoformat()
        if self.completed_at:
            d['completed_at'] = self.completed_at.isoformat()
        return d

    @classmethod
    def from_dict(cls, d):
        """Deserialize a step from a saved dict."""
        step = cls(
            tool_id=d['tool_id'],
            tool_name=d['tool_name'],
            properties=d.get('properties', {}),
            extent=d.get('extent'),
            step_order=d.get('step_order', 0),
        )
        step.id = d.get('id', step.id)
        step.status = d.get('status', 'pending')
        step.output_layer_id = d.get('output_layer_id')
        step.error_msg = d.get('error_msg')
        if d.get('started_at'):
            step.started_at = datetime.fromisoformat(d['started_at'])
        if d.get('completed_at'):
            step.completed_at = datetime.fromisoformat(d['completed_at'])
        return step

    def __repr__(self):
        return f"WorkflowStep({self.step_order}: {self.tool_name} [{self.status}])"


class Workflow:
    """An ordered sequence of WorkflowSteps that can be saved and replayed.

    Attributes:
        id: Unique workflow identifier.
        name: Human-readable name (e.g. 'Morning correction — Northeast').
        description: Optional description of what this workflow does.
        steps: Ordered list of WorkflowStep objects.
        status: 'idle' | 'running' | 'done' | 'error'.
        created_at: When the workflow was first created.
        last_run_at: When the workflow was last executed.
        run_count: Number of times this workflow has been executed.
    """

    def __init__(self, name='Untitled Workflow', description=''):
        self.id = str(uuid.uuid4())
        self.name = name
        self.description = description
        self.steps = []
        self.status = 'idle'
        self.created_at = datetime.now(timezone.utc)
        self.last_run_at = None
        self.run_count = 0

    def add_step(self, tool_id, tool_name, properties, extent=None):
        """Append a new step to the workflow.

        Args:
            tool_id: Registry key (e.g. 'load_dataset', 'scale_bias').
            tool_name: Human-readable name (e.g. 'Load Data').
            properties: Dict of tool property values.
            extent: GeoJSON polygon or None.

        Returns:
            The created WorkflowStep.
        """
        step = WorkflowStep(
            tool_id=tool_id,
            tool_name=tool_name,
            properties=properties,
            extent=extent,
            step_order=len(self.steps),
        )
        self.steps.append(step)
        return step

    def remove_step(self, step_index):
        """Remove a step by index and re-number remaining steps."""
        if 0 <= step_index < len(self.steps):
            self.steps.pop(step_index)
            for i, step in enumerate(self.steps):
                step.step_order = i

    def move_step(self, from_index, to_index):
        """Move a step from one position to another."""
        if (0 <= from_index < len(self.steps) and
                0 <= to_index < len(self.steps)):
            step = self.steps.pop(from_index)
            self.steps.insert(to_index, step)
            for i, s in enumerate(self.steps):
                s.step_order = i

    def reset_all(self):
        """Reset all steps to pending for a fresh replay."""
        for step in self.steps:
            step.reset()
        self.status = 'idle'

    def clone(self, new_name=None):
        """Create a deep copy of this workflow with a new ID.

        Args:
            new_name: Name for the clone. Defaults to 'Copy of <original>'.

        Returns:
            A new Workflow instance with copied steps.
        """
        name = new_name or f'Copy of {self.name}'
        wf = Workflow(name=name, description=self.description)
        for step in self.steps:
            wf.add_step(
                tool_id=step.tool_id,
                tool_name=step.tool_name,
                properties=copy.deepcopy(step.properties),
                extent=copy.deepcopy(step.extent),
            )
        return wf

    def to_dict(self):
        """Serialize workflow to a JSON-safe dict for saving."""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'steps': [s.to_dict() for s in self.steps],
            'status': self.status,
            'created_at': self.created_at.isoformat(),
            'last_run_at': self.last_run_at.isoformat() if self.last_run_at else None,
            'run_count': self.run_count,
        }

    @classmethod
    def from_dict(cls, d):
        """Deserialize a workflow from a saved dict."""
        wf = cls(name=d.get('name', 'Untitled'), description=d.get('description', ''))
        wf.id = d.get('id', wf.id)
        wf.status = d.get('status', 'idle')
        wf.run_count = d.get('run_count', 0)
        if d.get('created_at'):
            wf.created_at = datetime.fromisoformat(d['created_at'])
        if d.get('last_run_at'):
            wf.last_run_at = datetime.fromisoformat(d['last_run_at'])
        wf.steps = [WorkflowStep.from_dict(sd) for sd in d.get('steps', [])]
        return wf

    def __repr__(self):
        return f"Workflow('{self.name}', {len(self.steps)} steps, {self.status})"
