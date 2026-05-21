"""WorkflowEngine — executes and records workflow step sequences.

Runs each WorkflowStep in order, passing DataLayer outputs forward
as inputs to subsequent steps. Supports both:
  - **Replay**: Run a saved Workflow end-to-end
  - **Recording**: Capture individual tool runs into a Workflow

The engine resolves tool_id → Tool class via the TOOL_REGISTRY from app.py.
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# Tool registry lookup — maps tool_id strings to Tool classes.
# Lazily imported to avoid circular imports with app.py.
_TOOL_CLASS_MAP = None


def _get_tool_class_map():
    """Build tool_id → Tool class mapping from TOOL_REGISTRY."""
    global _TOOL_CLASS_MAP
    if _TOOL_CLASS_MAP is None:
        from ..app import TOOL_REGISTRY
        _TOOL_CLASS_MAP = {t['id']: t['class'] for t in TOOL_REGISTRY}
    return _TOOL_CLASS_MAP


class WorkflowEngine:
    """Executes workflows and records tool runs into workflows.

    Usage — replay a saved workflow:
        engine = WorkflowEngine()
        layers = engine.run(workflow)

    Usage — record user actions into a workflow:
        engine = WorkflowEngine()
        engine.start_recording('Morning correction')
        # ... user runs tools via UI ...
        engine.record_step('load_dataset', 'Load Data', props)
        engine.record_step('scale_bias', 'Scale/Bias', props, extent=geojson)
        workflow = engine.stop_recording()
        saved = workflow.to_dict()  # persist
    """

    def __init__(self):
        # Recording state
        self._recording = False
        self._active_workflow = None

        # Execution state
        self._current_step_index = -1
        self._produced_layers = []

    # =========================================================================
    # Replay — run a workflow end-to-end
    # =========================================================================

    def run(self, workflow, existing_layers=None, on_step_complete=None):
        """Execute all steps in a workflow sequentially.

        Args:
            workflow: Workflow object to execute.
            existing_layers: Optional list of DataLayer objects available
                             as inputs before the first step.
            on_step_complete: Optional callback(step_index, step, layer)
                              called after each step completes.

        Returns:
            List of DataLayer objects produced by all steps.

        Raises:
            Exception from any step — workflow.status set to 'error',
            failing step's status and error_msg are set.
        """
        tool_map = _get_tool_class_map()
        workflow.reset_all()
        workflow.status = 'running'

        # Accumulate all DataLayers produced during this run.
        # Start with any pre-existing layers the caller provides.
        all_layers = list(existing_layers) if existing_layers else []
        self._produced_layers = []
        self._current_step_index = -1

        for i, step in enumerate(workflow.steps):
            self._current_step_index = i
            step.status = 'running'
            step.started_at = datetime.now(timezone.utc)

            # Resolve Tool class from registry
            tool_class = tool_map.get(step.tool_id)
            if tool_class is None:
                step.status = 'error'
                step.error_msg = f"Unknown tool_id: '{step.tool_id}'"
                step.completed_at = datetime.now(timezone.utc)
                workflow.status = 'error'
                logger.error('Workflow step %d failed: %s', i, step.error_msg)
                raise ValueError(step.error_msg)

            try:
                layer = self._execute_step(step, tool_class, all_layers)
                all_layers.append(layer)
                self._produced_layers.append(layer)
                step.output_layer_id = str(layer.id)
                step.status = 'done'
                step.completed_at = datetime.now(timezone.utc)
                logger.info(
                    'Workflow step %d/%d done: %s → %s',
                    i + 1, len(workflow.steps), step.tool_name, layer.name,
                )
                if on_step_complete:
                    on_step_complete(i, step, layer)

            except Exception as e:
                step.status = 'error'
                step.error_msg = str(e)
                step.completed_at = datetime.now(timezone.utc)
                workflow.status = 'error'
                logger.exception('Workflow step %d failed: %s', i, e)
                raise

        workflow.status = 'done'
        workflow.last_run_at = datetime.now(timezone.utc)
        workflow.run_count += 1
        self._current_step_index = -1
        logger.info(
            'Workflow "%s" complete: %d steps, %d layers produced',
            workflow.name, len(workflow.steps), len(self._produced_layers),
        )
        return self._produced_layers

    def _execute_step(self, step, tool_class, available_layers):
        """Create and run a Tool instance for a single step.

        Args:
            step: WorkflowStep with properties and extent.
            tool_class: The Tool subclass to instantiate.
            available_layers: All DataLayers produced so far (inputs).

        Returns:
            The DataLayer produced by tool.run().
        """
        tool = tool_class()
        tool.inputs = list(available_layers)

        # Parse datetime strings back to datetime objects
        props = dict(step.properties)
        dt_str = props.get('ref_datetime', '')
        if dt_str and isinstance(dt_str, str):
            try:
                props['ref_datetime'] = datetime.fromisoformat(dt_str)
            except (ValueError, TypeError):
                props['ref_datetime'] = datetime.now(timezone.utc)

        tool.properties = props

        if step.extent:
            tool.extent = step.extent

        return tool.run()

    @property
    def current_step_index(self):
        """Index of the currently executing step, or -1 if idle."""
        return self._current_step_index

    @property
    def produced_layers(self):
        """DataLayers produced during the last run."""
        return list(self._produced_layers)

    # =========================================================================
    # Recording — capture user actions into a workflow
    # =========================================================================

    def start_recording(self, workflow_name='Recorded Workflow'):
        """Begin recording tool runs into a new Workflow.

        Args:
            workflow_name: Name for the new workflow.
        """
        from .workflow import Workflow
        self._active_workflow = Workflow(name=workflow_name)
        self._recording = True
        logger.info('Started recording workflow: %s', workflow_name)

    def record_step(self, tool_id, tool_name, properties, extent=None):
        """Record a tool execution as a new step in the active workflow.

        Call this after a tool runs successfully. The step captures the
        tool configuration so it can be replayed later.

        Args:
            tool_id: Registry key (e.g. 'load_dataset').
            tool_name: Human-readable name (e.g. 'Load Data').
            properties: Dict of tool property values as configured by user.
            extent: GeoJSON polygon or None.

        Returns:
            The created WorkflowStep, or None if not recording.
        """
        if not self._recording or self._active_workflow is None:
            return None

        # Serialize datetime objects to ISO strings for JSON compatibility
        serializable_props = {}
        for k, v in properties.items():
            if isinstance(v, datetime):
                serializable_props[k] = v.isoformat()
            else:
                serializable_props[k] = v

        step = self._active_workflow.add_step(
            tool_id=tool_id,
            tool_name=tool_name,
            properties=serializable_props,
            extent=extent,
        )
        # Mark as done since the user already ran it successfully
        step.status = 'done'
        step.completed_at = datetime.now(timezone.utc)
        logger.info(
            'Recorded step %d: %s', step.step_order, tool_name,
        )
        return step

    def stop_recording(self):
        """Stop recording and return the captured Workflow.

        Returns:
            The Workflow with all recorded steps, or None if not recording.
        """
        if not self._recording:
            return None
        wf = self._active_workflow
        self._recording = False
        self._active_workflow = None
        logger.info(
            'Stopped recording workflow "%s": %d steps captured',
            wf.name, len(wf.steps),
        )
        return wf

    def discard_recording(self):
        """Cancel recording without saving."""
        self._recording = False
        self._active_workflow = None

    @property
    def is_recording(self):
        """True if currently recording tool runs."""
        return self._recording

    @property
    def active_workflow(self):
        """The workflow being recorded, or None."""
        return self._active_workflow
