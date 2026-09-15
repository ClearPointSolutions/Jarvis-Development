"""Raw inserts exercise intentional PostgreSQL defaults, without ORM defaults."""

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from uuid6 import uuid7

from jarvis_persistence.models import MissionModel, MissionTeamVersionModel
from tests.integration.support import seed_run
from tests.integration.test_m8_evidence import task_rows

pytestmark = pytest.mark.integration


async def test_phase_04_and_05_server_defaults(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seed = await seed_run(session_factory)
    _, attempt, effect = await task_rows(session_factory, seed.run_id, 1)
    mission, team, identity = uuid7(), uuid7(), uuid7()
    async with session_factory() as session:
        session.add(
            MissionModel(
                id=mission,
                project_id=seed.project_id,
                objective="Default probe",
                mode="demo",
                selected_team_version_id=team,
            )
        )
        await session.flush()
        session.add(
            MissionTeamVersionModel(
                id=team,
                mission_id=mission,
                version=1,
                selection_json={},
                content_hash="a" * 64,
            )
        )
        await session.flush()
        values = {
            "id": identity,
            "owner": seed.user_id,
            "run": seed.run_id,
            "attempt": attempt,
            "effect": effect,
            "mission": mission,
            "team": team,
            "sha": "a" * 40,
            "digest": "a" * 64,
        }
        probes: tuple[tuple[str, str, str, str, tuple[Any, ...]], ...] = (
            (
                "accepted_target_heads",
                "id,repository_id,target_branch,head_sha",
                ":id,:id,'main',:sha",
                "generation,lease_generation",
                (0, 0),
            ),
            (
                "worker_assignments",
                "id,mission_id,team_version_id,run_id,task_attempt_id,role_key,"
                "fairness_sequence,required_capabilities_json,eligible_pool_snapshot_json,snapshot_hash",
                ":id,:mission,:team,:run,:attempt,'developer',1,'[]','{}',:digest",
                "priority,status",
                (0, "queued"),
            ),
            (
                "merge_candidates",
                "id,repository_id,target_branch,run_id,effect_id,task_attempt_id,profile_revision_id,"
                "base_sha,candidate_sha,verification_identity,review_identity,directive_identity",
                ":id,:id,'main',:run,:effect,:attempt,:id,:sha,:sha,:digest,:digest,:digest",
                "status",
                ("queued",),
            ),
            (
                "operational_alerts",
                "id,owner_user_id,deduplication_key,kind,severity,scope_type,scope_id,reason,"
                "first_seen_at,last_seen_at",
                ":id,:owner,'probe','probe','warning','owner','probe','probe',now(),now()",
                "status,details_json,occurrences",
                ("active", {}, 1),
            ),
            (
                "notification_outbox",
                "id,alert_id,destination_id,deduplication_key,redacted_payload_json,next_attempt_at",
                ":id,:id,'disabled-fixture','probe','{}',now()",
                "status,attempt_count,max_attempts",
                ("pending", 0, 5),
            ),
            (
                "backup_manifests",
                "id,backup_id,recovery_generation,manifest_json",
                ":id,'probe',1,'{}'",
                "status",
                ("building",),
            ),
            (
                "qualification_runs",
                "id,owner_user_id,profile,environment_identity,release_identity,started_at",
                ":id,:owner,'24h','fixture','fixture',now()",
                "status,notes",
                ("running", ""),
            ),
        )
        for table, columns, supplied, returning, expected in probes:
            row = (
                await session.execute(
                    text(
                        f"INSERT INTO control.{table} ({columns}) VALUES ({supplied}) "
                        f"RETURNING {returning}"
                    ),
                    values,
                )
            ).one()
            assert tuple(row) == expected, table
        # Transaction-local replacement; rollback restores the original singleton.
        await session.execute(text("DELETE FROM control.recovery_generations WHERE id = 1"))
        row = (
            await session.execute(
                text(
                    "INSERT INTO control.recovery_generations (id) VALUES (1) "
                    "RETURNING generation,reason"
                )
            )
        ).one()
        assert tuple(row) == (1, "initial")
        await session.rollback()
