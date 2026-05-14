# Named composition registry and $field expansion.
# Each composition is a template whose leaf string values starting with '$'
# are replaced by matching keys from the caller-supplied data dict.
# Unknown keys keep their $field placeholder intact.

import copy
import logging
from typing import Optional

logger = logging.getLogger(__name__)

BUILTIN_COMPOSITIONS: dict[str, dict] = {
    'approval_card': {
        'blocks': [
            {'type': 'text', 'content': '$action'},
            {'type': 'alert', 'variant': 'info', 'content': '$rationale'},
            {'type': 'alert', 'variant': 'warning', 'content': '$risks'},
            {'type': 'actions', 'items': '$options'},
        ]
    },
    # kpi_dashboard is handled specially in expand_composition() because its
    # data dict contains nested objects (chart, table) that map directly to
    # block properties rather than simple $field placeholders.
    'kpi_dashboard': {'blocks': []},
    'triage_table': {
        'blocks': [
            {'type': 'badge', 'label': '$statusLabel', 'variant': '$statusVariant'},
            {'type': 'table', 'columns': '$columns', 'rows': '$rows'},
            {'type': 'actions', 'items': '$bulkActions'},
        ]
    },
    'form_wizard': {
        'blocks': [
            {'type': 'stepper', 'steps': '$steps', 'current': '$currentStep'},
            {
                'type': 'form',
                'id': '$formId',
                'fields': '$fields',
                'submitLabel': '$submitLabel',
                'submitAction': '$submitAction',
            },
        ]
    },
    'comparison_view': {
        'blocks': [
            {'type': 'columns', 'blocks': '$columnBlocks'},
        ]
    },
    'activity_feed': {
        'blocks': [
            {'type': 'entries', 'items': '$items'},
            {'type': 'actions', 'items': '$actions'},
        ]
    },
    # Agent shows a received message with its draft reply and action buttons
    # so the user can approve, edit, or discard before it's sent.
    'email_reply': {
        'blocks': [
            {
                'type': 'card',
                'title': '$subject',
                'blocks': [
                    {'type': 'avatar', 'name': '$from', 'subtitle': '$from_email'},
                    {'type': 'divider'},
                    {'type': 'text', 'content': '$original_message'},
                ],
            },
            {
                'type': 'card',
                'title': 'Draft Reply',
                'blocks': [
                    {'type': 'text', 'content': '$draft_reply'},
                ],
            },
            {
                'type': 'actions',
                'items': '$reply_actions',
            },
        ]
    },
    # Agent requests API keys / credentials the user needs to provide
    # before it can continue an operation.
    'env_vars_form': {
        'blocks': [
            {'type': 'alert', 'variant': 'info', 'message': '$description'},
            {
                'type': 'form',
                'id': '$form_id',
                'fields': '$fields',
                'submitLabel': 'Save & Continue',
                'submitAction': 'env_vars_submit',
            },
        ]
    },
}


class CompositionRegistry:
    """Registry for composition templates that supports dynamic registration."""

    def __init__(self):
        self._compositions: dict[str, dict] = {}

    def register(self, name: str, template: dict) -> None:
        """Register a new composition. Skills call this at startup."""
        self._compositions[name] = template
        logger.info(f'Registered composition "{name}"', extra={'composition': name})

    def get(self, name: str) -> Optional[dict]:
        """Get a composition by name. Returns None if not found."""
        return self._compositions.get(name)

    def list_all(self) -> list[str]:
        """List all registered composition names."""
        return list(self._compositions.keys())

    def clear(self) -> None:
        """Clear all compositions. Used in tests."""
        self._compositions.clear()


# Global registry instance
registry = CompositionRegistry()

# Seed built-in compositions
for name, template in BUILTIN_COMPOSITIONS.items():
    registry.register(name, template)


def _expand_value(value: object, data: dict) -> object:
    """Recursively replace $field placeholder strings with data values.

    - Strings starting with '$' are replaced by the matching data key.
    - Dicts are recursively expanded field-by-field.
    - Lists are recursively expanded element-by-element.
    - Other values are returned unchanged.
    """
    if isinstance(value, str) and value.startswith('$'):
        key = value[1:]
        return data.get(key, value)
    if isinstance(value, dict):
        return {k: _expand_value(v, data) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_value(item, data) for item in value]
    return value


