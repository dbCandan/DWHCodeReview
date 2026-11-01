#!/usr/bin/env python3
"""Record only native lifecycle metadata; never read a transcript or a model response.

This is an observation hook: whatever happens, it exits 0 and never changes whether the agent
stops, continues or uses a tool. A record it cannot write is reported with a fixed warning.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import runpy
import sys
from pathlib import Path
from typing import Any

MAX_EVENT_BYTES = 262_144
RECORD_WARNING = "GOVERNANCE_RECORD_UNAVAILABLE: {code}; ajan akisi degismedi."


class GuardError(ValueError):
    """Redacted input or record failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _records() -> dict[str, Any]:
    path = Path(__file__).resolve().with_name("governance_records.py")
    if path.is_symlink() or not path.is_file():
        raise GuardError("record-writer-unavailable")
    return runpy.run_path(str(path))


def _record_location() -> Any:
    """The shared governance root; ``None`` selects the fixed operating-system location."""
    return None


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise GuardError("event-invalid")
        result[key] = value
    return result


def _invalid_constant(_value: str) -> object:
    raise GuardError("event-invalid")


def _native(record: dict[str, object], field: str) -> str | None:
    """A record carries a session or turn only when the client supplied it; never a local one."""
    value = record.get(field)
    if record.get(f"{field}_source") != "client-envelope" or not isinstance(value, str):
        return None
    return value


def _record(client_id: str, event_name: str) -> None:
    hook_root = Path(__file__).resolve().parent
    project_root = hook_root.parents[1]
    ingress = runpy.run_path(str(hook_root / "prompt_ingress_guard.py"))
    try:
        project_id = ingress["_read_project_id"](project_root)
    except Exception:
        raise GuardError("project-identity-unavailable") from None
    raw = sys.stdin.buffer.read(MAX_EVENT_BYTES + 1)
    if len(raw) > MAX_EVENT_BYTES:
        raise GuardError("event-too-large")
    try:
        event = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise GuardError("event-invalid") from None
    if not isinstance(event, dict):
        raise GuardError("event-invalid")
    supplied = event.get("hook_event_name")
    if supplied != event_name and not (client_id == "cursor" and supplied is None):
        raise GuardError("event-mismatch")
    # Cursor's documented envelopes need not repeat the configuration event name.
    event["hook_event_name"] = event_name
    normalizer = runpy.run_path(str(hook_root / "llm_call_events.py"))
    try:
        record = normalizer["normalize_event"](event, client_id=client_id, project_id=project_id)
    except ValueError:
        raise GuardError("event-invalid") from None
    writer = _records()
    writer["write_event"](
        "llm-call-events",
        project_id,
        record,
        record_id=str(record["event_id"]).removeprefix("event:"),
        context={
            "client": client_id,
            "client_source": "command",
            "session_hash": _native(record, "prompt_session_id"),
            "turn_hash": _native(record, "prompt_turn_id"),
            "identity_source": (
                "client-envelope"
                if _native(record, "prompt_session_id") and _native(record, "prompt_turn_id")
                else "unavailable"
            ),
        },
        location=_record_location(),
    )
    _refresh_identity(hook_root, writer, project_id)


def _refresh_identity(hook_root: Path, writer: dict[str, Any], project_id: str) -> None:
    """Refresh this user's corporate account binding; a failure never changes the event."""
    with contextlib.suppress(Exception):
        stream = writer["stream_directory"](project_id, location=_record_location())
        identity = runpy.run_path(str(hook_root / "governance_identity.py"))
        identity["refresh_binding"](stream, writer["os_user"]())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--client", required=True)
    parser.add_argument("--event", required=True)
    args = parser.parse_args()
    script = Path(__file__)
    with contextlib.suppress(Exception):
        status = _records()["ensure_profile_interpreter"](
            script.resolve(strict=True).parents[2], script, sys.argv[1:]
        )
        if status is not None:
            print(RECORD_WARNING.format(code=status), file=sys.stderr)
    try:
        _record(args.client, args.event)
    except Exception as exc:
        # Do not echo raw client JSON, provider errors, credentials or exception text.
        code = getattr(exc, "code", None)
        if not isinstance(code, str) or re.fullmatch(r"[a-z-]{1,64}", code) is None:
            code = "record-write-failed"
        print(RECORD_WARNING.format(code=code), file=sys.stderr)
    print("{}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
