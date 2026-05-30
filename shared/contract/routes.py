"""Pydantic contracts for high-risk Myah↔Hermes HTTP route shapes.

These models intentionally stay Python-only for this slice: they verify
provider/adapter payloads at the route boundary, while the frontend already
owns its local request/response types for these endpoints. Do not add them to
``_codegen_module.py`` until a frontend import needs the generated TypeScript
surface.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MyahMessageRequest(BaseModel):
    """Request body sent by the platform to the Myah plugin adapter."""

    model_config = ConfigDict(extra='allow')

    message: str
    session_id: str
    user_id: str
    message_id: str
    user_name: str | None = None
    chat_name: str | None = None
    ui_state: dict[str, Any] | None = None
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    model: str | None = None
    provider: str | None = None


class MyahMessageResponse(BaseModel):
    """Immediate response from ``/myah/v1/message`` before SSE streaming."""

    model_config = ConfigDict(extra='allow')

    stream_id: str
    session_id: str | None = None


class MyahConfirmRequest(BaseModel):
    """User confirmation forwarded to a blocked plugin/tool call."""

    model_config = ConfigDict(extra='allow')

    confirmation_id: str | None = None
    choice: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class MyahConfirmResponse(BaseModel):
    """Confirmation acknowledgement from the plugin adapter."""

    model_config = ConfigDict(extra='allow')

    ok: bool = True
    status: str | None = None


class MyahSecretRequest(BaseModel):
    """Secret value forwarded to the plugin after a ``secret.required`` event."""

    model_config = ConfigDict(extra='allow')

    var_name: str
    value: str | None = None
    secret: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MyahSecretResponse(BaseModel):
    """Secret submission acknowledgement from the plugin adapter."""

    model_config = ConfigDict(extra='allow')

    ok: bool = True
    status: str | None = None


class HermesJob(BaseModel):
    """Representative Hermes cron job shape consumed by the process routes."""

    model_config = ConfigDict(extra='allow')

    id: str
    name: str | None = None
    schedule: str | None = None
    enabled: bool | None = None
    status: str | None = None
    last_run: Any = None
    next_run: Any = None
    origin: dict[str, Any] | None = None
    myah: dict[str, Any] | None = None
    chat_id: str | None = None
    deliver: str | None = None
    repeat: bool | int | None = None
    skills: list[str] = Field(default_factory=list)


class HermesJobsListResponse(BaseModel):
    """Raw Hermes ``GET /api/jobs`` response, before platform unwrapping."""

    model_config = ConfigDict(extra='allow')

    jobs: list[HermesJob]


class HermesJobGetResponse(BaseModel):
    """Raw Hermes ``GET /api/jobs/{id}`` response, before platform unwrapping."""

    model_config = ConfigDict(extra='allow')

    job: HermesJob


class HermesJobRunResponse(BaseModel):
    """Raw Hermes ``POST /api/jobs/{id}/run`` response."""

    model_config = ConfigDict(extra='allow')

    ok: bool | None = None
    job: HermesJob | None = None
    run_id: str | None = None


__all__ = [
    'HermesJob',
    'HermesJobGetResponse',
    'HermesJobRunResponse',
    'HermesJobsListResponse',
    'MyahConfirmRequest',
    'MyahConfirmResponse',
    'MyahMessageRequest',
    'MyahMessageResponse',
    'MyahSecretRequest',
    'MyahSecretResponse',
]
