#!/usr/bin/env python3
"""Keep native file-tool writes away from the generated project's governance surface.

This dependency-free PreToolUse hook is a conditional native guard, not an immutability claim.
It inspects only the target paths of a native file-editing tool and never reads the proposed
content.  Claude Code, Codex, Cursor and VS Code Copilot report the same decision through exit 2;
each adapter only maps the client's documented or observed event shape to (path, operation) pairs.
Canonical deliveries replace governance files as whole files; partial edits and deletions of
digest-bound authority assets, writes that reach the surface through a symlink, hard link or case
variant, and writes to hook-owned locators are denied.  Shell, interpreter, external editor and
human edits stay outside this hook and are detected by the generated governance drift check, the
commit gate and CI.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import runpy
import stat
import sys
from pathlib import Path
from typing import Any, NoReturn

MAX_EVENT_BYTES = 262_144
MAX_PATH_CHARACTERS = 4_096
DENIAL_MARKER = "GOVERNANCE_SURFACE_PROTECTED"
# The Agent relays the denial to a person; the plain-language contract lives in rule 02.
PLAIN_LANGUAGE_RELAY = (
    "Durumu kullanıcıya rules/02-iletisim-tarzi.md içindeki sade dil sözleşmesiyle anlat."
)
# A drifted managed file goes back to its recorded bytes through the governance runtime.
RESTORE_ROUTE = (
    "Sapan yönetilen dosyayı kaydedilmiş doğru hâline geri almak için dosya aracını kullanma; "
    "python3 .kt-scaffold/hooks/governance_client.py restore <yol> çalıştır (Windows'ta python3 "
    "yerine .venv\\Scripts\\python.exe)."
)
CLIENTS = ("claude-code", "codex", "cursor", "github-copilot-vscode")
WHOLE = "whole"
PARTIAL = "partial"
PATCH = "patch"
CLAUDE_TOOLS = {"Write": WHOLE, "Edit": PARTIAL, "MultiEdit": PARTIAL, "NotebookEdit": PARTIAL}
# Codex routes every native file edit through apply_patch; Edit and Write are matcher aliases.
CODEX_TOOLS = {"apply_patch": PATCH, "Edit": PATCH, "Write": PATCH}
# VS Code ignores hook matchers, so every tool reaches the guard and unknown tools are not file
# edits.  The model-facing names are those of Copilot Chat 0.66; Copilot CLI reports its
# create/edit/str_replace_editor tools with Claude-format names in this hook file format.
COPILOT_TOOLS = {
    "apply_patch": PATCH,
    "create_directory": WHOLE,
    "create_file": WHOLE,
    "edit_notebook_file": PARTIAL,
    "insert_edit_into_file": PARTIAL,
    "multi_replace_string_in_file": PARTIAL,
    "replace_string_in_file": PARTIAL,
    "Edit": PARTIAL,
    "Write": WHOLE,
    "create": WHOLE,
    "edit": PARTIAL,
    "str_replace_editor": PARTIAL,
}
# cursor-agent 2026.09.18 sends every agent file edit as a whole-file Write with
# tool_input.file_path; Delete removes a file.  Exit 2 denies the tool call.
CURSOR_TOOLS = {"Write": WHOLE, "Delete": PARTIAL}
CLIENT_TOOLS = {
    "claude-code": CLAUDE_TOOLS,
    "codex": CODEX_TOOLS,
    "cursor": CURSOR_TOOLS,
    "github-copilot-vscode": COPILOT_TOOLS,
}
PROJECT_DIR_VARIABLES = {"claude-code": "CLAUDE_PROJECT_DIR", "cursor": "CURSOR_PROJECT_DIR"}
PATH_FIELDS = ("file_path", "notebook_path", "filePath", "path", "dirPath")
PATCH_FIELDS = ("command", "input", "patch")
# Update and Delete change an existing file in place; Add and Move create the named file whole.
PATCH_HEADERS = (
    ("*** Add File: ", WHOLE),
    ("*** Update File: ", PARTIAL),
    ("*** Delete File: ", PARTIAL),
    ("*** Move to: ", WHOLE),
)

# Human-approved canonical deliveries may replace these paths as whole files.
GOVERNED_DIRECTORIES = (
    ".agents",
    ".claude/agents",
    ".claude/commands",
    ".claude/rules",
    ".claude/skills",
    ".codex",
    ".cursor",
    ".github/agents",
    ".github/hooks",
    ".github/instructions",
    ".github/skills",
    ".kt-scaffold/agent-activation",
    ".kt-scaffold/agent-projections",
    ".kt-scaffold/hooks",
    "agent-evals",
    "agent-platform",
    "rules",
)
GOVERNED_FILES = (
    ".claude/settings.json",
    ".github/workflows/governance-drift.yml",
    ".github/workflows/security-scan.yml",
    ".gitleaks.toml",
    ".kt-scaffold/answers.yml",
    ".kt-scaffold/manifest.json",
    ".kt-scaffold/project-manifest.json",
    ".pre-commit-config.yaml",
    ".specify/memory/constitution.md",
    "AGENTS.md",
    "AGENTS.override.md",
    "CLAUDE.local.md",
    "CLAUDE.md",
    "app/backend/AGENTS.md",
    "app/frontend/AGENTS.md",
    "dependency-admission.json",
    "helm/AGENTS.md",
    "scripts/check-dependency-admission.py",
    "scripts/check-governance-drift.py",
    "technology-profile.yml",
)
# Digest-bound authority assets and hook configuration are never adapted by partial edits.
AUTHORITY_DIRECTORIES = (
    ".github/hooks",
    ".kt-scaffold/agent-activation",
    ".kt-scaffold/agent-projections",
    ".kt-scaffold/hooks",
    "agent-platform",
)
AUTHORITY_FILES = (
    ".claude/settings.json",
    ".codex/config.toml",
    ".codex/hooks.json",
    ".cursor/hooks.json",
    ".kt-scaffold/manifest.json",
    ".kt-scaffold/project-manifest.json",
    "scripts/check-governance-drift.py",
)
# Only the prompt hook writes locators; hook bypass settings are never written by the Agent.
# Copilot CLI reads inline hooks and disableAllHooks from the ungenerated .github/copilot files.
CLOSED_DIRECTORIES: tuple[str, ...] = ()
CLOSED_FILES = (
    ".claude/settings.local.json",
    ".github/copilot/settings.json",
    ".github/copilot/settings.local.json",
)


class GuardDenied(RuntimeError):
    def __init__(self, code: str, relative: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.relative = relative


def _deny(code: str, relative: str | None = None) -> NoReturn:
    raise GuardDenied(code, relative)


def _within(relative: str, directories: tuple[str, ...], files: tuple[str, ...]) -> bool:
    return relative in files or any(
        relative == directory or relative.startswith(directory + "/") for directory in directories
    )


def _folded(entries: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(entry.casefold() for entry in entries)


def classify(relative: str | None, *, folded: bool = False) -> str | None:
    """Return closed, authority or governed for a project-relative POSIX path."""

    if relative is None:
        return None
    if folded:
        relative = relative.casefold()

    def selected(entries: tuple[str, ...]) -> tuple[str, ...]:
        return _folded(entries) if folded else entries

    if _within(relative, selected(CLOSED_DIRECTORIES), selected(CLOSED_FILES)):
        return "closed"
    if _within(relative, selected(AUTHORITY_DIRECTORIES), selected(AUTHORITY_FILES)):
        return "authority"
    if _within(relative, selected(GOVERNED_DIRECTORIES), selected(GOVERNED_FILES)):
        return "governed"
    return None


def _project_root() -> str:
    script = Path(__file__)
    if script.is_symlink():
        _deny("HOOK_SCRIPT_UNSAFE")
    root = os.path.realpath(str(script.resolve().parents[2]))
    if not os.path.isdir(os.path.join(root, ".kt-scaffold")):
        _deny("PROJECT_ROOT_INVALID")
    return root


def _event() -> dict[str, Any]:
    raw = sys.stdin.buffer.read(MAX_EVENT_BYTES + 1)
    if len(raw) > MAX_EVENT_BYTES:
        _deny("HOOK_EVENT_OVERSIZE")
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        _deny("HOOK_EVENT_INVALID")
    if not isinstance(parsed, dict):
        _deny("HOOK_EVENT_INVALID")
    return parsed


def _normalize(raw: object, event: dict[str, Any], root: str) -> tuple[str, bool]:
    """Return the normalized absolute target and whether it was written with traversal."""

    if not isinstance(raw, str) or not raw or "\x00" in raw or len(raw) > MAX_PATH_CHARACTERS:
        _deny("HOOK_TARGET_PATH_INVALID")
    traversal = ".." in raw.replace("\\", "/").split("/")
    if not os.path.isabs(raw):
        cwd = event.get("cwd")
        base = cwd if isinstance(cwd, str) and cwd and os.path.isabs(cwd) else root
        raw = os.path.join(base, raw)
    target = os.path.normpath(raw)
    if os.sep == "/" and target.startswith("//"):
        # POSIX normpath keeps two leading slashes; the kernel and the anchor do not.
        target = "/" + target.lstrip("/")
    return target, traversal


def _patch_operations(tool_input: dict[str, Any]) -> list[tuple[object, str]]:
    text = next(
        (tool_input[field] for field in PATCH_FIELDS if isinstance(tool_input.get(field), str)),
        None,
    )
    if text is None:
        _deny("HOOK_PATCH_INVALID")
    operations: list[tuple[object, str]] = []
    for line in text.splitlines():
        for header, kind in PATCH_HEADERS:
            if line.startswith(header):
                operations.append((line[len(header) :].strip(), kind))
    if not operations:
        # An edit tool call whose targets cannot be named is never allowed through.
        _deny("HOOK_PATCH_INVALID")
    return operations


def _field_paths(tool_input: dict[str, Any]) -> list[object]:
    paths: list[object] = [tool_input[field] for field in PATH_FIELDS if field in tool_input]
    files = tool_input.get("files")
    if isinstance(files, list):
        paths.extend(files)
    replacements = tool_input.get("replacements")
    if isinstance(replacements, list):
        for replacement in replacements:
            if not isinstance(replacement, dict):
                _deny("HOOK_TOOL_INPUT_INVALID")
            paths.append(replacement.get("filePath", replacement.get("file_path")))
    return paths


def _tool(event: dict[str, Any], client: str) -> tuple[str, dict[str, Any] | None]:
    tool_name = event.get("tool_name")
    tool_input = event.get("tool_input")
    if tool_name is None and client == "github-copilot-vscode" and "toolName" in event:
        # Copilot CLI camelCase events carry the arguments as a JSON string.
        tool_name = event.get("toolName")
        arguments = event.get("toolArgs")
        try:
            tool_input = json.loads(arguments) if isinstance(arguments, str) else arguments
        except ValueError:
            _deny("HOOK_TOOL_INPUT_INVALID")
    if not isinstance(tool_name, str):
        _deny("HOOK_TOOL_NAME_INVALID")
    return tool_name, tool_input if isinstance(tool_input, dict) else None


def operations(event: dict[str, Any], client: str) -> list[tuple[object, str]]:
    """Map one client tool event to the (raw path, whole or partial) writes it performs."""

    tool_name, tool_input = _tool(event, client)
    kind = CLIENT_TOOLS[client].get(tool_name)
    if kind is None:
        return []
    if tool_input is None:
        _deny("HOOK_TOOL_INPUT_INVALID")
    if kind == PATCH:
        return _patch_operations(tool_input)
    if client in {"claude-code", "cursor"}:
        # Both document one path field per tool; any other field is not the edited file.
        field = "notebook_path" if tool_name == "NotebookEdit" else "file_path"
        return [(tool_input.get(field), kind)]
    if tool_name == "str_replace_editor" and tool_input.get("command") == "view":
        return []
    if tool_name == "str_replace_editor" and tool_input.get("command") == "create":
        kind = WHOLE
    paths = _field_paths(tool_input)
    if not paths:
        _deny("HOOK_TARGET_PATH_INVALID")
    return [(path, kind) for path in paths]


def _relative_to(path: str, root: str) -> str | None:
    if path == root:
        return ""
    prefix = root.rstrip(os.sep) + os.sep
    if not path.startswith(prefix):
        return None
    return path[len(prefix) :].replace(os.sep, "/")


def _anchor(root: str, client: str) -> str | None:
    """Return the client's project directory when it names this root, as permission rules do."""

    variable = PROJECT_DIR_VARIABLES.get(client)
    if variable is None:
        return None
    value = os.environ.get(variable)
    if not value or "\x00" in value or not os.path.isabs(value):
        return None
    anchor = os.path.normpath(value)
    return anchor if os.path.realpath(anchor) == root else None


