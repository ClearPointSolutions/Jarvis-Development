"""Apply durable commands in sequence; execution acknowledgement stays in nodes."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from jarvis_contracts.workflow import WorkflowSpec
from jarvis_contracts.workflow_nodes import NODE_DEFINITIONS
from jarvis_orchestrator.runtime.ownership import TERMINAL, RunOwnership, lock_events
from jarvis_persistence.models import JobModel, RunCommandModel, RunModel, WorkflowVersionModel


class CommandProcessor:
    def __init__(self, ownership: RunOwnership) -> None:
        self.ownership = ownership

    async def poll(self, limit: int = 100) -> None:
        async with self.ownership.sessions() as session:
            runs = list(
                (
                    await session.scalars(
                        select(RunCommandModel.run_id)
                        .where(RunCommandModel.status == "pending")
                        .group_by(RunCommandModel.run_id)
                        .order_by(RunCommandModel.run_id)
                        .limit(limit)
                    )
                ).all()
            )
        for run_id in runs:
            await self.apply(run_id)

    async def apply(self, run_id: UUID) -> None:
        async with self.ownership.sessions.begin() as session:
            await lock_events(session)
            run = await session.get(RunModel, run_id, with_for_update=True)
            if run is None:
                return
            commands = list(
                (
                    await session.scalars(
                        select(RunCommandModel)
                        .where(
                            RunCommandModel.run_id == run_id,
                            RunCommandModel.status == "pending",
                        )
                        .order_by(RunCommandModel.sequence)
                        .with_for_update()
                    )
                ).all()
            )
            cancel_pending = any(command.kind == "cancel" for command in commands)
            for command in commands:
                reason = "applied"
                status = "applied"
                if command.kind == "retry":
                    if run.status not in {"failed", "blocked"}:
                        reason, status = "retry_requires_failed_or_blocked", "rejected"
                    else:
                        await self._retry(session, run, command)
                elif run.status in TERMINAL:
                    reason, status = "terminal_run", "rejected"
                elif command.kind in {"pause", "resume"} and (
                    cancel_pending or run.desired_state == "cancelled"
                ):
                    reason, status = "cancel_dominates", "superseded"
                elif command.kind == "cancel":
                    run.desired_state = "cancelled"
                    run.status = "cancel_requested"
                    run.claimable_at = self.ownership.clock.now()
                    await self.ownership.event(session, run, "run.cancel_requested")
                elif command.kind == "pause":
                    if run.status == "paused":
                        reason, status = "already_paused", "rejected"
                    else:
                        run.desired_state = "paused"
                        run.status = "pause_requested"
                        run.claimable_at = self.ownership.clock.now()
                        await self.ownership.event(session, run, "run.pause_requested")
                elif command.kind == "resume":
                    if run.status != "paused":
                        reason, status = "resume_requires_paused", "rejected"
                    else:
                        run.desired_state = "running"
                        run.status = "queued"
                        retry_at = run.runtime_json.get("retry_at")
                        run.claimable_at = (
                            max(self.ownership.clock.now(), datetime.fromisoformat(retry_at))
                            if retry_at
                            else self.ownership.clock.now()
                        )
                        await self.ownership.event(session, run, "run.resumed")
                elif command.kind == "instruction":
                    instructions = list(run.runtime_json.get("instructions", []))
                    version = await session.get(WorkflowVersionModel, run.workflow_version_id)
                    try:
                        has_receiver = version is not None and any(
                            NODE_DEFINITIONS[node.type].external
                            and node.policy.accepts_runtime_instructions
                            for node in WorkflowSpec.model_validate(version.spec_json).nodes
                        )
                    except ValidationError:
                        has_receiver = False
                    if run.desired_state == "cancelled" or not has_receiver:
                        reason, status = "no_eligible_instruction_receiver", "rejected"
                    elif len(instructions) >= 100:
                        reason, status = "instruction_capacity", "rejected"
                    else:
                        instructions.append({"command_id": str(command.id), **command.payload_json})
                        run.runtime_json = {**run.runtime_json, "instructions": instructions}
                command.status = status
                command.applied_at = self.ownership.clock.now()
                run.version += 1
                await self.ownership.event(
                    session,
                    run,
                    "run.command_applied" if status == "applied" else "run.command_rejected",
                    {
                        "command_id": str(command.id),
                        "sequence": command.sequence,
                        "kind": command.kind,
                        "disposition": status,
                        "reason": reason,
                    },
                )

    async def _retry(self, session: AsyncSession, run: RunModel, command: RunCommandModel) -> None:
        number = await session.scalar(
            select(func.max(RunModel.run_number)).where(RunModel.job_id == run.job_id)
        )
        identifier = uuid7()
        linked = RunModel(
            id=identifier,
            job_id=run.job_id,
            run_number=(number or 0) + 1,
            parent_run_id=run.id,
            workflow_version_id=run.workflow_version_id,
            config_snapshot_id=run.config_snapshot_id,
            langgraph_thread_id=str(identifier),
            status="queued",
            desired_state="running",
            mode=run.mode,
            priority=run.priority,
            claimable_at=self.ownership.clock.now(),
            runtime_json={"demo_fixture": run.runtime_json["demo_fixture"]}
            if run.mode == "demo" and "demo_fixture" in run.runtime_json
            else {},
        )
        session.add(linked)
        job = await session.get(JobModel, run.job_id)
        assert job is not None
        job.status = "queued"
        await session.flush()
        await self.ownership.event(
            session,
            linked,
            "run.queued",
            {
                "retry_of_run_id": str(run.id),
                "command_id": str(command.id),
            },
        )
