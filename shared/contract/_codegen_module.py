"""Internal facade that pydantic2ts walks to emit the TypeScript contract.

This module is read **only** by ``platform/scripts/generate-ts-contract.sh``.
Its sole job is to expose every contract symbol as a Pydantic ``BaseModel``
field so pydantic2ts picks it up. The generated TypeScript file is the
artifact frontend code imports — never import from this module at runtime.

Phase 2+ extends ``ContractRoot`` with additional fields (event union, aux
task enum, output item union, etc.) so each new contract surface flows
through codegen automatically.
"""
from __future__ import annotations

from pydantic import BaseModel

from shared.contract.enums import ApprovalOption, AuxTask, HermesPlatform, OAuthStatus
from shared.contract.events import HermesEvent
from shared.contract.output_items import ArtifactCardItem, OutputItem


class ContractRoot(BaseModel):
    """Root model whose fields enumerate every exported contract symbol.

    pydantic2ts walks BaseModel subclasses in this module and pulls in any
    types they reference (including Enums and the constituent classes of
    discriminated unions) — that's how ``OAuthStatus`` and every member of
    :data:`HermesEvent` end up in the generated ``contract.ts``. Future
    phases add more fields here.
    """

    oauth_status: OAuthStatus
    # The discriminated union pulls every concrete event class into the
    # generated TypeScript, so each Hermes event gets its own ``interface``
    # and ``ContractRoot.hermes_event`` is the union frontend code uses
    # to narrow on the ``event`` discriminator field.
    hermes_event: HermesEvent
    # Phase 3 enums. Each is emitted as a TypeScript string-literal union
    # (e.g. ``export type AuxTask = "title_generation" | ...``) by
    # pydantic2ts, exactly mirroring how ``OAuthStatus`` appears.
    aux_task: AuxTask
    approval_option: ApprovalOption
    hermes_platform: HermesPlatform
    # Phase 4 — assistant-message output items. The discriminated union
    # pulls every concrete item class into the generated TypeScript so the
    # ``HermesOutputRenderer`` (and its subcomponents) can narrow on the
    # ``type`` field. The renderer's local ``types.ts`` re-exports these
    # from ``$lib/types/contract`` under their existing TS names.
    output_item: OutputItem
    # Phase 4A — explicit ArtifactCardItem field so pydantic2ts emits the
    # interface even though the union also references it. Without an
    # explicit field reference the codegen sometimes omits constituents
    # whose names don't already match an existing TS export.
    artifact_card: 'ArtifactCardItem | None' = None
