"""Routing rules management routes."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import ActivityAction, ActivityLog, RoutingRule, User
from app.schemas import (
    ActionResult,
    RoutingRuleCreate,
    RoutingRuleListOut,
    RoutingRuleOut,
    RoutingRuleUpdate,
)
from app.services.sip_service import sip_service

router = APIRouter(prefix="/routing-rules", tags=["routing-rules"])


async def _get_rule(db: AsyncSession, rule_id: int) -> RoutingRule | None:
    result = await db.execute(
        select(RoutingRule)
        .options(selectinload(RoutingRule.source_device), selectinload(RoutingRule.target_device))
        .where(RoutingRule.id == rule_id)
    )
    return result.scalar_one_or_none()


async def _rebuild_dialplan(db: AsyncSession) -> None:
    """Load all enabled rules from DB and regenerate extensions.conf in background."""
    result = await db.execute(
        select(RoutingRule)
        .where(RoutingRule.enabled == True)  # noqa: E712
        .order_by(RoutingRule.priority.desc(), RoutingRule.id)
    )
    rules = result.scalars().all()

    # Group by call_code → list of target SIP accounts
    rules_by_code: dict[str, list[str]] = {}
    for rule in rules:
        if not rule.call_code or not rule.target_sip_account:
            continue
        rules_by_code.setdefault(rule.call_code, [])
        if rule.target_sip_account not in rules_by_code[rule.call_code]:
            rules_by_code[rule.call_code].append(rule.target_sip_account)

    # Convert to apartment-style dicts for generate_extensions_conf
    apt_dicts = [
        {"call_code": code, "monitors": accounts, "cloud_relay_enabled": False, "cloud_sip_account": None}
        for code, accounts in rules_by_code.items()
    ]

    # Run blocking file I/O in thread pool so async loop is not blocked
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, sip_service.generate_extensions_conf, apt_dicts)


@router.get("", response_model=RoutingRuleListOut)
async def list_rules(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    count_result = await db.execute(select(func.count(RoutingRule.id)))
    total = count_result.scalar_one()

    result = await db.execute(
        select(RoutingRule)
        .options(selectinload(RoutingRule.source_device), selectinload(RoutingRule.target_device))
        .order_by(RoutingRule.priority.desc(), RoutingRule.id)
    )
    items = result.scalars().all()
    return RoutingRuleListOut(items=list(items), total=total)


@router.post("", response_model=RoutingRuleOut, status_code=status.HTTP_201_CREATED)
async def create_rule(
    payload: RoutingRuleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rule = RoutingRule(**payload.model_dump())
    db.add(rule)
    await db.flush()

    log = ActivityLog(
        action=ActivityAction.RULE_CREATED,
        actor=current_user.username,
        detail=f"Rule '{rule.name}' (call_code={rule.call_code}) created",
        success=True,
    )
    db.add(log)

    # Reload with relationships
    rule = await _get_rule(db, rule.id)
    await db.commit()
    await _rebuild_dialplan(db)
    return rule


@router.get("/{rule_id}", response_model=RoutingRuleOut)
async def get_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    rule = await _get_rule(db, rule_id)
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    return rule


@router.put("/{rule_id}", response_model=RoutingRuleOut)
async def update_rule(
    rule_id: int,
    payload: RoutingRuleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rule = await _get_rule(db, rule_id)
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(rule, field, value)

    log = ActivityLog(
        action=ActivityAction.RULE_UPDATED,
        actor=current_user.username,
        detail=f"Rule id={rule_id} updated",
        success=True,
    )
    db.add(log)
    await db.flush()
    result = await _get_rule(db, rule_id)
    await db.commit()
    await _rebuild_dialplan(db)
    return result


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rule = await _get_rule(db, rule_id)
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")

    log = ActivityLog(
        action=ActivityAction.RULE_DELETED,
        actor=current_user.username,
        detail=f"Rule '{rule.name}' (id={rule_id}) deleted",
        success=True,
    )
    db.add(log)
    await db.delete(rule)
    await db.commit()
    await _rebuild_dialplan(db)


@router.post("/sync-dialplan", response_model=ActionResult)
async def sync_dialplan(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Вручную пересгенерировать extensions.conf из текущих правил и перезагрузить dialplan."""
    await _rebuild_dialplan(db)
    return ActionResult(success=True, message="Dialplan синхронизирован")
