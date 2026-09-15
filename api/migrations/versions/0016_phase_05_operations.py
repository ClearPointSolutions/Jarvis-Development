"""Phase 5 unattended operations, recovery and qualification ledgers."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operational_alerts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("deduplication_key", sa.String(240), nullable=False),
        sa.Column("kind", sa.String(80), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("scope_type", sa.String(32), nullable=False),
        sa.Column("scope_id", sa.String(200), nullable=False),
        sa.Column("reason", sa.String(1024), nullable=False),
        sa.Column("details_json", JSONB(), server_default="{}", nullable=False),
        sa.Column("occurrences", sa.Integer(), server_default="1", nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_notified_at", sa.DateTime(timezone=True)),
        sa.Column("recovered_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["owner_user_id"], ["control.users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "owner_user_id", "deduplication_key", name="uq_operational_alert_dedup"
        ),
        sa.CheckConstraint(
            "severity IN ('warning','critical')", name="ck_operational_alerts_severity"
        ),
        sa.CheckConstraint("status IN ('active','recovered')", name="ck_operational_alerts_status"),
        schema="control",
    )
    op.create_index(
        "ix_operational_alerts_owner_status",
        "operational_alerts",
        ["owner_user_id", "status", "last_seen_at"],
        schema="control",
    )
    op.create_table(
        "notification_outbox",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("alert_id", UUID(as_uuid=True), nullable=False),
        sa.Column("destination_id", sa.String(160), nullable=False),
        sa.Column("deduplication_key", sa.String(240), nullable=False),
        sa.Column("redacted_payload_json", JSONB(), nullable=False),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="5", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error_code", sa.String(120)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["alert_id"], ["control.operational_alerts.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "destination_id", "deduplication_key", name="uq_notification_outbox_dedup"
        ),
        sa.CheckConstraint(
            "status IN ('pending','delivering','delivered','failed')",
            name="ck_notification_outbox_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND max_attempts > 0",
            name="ck_notification_outbox_attempt_bounds",
        ),
        schema="control",
    )
    op.create_index(
        "ix_notification_outbox_claim",
        "notification_outbox",
        ["status", "next_attempt_at"],
        schema="control",
    )
    op.create_table(
        "retention_tombstones",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("identity_scope", sa.String(120), nullable=False),
        sa.Column("identity_digest", sa.String(64), nullable=False),
        sa.Column("resource_kind", sa.String(80), nullable=False),
        sa.Column("owner_user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provenance_json", JSONB(), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["control.users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "identity_scope", "identity_digest", name="uq_retention_tombstone_identity"
        ),
        sa.CheckConstraint(
            "char_length(identity_digest) = 64",
            name="ck_retention_tombstones_identity_digest",
        ),
        schema="control",
    )
    op.create_table(
        "recovery_generations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("generation", sa.BigInteger(), server_default="1", nullable=False),
        sa.Column(
            "automatic_dispatch_enabled", sa.Boolean(), server_default="true", nullable=False
        ),
        sa.Column("reason", sa.String(1024), server_default="initial", nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("id = 1", name="ck_recovery_generations_singleton"),
        sa.CheckConstraint("generation > 0", name="ck_recovery_generations_generation_positive"),
        schema="control",
    )
    op.execute(
        "INSERT INTO control.recovery_generations "
        "(id, generation, automatic_dispatch_enabled, reason) VALUES (1, 1, true, 'initial')"
    )
    op.create_table(
        "backup_manifests",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("backup_id", sa.String(160), nullable=False),
        sa.Column("status", sa.String(16), server_default="building", nullable=False),
        sa.Column("recovery_generation", sa.BigInteger(), nullable=False),
        sa.Column("manifest_json", JSONB(), nullable=False),
        sa.Column("manifest_sha256", sa.String(64)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("backup_id", name="uq_backup_manifest_backup_id"),
        sa.CheckConstraint(
            "status IN ('building','complete','invalid','restored','blocked')",
            name="ck_backup_manifests_status",
        ),
        schema="control",
    )
    op.create_table(
        "qualification_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("profile", sa.String(8), nullable=False),
        sa.Column("environment_identity", sa.String(240), nullable=False),
        sa.Column("release_identity", sa.String(240), nullable=False),
        sa.Column("status", sa.String(16), server_default="running", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("observations_json", JSONB(), server_default="[]", nullable=False),
        sa.Column("notes", sa.String(2000), server_default="", nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["control.users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("profile IN ('24h','72h','7d')", name="ck_qualification_runs_profile"),
        sa.CheckConstraint(
            "status IN ('running','passed','failed','cancelled')",
            name="ck_qualification_runs_status",
        ),
        schema="control",
    )
    tables = (
        "operational_alerts, control.notification_outbox, control.retention_tombstones, "
        "control.recovery_generations, control.backup_manifests, control.qualification_runs"
    )
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE ON control.{tables} TO jarvis_v1_api, jarvis_v1_orchestrator"
    )
    op.execute(f"GRANT SELECT ON control.{tables} TO jarvis_v1_readonly")


def downgrade() -> None:
    op.drop_table("qualification_runs", schema="control")
    op.drop_table("backup_manifests", schema="control")
    op.drop_table("recovery_generations", schema="control")
    op.drop_table("retention_tombstones", schema="control")
    op.drop_index(
        "ix_notification_outbox_claim", table_name="notification_outbox", schema="control"
    )
    op.drop_table("notification_outbox", schema="control")
    op.drop_index(
        "ix_operational_alerts_owner_status", table_name="operational_alerts", schema="control"
    )
    op.drop_table("operational_alerts", schema="control")
