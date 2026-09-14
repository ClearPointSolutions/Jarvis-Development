"""Persistent missions, manager turns, fixed teams, and work items."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("version", sa.Integer(), server_default="0", nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "missions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "project_id",
            sa.UUID(),
            sa.ForeignKey("control.projects.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("constraints_json", JSONB(), nullable=False),
        sa.Column("lifecycle", sa.String(20), nullable=False),
        sa.Column("mode", sa.String(10), nullable=False),
        sa.Column("directive_version", sa.Integer(), nullable=False),
        sa.Column("selected_team_version_id", sa.UUID(), nullable=False),
        sa.Column("next_message_sequence", sa.BigInteger(), server_default="0", nullable=False),
        *timestamps(),
        sa.CheckConstraint(
            "lifecycle IN ('active','waiting','blocked','completed','archived')",
            name="ck_missions_lifecycle",
        ),
        sa.CheckConstraint("mode IN ('demo','real')", name="ck_missions_mode"),
        sa.CheckConstraint("directive_version > 0", name="ck_missions_directive_version_positive"),
        schema="control",
    )
    op.create_table(
        "mission_team_versions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "mission_id",
            sa.UUID(),
            sa.ForeignKey("control.missions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("selection_json", JSONB(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("mission_id", "version", name="uq_mission_team_version"),
        sa.CheckConstraint("version > 0", name="ck_mission_team_versions_version_positive"),
        sa.CheckConstraint(
            "char_length(content_hash) = 64", name="ck_mission_team_versions_content_hash_length"
        ),
        schema="control",
    )
    op.create_foreign_key(
        "fk_missions_selected_team_version",
        "missions",
        "mission_team_versions",
        ["selected_team_version_id"],
        ["id"],
        source_schema="control",
        referent_schema="control",
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_table(
        "mission_directives",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "mission_id",
            sa.UUID(),
            sa.ForeignKey("control.missions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("constraints_json", JSONB(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("mission_id", "version", name="uq_mission_directive_version"),
        sa.CheckConstraint("version > 0", name="ck_mission_directives_version_positive"),
        sa.CheckConstraint(
            "char_length(content_hash) = 64", name="ck_mission_directives_content_hash_length"
        ),
        schema="control",
    )
    op.create_table(
        "mission_messages",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "mission_id",
            sa.UUID(),
            sa.ForeignKey("control.missions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("identity", sa.String(160), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("directive_version", sa.Integer(), nullable=False),
        sa.Column("management_turn_id", sa.UUID()),
        sa.Column("context_json", JSONB(), nullable=False),
        sa.Column("disposition", sa.String(16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("mission_id", "sequence", name="uq_mission_message_sequence"),
        sa.CheckConstraint("sequence > 0", name="ck_mission_messages_sequence_positive"),
        sa.CheckConstraint("role IN ('user','manager','system')", name="ck_mission_messages_role"),
        sa.CheckConstraint(
            "disposition IN ('queued','delivered','stale','failed')",
            name="ck_mission_messages_disposition",
        ),
        schema="control",
    )
    op.create_table(
        "management_turns",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "mission_id",
            sa.UUID(),
            sa.ForeignKey("control.missions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "input_message_id",
            sa.UUID(),
            sa.ForeignKey("control.mission_messages.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("directive_version", sa.Integer(), nullable=False),
        sa.Column(
            "team_version_id",
            sa.UUID(),
            sa.ForeignKey("control.mission_team_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("input_snapshot_json", JSONB(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("mode", sa.String(10), nullable=False),
        sa.Column("allow_paid_inference", sa.Boolean(), nullable=False),
        sa.Column("model_call_id", sa.UUID()),
        sa.Column("response_json", JSONB()),
        sa.Column("failure_code", sa.String(120)),
        sa.Column("claimable_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("claimed_by", sa.String(160)),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('queued','running','applied','stale','failed')",
            name="ck_management_turns_status",
        ),
        sa.CheckConstraint("mode IN ('demo','real')", name="ck_management_turns_mode"),
        schema="control",
    )
    op.create_index(
        "ix_management_turns_claim",
        "management_turns",
        ["status", "claimable_at", "created_at"],
        schema="control",
    )
    op.create_foreign_key(
        "fk_mission_messages_management_turn",
        "mission_messages",
        "management_turns",
        ["management_turn_id"],
        ["id"],
        source_schema="control",
        referent_schema="control",
        ondelete="RESTRICT",
    )
    op.create_table(
        "mission_work_items",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "mission_id",
            sa.UUID(),
            sa.ForeignKey("control.missions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("key", sa.String(40), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("acceptance_criteria_json", JSONB(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("lifecycle", sa.String(16), nullable=False),
        sa.Column("directive_version", sa.Integer(), nullable=False),
        sa.Column(
            "team_version_id",
            sa.UUID(),
            sa.ForeignKey("control.mission_team_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "job_id", sa.UUID(), sa.ForeignKey("control.jobs.id", ondelete="RESTRICT"), unique=True
        ),
        sa.Column(
            "run_id", sa.UUID(), sa.ForeignKey("control.runs.id", ondelete="RESTRICT"), unique=True
        ),
        *timestamps(),
        sa.UniqueConstraint("mission_id", "key", name="uq_mission_work_item_key"),
        sa.CheckConstraint(
            "lifecycle IN ('pending','ready','started','accepted','blocked','cancelled')",
            name="ck_mission_work_items_lifecycle",
        ),
        schema="control",
    )
    op.create_table(
        "mission_work_item_dependencies",
        sa.Column(
            "work_item_id",
            sa.UUID(),
            sa.ForeignKey("control.mission_work_items.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "depends_on_work_item_id",
            sa.UUID(),
            sa.ForeignKey("control.mission_work_items.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.CheckConstraint(
            "work_item_id <> depends_on_work_item_id",
            name="ck_mission_work_item_dependencies_not_self",
        ),
        sa.UniqueConstraint(
            "work_item_id", "depends_on_work_item_id", name="uq_mission_work_item_dependency"
        ),
        schema="control",
    )
    op.add_column("model_calls", sa.Column("management_turn_id", sa.UUID()), schema="control")
    op.create_foreign_key(
        "fk_model_calls_management_turn_id_management_turns",
        "model_calls",
        "management_turns",
        ["management_turn_id"],
        ["id"],
        source_schema="control",
        referent_schema="control",
        ondelete="RESTRICT",
    )
    op.alter_column(
        "model_response_receipts",
        "run_id",
        existing_type=sa.UUID(),
        nullable=True,
        schema="control",
    )
    op.add_column(
        "model_response_receipts", sa.Column("management_turn_id", sa.UUID()), schema="control"
    )
    op.create_foreign_key(
        "fk_model_response_receipts_management_turn_id_management_turns",
        "model_response_receipts",
        "management_turns",
        ["management_turn_id"],
        ["id"],
        source_schema="control",
        referent_schema="control",
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_model_response_receipts_exactly_one_owner",
        "model_response_receipts",
        "num_nonnulls(run_id, management_turn_id) = 1",
        schema="control",
    )
    for table in ("mission_team_versions", "mission_directives"):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON control.{table} FOR EACH ROW EXECUTE FUNCTION control.reject_immutable_mutation()"
        )
    op.execute(
        "GRANT INSERT, UPDATE ON control.missions, control.mission_messages, control.management_turns, control.mission_work_items, control.mission_work_item_dependencies TO jarvis_v1_api"
    )
    op.execute(
        "GRANT INSERT ON control.mission_team_versions, control.mission_directives TO jarvis_v1_api"
    )
    op.execute(
        "GRANT SELECT ON control.missions, control.mission_team_versions, control.mission_directives, control.mission_messages, control.management_turns, control.mission_work_items, control.mission_work_item_dependencies TO jarvis_v1_api, jarvis_v1_orchestrator, jarvis_v1_readonly"
    )
    op.execute(
        "GRANT INSERT, UPDATE ON control.management_turns, control.mission_messages, control.missions, control.mission_work_items TO jarvis_v1_orchestrator"
    )
    op.execute(
        "GRANT INSERT, DELETE ON control.mission_work_item_dependencies TO jarvis_v1_orchestrator"
    )


def downgrade() -> None:
    # Phase-owned immutable records cannot survive once their owner table is
    # removed. Temporarily remove the legacy immutability triggers, discard only
    # management-turn-owned rows, then restore the pre-Phase-1 triggers.
    op.execute("DROP TRIGGER model_response_receipts_immutable ON control.model_response_receipts")
    op.execute("DELETE FROM control.model_response_receipts WHERE management_turn_id IS NOT NULL")
    op.execute(
        "CREATE TRIGGER model_response_receipts_immutable BEFORE UPDATE OR DELETE "
        "ON control.model_response_receipts FOR EACH ROW "
        "EXECUTE FUNCTION control.reject_immutable_mutation()"
    )
    op.execute("DROP TRIGGER model_calls_immutable ON control.model_calls")
    op.execute("DELETE FROM control.model_calls WHERE management_turn_id IS NOT NULL")
    op.execute(
        "CREATE TRIGGER model_calls_immutable BEFORE UPDATE OR DELETE "
        "ON control.model_calls FOR EACH ROW "
        "EXECUTE FUNCTION control.reject_immutable_mutation()"
    )
    op.drop_constraint(
        "ck_model_response_receipts_exactly_one_owner",
        "model_response_receipts",
        schema="control",
        type_="check",
    )
    op.drop_constraint(
        "fk_model_response_receipts_management_turn_id_management_turns",
        "model_response_receipts",
        schema="control",
        type_="foreignkey",
    )
    op.drop_column("model_response_receipts", "management_turn_id", schema="control")
    op.alter_column(
        "model_response_receipts",
        "run_id",
        existing_type=sa.UUID(),
        nullable=False,
        schema="control",
    )
    op.drop_constraint(
        "fk_model_calls_management_turn_id_management_turns",
        "model_calls",
        schema="control",
        type_="foreignkey",
    )
    op.drop_column("model_calls", "management_turn_id", schema="control")
    op.drop_table("mission_work_item_dependencies", schema="control")
    op.drop_table("mission_work_items", schema="control")
    op.drop_constraint(
        "fk_mission_messages_management_turn",
        "mission_messages",
        schema="control",
        type_="foreignkey",
    )
    op.drop_index("ix_management_turns_claim", table_name="management_turns", schema="control")
    op.drop_table("management_turns", schema="control")
    op.drop_table("mission_messages", schema="control")
    op.drop_table("mission_directives", schema="control")
    op.drop_constraint(
        "fk_missions_selected_team_version", "missions", schema="control", type_="foreignkey"
    )
    op.drop_table("mission_team_versions", schema="control")
    op.drop_table("missions", schema="control")
