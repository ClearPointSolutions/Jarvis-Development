"""Phase 4 physical worker capacity and repository-wide merge authority."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("integration_heads", sa.Column("target_branch", sa.String(200)), schema="control")
    op.execute("UPDATE control.integration_heads SET target_branch = branch")
    op.alter_column("integration_heads", "target_branch", nullable=False, schema="control")
    op.add_column(
        "worker_slots", sa.Column("physical_resource_id", sa.String(80)), schema="control"
    )
    op.execute(
        "UPDATE control.worker_slots SET physical_resource_id = worker_id::text "
        "WHERE physical_resource_id IS NULL"
    )
    op.alter_column("worker_slots", "physical_resource_id", nullable=False, schema="control")
    op.create_unique_constraint(
        "uq_worker_physical_slot_number",
        "worker_slots",
        ["physical_resource_id", "slot_number"],
        schema="control",
    )

    op.create_table(
        "worker_assignments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("mission_id", UUID(as_uuid=True), nullable=False),
        sa.Column("team_version_id", UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", UUID(as_uuid=True), nullable=False),
        sa.Column("task_attempt_id", UUID(as_uuid=True), nullable=False),
        sa.Column("role_key", sa.String(64), nullable=False),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column("fairness_sequence", sa.BigInteger(), nullable=False),
        sa.Column("required_capabilities_json", JSONB(), nullable=False),
        sa.Column("eligible_pool_snapshot_json", JSONB(), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), server_default="queued", nullable=False),
        sa.Column("selected_worker_revision_id", UUID(as_uuid=True)),
        sa.Column("worker_lease_id", UUID(as_uuid=True)),
        sa.Column("queued_reason", sa.String(240)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["mission_id"], ["control.missions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["team_version_id"], ["control.mission_team_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["run_id"], ["control.runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["task_attempt_id"], ["control.task_attempts.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["worker_lease_id"], ["control.worker_leases.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("task_attempt_id", name="uq_worker_assignment_attempt"),
        sa.CheckConstraint(
            "fairness_sequence > 0", name="ck_worker_assignments_fairness_sequence_positive"
        ),
        sa.CheckConstraint(
            "status IN ('queued','reserved','running','completed','failed','cancelled','unknown')",
            name="ck_worker_assignments_status",
        ),
        schema="control",
    )
    op.create_index(
        "ix_worker_assignments_fair_claim",
        "worker_assignments",
        ["status", "priority", "mission_id", "fairness_sequence"],
        schema="control",
    )

    op.create_table(
        "accepted_target_heads",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("repository_id", UUID(as_uuid=True), nullable=False),
        sa.Column("target_branch", sa.String(200), nullable=False),
        sa.Column("head_sha", sa.String(40), nullable=False),
        sa.Column("generation", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("lease_owner", UUID(as_uuid=True)),
        sa.Column("lease_generation", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("repository_id", "target_branch", name="uq_accepted_target_branch"),
        sa.CheckConstraint("generation >= 0", name="ck_accepted_target_heads_generation"),
        sa.CheckConstraint("char_length(head_sha) = 40", name="ck_accepted_target_heads_head_sha"),
        schema="control",
    )
    op.create_table(
        "merge_candidates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("repository_id", UUID(as_uuid=True), nullable=False),
        sa.Column("target_branch", sa.String(200), nullable=False),
        sa.Column("run_id", UUID(as_uuid=True), nullable=False),
        sa.Column("effect_id", UUID(as_uuid=True), nullable=False),
        sa.Column("task_attempt_id", UUID(as_uuid=True), nullable=False),
        sa.Column("profile_revision_id", UUID(as_uuid=True), nullable=False),
        sa.Column("base_sha", sa.String(40), nullable=False),
        sa.Column("candidate_sha", sa.String(40), nullable=False),
        sa.Column("verification_identity", sa.String(64), nullable=False),
        sa.Column("review_identity", sa.String(64), nullable=False),
        sa.Column("directive_identity", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), server_default="queued", nullable=False),
        sa.Column("expected_head_sha", sa.String(40)),
        sa.Column("accepted_generation", sa.BigInteger()),
        sa.Column("conflict_json", JSONB()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["run_id"], ["control.runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["effect_id"], ["control.effects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["task_attempt_id"], ["control.task_attempts.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "task_attempt_id", "candidate_sha", name="uq_merge_candidate_attempt_sha"
        ),
        sa.UniqueConstraint("effect_id", name="uq_merge_candidate_effect"),
        sa.CheckConstraint(
            "status IN ('queued','integrating','accepted','conflicted','rejected','blocked')",
            name="ck_merge_candidates_status",
        ),
        sa.CheckConstraint(
            "char_length(base_sha) = 40 AND char_length(candidate_sha) = 40",
            name="ck_merge_candidates_sha",
        ),
        schema="control",
    )
    op.create_index(
        "ix_merge_candidates_queue",
        "merge_candidates",
        ["repository_id", "target_branch", "status", "created_at"],
        schema="control",
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON control.worker_assignments, control.accepted_target_heads, control.merge_candidates TO jarvis_v1_api, jarvis_v1_orchestrator"
    )
    op.execute(
        "GRANT SELECT ON control.worker_assignments, control.accepted_target_heads, control.merge_candidates TO jarvis_v1_readonly"
    )


def downgrade() -> None:
    op.drop_index("ix_merge_candidates_queue", table_name="merge_candidates", schema="control")
    op.drop_table("merge_candidates", schema="control")
    op.drop_table("accepted_target_heads", schema="control")
    op.drop_index(
        "ix_worker_assignments_fair_claim", table_name="worker_assignments", schema="control"
    )
    op.drop_table("worker_assignments", schema="control")
    op.drop_constraint(
        "uq_worker_physical_slot_number", "worker_slots", schema="control", type_="unique"
    )
    op.drop_column("worker_slots", "physical_resource_id", schema="control")
    op.drop_column("integration_heads", "target_branch", schema="control")
