"""Rule groups."""

import re

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app import models, schemas
from app.db import get_session
from app.services import presenters

router = APIRouter(prefix="/api/rule-groups", tags=["rule-groups"])

COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _get_group(session: Session, group_id: int) -> models.RuleGroup:
    group = session.get(models.RuleGroup, group_id)
    if group is None:
        raise HTTPException(404, "Kural grubu bulunamadı.")
    return group


def _apply(
    session: Session, group: models.RuleGroup, body: schemas.RuleGroupInput, group_id: int | None
) -> None:
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "Grup adı zorunludur.")
    if len(name) > 100:
        raise HTTPException(422, "Grup adı en fazla 100 karakter olabilir.")
    if not COLOR_RE.fullmatch(body.color.strip()):
        raise HTTPException(422, "Renk #RRGGBB biçiminde olmalıdır.")
    existing = session.scalar(select(models.RuleGroup).where(models.RuleGroup.name == name))
    if existing is not None and existing.id != group_id:
        raise HTTPException(409, f"'{name}' adlı bir grup zaten var.")
    rule_ids = sorted(set(body.rule_ids))
    rules = list(session.scalars(select(models.Rule).where(models.Rule.id.in_(rule_ids))))
    if len(rules) != len(rule_ids):
        missing = set(rule_ids) - {r.id for r in rules}
        raise HTTPException(422, f"Kural bulunamadı: {', '.join(map(str, sorted(missing)))}")
    group.name = name
    group.description = body.description.strip()
    group.color = body.color.strip().upper()
    group.rules = rules


@router.get("", response_model=list[schemas.RuleGroupOut])
def list_groups(session: Session = Depends(get_session)) -> list[schemas.RuleGroupOut]:
    stmt = (
        select(models.RuleGroup)
        .options(selectinload(models.RuleGroup.rules))
        .order_by(models.RuleGroup.name)
    )
    return [presenters.group_out(group) for group in session.scalars(stmt)]


@router.post("", response_model=schemas.RuleGroupOut, status_code=201)
def create_group(
    body: schemas.RuleGroupInput, session: Session = Depends(get_session)
) -> schemas.RuleGroupOut:
    group = models.RuleGroup()
    _apply(session, group, body, None)
    session.add(group)
    session.commit()
    return presenters.group_out(group)


@router.put("/{group_id}", response_model=schemas.RuleGroupOut)
def update_group(
    group_id: int, body: schemas.RuleGroupInput, session: Session = Depends(get_session)
) -> schemas.RuleGroupOut:
    group = _get_group(session, group_id)
    _apply(session, group, body, group_id)
    session.commit()
    return presenters.group_out(group)


@router.delete("/{group_id}", status_code=204)
def delete_group(group_id: int, session: Session = Depends(get_session)) -> Response:
    session.delete(_get_group(session, group_id))
    session.commit()
    return Response(status_code=204)
