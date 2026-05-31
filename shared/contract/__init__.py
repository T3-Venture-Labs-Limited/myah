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
    ApprovalRequestEvent,
    ApprovalRespondedEvent,
    HermesEvent,
    MessageDeltaEvent,
    ReasoningAvailableEvent,
    ReasoningDeltaEvent,
    RunCancelledEvent,
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
    TodoPlanEntry,
    TodoPlanItem,
)
from shared.contract.routes import (
    HermesJob,
    HermesJobGetResponse,
    HermesJobRunResponse,
    HermesJobsListResponse,
    MyahConfirmRequest,
    MyahConfirmResponse,
    MyahMessageRequest,
    MyahMessageResponse,
    MyahSecretRequest,
    MyahSecretResponse,
)

__all__ = [
    'AUX_ALLOWED_TASKS',
    'ApprovalRequestEvent',
    'ApprovalOption',
    'ApprovalRespondedEvent',
    'AuxTask',
    'CodeInterpreterItem',
    'ConfirmationItem',
    'FunctionCallItem',
    'FunctionCallOutputItem',
    'HermesEvent',
    'HermesJob',
    'HermesJobGetResponse',
    'HermesJobRunResponse',
    'HermesJobsListResponse',
    'HermesPlatform',
    'MessageDeltaEvent',
    'MessageItem',
    'MyahConfirmRequest',
    'MyahConfirmResponse',
    'MyahMessageRequest',
    'MyahMessageResponse',
    'MyahSecretRequest',
    'MyahSecretResponse',
    'OAuthStatus',
    'OutputItem',
    'ReasoningAvailableEvent',
    'ReasoningDeltaEvent',
    'ReasoningItem',
    'RunCancelledEvent',
    'RunCompletedEvent',
    'RunFailedEvent',
    'SecretInputItem',
    'SecretRequiredEvent',
    'SecretResolvedEvent',
    'StatusEvent',
    'TodoPlanEntry',
    'TodoPlanItem',
    'ToolCompletedEvent',
    'ToolConfirmationRequiredEvent',
    'ToolStartedEvent',
]
