"""Private immutable normalized model response receipts for crash recovery."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_response_receipts",
        sa.Column("call_id", sa.UUID(), primary_key=True),
        sa.Column(
            "run_id",
            sa.UUID(),
            sa.ForeignKey("control.runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("response_digest", sa.String(64), nullable=False),
        sa.Column("response_json", JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        schema="control",
    )
    op.execute(
        "CREATE TRIGGER model_response_receipts_immutable BEFORE UPDATE OR DELETE "
        "ON control.model_response_receipts FOR EACH ROW "
        "EXECUTE FUNCTION control.reject_immutable_mutation()"
    )
    op.execute(
        "REVOKE ALL ON control.model_response_receipts FROM jarvis_v1_api, jarvis_v1_readonly"
    )
    op.execute("GRANT SELECT, INSERT ON control.model_response_receipts TO jarvis_v1_orchestrator")


def downgrade() -> None:
    op.drop_table("model_response_receipts", schema="control")
