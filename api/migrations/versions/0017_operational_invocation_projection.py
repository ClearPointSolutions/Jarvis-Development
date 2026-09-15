"""Permit the owner-scoped operational query without exposing invocation payloads."""

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # effect_id joins to the API's owner-scoped runs; created_at is the fallback
    # when a stalled invocation has never reported activity. No payload access.
    op.execute(
        "GRANT SELECT (effect_id, created_at) ON control.worker_invocations TO jarvis_v1_api"
    )


def downgrade() -> None:
    op.execute(
        "REVOKE SELECT (effect_id, created_at) ON control.worker_invocations FROM jarvis_v1_api"
    )
