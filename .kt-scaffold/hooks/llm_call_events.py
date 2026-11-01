#!/usr/bin/env python3
"""Normalize native lifecycle observations without retaining conversation content.

This module does not select a latest session, contact a model, or write files. From the
client's own session log it reads only the active model and effort, never conversation
content. Native hooks expose lifecycle observations, not every internal model request or
retry. A tool failure is never promoted to proof of a model API failure.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

CLIENTS = ("claude-code", "codex", "github-copilot-vscode", "cursor")
MAX_NATIVE_CORRELATION_BYTES = 4096
MAX_DURATION_MS = 604_800_000
INVALID_EVENT = "Invalid lifecycle event metadata."
CORRELATION_SOURCES = ("client-envelope", "local-generated-client-unavailable")
MODEL_SOURCES = ("native-event-observed", "client-log-observed", "unavailable")
MODEL_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,159}")
EFFORT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}")
UNAVAILABLE_MODEL: dict[str, object] = {"source": "unavailable", "id": None, "effort": None}
# Only the newest entries of the client's session log are read for the active model.
MAX_SESSION_LOG_TAIL_BYTES = 1024 * 1024
# Cursor's documented model parameters, most specific first.
CURSOR_EFFORT_PARAMETERS = ("effort", "reasoning_effort", "thinking")
SUPPORTED_NATIVE_EVENTS = {
    "claude-code": (
        "UserPromptSubmit",
        "Stop",
        "StopFailure",
        "SubagentStart",
        "SubagentStop",
        "PreToolUse",
        "PostToolUse",
        "PostToolUseFailure",
    ),
    # Existing native prompt ingress is the only Codex event adapted here.
    "codex": ("UserPromptSubmit",),
    "github-copilot-vscode": (
        "UserPromptSubmit",
        "Stop",
        "SubagentStart",
        "SubagentStop",
        "PreToolUse",
        "PostToolUse",
    ),
    "cursor": (
        "beforeSubmitPrompt",
        "stop",
        "subagentStart",
        "subagentStop",
        "preToolUse",
        "postToolUse",
        "postToolUseFailure",
    ),
}
ERROR_SUMMARIES = {
    "rate-limit": "The provider reported a rate limit.",
    "overloaded": "The provider reported unavailable capacity.",
    "authentication": "The provider rejected authentication.",
    "authorization": "The provider rejected authorization.",
    "billing": "The provider rejected account or billing state.",
    "invalid-request": "The provider rejected the request.",
    "model-unavailable": "The requested model was unavailable.",
    "provider-error": "The provider reported an API error.",
    "output-limit": "The provider reported an output limit.",
    "timeout": "The observed operation timed out.",
    "permission-denied": "The observed operation was denied.",
    "tool-error": "The client reported a tool failure.",
    "cancelled": "The client reported cancellation.",
    "unknown": "The client reported a failure without a supported error classification.",
}
CLAUDE_ERRORS = {
    "rate_limit": "rate-limit",
    "overloaded": "overloaded",
    "authentication_failed": "authentication",
    "oauth_org_not_allowed": "authorization",
    "account_on_hold": "billing",
    "billing_error": "billing",
    "invalid_request": "invalid-request",
    "model_not_found": "model-unavailable",
    "server_error": "provider-error",
    "max_output_tokens": "output-limit",
    "cloud_credential_error": "authentication",
    "unknown": "unknown",
}
EVENT_KEYS = frozenset(
    {
        "schema_version",
        "kind",
        "project_id",
        "client_id",
        "event_id",
        "invocation_id",
        "observed_at",
        "run_id",
        "trace_context",
        "prompt_session_id",
        "prompt_session_id_source",
        "prompt_turn_id",
        "prompt_turn_id_source",
        "agent_ref",
        "native_call_ref",
        "native_call_ref_source",
        "hook_event_name",
        "evidence_scope",
        "call_scope",
        "status",
        "error",
        "duration_ms",
        "raw_content_recorded",
        "complete_llm_attempt_coverage",
        "model",
    }
)


def _invalid() -> ValueError:
    return ValueError(INVALID_EVENT)


def _token() -> str:
    token = secrets.token_hex(16)
    while token == "0" * 32:
        token = secrets.token_hex(16)
    return token


def _native_digest(event: dict[str, object], keys: tuple[str, ...]) -> tuple[str | None, str]:
    for key in keys:
        value = event.get(key)
        if value is None or value == "":
            continue
        if not isinstance(value, str) or "\x00" in value:
            raise _invalid()
        try:
            encoded = value.encode("utf-8")
        except UnicodeError:
            raise _invalid() from None
        if len(encoded) > MAX_NATIVE_CORRELATION_BYTES:
            raise _invalid()
        return hashlib.sha256(encoded).hexdigest(), key
    return None, "unavailable"


def _model_value(value: object, pattern: re.Pattern[str]) -> str | None:
    return value if isinstance(value, str) and pattern.fullmatch(value) is not None else None


def _session_log_model(path: object, client_id: str) -> tuple[str | None, str | None]:
    """Return the newest model and effort the client wrote to its own session log."""
    if not isinstance(path, str) or not path or "\x00" in path:
        return None, None
    log = Path(path)
    if not log.is_absolute() or log.is_symlink() or not log.is_file():
        return None, None
    size = log.stat().st_size
    with log.open("rb") as handle:
        if size > MAX_SESSION_LOG_TAIL_BYTES:
            handle.seek(size - MAX_SESSION_LOG_TAIL_BYTES)
            handle.readline()
        lines = handle.read().splitlines()
    for raw in reversed(lines):
        try:
            entry = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        if client_id == "codex" and entry.get("type") == "turn_context":
            payload = entry.get("payload")
            if isinstance(payload, dict):
                model = _model_value(payload.get("model"), MODEL_ID_RE)
                if model is not None:
                    return model, _model_value(payload.get("effort"), EFFORT_RE)
        if client_id == "claude-code" and entry.get("type") == "assistant":
            message = entry.get("message")
            if isinstance(message, dict):
                model = _model_value(message.get("model"), MODEL_ID_RE)
                if model is not None:
                    return model, None
    return None, None


def _observed_model(event: dict[str, object], client_id: str) -> dict[str, object]:
    model: str | None = None
    source = "unavailable"
    if client_id == "cursor":
        model = _model_value(event.get("model_id"), MODEL_ID_RE) or _model_value(
            event.get("model"), MODEL_ID_RE
        )
    elif client_id in ("codex", "claude-code"):
        model = _model_value(event.get("model"), MODEL_ID_RE)
    if model is not None:
        source = "native-event-observed"
    effort: str | None = None
    if client_id == "claude-code":
        native_effort = event.get("effort")
        if isinstance(native_effort, dict):
            effort = _model_value(native_effort.get("level"), EFFORT_RE)
    elif client_id == "cursor":
        parameters = event.get("model_params")
        values = (
            {item.get("id"): item.get("value") for item in parameters if isinstance(item, dict)}
            if isinstance(parameters, list)
            else {}
        )
        for name in CURSOR_EFFORT_PARAMETERS:
            effort = _model_value(values.get(name), EFFORT_RE)
            if effort is not None:
                break
    if client_id in ("codex", "claude-code") and (model is None or effort is None):
        log_model, log_effort = _session_log_model(event.get("transcript_path"), client_id)
        if model is None and log_model is not None:
            model, source = log_model, "client-log-observed"
        if effort is None and log_model == model:
            effort = log_effort
    if model is None:
        return dict(UNAVAILABLE_MODEL)
    return {"source": source, "id": model, "effort": effort}


def observed_model(event: object, client_id: str) -> dict[str, object]:
    """Return the model and effort the client reports for this hook event.

    Codex and Cursor carry the model in every hook event, Claude Code in its session log;
    VS Code/Copilot does not report it. A value that cannot be observed stays unavailable
    and is never guessed. Observation never raises, so it cannot change a hook decision.
    """
    if not isinstance(event, dict) or client_id not in CLIENTS:
        return dict(UNAVAILABLE_MODEL)
    try:
        return _observed_model(event, client_id)
    except Exception:
        return dict(UNAVAILABLE_MODEL)


def validate_model(model: object) -> None:
    """Validate one observed model record."""
    if not isinstance(model, dict) or set(model) != {"source", "id", "effort"}:
        raise _invalid()
    source = model["source"]
    if source not in MODEL_SOURCES:
        raise _invalid()
    if source == "unavailable":
        if model["id"] is not None or model["effort"] is not None:
            raise _invalid()
        return
    if _model_value(model["id"], MODEL_ID_RE) is None:
        raise _invalid()
    if model["effort"] is not None and _model_value(model["effort"], EFFORT_RE) is None:
        raise _invalid()


def _correlation(digest: str | None, prefix: str, token: str) -> tuple[str, str]:
    if digest is not None:
        return f"{prefix}:client.{digest}", CORRELATION_SOURCES[0]
    return f"{prefix}:local.{token}", CORRELATION_SOURCES[1]


def _error(error_class: str, origin: str) -> dict[str, str]:
    return {"class": error_class, "summary": ERROR_SUMMARIES[error_class], "origin": origin}


def _native_outcome(
    event: dict[str, object], client_id: str, name: str
) -> tuple[str, str, dict[str, str] | None]:
    lower = name.lower()
    if lower in ("userpromptsubmit", "beforesubmitprompt"):
        return "started", "prompt-submission", None
    if lower == "subagentstart":
        return "started", "subagent-lifecycle", None
    if lower == "pretooluse":
        return "started", "tool-lifecycle", None
    if lower == "posttooluse":
        return "completed", "tool-lifecycle", None
    if lower == "stopfailure":
        error = event.get("error")
        if not isinstance(error, str):
            raise _invalid()
        return "failed", "turn-lifecycle", _error(CLAUDE_ERRORS.get(error, "unknown"), "llm-api")
    if lower == "posttoolusefailure":
        interrupt = event.get("is_interrupt", False)
        if type(interrupt) is not bool:
            raise _invalid()
        error_class = "tool-error"
        if client_id == "cursor":
            failure_type = event.get("failure_type")
            if not isinstance(failure_type, str) or failure_type not in (
                "error",
                "timeout",
                "permission_denied",
            ):
                raise _invalid()
            error_class = {
                "error": "tool-error",
                "timeout": "timeout",
                "permission_denied": "permission-denied",
            }[failure_type]
        if interrupt:
            return "cancelled", "tool-lifecycle", _error("cancelled", "tool")
        return "failed", "tool-lifecycle", _error(error_class, "tool")
    scope = "subagent-lifecycle" if lower == "subagentstop" else "turn-lifecycle"
    if client_id == "cursor":
        status = event.get("status")
        if not isinstance(status, str) or status not in ("completed", "error", "aborted"):
            raise _invalid()
        if status == "error":
            return "failed", scope, _error("unknown", "client-unspecified")
        if status == "aborted":
            return "cancelled", scope, _error("cancelled", "client-unspecified")
    return "completed", scope, None


def normalize_event(event: object, *, client_id: str, project_id: str) -> dict[str, object]:
    """Return one strict metadata observation; reject unsupported or malformed inputs.

    ``invocation_id`` identifies this hook execution, not an inferred provider
    attempt. Repeated delivered events receive separate IDs. Only native references
    may link different observations; a missing native turn remains explicitly local.
    """
    if not isinstance(event, dict) or client_id not in CLIENTS:
        raise _invalid()
    if not isinstance(project_id, str) or not re.fullmatch(
        r"project-(?!0{32}$)[0-9a-f]{32}", project_id
    ):
        raise _invalid()
    name = event.get("hook_event_name")
    if not isinstance(name, str) or name not in SUPPORTED_NATIVE_EVENTS[client_id]:
        raise _invalid()
    if "stop_hook_active" in event and type(event["stop_hook_active"]) is not bool:
        raise _invalid()
    session_digest, _ = _native_digest(event, ("session_id", "conversation_id", "chat_id"))
    turn_digest, _ = _native_digest(
        event, ("prompt_id", "turn_id", "request_id", "message_id", "generation_id")
    )
    agent_digest, _ = _native_digest(event, ("agent_id", "subagent_id"))
    call_digest, call_source = _native_digest(event, ("tool_use_id", "tool_call_id", "request_id"))
    if name in ("SubagentStart", "SubagentStop", "subagentStart") and agent_digest is None:
        raise _invalid()
    status, evidence_scope, error = _native_outcome(event, client_id, name)
    duration: object = event.get("duration_ms", event.get("duration"))
    if duration is not None and (type(duration) is not int or not 0 <= duration <= MAX_DURATION_MS):
        raise _invalid()
    invocation_token = _token()
    session_id, session_source = _correlation(session_digest, "session", _token())
    turn_id, turn_source = _correlation(turn_digest, "turn", invocation_token)
    observation: dict[str, object] = {
        "schema_version": "1.0",
        "kind": "LLMCallEvent",
        "project_id": project_id,
        "client_id": client_id,
        "event_id": f"event:{_token()}",
        "invocation_id": f"invocation:{invocation_token}",
        "observed_at": datetime.now(timezone.utc)  # noqa: UP017 - generated hook supports Python 3.9.
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
        "run_id": None,
        "trace_context": None,
        "prompt_session_id": session_id,
        "prompt_session_id_source": session_source,
        "prompt_turn_id": turn_id,
        "prompt_turn_id_source": turn_source,
        "agent_ref": f"agent:sha256:{agent_digest}" if agent_digest is not None else None,
        "native_call_ref": f"call:sha256:{call_digest}" if call_digest is not None else None,
        "native_call_ref_source": call_source,
        "hook_event_name": name,
        "evidence_scope": evidence_scope,
        "call_scope": "subagent"
        if agent_digest is not None or "subagent" in name.lower()
        else "main",
        "status": status,
        "error": error,
        "duration_ms": duration,
        "raw_content_recorded": False,
        "complete_llm_attempt_coverage": False,
        "model": observed_model(event, client_id),
    }
    validate_event(observation)
    return observation


def event_from_prompt_receipt(receipt: object) -> dict[str, object] | None:
    """Observe allowed prompt preparation using the ingress hook's existing IDs.

    A blocked prompt produces no call-start observation. The receipt remains its
    audit record. Preparing an allowed prompt does not prove a provider call began.
    """
    if not isinstance(receipt, dict) or receipt.get("kind") != "PromptIngressReceipt":
        raise _invalid()
    decision = receipt.get("decision")
    outcome = receipt.get("outcome")
    if decision == "block" and outcome in ("matched", "input-invalid", "guard-error"):
        return None
    if decision != "allow" or outcome not in ("clean", "record-masked"):
        raise _invalid()
    try:
        client_id = receipt["client_id"]
        name = "beforeSubmitPrompt" if client_id == "cursor" else "UserPromptSubmit"
        event = normalize_event(
            {"hook_event_name": name}, client_id=client_id, project_id=receipt["project_id"]
        )
        for key in (
            "invocation_id",
            "prompt_session_id",
            "prompt_session_id_source",
            "prompt_turn_id",
            "prompt_turn_id_source",
            "run_id",
            "model",
        ):
            event[key] = receipt[key]
        event["observed_at"] = receipt["occurred_at"]
        trace = receipt["trace_context"]
        if not isinstance(trace, dict):
            raise _invalid()
        event["trace_context"] = dict(trace)
    except KeyError:
        raise _invalid() from None
    validate_event(event)
    return event


def _matches(value: object, pattern: str) -> bool:
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def validate_event(event: object) -> None:
    """Validate the closed metadata contract without third-party dependencies."""
    if not isinstance(event, dict) or set(event) != EVENT_KEYS:
        raise _invalid()
    if event["schema_version"] != "1.0" or event["kind"] != "LLMCallEvent":
        raise _invalid()
    client = event["client_id"]
    name = event["hook_event_name"]
    if not isinstance(client, str) or client not in CLIENTS or not isinstance(name, str):
        raise _invalid()
    if name not in SUPPORTED_NATIVE_EVENTS[client]:
        raise _invalid()
    for key, pattern in (
        ("project_id", r"project-(?!0{32}$)[0-9a-f]{32}"),
        ("event_id", r"event:(?!0{32}$)[0-9a-f]{32}"),
        ("invocation_id", r"invocation:(?!0{32}$)[0-9a-f]{32}"),
    ):
        if not _matches(event[key], pattern):
            raise _invalid()
    if event["run_id"] is not None and not _matches(event["run_id"], r"run:(?!0{32}$)[0-9a-f]{32}"):
        raise _invalid()
    trace = event["trace_context"]
    if (trace is None) != (event["run_id"] is None):
        raise _invalid()
    if trace is not None:
        if not isinstance(trace, dict) or set(trace) != {
            "schema_version",
            "trace_id",
            "span_id",
            "parent_span_id",
            "trace_flags",
        }:
            raise _invalid()
        if trace["schema_version"] != "1.0" or trace["trace_flags"] != "01":
            raise _invalid()
        if not _matches(trace["trace_id"], r"(?!0{32}$)[0-9a-f]{32}") or not _matches(
            trace["span_id"], r"(?!0{16}$)[0-9a-f]{16}"
        ):
            raise _invalid()
        if trace["parent_span_id"] is not None and not _matches(
            trace["parent_span_id"], r"(?!0{16}$)[0-9a-f]{16}"
        ):
            raise _invalid()
    for prefix in ("session", "turn"):
        value = event[f"prompt_{prefix}_id"]
        source = event[f"prompt_{prefix}_id_source"]
        if source not in CORRELATION_SOURCES or not _matches(
            value, rf"{prefix}:(?:client\.[0-9a-f]{{64}}|local\.(?!0{{32}}$)[0-9a-f]{{32}})"
        ):
            raise _invalid()
        if (":client." in value) != (source == "client-envelope"):
            raise _invalid()
    if event["prompt_turn_id_source"] == CORRELATION_SOURCES[1] and (
        event["prompt_turn_id"].removeprefix("turn:local.")
        != event["invocation_id"].removeprefix("invocation:")
    ):
        raise _invalid()
    observed = event["observed_at"]
    if not _matches(observed, r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z"):
        raise _invalid()
    try:
        datetime.fromisoformat(observed.replace("Z", "+00:00"))
    except ValueError:
        raise _invalid() from None
    for key, prefix in (("agent_ref", "agent"), ("native_call_ref", "call")):
        if event[key] is not None and not _matches(event[key], rf"{prefix}:sha256:[0-9a-f]{{64}}"):
            raise _invalid()
    call_source = event["native_call_ref_source"]
    if call_source not in ("tool_use_id", "tool_call_id", "request_id", "unavailable"):
        raise _invalid()
    if (event["native_call_ref"] is None) != (call_source == "unavailable"):
        raise _invalid()
    scope = "subagent" if event["agent_ref"] is not None or "subagent" in name.lower() else "main"
    if event["call_scope"] != scope:
        raise _invalid()
    if name in ("SubagentStart", "SubagentStop", "subagentStart") and event["agent_ref"] is None:
        raise _invalid()
    duration = event["duration_ms"]
    if duration is not None and (type(duration) is not int or not 0 <= duration <= MAX_DURATION_MS):
        raise _invalid()
    if (
        event["raw_content_recorded"] is not False
        or event["complete_llm_attempt_coverage"] is not False
    ):
        raise _invalid()
    validate_model(event["model"])
    _validate_outcome(event, client, name)


def _validate_outcome(event: dict[str, object], client: str, name: str) -> None:
    lower = name.lower()
    status = event["status"]
    evidence_scope = event["evidence_scope"]
    expected_scope = (
        "prompt-submission"
        if lower in ("userpromptsubmit", "beforesubmitprompt")
        else "subagent-lifecycle"
        if "subagent" in lower
        else "tool-lifecycle"
        if "tooluse" in lower
        else "turn-lifecycle"
    )
    if evidence_scope != expected_scope:
        raise _invalid()
    statuses: tuple[str, ...]
    if lower in ("userpromptsubmit", "beforesubmitprompt", "subagentstart", "pretooluse"):
        statuses = ("started",)
    elif lower == "stopfailure":
        statuses = ("failed",)
    elif lower == "posttoolusefailure":
        statuses = ("failed", "cancelled")
    elif client == "cursor" and lower in ("stop", "subagentstop"):
        statuses = ("completed", "failed", "cancelled")
    else:
        statuses = ("completed",)
    if status not in statuses:
        raise _invalid()
    error = event["error"]
    if status in ("started", "completed"):
        if error is not None:
            raise _invalid()
        return
    if not isinstance(error, dict) or set(error) != {"class", "summary", "origin"}:
        raise _invalid()
    error_class = error["class"]
    if not isinstance(error_class, str) or error_class not in ERROR_SUMMARIES:
        raise _invalid()
    if error["summary"] != ERROR_SUMMARIES[error_class]:
        raise _invalid()
    if lower == "stopfailure":
        valid_classes = tuple(CLAUDE_ERRORS.values())
        origin = "llm-api"
    elif lower == "posttoolusefailure":
        valid_classes = (
            ("cancelled",)
            if status == "cancelled"
            else (
                ("tool-error", "timeout", "permission-denied")
                if client == "cursor"
                else ("tool-error",)
            )
        )
        origin = "tool"
    else:
        valid_classes = ("cancelled",) if status == "cancelled" else ("unknown",)
        origin = "client-unspecified"
    if error_class not in valid_classes or error["origin"] != origin:
        raise _invalid()
