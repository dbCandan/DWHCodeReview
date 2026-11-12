"""Rule exceptions (finding suppression)."""

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app import models, schemas
from app.db import get_session
from app.services import exceptions, presenters

router = APIRouter(tags=["rule-exceptions"])


@router.get("/api/rule-exceptions", response_model=list[schemas.RuleExceptionOut])
def list_exceptions(
    rule_id: int | None = None, session: Session = Depends(get_session)
) -> list[schemas.RuleExceptionOut]:
    stmt = (
        select(models.RuleException)
        .join(models.Rule)
        .options(selectinload(models.RuleException.rule))
        .order_by(models.Rule.code, models.RuleException.id)
    )
    if rule_id is not None:
        stmt = stmt.where(models.RuleException.rule_id == rule_id)
    return [presenters.exception_out(row) for row in session.scalars(stmt)]


@router.post(
    "/api/rules/{rule_id}/exceptions", response_model=schemas.RuleExceptionOut, status_code=201
)
def create_exception(
    rule_id: int, body: schemas.RuleExceptionInput, session: Session = Depends(get_session)
) -> schemas.RuleExceptionOut:
    rule = session.get(models.Rule, rule_id)
    if rule is None:
        raise HTTPException(404, "Kural bulunamadı.")
    database = exceptions.clean(body.database)
    schema = exceptions.clean(body.schema_)
    object_name = exceptions.clean(body.object_name)
    pattern = exceptions.clean(body.snippet_pattern)
    try:
        exceptions.validate(database, schema, object_name, pattern, body.reason)
    except exceptions.ExceptionError as error:
        raise HTTPException(422, str(error)) from None
    row = models.RuleException(
        rule=rule, database=database, schema=schema, object_name=object_name,
        snippet_pattern=pattern, reason=body.reason.strip(),
    )
    session.add(row)
    session.commit()
    return presenters.exception_out(row)


@router.delete("/api/rule-exceptions/{exception_id}", status_code=204)
def delete_exception(exception_id: int, session: Session = Depends(get_session)) -> Response:
    row = session.get(models.RuleException, exception_id)
    if row is None:
        raise HTTPException(404, "İstisna bulunamadı.")
    session.delete(row)
    session.commit()
    return Response(status_code=204)
