#!/usr/bin/env python3
"""Tell the Agent in the same turn when a shell command left the governance surface drifted.

This dependency-free post-tool hook is feedback, not a guard: a shell command has already run
and cannot be undone here.  It runs the generated drift check and, on drift, returns the client's
documented feedback shape so the Agent is told to restore the drifted file with the generated
governance runtime's restore command and stop.  It never reads
the command output or file contents and names only the paths the drift check reports.  Hook
failures stay silent; the pre-commit gate, the commit guard and CI remain the enforcing layers.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

CLIENTS = ("claude-code", "codex", "cursor")
DRIFT_MARKER = "GOVERNANCE_DRIFT_DETECTED"
DRIFT_CHECK = "scripts/check-governance-drift.py"
RESTORE_COMMAND = ".kt-scaffold/hooks/governance_client.py restore"
MAX_EVENT_BYTES = 262_144
MAX_DETAIL_LINES = 3
MAX_DETAIL_CHARACTERS = 400
CHECK_TIMEOUT_SECONDS = 8
# A local client override is not drift a shell command left behind and has no restore route;
# the commit gate and the governed review stop on it with their own guidance.
LOCAL_OVERRIDE_EXIT = 3


def _project_root() -> Path | None:
    script = Path(__file__)
    if script.is_symlink():
        return None
    root = script.resolve().parents[2]
    return root if (root / ".kt-scaffold").is_dir() and (root / DRIFT_CHECK).is_file() else None


def _drift_detail(root: Path) -> str | None:
    """Return the drift check's own path-level diagnostic, or None when the surface is current."""

    completed = subprocess.run(
        [sys.executable, str(root / DRIFT_CHECK)],
        cwd=root,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=CHECK_TIMEOUT_SECONDS,
        check=False,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
    )
    if completed.returncode in {0, LOCAL_OVERRIDE_EXIT}:
        return None
    lines = [line.strip() for line in completed.stderr.splitlines() if line.strip()]
    detail = "; ".join(lines[:MAX_DETAIL_LINES])[:MAX_DETAIL_CHARACTERS]
    return detail or "sapma denetimi başarısız oldu"


def _message(detail: str) -> str:
    return (
        f"{DRIFT_MARKER}: son kabuk komutundan sonra yönetişim yüzeyi kanonik özetten saptı "
        f"({detail}). rules/04-politika-catismasi.md geçerlidir: sapan dosyayı "
        f"python3 {RESTORE_COMMAND} <yol> ile kaydedilmiş doğru hâline geri al (Windows'ta "
        "python3 yerine .venv\\Scripts\\python.exe; komut doğru içeriği projenin commit "
        "geçmişinden alır ve .git klasörüne yazmaz), kontrolü veya bulguyu yüzeyi "
        "değiştirerek kapatma ve işe devam etmeden kullanıcıya rules/02-iletisim-tarzi.md "
        "içindeki sade dil sözleşmesiyle bildir. Doğru içerik git geçmişinde yoksa dosyayı elle "
        "yazma; proje fabrika güncellemesiyle güncellenir: proje fabrikası bağlantısındaki (MCP) "
        "proje_iskelesini_esitle aracı veya kt-iskelet guncelle komutu."
    )


def _feedback(client: str, message: str) -> dict[str, object]:
    if client == "cursor":
        return {"additional_context": message}
    context = {"hookEventName": "PostToolUse", "additionalContext": message}
    if client == "codex":
        # A Codex block replaces the tool result, hiding the output of the restoring command.
        return {"hookSpecificOutput": context}
    return {"decision": "block", "reason": message, "hookSpecificOutput": context}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--client", required=True, choices=CLIENTS)
    arguments = parser.parse_args(argv)
    # The event only triggers the check; its command and output are never inspected.
    sys.stdin.buffer.read(MAX_EVENT_BYTES)
    output: dict[str, object] = {}
    try:
        root = _project_root()
        detail = _drift_detail(root) if root is not None else None
        if detail is not None:
            output = _feedback(arguments.client, _message(detail))
    except (OSError, subprocess.SubprocessError, ValueError):
        output = {}
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
