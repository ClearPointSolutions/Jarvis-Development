"""Transactional admission and maximum-liability accounting for missions."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from jarvis_contracts.base import sha256_digest
from jarvis_contracts.missions import MissionResourceLimits, MissionUsageView
from jarvis_persistence.models import (
    MissionAdmissionControlModel,
    MissionModel,
    MissionResourceReservationModel,
)

COUNT_FIELDS = (
    "calls",
    "input_tokens",
    "output_tokens",
    "active_jobs",
    "wall_seconds",
    "iterations",
    "new_work_items",
)
LIMIT_FIELDS = {
    "calls": "max_calls",
    "input_tokens": "max_input_tokens",
    "output_tokens": "max_output_tokens",
    "active_jobs": "max_active_jobs",
    "wall_seconds": "max_wall_seconds",
    "iterations": "max_iterations",
    "new_work_items": "max_new_work_items",
}

SHARED_RESOURCE_LIMITS = MissionResourceLimits(
    max_calls=1_000_000,
    max_input_tokens=1_000_000_000,
    max_output_tokens=1_000_000_000,
    max_active_jobs=128,
    max_wall_seconds=31_536_000,
    max_iterations=100_000,
    max_new_work_items=100_000,
)


class MissionAdmissionDeniedError(RuntimeError):
    pass


class MissionBudgetDeniedError(RuntimeError):
    pass


def scope_keys(mission: MissionModel) -> tuple[str, str, str]:
    return ("global", f"team:{mission.selected_team_version_id}", f"mission:{mission.id}")


async def ensure_controls(session: AsyncSession, mission: MissionModel) -> None:
    mission_limits = MissionResourceLimits.model_validate(mission.resource_limits_json)
    for scope, key in zip(("global", "team", "mission"), scope_keys(mission), strict=True):
        row = await session.scalar(
            select(MissionAdmissionControlModel).where(
                MissionAdmissionControlModel.scope_key == key
            )
        )
        if row is None:
            await session.execute(
                insert(MissionAdmissionControlModel)
                .values(
                    id=uuid7(),
                    scope=scope,
                    scope_key=key,
                    state="open",
                    resource_limits_json=(
                        mission_limits if scope == "mission" else SHARED_RESOURCE_LIMITS
                    ).model_dump(mode="json"),
                )
                .on_conflict_do_nothing(index_elements=["scope_key"])
            )
    await session.flush()


async def require_admission(
    session: AsyncSession, mission: MissionModel, *, operation: str
) -> dict[str, str]:
    await ensure_controls(session, mission)
    rows = list(
        await session.scalars(
            select(MissionAdmissionControlModel)
            .where(MissionAdmissionControlModel.scope_key.in_(scope_keys(mission)))
            .order_by(MissionAdmissionControlModel.scope_key)
            .with_for_update()
        )
    )
    states = {row.scope: row.state for row in rows}
    denied = [row for row in rows if row.state != "open"]
    if denied:
        detail = ",".join(f"{row.scope}:{row.state}" for row in denied)
        raise MissionAdmissionDeniedError(f"{operation}_admission_paused:{detail}")
    if mission.lifecycle in {"paused", "cancelling", "cancelled", "completed", "archived"}:
        raise MissionAdmissionDeniedError(f"{operation}_mission_{mission.lifecycle}")
    return states


def _window_start(now: datetime, limits: MissionResourceLimits) -> datetime:
    epoch = int(now.timestamp())
    return datetime.fromtimestamp(epoch - (epoch % limits.window_seconds), tz=now.tzinfo)


def _add(target: dict[str, int | Decimal], values: Mapping[str, object]) -> None:
    for field in COUNT_FIELDS:
        value = values.get(field)
        if value is not None:
            if not isinstance(value, (int, str)):
                raise MissionBudgetDeniedError("budget_value_invalid")
            target[field] = int(target[field]) + int(value)
    amount = values.get("cost_amount")
    if amount is not None:
        target["cost_amount"] = Decimal(str(target["cost_amount"])) + Decimal(str(amount))


async def reserve(
    session: AsyncSession,
    mission: MissionModel,
    *,
    action_id: str,
    kind: str,
    liability: dict[str, int | str | None],
    currency: str,
    price_unit: str = "currency",
    now: datetime,
) -> tuple[MissionResourceReservationModel, ...]:
    """Atomically reserve the same maximum liability at all three scopes."""

    await ensure_controls(session, mission)
    controls = list(
        await session.scalars(
            select(MissionAdmissionControlModel)
            .where(MissionAdmissionControlModel.scope_key.in_(scope_keys(mission)))
            .order_by(MissionAdmissionControlModel.scope_key)
            .with_for_update()
        )
    )
    created: list[MissionResourceReservationModel] = []
    digest = sha256_digest(liability)
    for control in controls:
        limits = MissionResourceLimits.model_validate(control.resource_limits_json)
        if limits.currency != currency:
            raise MissionBudgetDeniedError("budget_currency_mismatch")
        window = _window_start(now, limits)
        existing = await session.scalar(
            select(MissionResourceReservationModel).where(
                MissionResourceReservationModel.scope_key == control.scope_key,
                MissionResourceReservationModel.action_id == action_id,
            )
        )
        if existing is not None:
            if (
                sha256_digest(existing.liability_json) != digest
                or existing.currency != currency
                or existing.price_unit != price_unit
            ):
                raise MissionBudgetDeniedError("budget_reservation_identity_mismatch")
            created.append(existing)
            continue
        rows = list(
            await session.scalars(
                select(MissionResourceReservationModel).where(
                    MissionResourceReservationModel.scope_key == control.scope_key,
                    MissionResourceReservationModel.window_started_at == window,
                    MissionResourceReservationModel.status != "released",
                )
            )
        )
        total: dict[str, int | Decimal] = {field: 0 for field in COUNT_FIELDS}
        total["cost_amount"] = Decimal(0)
        for row in rows:
            if row.currency != currency or row.price_unit != price_unit:
                raise MissionBudgetDeniedError("budget_price_unit_mismatch")
            values = (row.actual_json or {}) if row.status == "reconciled" else row.liability_json
            _add(total, values)
        _add(total, liability)
        for field, limit_name in LIMIT_FIELDS.items():
            if int(total[field]) > int(getattr(limits, limit_name)):
                raise MissionBudgetDeniedError(f"budget_{field}_exceeded")
        cost = Decimal(str(total["cost_amount"]))
        if cost and (limits.max_cost is None or cost > limits.max_cost):
            raise MissionBudgetDeniedError("budget_cost_exceeded")
        row = MissionResourceReservationModel(
            id=uuid7(),
            mission_id=mission.id,
            scope_key=control.scope_key,
            action_id=action_id,
            kind=kind,
            liability_json=dict(liability),
            status="reserved",
            currency=currency,
            price_unit=price_unit,
            window_started_at=window,
        )
        session.add(row)
        created.append(row)
    await session.flush()
    return tuple(created)


async def reconcile(
    session: AsyncSession,
    mission: MissionModel,
    *,
    action_id: str,
    actual: dict[str, int | str | None] | None,
    unknown: bool,
    now: datetime,
) -> None:
    rows = list(
        await session.scalars(
            select(MissionResourceReservationModel)
            .where(
                MissionResourceReservationModel.scope_key.in_(scope_keys(mission)),
                MissionResourceReservationModel.action_id == action_id,
            )
            .with_for_update()
        )
    )
    if not rows:
        raise MissionBudgetDeniedError("budget_reservation_missing")
    for row in rows:
        if row.status in {"reconciled", "unknown"}:
            continue
        row.actual_json = actual
        row.status = "unknown" if unknown else "reconciled"
        row.reconciled_at = now


async def release(
    session: AsyncSession, mission: MissionModel, *, action_id: str, now: datetime
) -> None:
    rows = list(
        await session.scalars(
            select(MissionResourceReservationModel)
            .where(
                MissionResourceReservationModel.scope_key.in_(scope_keys(mission)),
                MissionResourceReservationModel.action_id == action_id,
            )
            .with_for_update()
        )
    )
    for row in rows:
        if row.status == "reserved":
            row.status = "released"
            row.reconciled_at = now


async def usage_view(
    session: AsyncSession, mission: MissionModel, now: datetime
) -> MissionUsageView:
    limits = MissionResourceLimits.model_validate(mission.resource_limits_json)
    window = _window_start(now, limits)
    rows = list(
        await session.scalars(
            select(MissionResourceReservationModel).where(
                MissionResourceReservationModel.scope_key == f"mission:{mission.id}",
                MissionResourceReservationModel.window_started_at == window,
                MissionResourceReservationModel.status != "released",
            )
        )
    )
    reserved: dict[str, int | Decimal] = {field: 0 for field in COUNT_FIELDS}
    actual: dict[str, int | Decimal] = {field: 0 for field in COUNT_FIELDS}
    reserved["cost_amount"] = Decimal(0)
    actual["cost_amount"] = Decimal(0)
    unknown = False
    for row in rows:
        if row.status in {"reserved", "unknown"}:
            _add(reserved, row.liability_json)
            unknown = unknown or row.status == "unknown"
        elif row.actual_json is not None:
            _add(actual, row.actual_json)

    def public(values: dict[str, int | Decimal]) -> dict[str, int | str | None]:
        return {
            **{field: int(values[field]) for field in COUNT_FIELDS},
            "cost_amount": str(values["cost_amount"]),
            "currency": limits.currency,
        }

    return MissionUsageView(
        window_started_at=window,
        window_seconds=limits.window_seconds,
        reserved=public(reserved),
        actual=public(actual),
        unknown_liability=unknown,
        limits=limits,
    )
