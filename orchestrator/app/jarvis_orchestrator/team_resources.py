"""Atomic team inference admission shared by managers and run model nodes."""

from uuid import UUID

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from jarvis_persistence.models import ManagementTurnModel, ModelCallModel, RunModel


async def inference_calls(session: AsyncSession, mission_id: UUID, team_version_id: UUID) -> int:
    """Count logical calls, not the paired started/result accounting rows."""
    management_turns = select(ManagementTurnModel.id).where(
        ManagementTurnModel.mission_id == mission_id,
        ManagementTurnModel.team_version_id == team_version_id,
    )
    runs = select(RunModel.id).where(
        RunModel.runtime_json["mission_id"].astext == str(mission_id),
        RunModel.runtime_json["team_version_id"].astext == str(team_version_id),
    )
    return int(
        await session.scalar(
            select(func.count(func.distinct(ModelCallModel.correlation_id))).where(
                or_(
                    ModelCallModel.management_turn_id.in_(management_turns),
                    ModelCallModel.run_id.in_(runs),
                )
            )
        )
        or 0
    )


async def reserve_inference_call(
    session: AsyncSession,
    mission_id: UUID,
    team_version_id: UUID,
    maximum: int,
) -> None:
    """Serialize check-plus-intent; caller records its started row before commit."""
    key = f"team-inference:{mission_id}:{team_version_id}"
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": key})
    if await inference_calls(session, mission_id, team_version_id) >= maximum:
        raise ValueError("team_inference_call_budget_exceeded")
