"""M2 security identities, run projection watermarks, and event wakeups.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from uuid6 import uuid7

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("role", sa.String(length=30), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("version", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint("role IN ('owner')", name=op.f("ck_users_role")),
        sa.CheckConstraint("username = lower(username)", name=op.f("ck_users_username_normalized")),
        sa.CheckConstraint(
            "username ~ '^[a-z0-9][a-z0-9_.-]{2,63}$'",
            name=op.f("ck_users_username_format"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("username", name=op.f("uq_users_username")),
        schema="control",
    )
    op.create_index(
        "uq_users_enabled_owner",
        "users",
        ["role"],
        unique=True,
        schema="control",
        postgresql_where=sa.text("enabled"),
    )

    # M1 had no project-creation API, but a developer database may contain M1 fixtures.
    # A disabled, unusable owner preserves those rows without making them accessible.
    legacy_owner_id = uuid7()
    op.execute(
        sa.text(
            "INSERT INTO control.users "
            "(id, username, password_hash, role, enabled, version) "
            "VALUES (:id, 'migration-unassigned', '!disabled-unusable', 'owner', false, 0)"
        ).bindparams(id=legacy_owner_id)
    )
    op.add_column(
        "projects", sa.Column("owner_user_id", sa.UUID(), nullable=True), schema="control"
    )
    op.execute(
        sa.text(
            "UPDATE control.projects SET owner_user_id = :id WHERE owner_user_id IS NULL"
        ).bindparams(id=legacy_owner_id)
    )
    op.alter_column("projects", "owner_user_id", nullable=False, schema="control")
    op.create_foreign_key(
        op.f("fk_projects_owner_user_id_users"),
        "projects",
        "users",
        ["owner_user_id"],
        ["id"],
        source_schema="control",
        referent_schema="control",
        ondelete="RESTRICT",
    )
    op.create_index("ix_projects_owner_user_id", "projects", ["owner_user_id"], schema="control")

    op.create_table(
        "sessions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf_secret_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.String(length=64), nullable=True),
        sa.Column("ip_prefix", sa.String(length=96), nullable=True),
        sa.Column("user_agent_hash", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "expires_at <= absolute_expires_at", name=op.f("ck_sessions_expiry_order")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["control.users.id"],
            name=op.f("fk_sessions_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_sessions_token_hash")),
        schema="control",
    )
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"], schema="control")
    op.create_index(
        "ix_sessions_user_active",
        "sessions",
        ["user_id", "expires_at"],
        schema="control",
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    op.create_table(
        "login_rate_limits",
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("subject_hash", sa.String(length=64), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "scope IN ('account','network')", name=op.f("ck_login_rate_limits_scope")
        ),
        sa.CheckConstraint(
            "failed_count >= 0", name=op.f("ck_login_rate_limits_failed_count_nonnegative")
        ),
        sa.PrimaryKeyConstraint("scope", "subject_hash", name=op.f("pk_login_rate_limits")),
        schema="control",
    )
    op.create_index(
        "ix_login_rate_limits_locked_until",
        "login_rate_limits",
        ["locked_until"],
        schema="control",
    )

    op.add_column(
        "runs",
        sa.Column("last_event_position", sa.BigInteger(), server_default="0", nullable=False),
        schema="control",
    )
    op.add_column(
        "runs",
        sa.Column("last_run_sequence", sa.BigInteger(), server_default="0", nullable=False),
        schema="control",
    )
    op.add_column(
        "runs",
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True),
        schema="control",
    )
    op.create_check_constraint(
        op.f("ck_runs_last_event_position_nonnegative"),
        "runs",
        "last_event_position >= 0",
        schema="control",
    )
    op.create_check_constraint(
        op.f("ck_runs_last_run_sequence_nonnegative"),
        "runs",
        "last_run_sequence >= 0",
        schema="control",
    )

    op.execute(
        """
        CREATE FUNCTION event_store.notify_event_commit()
        RETURNS trigger LANGUAGE plpgsql AS $body$
        DECLARE wake_position bigint;
        BEGIN
          SELECT max(global_position) INTO wake_position FROM inserted_events;
          IF wake_position IS NOT NULL THEN
            PERFORM pg_notify('jarvis_v1_events', wake_position::text);
          END IF;
          RETURN NULL;
        END
        $body$
        """
    )
    op.execute(
        """
        CREATE TRIGGER events_notify_after_insert
        AFTER INSERT ON event_store.events
        REFERENCING NEW TABLE AS inserted_events
        FOR EACH STATEMENT EXECUTE FUNCTION event_store.notify_event_commit()
        """
    )

    op.execute("GRANT SELECT, UPDATE ON control.users TO jarvis_v1_api")
    op.execute("GRANT SELECT, INSERT, UPDATE ON control.sessions TO jarvis_v1_api")
    op.execute("GRANT SELECT, INSERT, UPDATE ON control.login_rate_limits TO jarvis_v1_api")


def downgrade() -> None:
    op.execute("DROP TRIGGER events_notify_after_insert ON event_store.events")
    op.execute("DROP FUNCTION event_store.notify_event_commit()")
    op.drop_constraint(
        op.f("ck_runs_last_run_sequence_nonnegative"), "runs", schema="control", type_="check"
    )
    op.drop_constraint(
        op.f("ck_runs_last_event_position_nonnegative"), "runs", schema="control", type_="check"
    )
    op.drop_column("runs", "last_event_at", schema="control")
    op.drop_column("runs", "last_run_sequence", schema="control")
    op.drop_column("runs", "last_event_position", schema="control")
    op.drop_index(
        "ix_login_rate_limits_locked_until", table_name="login_rate_limits", schema="control"
    )
    op.drop_table("login_rate_limits", schema="control")
    op.drop_index("ix_sessions_user_active", table_name="sessions", schema="control")
    op.drop_index("ix_sessions_expires_at", table_name="sessions", schema="control")
    op.drop_table("sessions", schema="control")
    op.drop_index("ix_projects_owner_user_id", table_name="projects", schema="control")
    op.drop_constraint(
        op.f("fk_projects_owner_user_id_users"), "projects", schema="control", type_="foreignkey"
    )
    op.drop_column("projects", "owner_user_id", schema="control")
    op.drop_index("uq_users_enabled_owner", table_name="users", schema="control")
    op.drop_table("users", schema="control")
