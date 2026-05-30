/* tslint:disable */
/* eslint-disable */
/**
/* This file was automatically generated from pydantic models by running pydantic2ts.
/* Do not modify it by hand - just update the pydantic models and then re-run the script
*/

/**
 * Status values Hermes returns from the OAuth device-code poll endpoint.
 *
 * The wire vocabulary is whatever ``hermes_cli/web_server.py`` writes into
 * ``_oauth_sessions[session_id]['status']``. As of the 2026-04-25 audit,
 * Hermes actually emits four of the six values below (``pending``,
 * ``approved``, ``expired``, ``error``); ``denied`` and ``cancelled`` are
 * documented in the upstream comment at ``web_server.py:1410`` as part of
 * the contract and are reserved here so the backend does not need a
 * breaking change when Hermes starts emitting them.
 *
 * The platform backend translates ``approved`` to ``complete`` for the
 * Svelte frontend (see ``routers/providers.py``), but that translation is a
 * separate concern from this enum, which mirrors Hermes' own vocabulary.
 */
export type OAuthStatus = "pending" | "approved" | "denied" | "cancelled" | "expired" | "error";
/**
 * Auxiliary task names dispatched via ``POST /myah/v1/aux/{task}``.
 *
 * The wire vocabulary matches the Hermes-side allow-list at
 * ``agent/hermes/gateway/platforms/myah.py::_AUX_ALLOWED_TASKS``. Both ends
 * must agree exactly: an allow-listed task on one side that the other
 * rejects produces a 400 to the user with no fallback. Adding a new aux
 * task requires a coordinated change here AND upstream — the cross-tier
 * drift test (Phase 5) will fail otherwise.
 *
 * Today (2026-04-25) only two tasks are routed through the aux endpoint;
 * the platform-level ``AUX_DEFAULT_TASKS`` frozenset in
 * ``myah/config.py`` enumerates a broader set of *config* tasks
 * (``compression``, ``session_search``, ``approval``, ...) but those run
 * inside the agent and are not dispatched over the HTTP aux surface.
 */
export type AuxTask = "title_generation" | "follow_up_generation";
/**
 * Choices the user sends back to Hermes for ``tool.confirmation_required``.
 *
 * Dispatched by ``POST /openai/chat/confirm`` on the platform backend, then
 * forwarded to ``/myah/v1/confirm/{stream_id}`` on the per-user agent
 * container. The wire vocabulary is fixed: any string outside this enum
 * must be rejected with HTTP 400, otherwise the agent's approval state
 * machine will hang waiting for a recognised choice.
 */
export type ApprovalOption = "approve" | "deny" | "approve_session";
/**
 * Mirror of the upstream Hermes platform enum.
 *
 * Source of truth: ``agent/hermes/gateway/config.py::Platform``. Every
 * value in the upstream enum MUST appear here; the cross-tier drift test
 * in ``__tests__/test_tasks_approvals_platforms.py`` imports the upstream
 * enum at runtime and asserts set-equality with this one. When Hermes
 * adds a new platform (e.g. another bridge), bump this enum in the same
 * PR that lifts the submodule SHA — the test fails fast otherwise.
 *
 * The ``MYAH`` value is the one this platform identifies as on the wire;
 * the rest are present so that responses, status payloads, and config
 * enums can round-trip every Hermes-supported platform without losing
 * fidelity.
 */
export type HermesPlatform =
  | "local"
  | "api_server"
  | "webhook"
  | "myah"
  | "telegram"
  | "discord"
  | "slack"
  | "whatsapp"
  | "signal"
  | "mattermost"
  | "matrix"
  | "email"
  | "sms"
  | "homeassistant"
  | "dingtalk"
  | "feishu"
  | "wecom"
  | "wecom_callback"
  | "weixin"
  | "qqbot"
  | "bluebubbles";

/**
 * Inline artifact preview card attached to an assistant message.
 *
 * Replaces the legacy ``hermes:artifact`` socket event broadcast — the
 * artifact reference is now part of the message itself, so it survives
 * DB persistence + reload without re-running an SSE consumer.
 *
 * Wire source: ``hermes_stream_handler.py`` (post-run persisted-files
 * branch + the in-flight ``tool.completed`` branch). Either ``file_id``
 * (when the file was persisted into Myah storage) or ``path`` (when the
 * artifact lives only inside the agent container) MUST be present so
 * the renderer can fetch content.
 */
