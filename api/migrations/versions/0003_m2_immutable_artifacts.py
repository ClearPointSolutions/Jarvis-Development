"""M2 immutable event artifact metadata and least-privilege writer grants.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("GRANT SELECT ON public.alembic_version TO jarvis_v1_api")
    op.execute("GRANT INSERT ON control.artifacts TO jarvis_v1_api")
    op.execute("REVOKE UPDATE ON control.artifacts FROM jarvis_v1_orchestrator")
    op.execute(
        "CREATE TRIGGER artifacts_immutable BEFORE UPDATE OR DELETE ON control.artifacts "
        "FOR EACH ROW EXECUTE FUNCTION control.reject_immutable_mutation()"
    )


def downgrade() -> None:
    op.execute("REVOKE SELECT ON public.alembic_version FROM jarvis_v1_api")
    op.execute("DROP TRIGGER artifacts_immutable ON control.artifacts")
    op.execute("REVOKE INSERT ON control.artifacts FROM jarvis_v1_api")
    op.execute("GRANT UPDATE ON control.artifacts TO jarvis_v1_orchestrator")