def expand_composition(name: str, data: dict) -> dict:
    """Expand a named composition template with caller-supplied data.

    Recursively replaces all $field placeholder strings throughout the
    entire block tree (including nested ``blocks`` arrays in layout blocks).

    Args:
        name: Key in registry (built-in or skill-registered).
        data: Dict whose keys match the $field placeholders in the template.

    Returns:
        A deep copy of the template with all $field strings replaced.
    """
    template = registry.get(name)
    if template is None:
        # Unknown compositions render a plain text block rather than raising,
        # so the frontend always receives a valid payload.
        return {'blocks': [{'type': 'text', 'content': f'Unknown composition: {name}'}]}

    # ── Compositions with nested data need special handling ───────────────
    # The $field placeholder system only works for flat key→value mappings.
    # Compositions whose data contains nested objects (lists of dicts, sub-
    # objects that map to block properties) are built directly here.

    if name == 'kpi_dashboard':
        blocks: list = []
        metrics = data.get('metrics')
        if isinstance(metrics, list) and metrics:
            blocks.append({'type': 'metrics', 'items': metrics})
        chart = data.get('chart')
        if isinstance(chart, dict):
            blocks.append(
                {
                    'type': 'chart',
                    'chartType': chart.get('chartType', 'bar'),
                    'labels': chart.get('labels', []),
                    'datasets': chart.get('datasets', []),
                    'title': chart.get('title', ''),
                    'description': chart.get('description', ''),
                }
            )
        table = data.get('table')
        if isinstance(table, dict):
            blocks.append(
                {
                    'type': 'table',
                    'columns': table.get('columns', []),
                    'rows': table.get('rows', []),
                }
            )
        return {'blocks': blocks}

    if name == 'form_wizard':
        blocks = []
        steps = data.get('steps', [])
        current_step = data.get('currentStep', 0)
        if isinstance(steps, list) and steps:
            # Stepper progress indicator
            stepper_steps = [
                {
                    'label': s.get('label', f'Step {i + 1}'),
                    'status': 'complete' if i < current_step else 'active' if i == current_step else 'pending',
                }
                for i, s in enumerate(steps)
            ]
            blocks.append({'type': 'stepper', 'steps': stepper_steps})
            # Form for the current step
            if 0 <= current_step < len(steps):
                step = steps[current_step]
                fields = step.get('fields', [])
                blocks.append(
                    {
                        'type': 'form',
                        'id': f'form_wizard_step_{current_step}',
                        'fields': fields,
                        'submitLabel': 'Next' if current_step < len(steps) - 1 else 'Submit',
                        'submitAction': 'form_wizard_next',
                    }
                )
        return {'blocks': blocks}

    if name == 'env_vars_form':
        blocks = []
        description = data.get('description', '')
        if description:
            blocks.append({'type': 'alert', 'variant': 'info', 'message': description})
        service = data.get('service', '')
        if service and not description:
            blocks.append(
                {
                    'type': 'alert',
                    'variant': 'info',
                    'message': f'Please provide your {service} credentials to continue.',
                }
            )
        fields = data.get('fields', [])
        # Default field type to 'password' for credential inputs
        for f in fields:
            if 'type' not in f:
                f['type'] = 'password'
        blocks.append(
            {
                'type': 'form',
                'id': data.get('form_id', 'env_vars'),
                'fields': fields,
                'submitLabel': 'Save & Continue',
                'submitAction': 'env_vars_submit',
            }
        )
        return {'blocks': blocks}

    if name == 'approval_card':
        blocks = []
        title = data.get('title', '')
        description = data.get('description', data.get('action', ''))
        risk = data.get('risk', data.get('risks', ''))
        actions = data.get('actions', data.get('options', []))
        if title:
            blocks.append({'type': 'text', 'content': title})
        if description:
            blocks.append({'type': 'alert', 'variant': 'info', 'content': description})
        if risk:
            blocks.append({'type': 'alert', 'variant': 'warning', 'content': risk})
        if isinstance(actions, list) and actions:
            blocks.append({'type': 'actions', 'items': actions})
        return {'blocks': blocks}

    if name == 'triage_table':
        blocks = []
        items = data.get('items', [])
        if isinstance(items, list) and items:
            # Summary badge
            urgent = [i for i in items if str(i.get('status', '')).lower() in ('urgent', 'high', 'critical')]
            label = f'{len(items)} item{"s" if len(items) != 1 else ""}'
            if urgent:
                label += f', {len(urgent)} urgent'
            blocks.append({'type': 'badge', 'label': label, 'variant': 'warning' if urgent else 'info'})
            # Table
            blocks.append(
                {
                    'type': 'table',
                    'columns': ['#', 'Summary', 'Status', 'Action'],
                    'rows': [
                        [str(it.get('id', i + 1)), it.get('summary', ''), it.get('status', ''), it.get('action', '')]
                        for i, it in enumerate(items)
                    ],
                }
            )
        bulk_actions = data.get('bulkActions', data.get('actions', []))
        if isinstance(bulk_actions, list) and bulk_actions:
            blocks.append({'type': 'actions', 'items': bulk_actions})
        return {'blocks': blocks}

    if name == 'comparison_view':
        blocks = []
        options = data.get('options', [])
        if isinstance(options, list) and options:
            # ColumnsBlock expects blocks = [[col1_block1, col1_block2, ...], [col2_block1, ...]]
            # Each column is an array of blocks
            col_arrays: list = []
            for opt in options:
                title = opt.get('title', '')
                features = opt.get('features', [])
                price = opt.get('price', '')
                card_blocks: list = []
                if price:
                    card_blocks.append({'type': 'badge', 'label': price, 'variant': 'info'})
                if isinstance(features, list) and features:
                    card_blocks.append(
                        {
                            'type': 'entries',
                            'items': [{'label': f, 'value': '✓'} for f in features],
                        }
                    )
                # Each column is an array: [card_block]
                col_arrays.append([{'type': 'card', 'title': title, 'blocks': card_blocks}])
            blocks.append({'type': 'columns', 'blocks': col_arrays})
        return {'blocks': blocks}

    if name == 'activity_feed':
        blocks = []
        entries = data.get('entries', data.get('items', []))
        if isinstance(entries, list) and entries:
            blocks.append(
                {
                    'type': 'entries',
                    'items': [
                        {
                            'label': e.get('action', e.get('title', '')),
                            'value': e.get('time', ''),
                            'description': e.get('detail', e.get('description', '')),
                            'status': e.get('status', ''),
                        }
                        for e in entries
                    ],
                }
            )
        actions = data.get('actions', [])
        if isinstance(actions, list) and actions:
            blocks.append({'type': 'actions', 'items': actions})
        return {'blocks': blocks}

    if name == 'email_reply':
        blocks = []
        # Original message card
        original_blocks = []
        if data.get('from') or data.get('from_email'):
            original_blocks.append(
                {
                    'type': 'avatar',
                    'name': data.get('from', 'Sender'),
                    'subtitle': data.get('from_email', ''),
                }
            )
        if data.get('original_message'):
            original_blocks.append({'type': 'divider'})
            original_blocks.append({'type': 'text', 'content': data['original_message']})
        if original_blocks:
            blocks.append(
                {
                    'type': 'card',
                    'title': data.get('subject', 'Message'),
                    'blocks': original_blocks,
                }
            )
        # Draft reply card
        if data.get('draft_reply'):
            blocks.append(
                {
                    'type': 'card',
                    'title': 'Draft Reply',
                    'blocks': [{'type': 'text', 'content': data['draft_reply']}],
                }
            )
        # Action buttons
        reply_actions = data.get('reply_actions', ['Send', 'Edit', 'Discard'])
        blocks.append({'type': 'actions', 'items': reply_actions})
        return {'blocks': blocks}

    # ──────────────────────────────────────────────────────────────────────

    expanded = copy.deepcopy(template)

    expanded['blocks'] = [_expand_value(block, data) for block in expanded.get('blocks', [])]

    return expanded
