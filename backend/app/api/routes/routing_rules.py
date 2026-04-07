"""Routing rules management routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import ActivityAction, ActivityLog, RoutingRule, User
from app.schemas import (
    RoutingRuleCreate,
    RoutingRuleListOut,
    RoutingRuleOut,
    RoutingRuleUpdate,
)

router = APIRouter(prefix="/routing-rules", tags=["routing-rules"])


async def _get_rule(db: AsyncSession, rule_id: int) -> RoutingRule | None:
    result = await db.execute(
        select(RoutingRule)
        .options(selectinload(RoutingRule.source_device), selectinload(RoutingRule.target_device))
        .where(RoutingRule.id == rule_id)
    )
    return result.scalar_one_or_none()


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
    return await _get_rule(db, rule_id)


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
