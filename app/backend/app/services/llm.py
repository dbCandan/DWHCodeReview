"""OpenAI-compatible chat client used by LLM rules.

`POST {base_url}/chat/completions`; the model must answer
`{"violations":[{"line":<int>,"snippet":"...","reason":"..."}]}`. The reply is parsed
robustly: `<think>` blocks and markdown fences are dropped and the first JSON object
in the text is used.

Large objects are reviewed in chunks (`plan_chunks`): the numbered SQL is split at statement
boundaries with a small overlap, every chunk keeps the original line numbers and gets a
"BAĞLAM" block (object header + DECLARE lines); findings of all chunks are merged and
de-duplicated. Transient transport errors are retried per call (`RETRY_DELAYS`).
"""

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.services.rule_engine import SNIPPET_MAX, EngineFinding, RuleSpec

# Tests replace this with an `httpx.MockTransport`.
http_transport: httpx.BaseTransport | None = None


class LlmError(Exception):
    """LLM call or reply failure; the message is Turkish and safe to show.

    `transient` marks transport failures worth retrying (timeouts, dropped connections,
    HTTP 502/503/504). `findings` carries the results of the chunks that did succeed when
    only some chunks of a large object failed.
    """

    def __init__(self, message: str, transient: bool = False,
                 findings: list[EngineFinding] | None = None) -> None:
        super().__init__(message)
        self.transient = transient
        self.findings = findings or []


DEFAULT_CHUNK_LINES = 250
CHUNK_CHARS = 20_000
CHUNK_OVERLAP = 15
CONTEXT_MAX_LINES = 60
# Waits (seconds) before the retries of a transient failure; tests set this to (0, 0).
RETRY_DELAYS: tuple[float, ...] = (5.0, 15.0)
sleep = time.sleep


@dataclass(frozen=True, slots=True)
class LlmConfig:
    base_url: str
    model: str
    api_key: str | None = field(default=None, repr=False)
    temperature: float = 0.0
    timeout_seconds: int = 120
    chunk_lines: int = DEFAULT_CHUNK_LINES


SYSTEM_PROMPT = """Sen bir SQL Server (T-SQL) kod inceleme kural denetleyicisisin.

Görevin: Verilen SQL kodunu YALNIZCA verilen kural açısından değerlendirmek ve kesin ihlalleri raporlamak.

DAVRANIŞ KURALLARI:
1. Sadece gerçek ve net ihlalleri raporla; şüpheli veya "olabilir" durumlar ihlal değildir.
2. Kural kapsamı dışında hiçbir konuda yorum, öneri veya genel kalite değerlendirmesi yapma.
3. İhlal yoksa yanıtın tamamı tam olarak şu olmalıdır: {"violations": []}

ZORUNLU ÇIKTI BİÇİMİ (en yüksek öncelik):
- Yanıt tek bir JSON nesnesidir; ilk karakter "{", son karakter "}" olmalıdır.
- Markdown (```), açıklama metni, "JSON:" gibi etiketler, <think> blokları YASAKTIR.
- Kökte yalnızca "violations" anahtarı bulunur; değeri bir dizidir (boş olabilir).
- Her ihlal öğesi şu alanları içerir:
  "line": ihlalin başladığı satır numarası (tam sayı; koddaki L001 öneki 1 demektir),
  "snippet": ilgili SQL parçası (koddan aynen, satır öneki olmadan),
  "reason": ihlalin kısa Türkçe açıklaması.

Örnek:
{"violations": [{"line": 12, "snippet": "SELECT a.x FROM A a, B b", "reason": "A ve B arasında join koşulu yok."}]}"""

USER_TEMPLATE = """Aşağıdaki SQL nesnesini verilen kurala göre incele.

KURAL KODU: {code}
KURAL ADI: {name}

KURAL TANIMI:
{prompt}

NESNE: {object_name}
{metadata}{chunk}
SQL (her satırın başında satır numarası vardır, örn. "L001| "):
{numbered}

Yalnızca {{"violations": [...]}} biçiminde JSON döndür. İhlal yoksa {{"violations": []}}."""