export interface ArtifactCardItem {
  type: "artifact_card";
  id: string;
  file_id?: string | null;
  path?: string | null;
  filename: string;
  mime?: string | null;
  mtime?: number;
  kind:
    | "xlsx"
    | "csv"
    | "docx"
    | "markdown"
    | "code"
    | "image"
    | "video"
    | "pdf"
    | "pptx"
    | "html"
    | "json"
    | "audio"
    | "text"
    | "sqlite";
  summary?: string | null;
  preview?:
    | {
        [k: string]: unknown;
      }
    | unknown[]
    | string
    | null;
  [k: string]: unknown;
}
/**
 * Root model whose fields enumerate every exported contract symbol.
 *
 * pydantic2ts walks BaseModel subclasses in this module and pulls in any
 * types they reference (including Enums and the constituent classes of
 * discriminated unions) — that's how ``OAuthStatus`` and every member of
 * :data:`HermesEvent` end up in the generated ``contract.ts``. Future
 * phases add more fields here.
 */
export interface ContractRoot {
  oauth_status: OAuthStatus;
  hermes_event:
    | MessageDeltaEvent
    | ReasoningDeltaEvent
    | ReasoningAvailableEvent
    | ToolStartedEvent
    | ToolCompletedEvent
    | ToolConfirmationRequiredEvent
    | ApprovalRequestEvent
    | ApprovalRespondedEvent
    | SecretRequiredEvent
    | SecretResolvedEvent
    | RunCompletedEvent
    | RunFailedEvent
    | RunCancelledEvent
    | StatusEvent;
  aux_task: AuxTask;
  approval_option: ApprovalOption;
  hermes_platform: HermesPlatform;
  output_item:
    | MessageItem
    | FunctionCallItem
    | FunctionCallOutputItem
    | ReasoningItem
    | CodeInterpreterItem
    | ConfirmationItem
    | SecretInputItem
    | ArtifactCardItem;
  artifact_card?: ArtifactCardItem | null;
}
/**
 * A streamed delta of visible assistant text.
 *
 * Wire source: ``myah.py::_stream_delta`` and
 * ``api_server.py::_text_cb``.
 */
export interface MessageDeltaEvent {
  event: "message.delta";
  delta: string;
  run_id?: string | null;
  stream_id?: string | null;
  timestamp?: number | null;
  [k: string]: unknown;
}
/**
 * Real-time reasoning token from the model's chain-of-thought channel.
 *
 * Wire source: ``myah.py::_reasoning`` and
 * ``api_server.py::_reasoning_cb``. Also emitted by ``_format_tool_event``
 * for the legacy ``"_thinking"`` callback shape.
 */
export interface ReasoningDeltaEvent {
  event: "reasoning.delta";
  text: string;
  run_id?: string | null;
  stream_id?: string | null;
  timestamp?: number | null;
  [k: string]: unknown;
}
/**
 * Post-hoc reasoning snapshot for XML-scratchpad models.
 *
 * Wire source: ``api_server.py::_make_run_event_callback`` and
 * ``myah.py::_format_tool_event`` (``reasoning.available`` branch).
 */
export interface ReasoningAvailableEvent {
  event: "reasoning.available";
  text: string;
  run_id?: string | null;
  stream_id?: string | null;
  timestamp?: number | null;
  [k: string]: unknown;
}
/**
 * A tool invocation has begun.
 *
 * Wire sources differ slightly between the API server and the Myah adapter:
 *
 * * ``api_server.py`` packs ``args`` as a stringified JSON snippet
 *   (``str(args)[:500]``) — pydantic accepts both ``dict`` and ``str``
 *   because ``args`` is typed as ``Any``.
 * * ``myah.py`` packs ``args`` as a ``dict`` (or ``{}``).
 *
 * The ``tool`` field is the human-facing tool name used by the agent (e.g.
 * ``shell_exec``); ``call_id`` is the upstream's correlation identifier so
 * ``tool.completed`` can be matched back to the matching ``tool.started``.
 */