def lexical_relative(target: str, root: str, anchor: str | None = None) -> str | None:
    """Map a path to the project as written, without resolving links inside the project."""

    if anchor is not None:
        return _relative_to(target, anchor)
    parts = target.split(os.sep)
    for index in range(1, len(parts) + 1):
        prefix = os.sep.join(parts[:index]) or os.sep
        if os.path.realpath(prefix) == root:
            return "/".join(part for part in parts[index:] if part)
    return None


def _surface_inodes(root: str) -> dict[tuple[int, int], str]:
    inodes: dict[tuple[int, int], str] = {}

    def record(relative: str) -> None:
        try:
            info = os.lstat(os.path.join(root, relative))
        except OSError:
            return
        if stat.S_ISREG(info.st_mode):
            inodes.setdefault((info.st_dev, info.st_ino), relative)

    for relative in (*GOVERNED_FILES, *AUTHORITY_FILES, *CLOSED_FILES):
        record(relative)
    for directory in (*GOVERNED_DIRECTORIES, *AUTHORITY_DIRECTORIES, *CLOSED_DIRECTORIES):
        base = os.path.join(root, directory)
        if os.path.islink(base) or not os.path.isdir(base):
            continue
        for current, directories, files in os.walk(base, followlinks=False):
            directories[:] = [
                name for name in directories if not os.path.islink(os.path.join(current, name))
            ]
            for name in files:
                record(os.path.relpath(os.path.join(current, name), root).replace(os.sep, "/"))
    return inodes


