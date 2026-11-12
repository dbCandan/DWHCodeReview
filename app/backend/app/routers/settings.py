"""LLM settings."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app import crypto, schemas
from app.db import get_session
from app.services import llm, presenters

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _validate(body: schemas.LlmSettingsInput) -> None:
    base_url = body.base_url.strip()
    if base_url and not base_url.lower().startswith(("http://", "https://")):
        raise HTTPException(422, "Base URL http:// veya https:// ile başlamalıdır.")
    if body.enabled and (not base_url or not body.model.strip()):
        raise HTTPException(422, "LLM etkinken Base URL ve model zorunludur.")
    if not 0 <= body.temperature <= 2:
        raise HTTPException(422, "Temperature 0 ile 2 arasında olmalıdır.")
    if not 5 <= body.timeout_seconds <= 3600:
        raise HTTPException(422, "Zaman aşımı 5 ile 3600 saniye arasında olmalıdır.")
    if not 50 <= body.chunk_lines <= 2000:
        raise HTTPException(422, "Parça satır sayısı 50 ile 2000 arasında olmalıdır.")


@router.get("/llm", response_model=schemas.LlmSettingsOut)
def get_llm(session: Session = Depends(get_session)) -> schemas.LlmSettingsOut:
    return presenters.llm_settings_out(presenters.llm_settings_row(session))


@router.put("/llm", response_model=schemas.LlmSettingsOut)
def put_llm(
    body: schemas.LlmSettingsInput, session: Session = Depends(get_session)
) -> schemas.LlmSettingsOut:
    _validate(body)
    row = presenters.llm_settings_row(session)
    row.enabled = body.enabled
    row.base_url = body.base_url.strip()
    row.model = body.model.strip()
    row.temperature = body.temperature
    row.timeout_seconds = body.timeout_seconds
    row.chunk_lines = body.chunk_lines
    if body.api_key and body.api_key.strip():
        row.api_key_enc = crypto.encrypt(body.api_key.strip())
    session.commit()
    return presenters.llm_settings_out(row)


def _config(body: schemas.LlmSettingsInput, session: Session) -> llm.LlmConfig:
    api_key = body.api_key.strip() if body.api_key and body.api_key.strip() else None
    if api_key is None:
        api_key = crypto.decrypt(presenters.llm_settings_row(session).api_key_enc)
    return llm.LlmConfig(
        base_url=body.base_url.strip(),
        model=body.model.strip(),
        api_key=api_key,
        temperature=body.temperature,
        timeout_seconds=max(5, min(body.timeout_seconds, 3600)),
        chunk_lines=max(50, min(body.chunk_lines, 2000)),
    )


@router.post("/llm/test", response_model=schemas.LlmTestResult)
async def test_llm(
    body: schemas.LlmSettingsInput, session: Session = Depends(get_session)
) -> schemas.LlmTestResult:
    base_url = body.base_url.strip()
    if not base_url.lower().startswith(("http://", "https://")) or not body.model.strip():
        return schemas.LlmTestResult(ok=False, message="Base URL ve model zorunludur.")
    config = _config(body, session)
    ok, message, latency = await run_in_threadpool(llm.test_connection, config)
    return schemas.LlmTestResult(ok=ok, message=message, latency_ms=latency)


@router.post("/llm/models", response_model=schemas.LlmModelList)
async def llm_models(
    body: schemas.LlmSettingsInput, session: Session = Depends(get_session)
) -> schemas.LlmModelList:
    """Model ids the endpoint offers (OpenAI-compatible GET /models), embeddings excluded."""
    if not body.base_url.strip().lower().startswith(("http://", "https://")):
        return schemas.LlmModelList(error="Base URL http:// veya https:// ile başlamalıdır.")
    try:
        models = await run_in_threadpool(llm.list_models, _config(body, session))
    except llm.LlmError as error:
        return schemas.LlmModelList(error=str(error))
    return schemas.LlmModelList(models=[m for m in models if "embed" not in m.lower()])