export interface ToolStartedEvent {
  event: "tool.started";
  tool: string;
  call_id?: string | null;
  args?: {
    [k: string]: unknown;
  };
  preview?: string | null;
  run_id?: string | null;
  stream_id?: string | null;
  timestamp?: number | null;
  [k: string]: unknown;
}
/**
 * A tool invocation has finished (successfully or with an error).
 *
 * The ``error`` field carries a boolean flag (not the error message
 * itself); ``result`` carries the tool's stringified output, truncated by
 * the upstream emitter.
 *
 * Wire sources: ``api_server.py::_make_run_event_callback`` and
 * ``myah.py::_format_tool_event``.
 */
export interface ToolCompletedEvent {
  event: "tool.completed";
  tool: string;
  call_id?: string | null;
  args?: {
    [k: string]: unknown;
  };
  result?: {
    [k: string]: unknown;
  };
  duration?: number | null;
  error?: boolean;
  run_id?: string | null;
  stream_id?: string | null;
  timestamp?: number | null;
  [k: string]: unknown;
}
/**
 * The agent is blocked waiting for user approval of a dangerous action.
 *
 * Wire sources: ``myah.py::send_exec_approval`` and
 * ``api_server.py::_confirmation_notify`` (which forwards the approval
 * payload from ``tools.approval`` largely as-is). The ``options`` list is
 * typed as ``list[str]`` because the wire vocabulary is fixed today
 * (``approve``, ``deny``, ``approve_session``) but the formal enum lives
 * in Phase 3 of Workstream I, not here.
 */
export interface ToolConfirmationRequiredEvent {
  event: "tool.confirmation_required";
  confirmation_id?: string | null;
  action_type?: string;
  description?: string;
  options?: string[];
  metadata?: {
    [k: string]: unknown;
  };
  run_id?: string | null;
  stream_id?: string | null;
  timestamp?: number | null;
  [k: string]: unknown;
}
/**
 * The Hermes API server is waiting for a dangerous-action approval.
 *
 * Wire source: ``api_server.py::_approval_notify``. The payload starts as
 * ``tools.approval`` approval data (``command``, ``description``,
 * ``pattern_key`` and ``pattern_keys``), then the API server adds the
 * ``approval.request`` discriminator, run metadata, and the allowed
 * response choices. The platform does not currently render these API-server
 * approvals directly, but recognising the event prevents typed validation
 * from logging it as unknown when Hermes emits it.
 */
export interface ApprovalRequestEvent {
  event: "approval.request";
  command?: string | null;
  description?: string | null;
  pattern_key?: string | null;
  pattern_keys?: string[];
  choices?: string[];
  run_id?: string | null;
  stream_id?: string | null;
  timestamp?: number | null;
  [k: string]: unknown;
}
/**
 * The pending Hermes API-server approval has been resolved.
 *
 * Wire source: ``api_server.py::_handle_approval_response``. ``choice`` is
 * one of the API-server approval choices today, and ``resolved`` is the
 * number of queued approval entries released by the response.
 */
export interface ApprovalRespondedEvent {
  event: "approval.responded";
  choice?: string | null;
  resolved?: number | null;
  run_id?: string | null;
  stream_id?: string | null;
  timestamp?: number | null;
  [k: string]: unknown;
}
/**
 * The agent has paused waiting for the user to supply a secret value.
 *
 * Wire source: ``myah.py::_secret_capture_callback``.
 */
export interface SecretRequiredEvent {
  event: "secret.required";
  var_name: string;
  prompt?: string;
  help?: string;
  skill_name?: string;
  run_id?: string | null;
  stream_id?: string | null;
  timestamp?: number | null;
  [k: string]: unknown;
}
/**
 * The pending secret prompt has been answered (or timed out).
 *
 * Wire source: ``myah.py::_secret_capture_callback`` (success +
 * timeout branches). The ``status`` field carries either ``stored`` or
 * ``timeout`` today; reserved values are accepted via ``extra='allow'``.
 */
export interface SecretResolvedEvent {
  event: "secret.resolved";
  var_name: string;
  status?: string;
  run_id?: string | null;
  stream_id?: string | null;
  timestamp?: number | null;
  [k: string]: unknown;
}
/**
 * The agent run finished successfully.
 *
 * Carries optional final ``output`` text (the API server emits it; the
 * Myah adapter does not because tokens already streamed via
 * ``message.delta``), the ``usage`` accounting dict, and the Myah-only
 * ``model``/``provider`` attribution fields used for per-message badges.
 *
 * Wire sources: ``myah.py::_dispatch_message`` finally branch and
 * ``api_server.py::_run_and_close``.
 */