def resolved_class(target: str, root: str) -> tuple[str | None, str | None]:
    """Classify the real destination, including case variants and hard links."""

    real = os.path.realpath(target)
    relative = _relative_to(real, root)
    category = classify(relative, folded=True)
    if category is not None:
        return category, relative
    try:
        info = os.stat(real)
    except OSError:
        return None, relative
    if stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
        linked = _surface_inodes(root).get((info.st_dev, info.st_ino))
        if linked is not None:
            return classify(linked), linked
    return None, relative


# Inside the shared governance root the agent may only write a specialist's unchanged evaluation.
# `governance_client.py` writes the run inputs, reports, decision, receipt, audit and publication
# marks; every other record stays closed.
AGENT_WRITABLE_SHARED_PATH = re.compile(
    r"project-[0-9a-f]{32}/governed-review/run-[A-Za-z0-9][A-Za-z0-9._-]{3,119}/"
    r"work/[a-z][a-z0-9]*(?:-[a-z0-9]+)*-evaluation\.json"
)


def _shared_root() -> str | None:
    path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "governance_records.py")
    if os.path.islink(path) or not os.path.isfile(path):
        return None
    try:
        location = runpy.run_path(path)["resolve_location"]()
    except Exception:
        return None
    return os.path.realpath(str(location.root))


