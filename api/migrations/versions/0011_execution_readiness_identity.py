"""Record truthful orchestrator runtime identity for readiness projections."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orchestrator_instances",
        sa.Column("runtime_mode", sa.String(16), nullable=False, server_default="unknown"),
        schema="control",
    )
    op.add_column(
        "orchestrator_instances",
        sa.Column("runtime_manifest_sha256", sa.String(64)),
        schema="control",
    )
    op.add_column(
        "orchestrator_instances",
        sa.Column("runtime_summary_json", JSONB(), nullable=False, server_default="{}"),
        schema="control",
    )
    op.create_check_constraint(
        op.f("ck_orchestrator_instances_runtime_mode"),
        "orchestrator_instances",
        "runtime_mode IN ('real','demo','unknown')",
        schema="control",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_orchestrator_instances_runtime_mode"),
        "orchestrator_instances",
        schema="control",
        type_="check",
        if_exists=True,
    )
    op.drop_column("orchestrator_instances", "runtime_summary_json", schema="control")
    op.drop_column("orchestrator_instances", "runtime_manifest_sha256", schema="control")
    op.drop_column("orchestrator_instances", "runtime_mode", schema="control")