export interface RunCompletedEvent {
  event: "run.completed";
  output?: string | null;
  usage?: {
    [k: string]: unknown;
  } | null;
  model?: string | null;
  provider?: string | null;
  run_id?: string | null;
  stream_id?: string | null;
  timestamp?: number | null;
  [k: string]: unknown;
}
/**
 * The agent run terminated with an error.
 *
 * Wire sources: ``myah.py::_dispatch_message`` (multiple branches) and
 * ``api_server.py::_run_and_close``.
 */
export interface RunFailedEvent {
  event: "run.failed";
  error?: string;
  run_id?: string | null;
  stream_id?: string | null;
  timestamp?: number | null;
  [k: string]: unknown;
}
/**
 * The agent run was cancelled (e.g., user-initiated stop or upstream
 * asyncio.CancelledError during streaming).
 *
 * Hermes emits this from gateway/platforms/api_server.py:3122 when an
 * asyncio.CancelledError fires inside the run loop. The platform marks
 * the run as cancelled in the chat record so the UI shows a cancelled
 * state instead of leaving the message stuck mid-stream.
 */
export interface RunCancelledEvent {
  event: "run.cancelled";
  run_id?: string | null;
  stream_id?: string | null;
  timestamp?: number | null;
  [k: string]: unknown;
}
/**
 * Free-form status hint emitted by the Myah adapter.
 *
 * The platform stream handler does not currently react to ``status``
 * events — they're typed here so the new validation layer recognises
 * them as well-formed Hermes events rather than logging a warning. If
 * the platform later wants to surface them in the UI, the model is
 * already in place.
 *
 * Wire sources: ``myah.py::_status``, ``myah.py::_format_tool_event``
 * fallback branch, and ``myah.py::_handle_message`` (typing indicator).
 */
export interface StatusEvent {
  event: "status";
  text?: string | null;
  status?: string | null;
  run_id?: string | null;
  stream_id?: string | null;
  timestamp?: number | null;
  [k: string]: unknown;
}
/**
 * An assistant (or user) message item with one or more text parts.
 *
 * The ``role`` field is ``"assistant"`` for normal stream output but the
 * handler also writes user messages into the same shape when re-rendering
 * a chat from the DB. The status transitions ``in_progress`` -> ``completed``
 * when the run ends or a tool call closes the current message.
 *
 * Wire source: ``hermes_stream_handler.py:208`` (``_get_or_create_message_item``).
 */
export interface MessageItem {
  type: "message";
  id: string;
  status: "in_progress" | "completed";
  role: string;
  content: OutputTextPart[];
  [k: string]: unknown;
}
/**
 * A plain visible-text part inside an assistant message.
 *
 * Wire source: ``hermes_stream_handler.py::_get_or_create_message_item``
 * (line 213) and the streaming append loop (line 442).
 */
export interface OutputTextPart {
  type: "output_text";
  text: string;
  [k: string]: unknown;
}
/**
 * A tool invocation in the output stream.
 *
 * ``arguments`` is stored as a JSON string (not a parsed dict) because the
 * upstream handler serialises with ``json.dumps`` at
 * ``hermes_stream_handler.py:505`` to keep the wire format stable across
 * parses. Frontend code re-parses on demand.
 *
 * Wire source: ``hermes_stream_handler.py:527`` (``tool.started`` branch).
 * The status transitions ``in_progress`` -> ``completed`` (or ``failed``)
 * when the matching ``tool.completed`` event arrives.
 */
export interface FunctionCallItem {
  type: "function_call";
  id: string;
  call_id: string;
  name: string;
  arguments: string;
  status: "in_progress" | "completed" | "failed";
  [k: string]: unknown;
}
/**
 * The result of a tool invocation.
 *
 * ``status`` is typed as ``str`` (not a Literal union) because the upstream
 * handler hardcodes ``"completed"`` today but the frontend only treats it
 * as a display hint; future Hermes versions could emit other values.
 *
 * Wire source: ``hermes_stream_handler.py:552`` (``tool.completed`` branch).
 */