def _shared_denial(target: str) -> tuple[str, str] | None:
    shared = _shared_root()
    if shared is None:
        return None
    for candidate in (os.path.normpath(target), os.path.realpath(target)):
        relative = _relative_to(candidate, shared)
        if relative is None:
            continue
        if (
            relative
            and AGENT_WRITABLE_SHARED_PATH.fullmatch(relative)
            and not os.path.islink(candidate)
        ):
            continue
        return "GOVERNANCE_RECORD_CLOSED", relative or "."
    return None


def _decide_target(
    raw: object, kind: str, event: dict[str, Any], root: str, client: str
) -> tuple[str, str] | None:
    target, traversal = _normalize(raw, event, root)
    shared = _shared_denial(target)
    if shared is not None:
        return shared
    lexical = lexical_relative(target, root, _anchor(root, client))
    # Canonical deliveries name governance paths directly; traversal is treated as an alias.
    direct = None if traversal else classify(lexical)
    category, resolved = resolved_class(target, root)
    if category is None and direct is None:
        return None
    shown = lexical if direct is not None and lexical is not None else resolved or ""
    if direct != category:
        # A link, hard link or case variant would sidestep the path-scoped approval rule.
        return "GOVERNANCE_SURFACE_ALIAS", shown
    if category == "closed":
        return "GOVERNANCE_SURFACE_CLOSED", shown
    if category == "authority" and kind == PARTIAL:
        return "AUTHORITY_PARTIAL_EDIT", shown
    replaces = os.path.lexists(target) and not os.path.isdir(target)
    if category == "authority" and replaces and client != "claude-code":
        # Only Claude Code gates whole-file replacement with a path-scoped approval rule.
        return "AUTHORITY_REPLACEMENT", shown
    return None


