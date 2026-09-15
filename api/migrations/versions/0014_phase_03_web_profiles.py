"""Phase 3 project execution-profile selection."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("project_type", sa.String(20), server_default="python", nullable=False),
        schema="control",
    )
    op.add_column(
        "projects",
        sa.Column(
            "execution_profile_revision_ids_json",
            JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        schema="control",
    )
    op.create_check_constraint(
        "ck_projects_project_type",
        "projects",
        "project_type IN ('python','node','full_stack')",
        schema="control",
    )
    op.create_check_constraint(
        "ck_projects_execution_profiles_array",
        "projects",
        "jsonb_typeof(execution_profile_revision_ids_json) = 'array'",
        schema="control",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_projects_execution_profiles_array", "projects", schema="control", type_="check"
    )
    op.drop_constraint("ck_projects_project_type", "projects", schema="control", type_="check")
    op.drop_column("projects", "execution_profile_revision_ids_json", schema="control")
    op.drop_column("projects", "project_type", schema="control")