def numbered_sql(sql: str) -> str:
    lines = sql.splitlines() or [""]
    return numbered_lines(lines, 0, len(lines), len(lines))


def numbered_lines(lines: list[str], start: int, end: int, total: int) -> str:
    """Lines [start, end) (0-based) prefixed with their 1-based number, e.g. "L0123| "."""
    width = max(3, len(str(total)))
    return "\n".join(f"L{number + 1:0{width}d}| {lines[number]}" for number in range(start, end))


# ------------------------------------------------------------------ HTTP
def _client(timeout: float) -> httpx.Client:
    return httpx.Client(timeout=timeout, transport=http_transport)


def _endpoint(base_url: str) -> str:
    base = base_url.strip().rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def chat(config: LlmConfig, messages: list[dict[str, str]], max_tokens: int | None = None) -> str:
    """Send one chat completion and return the reply text."""
    headers = {"Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    body: dict[str, Any] = {
        "model": config.model,
        "messages": messages,
        "temperature": config.temperature,
        "stream": False,
    }
    if max_tokens:
        body["max_tokens"] = max_tokens
    try:
        with _client(float(config.timeout_seconds)) as client:
            response = client.post(_endpoint(config.base_url), json=body, headers=headers)
    except httpx.TimeoutException:
        raise LlmError("LLM zamanında yanıt vermedi (zaman aşımı).", transient=True) from None
    except httpx.ConnectError:
        raise LlmError(_unreachable_message(config.base_url), transient=True) from None
    except httpx.TransportError as error:  # ReadError, RemoteProtocolError, WriteError...
        raise LlmError(
            f"LLM isteği başarısız oldu: {type(error).__name__}.", transient=True
        ) from None
    except httpx.HTTPError as error:
        raise LlmError(f"LLM isteği başarısız oldu: {type(error).__name__}.") from None

    if response.status_code == 401 or response.status_code == 403:
        raise LlmError(f"LLM API anahtarı reddedildi (HTTP {response.status_code}).")
    if response.status_code == 404:
        raise LlmError("LLM uç noktası veya model bulunamadı (HTTP 404).")
    try:
        data = response.json()
    except ValueError:
        data = None
    if response.status_code >= 400:
        detail = _error_message(data)
        suffix = f": {detail}" if detail else "."
        raise LlmError(
            f"LLM isteği başarısız oldu (HTTP {response.status_code}){suffix}",
            transient=response.status_code in (502, 503, 504),
        )
    if data is None:
        raise LlmError("LLM yanıtı JSON değil.")
    detail = _error_message(data)
    if detail:
        raise LlmError(f"LLM hata döndürdü: {detail}")
    return _response_text(data)


def _error_message(data: object) -> str | None:
    if not isinstance(data, dict):
        return None
    err = data.get("error")
    if isinstance(err, str) and err.strip():
        return err.strip()[:300]
    if isinstance(err, dict):
        for key in ("message", "detail", "msg"):
            value = err.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:300]
    return None


def _response_text(data: object) -> str:
    if isinstance(data, dict):
        choices = data.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            first = choices[0]
            message = first.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    return "".join(
                        part.get("text", "") for part in content if isinstance(part, dict)
                    )
            if isinstance(first.get("text"), str):
                return str(first["text"])
        for key in ("response", "output", "content", "text"):
            if isinstance(data.get(key), str):
                return str(data[key])
    raise LlmError("LLM yanıtında metin bulunamadı.")


# ------------------------------------------------------------------ parsing
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"```(?:json|JSON)?")


def extract_json(text: str) -> Any:
    """The first JSON object (or array) in the text; prose around it is ignored."""
    cleaned = text or ""
    lowered = cleaned.lower()
    if "</think>" in lowered:  # reasoning may come without an opening tag
        cleaned = cleaned[lowered.rfind("</think>") + len("</think>") :]
    cleaned = _THINK.sub("", cleaned)
    cleaned = _FENCE.sub("", cleaned).strip().lstrip("﻿")
    decoder = json.JSONDecoder()
    starts = [i for i, ch in enumerate(cleaned) if ch == "{"] or [
        i for i, ch in enumerate(cleaned) if ch == "["
    ]
    for start in starts:
        try:
            return decoder.raw_decode(cleaned, start)[0]
        except json.JSONDecodeError:
            continue
    raise LlmError("LLM yanıtı JSON olarak çözümlenemedi.")


