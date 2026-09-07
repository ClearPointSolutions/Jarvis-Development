"""M4 owner-scoped drafts and immutable workflow configuration bindings.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workflow_templates", sa.Column("owner_user_id", sa.UUID()), schema="control")
    op.create_foreign_key(
        "fk_workflow_templates_owner_user_id_users",
        "workflow_templates",
        "users",
        ["owner_user_id"],
        ["id"],
        source_schema="control",
        referent_schema="control",
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_workflow_templates_owner_user_id",
        "workflow_templates",
        ["owner_user_id"],
        schema="control",
    )
    op.add_column(
        "workflow_templates", sa.Column("current_draft_version_id", sa.UUID()), schema="control"
    )
    op.create_foreign_key(
        "fk_workflow_templates_current_draft_version",
        "workflow_templates",
        "workflow_versions",
        ["current_draft_version_id"],
        ["id"],
        source_schema="control",
        referent_schema="control",
        ondelete="RESTRICT",
    )
    op.add_column(
        "workflow_versions",
        sa.Column("resolved_snapshot_json", postgresql.JSONB()),
        schema="control",
    )
    op.add_column("workflow_versions", sa.Column("snapshot_hash", sa.String(64)), schema="control")
    op.create_table(
        "workflow_revision_references",
        sa.Column(
            "workflow_version_id",
            sa.UUID(),
            sa.ForeignKey("control.workflow_versions.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "revision_id",
            sa.UUID(),
            sa.ForeignKey("control.configuration_revisions.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        schema="control",
    )
    # Lock the referenced version before binding insertion so publish cannot race it.
    op.execute("""
        CREATE FUNCTION control.guard_workflow_binding() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP <> 'INSERT' THEN
            RAISE EXCEPTION 'workflow bindings are immutable' USING ERRCODE = '55000';
          END IF;
          PERFORM 1 FROM control.workflow_versions WHERE id = NEW.workflow_version_id
            AND published_at IS NULL FOR UPDATE;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'published workflow bindings are immutable' USING ERRCODE = '55000';
          END IF;
          RETURN NEW;
        END $$
    """)
    op.execute(
        "CREATE TRIGGER workflow_bindings_immutable BEFORE INSERT OR UPDATE OR DELETE ON control.workflow_revision_references FOR EACH ROW EXECUTE FUNCTION control.guard_workflow_binding()"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON control.workflow_templates, control.workflow_versions TO jarvis_v1_api"
    )
    op.execute("GRANT SELECT, INSERT ON control.workflow_revision_references TO jarvis_v1_api")
    op.execute(
        "GRANT SELECT ON control.workflow_revision_references TO jarvis_v1_orchestrator, jarvis_v1_readonly"
    )
    # Cross-template pointer injection is invalid even for application SQL.
    op.execute("""
        CREATE FUNCTION control.guard_workflow_pointers() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.current_draft_version_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM control.workflow_versions WHERE id=NEW.current_draft_version_id
            AND workflow_template_id=NEW.id AND published_at IS NULL
          ) THEN RAISE EXCEPTION 'invalid draft pointer' USING ERRCODE='23514'; END IF;
          IF NEW.current_published_version_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM control.workflow_versions WHERE id=NEW.current_published_version_id
            AND workflow_template_id=NEW.id AND published_at IS NOT NULL
          ) THEN RAISE EXCEPTION 'invalid publication pointer' USING ERRCODE='23514'; END IF;
          IF TG_OP='UPDATE' AND (NEW.owner_user_id IS DISTINCT FROM OLD.owner_user_id OR NEW.key <> OLD.key) THEN
            RAISE EXCEPTION 'workflow identity is immutable' USING ERRCODE='55000';
          END IF;
          RETURN NEW;
        END $$
    """)
    op.execute(
        "CREATE TRIGGER workflow_template_pointers BEFORE INSERT OR UPDATE ON control.workflow_templates FOR EACH ROW EXECUTE FUNCTION control.guard_workflow_pointers()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER workflow_template_pointers ON control.workflow_templates")
    op.execute("DROP FUNCTION control.guard_workflow_pointers()")
    op.drop_table("workflow_revision_references", schema="control")
    op.execute("DROP FUNCTION control.guard_workflow_binding()")
    op.execute(
        "REVOKE INSERT, UPDATE ON control.workflow_templates, control.workflow_versions FROM jarvis_v1_api"
    )
    op.drop_column("workflow_versions", "snapshot_hash", schema="control")
    op.drop_column("workflow_versions", "resolved_snapshot_json", schema="control")
    op.drop_constraint(
        "fk_workflow_templates_current_draft_version",
        "workflow_templates",
        schema="control",
        type_="foreignkey",
    )
    op.drop_column("workflow_templates", "current_draft_version_id", schema="control")
    op.drop_index(
        "ix_workflow_templates_owner_user_id",
        table_name="workflow_templates",
        schema="control",
    )
    op.drop_constraint(
        "fk_workflow_templates_owner_user_id_users",
        "workflow_templates",
        schema="control",
        type_="foreignkey",
    )
    op.drop_column("workflow_templates", "owner_user_id", schema="control")
