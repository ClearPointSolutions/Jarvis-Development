"""Bounded mission autonomy, durable wakeups, controls, and reservations."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_missions_lifecycle", "missions", schema="control", type_="check")
    op.create_check_constraint(
        "ck_missions_lifecycle",
        "missions",
        "lifecycle IN ('active','idle','waiting_for_capacity','waiting_for_approval',"
        "'blocked','paused','cancelling','cancelled','completed','archived')",
        schema="control",
    )
    op.add_column(
        "missions",
        sa.Column("autonomous", sa.Boolean(), server_default=sa.false(), nullable=False),
        schema="control",
    )
    for name, length in (
        ("waiting_reason", 240),
        ("next_action", 240),
        ("next_action_basis", 1024),
        ("user_action_required", 1024),
    ):
        op.add_column("missions", sa.Column(name, sa.String(length)), schema="control")
    op.add_column(
        "missions",
        sa.Column(
            "resource_limits_json",
            JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        schema="control",
    )
    op.add_column(
        "missions",
        sa.Column(
            "budget_window_started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema="control",
    )

    op.create_table(
        "mission_wakeups",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "mission_id",
            sa.UUID(),
            sa.ForeignKey("control.missions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("deduplication_key", sa.String(200), nullable=False),
        sa.Column("directive_version", sa.Integer(), nullable=False),
        sa.Column(
            "team_version_id",
            sa.UUID(),
            sa.ForeignKey("control.mission_team_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_event_cursor", sa.BigInteger()),
        sa.Column("accepted_target_identity", sa.String(200)),
        sa.Column("accepted_source_identity", sa.String(200)),
        sa.Column("snapshot_json", JSONB(), nullable=False),
        sa.Column("outcome_json", JSONB()),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("claimed_by", sa.String(160)),
        sa.Column("management_turn_id", sa.UUID()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("mission_id", "deduplication_key", name="uq_mission_wakeup_dedup"),
        sa.CheckConstraint(
            "kind IN ('user_direction','job_completed','job_failed','approval_decided','deadline')",
            name="ck_mission_wakeups_kind",
        ),
        sa.CheckConstraint(
            "status IN ('pending','claimed','turn_queued','committed','stale','failed')",
            name="ck_mission_wakeups_status",
        ),
        schema="control",
    )
    op.create_index(
        "ix_mission_wakeups_claim",
        "mission_wakeups",
        ["status", "scheduled_for", "created_at"],
        schema="control",
    )
    op.add_column("management_turns", sa.Column("wakeup_id", sa.UUID()), schema="control")
    op.add_column(
        "management_turns", sa.Column("source_event_cursor", sa.BigInteger()), schema="control"
    )
    op.create_unique_constraint(
        "uq_management_turns_wakeup_id", "management_turns", ["wakeup_id"], schema="control"
    )
    op.create_foreign_key(
        "fk_management_turns_wakeup",
        "management_turns",
        "mission_wakeups",
        ["wakeup_id"],
        ["id"],
        source_schema="control",
        referent_schema="control",
        ondelete="RESTRICT",
    )
    op.add_column("mission_work_items", sa.Column("source_wakeup_id", sa.UUID()), schema="control")
    op.add_column(
        "mission_work_items", sa.Column("accepted_event_cursor", sa.BigInteger()), schema="control"
    )
    op.create_foreign_key(
        "fk_mission_work_items_source_wakeup_id_mission_wakeups",
        "mission_work_items",
        "mission_wakeups",
        ["source_wakeup_id"],
        ["id"],
        source_schema="control",
        referent_schema="control",
        ondelete="RESTRICT",
    )

    op.create_table(
        "mission_admission_controls",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("scope_key", sa.String(200), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("safe_point_instruction", sa.String(2000)),
        sa.Column(
            "resource_limits_json",
            JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("version", sa.Integer(), server_default="0", nullable=False),
        sa.UniqueConstraint("scope_key", name="uq_mission_admission_scope_key"),
        sa.CheckConstraint(
            "scope IN ('mission','team','global')", name="ck_mission_admission_controls_scope"
        ),
        sa.CheckConstraint(
            "state IN ('open','paused','draining','cancelling')",
            name="ck_mission_admission_controls_state",
        ),
        schema="control",
    )
    op.create_table(
        "mission_resource_reservations",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "mission_id",
            sa.UUID(),
            sa.ForeignKey("control.missions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("scope_key", sa.String(200), nullable=False),
        sa.Column("action_id", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("liability_json", JSONB(), nullable=False),
        sa.Column("actual_json", JSONB()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("price_unit", sa.String(40), server_default="currency", nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("reconciled_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("scope_key", "action_id", name="uq_mission_resource_action"),
        sa.CheckConstraint(
            "status IN ('reserved','reconciled','unknown','released')",
            name="ck_mission_resource_reservations_status",
        ),
        schema="control",
    )
    op.create_index(
        "ix_mission_resource_scope_window",
        "mission_resource_reservations",
        ["scope_key", "window_started_at"],
        schema="control",
    )

    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON control.mission_admission_controls, "
        "control.mission_resource_reservations TO jarvis_v1_api, jarvis_v1_orchestrator"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON control.mission_wakeups TO "
        "jarvis_v1_api, jarvis_v1_orchestrator"
    )
    op.execute(
        "GRANT SELECT ON control.mission_wakeups, control.mission_admission_controls, "
        "control.mission_resource_reservations TO jarvis_v1_readonly"
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_mission_work_items_source_wakeup_id_mission_wakeups",
        "mission_work_items",
        schema="control",
        type_="foreignkey",
    )
    op.drop_column("mission_work_items", "accepted_event_cursor", schema="control")
    op.drop_column("mission_work_items", "source_wakeup_id", schema="control")
    op.drop_constraint(
        "fk_management_turns_wakeup", "management_turns", schema="control", type_="foreignkey"
    )
    op.drop_constraint(
        "uq_management_turns_wakeup_id", "management_turns", schema="control", type_="unique"
    )
    op.drop_column("management_turns", "source_event_cursor", schema="control")
    op.drop_column("management_turns", "wakeup_id", schema="control")
    op.drop_index(
        "ix_mission_resource_scope_window",
        table_name="mission_resource_reservations",
        schema="control",
    )
    op.drop_table("mission_resource_reservations", schema="control")
    op.drop_table("mission_admission_controls", schema="control")
    op.drop_index("ix_mission_wakeups_claim", table_name="mission_wakeups", schema="control")
    op.drop_table("mission_wakeups", schema="control")
    for name in (
        "budget_window_started_at",
        "resource_limits_json",
        "user_action_required",
        "next_action_basis",
        "next_action",
        "waiting_reason",
        "autonomous",
    ):
        op.drop_column("missions", name, schema="control")
    op.drop_constraint("ck_missions_lifecycle", "missions", schema="control", type_="check")
    op.create_check_constraint(
        "ck_missions_lifecycle",
        "missions",
        "lifecycle IN ('active','waiting','blocked','completed','archived')",
        schema="control",
    )
