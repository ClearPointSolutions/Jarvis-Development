"""Private immutable per-call paid inference budget authorization grants."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_budget_grants",
        sa.Column("call_id", sa.UUID(), primary_key=True),
        sa.Column(
            "run_id",
            sa.UUID(),
            sa.ForeignKey("control.runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "route_revision_id",
            sa.UUID(),
            sa.ForeignKey("control.configuration_revisions.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "profile_revision_id",
            sa.UUID(),
            sa.ForeignKey("control.configuration_revisions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "provider_revision_id",
            sa.UUID(),
            sa.ForeignKey("control.configuration_revisions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("policy_digest", sa.String(64), nullable=False),
        sa.Column("decision", sa.String(24), nullable=False),
        sa.Column("reasons_json", JSONB(), nullable=False),
        sa.Column("estimated_cost", sa.Numeric(20, 10)),
        sa.Column("run_spend_before", sa.Numeric(20, 10)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "decision IN ('allow', 'deny', 'require_approval')",
            name="ck_model_budget_grants_decision",
        ),
        schema="control",
    )
    op.create_index(
        "ix_model_budget_grants_run_id", "model_budget_grants", ["run_id"], schema="control"
    )
    op.execute(
        "CREATE TRIGGER model_budget_grants_immutable BEFORE UPDATE OR DELETE "
        "ON control.model_budget_grants FOR EACH ROW "
        "EXECUTE FUNCTION control.reject_immutable_mutation()"
    )
    op.execute("REVOKE ALL ON control.model_budget_grants FROM jarvis_v1_api")
    op.execute("GRANT SELECT ON control.model_budget_grants TO jarvis_v1_readonly")
    op.execute("GRANT SELECT, INSERT ON control.model_budget_grants TO jarvis_v1_orchestrator")


def downgrade() -> None:
    op.drop_index("ix_model_budget_grants_run_id", "model_budget_grants", schema="control")
    op.drop_table("model_budget_grants", schema="control")