def decide(event: dict[str, Any], root: str, client: str = "claude-code") -> tuple[str, str] | None:
    """Return a denial code and path, or None to leave the decision to permission rules."""

    for raw, kind in operations(event, client):
        denial = _decide_target(raw, kind, event, root, client)
        if denial is not None:
            return denial
    return None


def _record_location() -> Any:
    """The shared governance root; ``None`` selects the fixed operating-system location."""
    return None


def _managed_preferences() -> Any:
    """Jamf's managed preference file; ``None`` selects the fixed system path."""
    return None


def _device_refusal(hook: str, client: str) -> str | None:
    """The fixed refusal when this device is stopped; read locally before any other check."""
    path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "governance_records.py")
    try:
        records = runpy.run_path(path)
        decision, _ = records["device_gate"](
            location=_record_location(), managed_preferences=_managed_preferences()
        )
    except Exception:
        return None
    if decision not in {"stop", "unverified"}:
        return None
    records["record_refusal"](hook, decision, client=client, location=_record_location())
    return str(records["gate_message"](decision, marker=True))


def _message(code: str, relative: str | None, client: str) -> str:
    if code == "GOVERNANCE_RECORD_CLOSED":
        return (
            f"{DENIAL_MARKER}: {code}; `{relative}` ortak yönetişim kökündedir (yönetişim "
            "kayıtlarının tutulduğu ortak klasör). Kayıtları, audit'i ve yayın işaretlerini "
            "yalnız kancalar ve governance_client.py komutları yazar; dosya aracıyla oluşturma "
            "veya değiştirme. İnceleme koşumunda "
            "yalnız uzman değerlendirmesi work/<ajan>-evaluation.json yazılabilir; koşum "
            "girdilerini, raporları, kararı ve receipt'i governance_client.py komutları yazar. "
            f"{PLAIN_LANGUAGE_RELAY}"
        )
    subject = (
        f"`{relative}` yönetişim yüzeyindedir (proje kurallarını, denetimlerini ve kayıtlarını "
        "tutan korumalı dosyalar)"
        if relative
        else "dosya aracı hedefi doğrulanamadı ve yazım reddedildi"
    )
    delivery = (
        "Kullanıcının açıkça başlattığı /kt-guncelle, /kt-yansit veya MCP iskele eşitlemesinde "
        "yalnız teslim edilen baytları proje kökünden doğrudan yolla tam dosya olarak yaz; bu "
        "yazım insan onayı ister."
        if client == "claude-code"
        else "Bu istemcide mevcut yetki varlığı yerel dosya aracıyla değiştirilemez; kanonik "
        "güncellemede dur ve kullanıcıya kt-iskelet guncelle komutunu kendisinin "
        "çalıştırmasını söyle."
    )
    return (
        f"{DENIAL_MARKER}: {code}; {subject}. rules/04-politika-catismasi.md içindeki "
        "yönetişim yüzeyi bütünlüğü sınırı geçerlidir: ürün işinde veya bulgu düzeltmesinde "
        "POLICY_CONFLICT ile yanıt ver. Kontrol, bulgu veya kanıtı bu yüzeyi değiştirerek çözme; "
        f"kabuk, yorumlayıcı, bağlantı veya başka yolla atlatma. {delivery} {RESTORE_ROUTE} "
        f"{PLAIN_LANGUAGE_RELAY}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--client", required=True, choices=CLIENTS)
    parser.add_argument("--self-check", action="store_true")
    arguments = parser.parse_args(argv)
    if arguments.self_check:
        print(
            json.dumps(
                {
                    "blocking": True,
                    "content_inspection": False,
                    "enforcement_claim": "conditional-native-guard",
                    "native_exit_2_deny": True,
                    "ok": True,
                    "shell_coverage": False,
                },
                sort_keys=True,
            )
        )
        return 0
    client = arguments.client
    refusal = _device_refusal("file", client)
    if refusal is not None:
        with contextlib.suppress(OSError):
            sys.stdin.buffer.read(MAX_EVENT_BYTES + 1)
        print(refusal, file=sys.stderr)
        return 2
    try:
        root = _project_root()
        decision = decide(_event(), root, client)
    except GuardDenied as error:
        print(_message(error.code, error.relative, client), file=sys.stderr)
        return 2
    except Exception:
        print(_message("VALIDATION_FAILURE", None, client), file=sys.stderr)
        return 2
    if decision is not None:
        print(_message(*decision, client), file=sys.stderr)
        return 2
    print(json.dumps({"permission": "allow"}) if client == "cursor" else "{}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
