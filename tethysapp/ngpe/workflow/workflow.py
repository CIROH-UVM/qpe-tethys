"""Workflow and WorkflowStep — define replayable processing pipelines.

A Workflow is an ordered sequence of WorkflowSteps. Each step wraps
a Tool instance with its configured properties. Workflows can be
serialized to/from dicts for saving to JSON and replayed via
WorkflowEngine.

Design decisions (Pat, 2026-05-24):
  - WorkflowStep wraps an actual Tool object (not property copies).
  - Steps have a back-reference to their parent Workflow (no step_order).
  - Everything is always part of a workflow (no start/stop recording).

Usage:
    wf = Workflow(name='Morning correction')
    tool1 = LoadDatasetTool()
    tool1.properties = {'dataset_id': 'mrms_qpe_01h', ...}
    wf.add_step(tool1)

    tool2 = ScaleBiasTool()
    tool2.properties = {'operation': 'bias', 'value': '0.5', ...}
    tool2.extent = geojson
    wf.add_step(tool2)

    saved = wf.to_dict()          # persist as JSON
    wf2 = Workflow.from_dict(saved)  # reload later
"""

import uuid
import copy
from datetime import datetime, timezone


class WorkflowStep:
    """One step in a workflow — wraps a Tool instance with execution state.

    The step holds the actual Tool object. Workflow-specific concerns
    (status tracking, timing, error handling) live here so that Tool
    subclasses stay simple and don't need to know about workflows.

    Attributes:
        id: Unique step identifier.
        tool: The Tool instance with its configured properties/extent.
        workflow: Back-reference to the parent Workflow (set by Workflow.add_step).
        status: 'pending' | 'running' | 'done' | 'error' | 'skipped'.
        output_layer_id: UUID string of the DataLayer produced (set after run).
        error_msg: Error message if status == 'error'.
        started_at: Timestamp when step execution began.
        completed_at: Timestamp when step execution finished.
    """

    def __init__(self, tool):
        self.id = str(uuid.uuid4())
        self.tool = tool
        self.workflow = None  # Set by Workflow.add_step()

        # Execution state
        self.status = 'pending'
        self.output_layer_id = None
        self.error_msg = None
        self.started_at = None
        self.completed_at = None

    @property
    def tool_id(self):
        """Registry key for the tool (derived from TOOL_REGISTRY)."""
        from ..app import TOOL_REGISTRY
        for entry in TOOL_REGISTRY:
            if isinstance(self.tool, entry['class']):
                return entry['id']
        return self.tool.__class__.__name__

    @property
    def tool_name(self):
        """Human-readable tool name."""
        return self.tool.name

    @property
    def step_index(self):
        """Position of this step in the parent workflow (0-based), or -1."""
        if self.workflow is None:
            return -1
        try:
            return self.workflow.steps.index(self)
        except ValueError:
            return -1

    @property
    def previous_step(self):
        """The step before this one, or None."""
        idx = self.step_index
        if idx <= 0 or self.workflow is None:
            return None
        return self.workflow.steps[idx - 1]

    @property
    def next_step(self):
        """The step after this one, or None."""
        idx = self.step_index
        if self.workflow is None or idx < 0 or idx >= len(self.workflow.steps) - 1:
            return None
        return self.workflow.steps[idx + 1]

    def reset(self):
        """Reset execution state for replay."""
        self.status = 'pending'
        self.output_layer_id = None
        self.error_msg = None
        self.started_at = None
        self.completed_at = None
        self.tool.status = 'idle'

    def to_dict(self):
        """Serialize step to a JSON-safe dict for saving."""
        # Serialize tool properties — convert datetime objects to ISO strings
        props = {}
        for k, v in self.tool.properties.items():
            if isinstance(v, datetime):
                props[k] = v.isoformat()
            else:
                props[k] = v

        d = {
            'id': self.id,
            'tool_id': self.tool_id,
            'tool_name': self.tool_name,
            'properties': props,
            'extent': copy.deepcopy(self.tool.extent),
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
        """Deserialize a step from a saved dict.

        Creates a new Tool instance from the registry and populates
        its properties from the saved dict.
        """
        from ..app import TOOL_REGISTRY

        tool_id = d['tool_id']
        tool_entry = next(
            (t for t in TOOL_REGISTRY if t['id'] == tool_id), None
        )
        if tool_entry is None:
            raise ValueError(f"Unknown tool_id in saved workflow: '{tool_id}'")

        tool = tool_entry['class']()
        tool.properties = dict(d.get('properties', {}))
        tool.extent = copy.deepcopy(d.get('extent'))

        step = cls(tool)
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
        idx = self.step_index
        pos = str(idx) if idx >= 0 else '?'
        return f"WorkflowStep({pos}: {self.tool_name} [{self.status}])"


class Workflow:
    """An ordered sequence of WorkflowSteps that can be saved and replayed.

    The workflow is always active — every tool action is automatically
    a step. There is no separate "recording" mode.

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

    def add_step(self, tool):
        """Append a new step wrapping the given Tool instance.

        Sets the step's workflow back-reference to this workflow.

        Args:
            tool: A Tool instance (e.g., LoadDatasetTool(), ScaleBiasTool()).

        Returns:
            The created WorkflowStep.
        """
        step = WorkflowStep(tool)
        step.workflow = self
        self.steps.append(step)
        return step

    def remove_step(self, step_index):
        """Remove a step by index."""
        if 0 <= step_index < len(self.steps):
            removed = self.steps.pop(step_index)
            removed.workflow = None

    def move_step(self, from_index, to_index):
        """Move a step from one position to another."""
        if (0 <= from_index < len(self.steps) and
                0 <= to_index < len(self.steps)):
            step = self.steps.pop(from_index)
            self.steps.insert(to_index, step)

    def reset_all(self):
        """Reset all steps to pending for a fresh replay."""
        for step in self.steps:
            step.reset()
        self.status = 'idle'

    def clone(self, new_name=None):
        """Create a deep copy of this workflow with a new ID.

        Each step gets a fresh Tool instance with copied properties.

        Args:
            new_name: Name for the clone. Defaults to 'Copy of <original>'.

        Returns:
            A new Workflow instance with copied steps.
        """
        name = new_name or f'Copy of {self.name}'
        wf = Workflow(name=name, description=self.description)
        for step in self.steps:
            tool_copy = step.tool.__class__()
            tool_copy.properties = copy.deepcopy(step.tool.properties)
            tool_copy.extent = copy.deepcopy(step.tool.extent)
            wf.add_step(tool_copy)
        return wf

    @property
    def current_step(self):
        """The currently running step, or None."""
        for step in self.steps:
            if step.status == 'running':
                return step
        return None

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
        for sd in d.get('steps', []):
            step = WorkflowStep.from_dict(sd)
            step.workflow = wf
            wf.steps.append(step)
        return wf

    def __repr__(self):
        return f"Workflow('{self.name}', {len(self.steps)} steps, {self.status})"