_LINE_REF = re.compile(r"L?\s*0*(\d+)", re.IGNORECASE)


def _coerce_line(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        match = _LINE_REF.search(value)
        if match:
            return int(match.group(1))
    if isinstance(value, list) and value:
        return _coerce_line(value[0])
    return None


def _strip_line_prefix(snippet: str) -> str:
    return re.sub(r"^\s*L\d{3,}\|\s?", "", snippet, flags=re.MULTILINE)


def _find_line(lines: list[str], snippet: str) -> int | None:
    first = next((ln.strip() for ln in snippet.splitlines() if ln.strip()), "")
    if len(first) < 4:
        return None
    needle = re.sub(r"\s+", " ", first).lower()
    for number, line in enumerate(lines, 1):
        if needle in re.sub(r"\s+", " ", line).lower():
            return number
    return None


def parse_violations(text: str, sql: str, default_message: str) -> list[EngineFinding]:
    data = extract_json(text)
    if isinstance(data, dict):
        items = data.get("violations")
        if items is None:
            for key in ("findings", "issues", "results"):
                if isinstance(data.get(key), list):
                    items = data[key]
                    break
        if items is None:
            items = []
    elif isinstance(data, list):
        items = data
    else:
        items = []
    if not isinstance(items, list):
        raise LlmError("LLM yanıtında 'violations' bir dizi değil.")

    lines = sql.splitlines()
    findings: list[EngineFinding] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        snippet = _strip_line_prefix(str(item.get("snippet") or "")).strip()
        reason = str(item.get("reason") or item.get("message") or "").strip()
        line = _coerce_line(item.get("line", item.get("line_number", item.get("line_reference"))))
        if line is not None and not 1 <= line <= max(len(lines), 1):
            line = None
        if line is None and snippet:
            line = _find_line(lines, snippet)
        if not snippet and line is not None and lines:
            snippet = lines[line - 1].strip()
        if len(snippet) > SNIPPET_MAX:
            snippet = snippet[: SNIPPET_MAX - 1] + "…"
        findings.append(EngineFinding(line, snippet, reason or default_message))
    return findings


# ------------------------------------------------------------------ chunking
_BOUNDARY = re.compile(r"^\s*(?:GO\s*)?$|;\s*$", re.IGNORECASE)


def plan_chunks(
    lines: list[str], chunk_lines: int, chunk_chars: int = CHUNK_CHARS,
    overlap: int = CHUNK_OVERLAP,
) -> list[tuple[int, int]]:
    """0-based [start, end) line ranges; one range when the object is small enough.

    A chunk holds at most `chunk_lines` lines and about `chunk_chars` characters. It ends
    after the last statement boundary (a `GO` line, a line ending with `;` or a blank line)
    found searching backwards from the limit (in its second half); otherwise it is cut hard.
    Consecutive chunks overlap by `overlap` lines.
    """
    total = len(lines)
    chunk_lines = max(1, chunk_lines)
    if total <= chunk_lines and sum(len(line) + 1 for line in lines) <= chunk_chars:
        return [(0, total)]
    chunks: list[tuple[int, int]] = []
    start = 0
    while start < total:
        limit = min(start + chunk_lines, total)
        size = 0
        for index in range(start, limit):
            size += len(lines[index]) + 1
            if size > chunk_chars and index > start:
                limit = index
                break
        end = limit
        if limit < total:
            floor = start + max(1, (limit - start) // 2)
            for candidate in range(limit, floor, -1):
                if _BOUNDARY.search(lines[candidate - 1]):
                    end = candidate
                    break
        chunks.append((start, end))
        if end >= total:
            break
        start = max(end - overlap, start + 1)
    return chunks


_HEADER = re.compile(
    r"\bCREATE\s+(?:OR\s+ALTER\s+)?(?:PROC(?:EDURE)?|FUNCTION|VIEW|TRIGGER)\b.*?\bAS\b",
    re.IGNORECASE | re.DOTALL,
)
_DECLARE = re.compile(r"\bDECLARE\b", re.IGNORECASE)


def context_lines(sql: str, masked: str | None = None) -> list[int]:
    """0-based line numbers of the object header (CREATE ... AS) and all DECLARE lines."""
    from app.services.rule_engine import mask_sql

    masked = masked if masked is not None else mask_sql(sql)
    picked: list[int] = []
    header = _HEADER.search(masked)
    if header:
        first = masked.count("\n", 0, header.start())
        last = masked.count("\n", 0, header.end())
        picked.extend(range(first, min(last + 1, first + 40)))
    for index, line in enumerate(masked.splitlines()):
        if _DECLARE.search(line) and index not in picked:
            picked.append(index)
    return sorted(picked)[:CONTEXT_MAX_LINES]


def _chunk_text(lines: list[str], context: list[int], index: int, count: int,
                start: int, end: int) -> str:
    width = max(3, len(str(len(lines))))
    ctx = "\n".join(f"L{n + 1:0{width}d}| {lines[n]}" for n in context) or "(yok)"
    return (
        f"\nBAĞLAM (nesne başlığı ve DECLARE satırları):\n{ctx}\n\n"
        f"Bu, nesnenin {index}/{count}. parçasıdır (satır {start + 1}–{end}). Yalnız bu "
        "parçadaki satırlar için ihlal raporla; başka parçalardaki kodu varsayma. Bağlam bloğu "
        "yalnız bilgi içindir.\n"
    )


def _chat_with_retry(config: LlmConfig, messages: list[dict[str, str]]) -> str:
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            return chat(config, messages)
        except LlmError as error:
            if not error.transient or attempt == len(RETRY_DELAYS):
                raise
            sleep(RETRY_DELAYS[attempt])
    raise AssertionError("unreachable")  # pragma: no cover


def _dedupe_key(finding: EngineFinding) -> tuple[int | None, str]:
    return finding.line, re.sub(r"\s+", " ", finding.snippet).strip().lower()


def review(
    config: LlmConfig,
    rule: RuleSpec,
    sql: str,
    object_name: str,
    metadata_text: str | None = None,
) -> list[EngineFinding]:
    """LLM review of one object; `metadata_text` (KATALOG METADATASI) goes before the SQL.

    Small objects take one call with the same prompt as before chunking existed. Large
    objects are split (`plan_chunks`); a chunk whose text fails the rule's precondition is
    skipped. If some chunks fail, an LlmError carrying the other chunks' findings is raised.
    """
    from app.services.rule_engine import PRECONDITION_FLAGS, mask_sql

    lines = sql.splitlines() or [""]
    chunks = plan_chunks(lines, config.chunk_lines)
    default_message = rule.description.strip() or rule.name
    metadata = f"\n{metadata_text.strip()}\n" if metadata_text else ""

    def ask(numbered: str, chunk: str) -> list[EngineFinding]:
        user = USER_TEMPLATE.format(
            code=rule.code,
            name=rule.name,
            prompt=(rule.llm_prompt or "").strip(),
            object_name=object_name or "-",
            metadata=metadata,
            chunk=chunk,
            numbered=numbered,
        )
        text = _chat_with_retry(
            config,
            [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}],
        )
        return parse_violations(text, sql, default_message)

    if len(chunks) == 1:
        return ask(numbered_sql(sql), "")

    masked = mask_sql(sql)
    haystack_lines = masked.splitlines() if rule.ignore_comments else lines
    precondition = None
    if rule.precondition:
        try:
            precondition = re.compile(rule.precondition, PRECONDITION_FLAGS)
        except re.error:
            precondition = None
    context = context_lines(sql, masked)
    findings: list[EngineFinding] = []
    seen: set[tuple[int | None, str]] = set()
    errors: list[str] = []
    for index, (start, end) in enumerate(chunks, 1):
        if precondition is not None and not precondition.search(
            "\n".join(haystack_lines[start:end])
        ):
            continue
        chunk_context = [n for n in context if not start <= n < end]
        try:
            found = ask(numbered_lines(lines, start, end, len(lines)),
                        _chunk_text(lines, chunk_context, index, len(chunks), start, end))
        except LlmError as error:
            errors.append(f"parça {index}/{len(chunks)} (satır {start + 1}–{end}): {error}")
            continue
        for finding in found:
            key = _dedupe_key(finding)
            if key not in seen:
                seen.add(key)
                findings.append(finding)
    if errors:
        raise LlmError("; ".join(errors), findings=findings)
    return findings


def _unreachable_message(base_url: str) -> str:
    host = (httpx.URL(base_url).host or "").lower()
    message = "LLM sunucusuna ulaşılamadı. Sunucunun çalıştığını ve Base URL'i kontrol edin."
    if host.endswith("docker.internal"):
        message += (
            " 'host.docker.internal' yalnızca Docker konteynerlerinin içinde anlamlıdır; bu uygulama"
            " doğrudan bu bilgisayarda çalışır. Model bu bilgisayardaysa 127.0.0.1, başka bir"
            " cihazdaysa o cihazın IP adresini kullanın (örn. http://100.x.x.x:1234/v1)."
        )
    elif host in ("127.0.0.1", "localhost", "::1"):
        message += (
            " Yerel sunucu (LM Studio: 'lms server start', Ollama: 'ollama serve') açık mı?"
        )
    return message


def list_models(config: LlmConfig) -> list[str]:
    """Model ids from the OpenAI-compatible ``GET /models``; raises LlmError on failure."""
    base = config.base_url.strip().rstrip("/")
    if base.endswith("/chat/completions"):
        base = base[: -len("/chat/completions")]
    headers = {"Authorization": f"Bearer {config.api_key}"} if config.api_key else {}
    try:
        with _client(min(float(config.timeout_seconds), 15.0)) as client:
            response = client.get(f"{base}/models", headers=headers)
    except httpx.TimeoutException:
        raise LlmError("LLM sunucusu zamanında yanıt vermedi (zaman aşımı).") from None
    except httpx.HTTPError:
        raise LlmError(_unreachable_message(config.base_url)) from None
    if response.status_code in (401, 403):
        raise LlmError(f"LLM API anahtarı reddedildi (HTTP {response.status_code}).")
    if response.status_code >= 400:
        raise LlmError(f"Model listesi alınamadı (HTTP {response.status_code}).")
    try:
        data = response.json()
    except ValueError:
        raise LlmError("Model listesi JSON değil. Base URL '/v1' ile mi bitiyor?") from None
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise LlmError("Model listesi beklenen biçimde değil.")
    return sorted(
        str(item["id"]) for item in items if isinstance(item, dict) and item.get("id")
    )


def test_connection(config: LlmConfig) -> tuple[bool, str, int | None]:
    """Small round trip; returns (ok, message, latency_ms)."""
    started = time.perf_counter()
    try:
        models = list_models(config)
    except LlmError as error:
        if "ulaşılamadı" in str(error) or "reddedildi" in str(error):
            return False, str(error), None
        models = []  # some providers have no /models; go on with the chat call
    if models and config.model not in models:
        chat_models = [m for m in models if "embed" not in m.lower()]
        return (
            False,
            f"'{config.model}' modeli sunucuda yok. Mevcut modeller: {', '.join(chat_models)}",
            None,
        )
    try:
        chat(
            config,
            [
                {"role": "system", "content": "Yalnızca JSON yanıt ver."},
                {"role": "user", "content": 'Şunu aynen döndür: {"ok": true}'},
            ],
        )
    except LlmError as error:
        return False, str(error), None
    latency = int((time.perf_counter() - started) * 1000)
    return True, f"LLM bağlantısı başarılı ({config.model}).", latency
