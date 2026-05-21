"""WorkflowStore — in-memory registry for saved and recent workflows.

Provides save, load, list, and delete operations. Workflows are stored
as dicts in memory. A future version can persist to JSON files or DB.

Usage:
    store = WorkflowStore()
    store.save(workflow)
    wf = store.load(workflow_id)
    all_wfs = store.list_all()
"""

import json
import os
import re
import logging
from datetime import datetime, timezone

from .workflow import Workflow

logger = logging.getLogger(__name__)

# Regex to validate workflow IDs (UUID format only — no path traversal).
_VALID_ID = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')

# Directory for persisted workflow JSON files.
# Use app workspaces (not public/) so workflows are not web-accessible.
_APP_DIR = os.path.dirname(os.path.dirname(__file__))
_WORKFLOW_DIR = os.path.join(_APP_DIR, 'workspaces', 'app_workspace', 'workflows')
os.makedirs(_WORKFLOW_DIR, exist_ok=True)


class WorkflowStore:
    """In-memory + file-backed store for workflows.

    Workflows are kept in memory for fast access and also written to
    JSON files in public/data/workflows/ for persistence across restarts.
    """

    def __init__(self):
        self._workflows = {}  # id → Workflow dict
        self._load_from_disk()

    def _load_from_disk(self):
        """Load any previously saved workflow JSON files."""
        if not os.path.isdir(_WORKFLOW_DIR):
            return
        for filename in os.listdir(_WORKFLOW_DIR):
            if not filename.endswith('.json'):
                continue
            filepath = os.path.join(_WORKFLOW_DIR, filename)
            try:
                with open(filepath, 'r') as f:
                    d = json.load(f)
                self._workflows[d['id']] = d
                logger.info('Loaded workflow from disk: %s', d.get('name'))
            except Exception:
                logger.warning('Failed to load workflow file: %s', filepath)

    def save(self, workflow):
        """Save a workflow (in memory and to disk).

        Args:
            workflow: Workflow object or dict from workflow.to_dict().
        """
        if isinstance(workflow, Workflow):
            d = workflow.to_dict()
        else:
            d = dict(workflow)

        # Validate ID format to prevent path traversal
        wf_id = d.get('id', '')
        if not _VALID_ID.match(wf_id):
            logger.error('Invalid workflow ID rejected: %s', wf_id)
            return

        d['saved_at'] = datetime.now(timezone.utc).isoformat()
        self._workflows[wf_id] = d

        # Write to disk
        filepath = os.path.join(_WORKFLOW_DIR, f"{wf_id}.json")
        try:
            with open(filepath, 'w') as f:
                json.dump(d, f, indent=2, default=str)
            logger.info('Saved workflow to %s', filepath)
        except Exception:
            logger.exception('Failed to save workflow to disk')

    def load(self, workflow_id):
        """Load a workflow by ID.

        Args:
            workflow_id: UUID string.

        Returns:
            Workflow object, or None if not found.
        """
        d = self._workflows.get(workflow_id)
        if d is None:
            return None
        return Workflow.from_dict(d)

    def list_all(self):
        """Return summary list of all saved workflows, newest first.

        Returns:
            List of dicts with keys: id, name, description, step_count,
            status, created_at, last_run_at, run_count, saved_at.
        """
        summaries = []
        for wf_id, d in self._workflows.items():
            summaries.append({
                'id': d['id'],
                'name': d.get('name', 'Untitled'),
                'description': d.get('description', ''),
                'step_count': len(d.get('steps', [])),
                'status': d.get('status', 'idle'),
                'created_at': d.get('created_at'),
                'last_run_at': d.get('last_run_at'),
                'run_count': d.get('run_count', 0),
                'saved_at': d.get('saved_at'),
            })
        summaries.sort(key=lambda s: s.get('saved_at') or '', reverse=True)
        return summaries

    def delete(self, workflow_id):
        """Delete a workflow by ID (from memory and disk).

        Returns:
            True if deleted, False if not found.
        """
        if not _VALID_ID.match(workflow_id):
            return False
        if workflow_id not in self._workflows:
            return False
        del self._workflows[workflow_id]

        filepath = os.path.join(_WORKFLOW_DIR, f"{workflow_id}.json")
        if os.path.exists(filepath):
            os.remove(filepath)
            logger.info('Deleted workflow file: %s', filepath)
        return True

    def __len__(self):
        return len(self._workflows)
