"""M3 private references, durable circuit state and immutable usage accounting.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("GRANT INSERT, UPDATE ON control.configurations TO jarvis_v1_api")
    op.execute("GRANT INSERT ON control.configuration_revisions TO jarvis_v1_api")
    op.add_column(
        "configurations",
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        schema="control",
    )
    op.create_table(
        "configuration_private_refs",
        sa.Column(
            "revision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("control.configuration_revisions.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("secret_ref", sa.String(220)),
        sa.Column("deployment_ref", sa.String(220)),
        schema="control",
    )
    op.create_table(
        "provider_health",
        sa.Column(
            "revision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("control.configuration_revisions.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("circuit_state", sa.String(24), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True)),
        sa.Column("next_probe_at", sa.DateTime(timezone=True)),
        sa.Column("probe_lease_until", sa.DateTime(timezone=True)),
        sa.Column("observed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("version", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint(
            "status IN ('healthy','degraded','unavailable','misconfigured','unknown')",
            name="ck_provider_health_status",
        ),
        sa.CheckConstraint(
            "circuit_state IN ('closed','open','half_open')",
            name="ck_provider_health_circuit_state",
        ),
        sa.CheckConstraint("failure_count >= 0", name="ck_provider_health_failure_count"),
        schema="control",
    )
    op.create_table(
        "model_calls",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "profile_revision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("control.configuration_revisions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "provider_revision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("control.configuration_revisions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "route_revision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("control.configuration_revisions.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("control.runs.id", ondelete="RESTRICT"),
        ),
        sa.Column("correlation_id", sa.String(200), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("record_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("correlation_id", "idempotency_key", name="uq_model_calls_request"),
        schema="control",
    )
    op.create_index(
        "ix_model_calls_run_created", "model_calls", ["run_id", "created_at"], schema="control"
    )
    for table in ("configuration_private_refs", "model_calls"):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON control.{table} FOR EACH ROW EXECUTE FUNCTION control.reject_immutable_mutation()"
        )
    op.execute("GRANT SELECT, INSERT ON control.configuration_private_refs TO jarvis_v1_api")
    op.execute("GRANT SELECT ON control.configuration_private_refs TO jarvis_v1_orchestrator")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON control.provider_health TO jarvis_v1_api, jarvis_v1_orchestrator"
    )
    op.execute("GRANT SELECT ON control.provider_health, control.model_calls TO jarvis_v1_readonly")
    op.execute(
        "GRANT SELECT, INSERT ON control.model_calls TO jarvis_v1_api, jarvis_v1_orchestrator"
    )


def downgrade() -> None:
    op.execute("REVOKE INSERT, UPDATE ON control.configurations FROM jarvis_v1_api")
    op.execute("REVOKE INSERT ON control.configuration_revisions FROM jarvis_v1_api")
    op.drop_table("model_calls", schema="control")
    op.drop_table("provider_health", schema="control")
    op.drop_table("configuration_private_refs", schema="control")
    op.drop_column("configurations", "description", schema="control")