export interface FunctionCallOutputItem {
  type: "function_call_output";
  id: string;
  call_id: string;
  output: InputTextPart[];
  status: string;
  [k: string]: unknown;
}
/**
 * A plain text part inside a tool-result payload.
 *
 * Wire source: ``hermes_stream_handler.py::tool.completed`` branch at
 * line 555 (``output: [{'type': 'input_text', 'text': result_text}]``).
 */
export interface InputTextPart {
  type: "input_text";
  text: string;
  [k: string]: unknown;
}
/**
 * A chain-of-thought / reasoning summary item.
 *
 * The ``duration`` field is set when the reasoning block completes (either
 * by a subsequent tool call closing the in-flight reasoning at
 * ``hermes_stream_handler.py:520`` or by run completion). It is rendered as
 * the seconds shown in the ``Thought for N seconds`` chip.
 *
 * Wire source: ``hermes_stream_handler.py:635`` (``reasoning.delta``
 * branch's create-on-first-delta path).
 */
export interface ReasoningItem {
  type: "reasoning";
  id: string;
  status: "in_progress" | "completed";
  summary: SummaryTextPart[];
  duration?: number | null;
  [k: string]: unknown;
}
/**
 * A text part inside a reasoning item's summary array.
 *
 * Wire source: ``hermes_stream_handler.py::reasoning.delta`` branch at
 * line 638 (the initial empty summary entry) and append at line 644.
 */
export interface SummaryTextPart {
  type: "summary_text";
  text: string;
  [k: string]: unknown;
}
/**
 * A Myah-only legacy code-interpreter pass-through item.
 *
 * Hermes does not emit this today (the canonical tool-call flow uses
 * ``function_call`` + ``function_call_output``). The platform retains the
 * item shape because pre-Hermes message history may carry it and the
 * frontend renders it via ``CodeExecutionBlock.svelte``. Once all legacy
 * chat history is migrated this entire item type can be retired; until
 * then, the contract documents its shape.
 *
 * Wire source: ``utils/middleware.py:1994`` (legacy code-interpreter
 * branch in the OpenAI-routing path, not the Hermes path).
 */
export interface CodeInterpreterItem {
  type: "myah:code_interpreter";
  id: string;
  code: string;
  lang: string;
  status: "in_progress" | "completed";
  duration?: number | null;
  output?: CodeInterpreterOutputPayload | null;
  [k: string]: unknown;
}
/**
 * The structured payload attached to a code_interpreter item's output.
 *
 * The legacy upstream Open WebUI code-interpreter writes any of ``result``,
 * ``error``, or ``output`` into a free-form dict; the contract carries them
 * explicitly so the generated TS interface narrows correctly.
 */
export interface CodeInterpreterOutputPayload {
  result?: string | null;
  error?: string | null;
  output?: string | null;
  [k: string]: unknown;
}
/**
 * An approval card waiting on user response.
 *
 * ``status`` transitions ``pending`` -> ``resolved`` (user picked an
 * option) or ``cancelled`` (run aborted before resolution). The ``chosen``
 * field carries the option ID the user selected — its allowed values come
 * from Phase 3's ``ApprovalOption`` enum (``approve``, ``deny``,
 * ``approve_session``); typed here as ``str`` because Phase 3 had not
 * landed at the time Phase 4 was authored.
 *
 * Wire source: ``hermes_stream_handler.py:663``
 * (``tool.confirmation_required`` branch).
 */
export interface ConfirmationItem {
  type: "confirmation";
  id: string;
  confirmation_id: string;
  run_id: string;
  action_type: string;
  description: string;
  options: string[];
  metadata: {
    [k: string]: unknown;
  };
  status: "pending" | "resolved" | "cancelled";
  chosen?: string | null;
  [k: string]: unknown;
}
/**
 * A secret-prompt card waiting on user input.
 *
 * ``status`` transitions ``pending`` -> ``stored`` (user supplied the
 * secret) or ``timeout`` (poll expired). The ``help`` field carries either
 * a URL or a freeform hint string — frontends should treat it as
 * untrusted display text.
 *
 * Wire source: ``hermes_stream_handler.py:690`` (``secret.required``
 * branch). Status updates land in the same item via the
 * ``secret.resolved`` branch at line 711.
 */
export interface SecretInputItem {
  type: "secret_input";
  id: string;
  run_id: string;
  var_name: string;
  prompt: string;
  help: string;
  skill_name: string;
  status: "pending" | "stored" | "timeout";
  [k: string]: unknown;
}
