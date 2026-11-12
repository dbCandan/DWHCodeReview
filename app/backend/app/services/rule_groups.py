"""Kind-based groups: regex/builtin rules belong to the quick-scan group, LLM rules to the
LLM group (RULE_ASSISTANT_SPEC "Ek: konu grupları"). Nothing happens when a group is missing."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models

QUICK_GROUP = "Hızlı Tarama (LLM'siz)"
LLM_GROUP = "LLM Kuralları"


def kind_group_ids(session: Session, kind: str) -> tuple[int | None, int | None]:
    """(group id to belong to, group id to leave) for a rule kind."""
    groups = {
        g.name: g.id
        for g in session.scalars(
            select(models.RuleGroup).where(models.RuleGroup.name.in_((QUICK_GROUP, LLM_GROUP)))
        )
    }
    if kind == "llm":
        return groups.get(LLM_GROUP), groups.get(QUICK_GROUP)
    return groups.get(QUICK_GROUP), groups.get(LLM_GROUP)


def sync_kind_groups(session: Session, rule: models.Rule) -> None:
    """Put the rule in the group of its kind and take it out of the other one."""
    join_id, leave_id = kind_group_ids(session, rule.kind)
    groups = [g for g in rule.groups if g.id != leave_id]
    if join_id is not None and all(g.id != join_id for g in groups):
        groups.append(session.get(models.RuleGroup, join_id))
    rule.groups = groups
