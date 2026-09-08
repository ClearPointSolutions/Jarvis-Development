"""M5 durable run queue and control metadata.

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("GRANT INSERT ON control.run_config_snapshots TO jarvis_v1_api")
    for column in (
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mode", sa.String(10), nullable=False, server_default="demo"),
        sa.Column("runtime_json", JSONB(), nullable=False, server_default="{}"),
        sa.Column("result_summary", sa.String(1024)),
        sa.Column("current_node", sa.String(80)),
    ):
        op.add_column("runs", column, schema="control")
    op.add_column(
        "run_leases", sa.Column("heartbeat_at", sa.DateTime(timezone=True)), schema="control"
    )
    op.create_check_constraint(
        op.f("ck_runs_mode"), "runs", "mode IN ('demo','real')", schema="control"
    )
    op.create_check_constraint(
        op.f("ck_runs_runtime_object"),
        "runs",
        "jsonb_typeof(runtime_json) = 'object'",
        schema="control",
    )
    op.create_index(
        "ix_runs_claim_order",
        "runs",
        ["priority", "claimable_at", "created_at", "id"],
        schema="control",
    )


def downgrade() -> None:
    op.execute("REVOKE INSERT ON control.run_config_snapshots FROM jarvis_v1_api")
    op.drop_index("ix_runs_claim_order", table_name="runs", schema="control")
    op.drop_constraint(
        op.f("ck_runs_runtime_object"), "runs", schema="control", type_="check", if_exists=True
    )
    op.drop_constraint(
        op.f("ck_runs_mode"), "runs", schema="control", type_="check", if_exists=True
    )
    op.drop_column("run_leases", "heartbeat_at", schema="control")
    for name in ("current_node", "result_summary", "runtime_json", "mode", "priority"):
        op.drop_column("runs", name, schema="control")
