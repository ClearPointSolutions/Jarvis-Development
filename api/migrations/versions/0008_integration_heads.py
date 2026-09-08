"""M8 sealed integration generation selection and fenced repository lease."""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "integration_heads",
        sa.Column(
            "run_id",
            sa.UUID(),
            sa.ForeignKey("control.runs.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("repository_id", sa.UUID(), primary_key=True),
        sa.Column("base_sha", sa.String(40), nullable=False),
        sa.Column("head_sha", sa.String(40), nullable=False),
        sa.Column("branch", sa.String(200), nullable=False),
        sa.Column(
            "snapshot_artifact_id",
            sa.UUID(),
            sa.ForeignKey("control.artifacts.id", ondelete="RESTRICT"),
        ),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column(
            "lease_owner", sa.UUID(), sa.ForeignKey("control.effects.id", ondelete="RESTRICT")
        ),
        sa.Column("acquired_at", sa.DateTime(timezone=True)),
        sa.Column("renewed_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("released_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("generation >= 0", name="generation"),
        sa.CheckConstraint("char_length(head_sha) = 40 AND char_length(base_sha) = 40", name="sha"),
        schema="control",
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON control.integration_heads TO jarvis_v1_orchestrator"
    )
    op.execute("GRANT SELECT ON control.integration_heads TO jarvis_v1_api, jarvis_v1_readonly")


def downgrade() -> None:
    op.drop_table("integration_heads", schema="control")
