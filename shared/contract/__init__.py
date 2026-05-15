"""Public surface of the platform↔Hermes typed contract.

Import enums and Pydantic event models from this package. Future
Phase 3-5 work adds aux task names, approval options, output items, and
platform enums alongside ``OAuthStatus`` and the Hermes event union.
"""
from __future__ import annotations

from shared.contract.enums import (
    AUX_ALLOWED_TASKS,
    ApprovalOption,
    AuxTask,
    HermesPlatform,
    OAuthStatus,
)
from shared.contract.events import (
    HermesEvent,
    MessageDeltaEvent,
    ReasoningAvailableEvent,
    ReasoningDeltaEvent,
    RunCompletedEvent,
    RunFailedEvent,
    SecretRequiredEvent,
    SecretResolvedEvent,
    StatusEvent,
    ToolCompletedEvent,
    ToolConfirmationRequiredEvent,
    ToolStartedEvent,
)
from shared.contract.output_items import (
    CodeInterpreterItem,
    ConfirmationItem,
    FunctionCallItem,
    FunctionCallOutputItem,
    MessageItem,
    OutputItem,
    ReasoningItem,
    SecretInputItem,
)

__all__ = [
    'AUX_ALLOWED_TASKS',
    'ApprovalOption',
    'AuxTask',
    'CodeInterpreterItem',
    'ConfirmationItem',
    'FunctionCallItem',
    'FunctionCallOutputItem',
    'HermesEvent',
    'HermesPlatform',
    'MessageDeltaEvent',
    'MessageItem',
    'OAuthStatus',
    'OutputItem',
    'ReasoningAvailableEvent',
    'ReasoningDeltaEvent',
    'ReasoningItem',
    'RunCompletedEvent',
    'RunFailedEvent',
    'SecretInputItem',
    'SecretRequiredEvent',
    'SecretResolvedEvent',
    'StatusEvent',
    'ToolCompletedEvent',
    'ToolConfirmationRequiredEvent',
    'ToolStartedEvent',
]
