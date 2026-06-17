"""WorkflowEngine — executes workflow step sequences.

Runs each WorkflowStep in order, passing DataLayer outputs forward
as inputs to subsequent steps. Each step's Tool instance is executed
directly — no need to reconstruct tools from saved properties.

Supports:
  - Full run: execute all steps
  - Partial run: execute up to a specific step (run_up_to)
  - Single step: execute one step with available context (run_single_step)

Design (Pat, 2026-05-24):
  - No recording mode — the workflow is always active.
  - Steps wrap Tool objects; the engine just runs them in order.
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class WorkflowEngine:
    """Executes workflows by running each step's Tool in sequence.

    Usage:
        engine = WorkflowEngine()
        # Run all steps
        layers = engine.run(workflow, existing_layers=[...])
        # Run up to step 2 (steps 0, 1, 2)
        layers = engine.run(workflow, existing_layers=[...], up_to_step=2)
        # Run a single step
        layer = engine.run_single_step(workflow, step_index=0, existing_layers=[...])
    """

    def __init__(self):
        self._produced_layers = []

    def run(self, workflow, existing_layers=None, on_step_complete=None,
            up_to_step=None):
        """Execute steps in a workflow sequentially.

        Args:
            workflow: Workflow object to execute.
            existing_layers: Optional list of DataLayer objects available
                             as inputs before the first step.
            on_step_complete: Optional callback(step_index, step, layer)
                              called after each step completes.
            up_to_step: If set, only run steps 0..up_to_step (inclusive).
                        None means run all steps.

        Returns:
            List of DataLayer objects produced by the executed steps.
        """
        last_step = up_to_step if up_to_step is not None else len(workflow.steps) - 1

        # Validate all steps that will be executed before running any
        validation_errors = []
        for i, step in enumerate(workflow.steps):
            if i > last_step:
                break
            step_errors = step.tool.validate_inputs()
            if step_errors:
                validation_errors.append(
                    f"Step {i + 1} ({step.tool_name}): {'; '.join(step_errors)}"
                )
        if validation_errors:
            raise ValueError(
                'Fix these before running:\n' + '\n'.join(validation_errors)
            )

        # Only reset steps that will be executed
        for i, step in enumerate(workflow.steps):
            if i <= last_step:
                step.reset()
        workflow.status = 'running'

        all_layers = list(existing_layers) if existing_layers else []
        self._produced_layers = []

        for i, step in enumerate(workflow.steps):
            if i > last_step:
                break

            step.status = 'running'
            step.started_at = datetime.now(timezone.utc)

            try:
                layer = self._execute_step(step, all_layers)
                all_layers.append(layer)
                self._produced_layers.append(layer)
                step.output_layer_id = str(layer.id)
                step.status = 'done'
                step.completed_at = datetime.now(timezone.utc)
                logger.info(
                    'Workflow step %d/%d done: %s -> %s',
                    i + 1, last_step + 1, step.tool_name, layer.name,
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

        # Mark done only if we ran all steps
        if last_step >= len(workflow.steps) - 1:
            workflow.status = 'done'
            workflow.run_count += 1
        else:
            workflow.status = 'idle'  # Partial run — not fully complete
        workflow.last_run_at = datetime.now(timezone.utc)
        logger.info(
            'Workflow "%s": ran steps 0-%d, %d layers produced',
            workflow.name, last_step, len(self._produced_layers),
        )
        return self._produced_layers

    def run_single_step(self, workflow, step_index, existing_layers=None,
                        on_step_complete=None):
        """Execute a single step with available context.

        Collects output layers from all prior completed steps plus
        existing_layers, then runs just the specified step.

        Args:
            workflow: Workflow object containing the step.
            step_index: Index of the step to run.
            existing_layers: External DataLayer objects available as inputs.
            on_step_complete: Optional callback(step_index, step, layer).

        Returns:
            The DataLayer produced by the step.
        """
        if step_index < 0 or step_index >= len(workflow.steps):
            raise ValueError(f'Step index {step_index} out of range')

        step = workflow.steps[step_index]

        # Validate before running
        step_errors = step.tool.validate_inputs()
        if step_errors:
            raise ValueError(
                f"Step {step_index + 1} ({step.tool_name}): "
                f"{'; '.join(step_errors)}"
            )

        step.reset()
        step.status = 'running'
        step.started_at = datetime.now(timezone.utc)

        # Build available layers: existing + outputs from prior completed steps
        all_layers = list(existing_layers) if existing_layers else []
        for i, prev_step in enumerate(workflow.steps):
            if i >= step_index:
                break
            if prev_step.output_layer_id:
                # Find the layer in existing_layers by ID
                for layer in all_layers:
                    if str(layer.id) == prev_step.output_layer_id:
                        break  # Already in the list
                # If not found in all_layers, it may have been cleaned up
                # — that's okay, the step will fail with a clear error

        try:
            layer = self._execute_step(step, all_layers)
            self._produced_layers.append(layer)
            step.output_layer_id = str(layer.id)
            step.status = 'done'
            step.completed_at = datetime.now(timezone.utc)
            logger.info(
                'Single step %d done: %s -> %s',
                step_index + 1, step.tool_name, layer.name,
            )
            if on_step_complete:
                on_step_complete(step_index, step, layer)
            return layer

        except Exception as e:
            step.status = 'error'
            step.error_msg = str(e)
            step.completed_at = datetime.now(timezone.utc)
            logger.exception('Single step %d failed: %s', step_index, e)
            raise

    def _execute_step(self, step, available_layers):
        """Run a single step's Tool with the available inputs.

        Uses a copy of properties for execution so that datetime parsing
        doesn't mutate the original strings (which the UI needs as strings
        for HTML input elements).

        Args:
            step: WorkflowStep wrapping a configured Tool.
            available_layers: All DataLayers produced so far (inputs).

        Returns:
            The DataLayer produced by tool.run().
        """
        tool = step.tool

        # Provide all available layers as inputs for tool chaining
        tool.inputs = list(available_layers)

        # Work with a copy — parse datetime strings to datetime objects
        # without mutating tool.properties (UI needs strings for inputs).
        run_props = dict(tool.properties)
        dt_str = run_props.get('ref_datetime', '')
        if dt_str and isinstance(dt_str, str):
            try:
                run_props['ref_datetime'] = datetime.fromisoformat(dt_str)
            except (ValueError, TypeError):
                run_props['ref_datetime'] = datetime.now(timezone.utc)
        elif not dt_str:
            run_props['ref_datetime'] = datetime.now(timezone.utc)

        # Resolve step references (e.g., "step:0") to actual layer names.
        # This allows Scale/Bias to reference "output of step 1" before
        # that step has run, making workflows fully self-contained.
        layer_id = run_props.get('layer_id', '')
        if layer_id and isinstance(layer_id, str) and layer_id.startswith('step:'):
            run_props['layer_id'] = self._resolve_step_reference(
                layer_id, step, available_layers
            )

        # Temporarily set parsed properties for execution, then restore
        original_props = tool.properties
        tool.properties = run_props
        try:
            result = tool.run()
        finally:
            tool.properties = original_props
        return result

    def _resolve_step_reference(self, layer_id, current_step, available_layers):
        """Resolve a 'step:N' reference to an actual layer name.

        Args:
            layer_id: String like 'step:0' or 'step:1'.
            current_step: The WorkflowStep being executed.
            available_layers: All DataLayers produced so far.

        Returns:
            The layer name string that ScaleBiasTool can match against.

        Raises:
            ValueError if the referenced step hasn't produced output.
        """
        try:
            ref_index = int(layer_id.split(':')[1])
        except (IndexError, ValueError):
            raise ValueError(f"Invalid step reference: '{layer_id}'")

        workflow = current_step.workflow
        if workflow is None or ref_index < 0 or ref_index >= len(workflow.steps):
            raise ValueError(
                f"Step reference '{layer_id}' is out of range "
                f"(workflow has {len(workflow.steps) if workflow else 0} steps)"
            )

        ref_step = workflow.steps[ref_index]
        if not ref_step.output_layer_id:
            raise ValueError(
                f"Step {ref_index + 1} ({ref_step.tool_name}) has not "
                f"produced output yet — run it first"
            )

        # Find the output layer by ID
        for layer in available_layers:
            if str(layer.id) == ref_step.output_layer_id:
                logger.info(
                    'Resolved %s -> layer "%s" (from step %d)',
                    layer_id, layer.name, ref_index + 1,
                )
                return layer.name

        raise ValueError(
            f"Output layer from step {ref_index + 1} not found in "
            f"available layers"
        )

    @property
    def produced_layers(self):
        """DataLayers produced during the last run."""
        return list(self._produced_layers)
