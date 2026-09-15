"""M1 relational model for durable orchestration facts."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from uuid6 import uuid7

CONTROL_SCHEMA = "control"
EVENT_SCHEMA = "event_store"
LANGGRAPH_SCHEMA = "langgraph"

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class ModelResponseReceiptModel(Base):
    __tablename__ = "model_response_receipts"
    __table_args__ = (
        CheckConstraint("num_nonnulls(run_id, management_turn_id) = 1", name="exactly_one_owner"),
        {"schema": CONTROL_SCHEMA},
    )

    call_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID | None] = mapped_column(ForeignKey("control.runs.id", ondelete="RESTRICT"))
    management_turn_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("control.management_turns.id", ondelete="RESTRICT")
    )
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    response_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    response_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ModelBudgetGrantModel(Base):
    """Immutable per-call authorization for billed inference."""

    __tablename__ = "model_budget_grants"
    __table_args__ = (
        CheckConstraint("decision IN ('allow', 'deny', 'require_approval')", name="decision"),
        {"schema": CONTROL_SCHEMA},
    )

    call_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("control.runs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    route_revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.configuration_revisions.id", ondelete="RESTRICT")
    )
    profile_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.configuration_revisions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    provider_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.configuration_revisions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(String(24), nullable=False)
    reasons_json: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    run_spend_before: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MutableRow:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class UserModel(MutableRow, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('owner')", name="role"),
        CheckConstraint("username = lower(username)", name="username_normalized"),
        CheckConstraint("username ~ '^[a-z0-9][a-z0-9_.-]{2,63}$'", name="username_format"),
        Index(
            "uq_users_enabled_owner",
            "role",
            unique=True,
            postgresql_where=text("enabled"),
        ),
        {"schema": CONTROL_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid7)
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False, default="owner")
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SessionModel(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint("expires_at <= absolute_expires_at", name="expiry_order"),
        Index(
            "ix_sessions_user_active",
            "user_id",
            "expires_at",
            postgresql_where=text("revoked_at IS NULL"),
        ),
        Index("ix_sessions_expires_at", "expires_at"),
        {"schema": CONTROL_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid7)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.users.id", ondelete="RESTRICT"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    csrf_secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(String(64))
    ip_prefix: Mapped[str | None] = mapped_column(String(96))
    user_agent_hash: Mapped[str | None] = mapped_column(String(64))


class LoginRateLimitModel(Base):
    __tablename__ = "login_rate_limits"
    __table_args__ = (
        CheckConstraint("scope IN ('account','network')", name="scope"),
        CheckConstraint("failed_count >= 0", name="failed_count_nonnegative"),
        Index("ix_login_rate_limits_locked_until", "locked_until"),
        {"schema": CONTROL_SCHEMA},
    )

    scope: Mapped[str] = mapped_column(String(20), primary_key=True)
    subject_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProjectModel(MutableRow, Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'archived')", name="status"),
        CheckConstraint("project_type IN ('python','node','full_stack')", name="project_type"),
        CheckConstraint(
            "jsonb_typeof(execution_profile_revision_ids_json) = 'array'",
            name="execution_profiles_array",
        ),
        Index("ix_projects_owner_user_id", "owner_user_id"),
        {"schema": CONTROL_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid7)
    owner_user_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.users.id", ondelete="RESTRICT"), nullable=False
    )
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    project_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="python", server_default="python"
    )
    execution_profile_revision_ids_json: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")


class MissionModel(MutableRow, Base):
    __tablename__ = "missions"
    __table_args__ = (
        CheckConstraint(
            "lifecycle IN ('active','idle','waiting_for_capacity','waiting_for_approval',"
            "'blocked','paused','cancelling','cancelled','completed','archived')",
            name="lifecycle",
        ),
        CheckConstraint("mode IN ('demo','real')", name="mode"),
        CheckConstraint("directive_version > 0", name="directive_version_positive"),
        {"schema": CONTROL_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid7)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.projects.id", ondelete="RESTRICT"), nullable=False
    )
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    constraints_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    lifecycle: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    mode: Mapped[str] = mapped_column(String(10), nullable=False)
    autonomous: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    waiting_reason: Mapped[str | None] = mapped_column(String(240))
    next_action: Mapped[str | None] = mapped_column(String(240))
    next_action_basis: Mapped[str | None] = mapped_column(String(1024))
    user_action_required: Mapped[str | None] = mapped_column(String(1024))
    resource_limits_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    budget_window_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    directive_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    selected_team_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            f"{CONTROL_SCHEMA}.mission_team_versions.id",
            name="fk_missions_selected_team_version",
            ondelete="RESTRICT",
            use_alter=True,
            deferrable=True,
            initially="DEFERRED",
        ),
        nullable=False,
    )
    next_message_sequence: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )


class MissionTeamVersionModel(Base):
    __tablename__ = "mission_team_versions"
    __table_args__ = (
        UniqueConstraint("mission_id", "version", name="uq_mission_team_version"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint("char_length(content_hash) = 64", name="content_hash_length"),
        {"schema": CONTROL_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid7)
    mission_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.missions.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    selection_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MissionDirectiveModel(Base):
    __tablename__ = "mission_directives"
    __table_args__ = (
        UniqueConstraint("mission_id", "version", name="uq_mission_directive_version"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint("char_length(content_hash) = 64", name="content_hash_length"),
        {"schema": CONTROL_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid7)
    mission_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.missions.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    constraints_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MissionMessageModel(Base):
    __tablename__ = "mission_messages"
    __table_args__ = (
        UniqueConstraint("mission_id", "sequence", name="uq_mission_message_sequence"),
        CheckConstraint("sequence > 0", name="sequence_positive"),
        CheckConstraint("role IN ('user','manager','system')", name="role"),
        CheckConstraint(
            "disposition IN ('queued','delivered','stale','failed')", name="disposition"
        ),
        {"schema": CONTROL_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid7)
    mission_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.missions.id", ondelete="RESTRICT"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    identity: Mapped[str] = mapped_column(String(160), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    directive_version: Mapped[int] = mapped_column(Integer, nullable=False)
    management_turn_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            f"{CONTROL_SCHEMA}.management_turns.id",
            name="fk_mission_messages_management_turn",
            ondelete="RESTRICT",
            use_alter=True,
        )
    )
    context_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    disposition: Mapped[str] = mapped_column(String(16), nullable=False, default="delivered")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ManagementTurnModel(Base):
    __tablename__ = "management_turns"
    __table_args__ = (
        CheckConstraint("status IN ('queued','running','applied','stale','failed')", name="status"),
        CheckConstraint("mode IN ('demo','real')", name="mode"),
        Index("ix_management_turns_claim", "status", "claimable_at", "created_at"),
        {"schema": CONTROL_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid7)
    mission_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.missions.id", ondelete="RESTRICT"), nullable=False
    )
    input_message_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.mission_messages.id", ondelete="RESTRICT"), nullable=False
    )
    directive_version: Mapped[int] = mapped_column(Integer, nullable=False)
    team_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.mission_team_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    wakeup_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            f"{CONTROL_SCHEMA}.mission_wakeups.id",
            name="fk_management_turns_wakeup",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        unique=True,
    )
    source_event_cursor: Mapped[int | None] = mapped_column(BigInteger)
    input_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    mode: Mapped[str] = mapped_column(String(10), nullable=False)
    allow_paid_inference: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    model_call_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    response_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    failure_code: Mapped[str | None] = mapped_column(String(120))
    claimable_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claimed_by: Mapped[str | None] = mapped_column(String(160))
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MissionWorkItemModel(MutableRow, Base):
    __tablename__ = "mission_work_items"
    __table_args__ = (
        UniqueConstraint("mission_id", "key", name="uq_mission_work_item_key"),
        CheckConstraint(
            "lifecycle IN ('pending','ready','started','accepted','blocked','cancelled')",
            name="lifecycle",
        ),
        {"schema": CONTROL_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid7)
    mission_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.missions.id", ondelete="RESTRICT"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    acceptance_criteria_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lifecycle: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    directive_version: Mapped[int] = mapped_column(Integer, nullable=False)
    team_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.mission_team_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.jobs.id", ondelete="RESTRICT"), unique=True
    )
    run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.runs.id", ondelete="RESTRICT"), unique=True
    )
    source_wakeup_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.mission_wakeups.id", ondelete="RESTRICT")
    )
    accepted_event_cursor: Mapped[int | None] = mapped_column(BigInteger)


class MissionWorkItemDependencyModel(Base):
    __tablename__ = "mission_work_item_dependencies"
    __table_args__ = (
        CheckConstraint("work_item_id <> depends_on_work_item_id", name="not_self"),
        {"schema": CONTROL_SCHEMA},
    )

    work_item_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.mission_work_items.id", ondelete="RESTRICT"), primary_key=True
    )
    depends_on_work_item_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.mission_work_items.id", ondelete="RESTRICT"), primary_key=True
    )


class MissionWakeupModel(Base):
    """Durable, deduplicated reason for a finite management turn."""

    __tablename__ = "mission_wakeups"
    __table_args__ = (
        UniqueConstraint("mission_id", "deduplication_key", name="uq_mission_wakeup_dedup"),
        CheckConstraint(
            "kind IN ('user_direction','job_completed','job_failed','approval_decided','deadline')",
            name="kind",
        ),
        CheckConstraint(
            "status IN ('pending','claimed','turn_queued','committed','stale','failed')",
            name="status",
        ),
        Index("ix_mission_wakeups_claim", "status", "scheduled_for", "created_at"),
        {"schema": CONTROL_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid7)
    mission_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.missions.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    deduplication_key: Mapped[str] = mapped_column(String(200), nullable=False)
    directive_version: Mapped[int] = mapped_column(Integer, nullable=False)
    team_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.mission_team_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_event_cursor: Mapped[int | None] = mapped_column(BigInteger)
    accepted_target_identity: Mapped[str | None] = mapped_column(String(200))
    accepted_source_identity: Mapped[str | None] = mapped_column(String(200))
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    outcome_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claimed_by: Mapped[str | None] = mapped_column(String(160))
    management_turn_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MissionAdmissionControlModel(MutableRow, Base):
    __tablename__ = "mission_admission_controls"
    __table_args__ = (
        CheckConstraint("scope IN ('mission','team','global')", name="scope"),
        CheckConstraint("state IN ('open','paused','draining','cancelling')", name="state"),
        UniqueConstraint("scope_key", name="uq_mission_admission_scope_key"),
        {"schema": CONTROL_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid7)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_key: Mapped[str] = mapped_column(String(200), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    safe_point_instruction: Mapped[str | None] = mapped_column(String(2000))
    resource_limits_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )


class MissionResourceReservationModel(Base):
    """Maximum liability retained until actual usage is known."""

    __tablename__ = "mission_resource_reservations"
    __table_args__ = (
        UniqueConstraint("scope_key", "action_id", name="uq_mission_resource_action"),
        CheckConstraint("status IN ('reserved','reconciled','unknown','released')", name="status"),
        Index("ix_mission_resource_scope_window", "scope_key", "window_started_at"),
        {"schema": CONTROL_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid7)
    mission_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.missions.id", ondelete="RESTRICT"), nullable=False
    )
    scope_key: Mapped[str] = mapped_column(String(200), nullable=False)
    action_id: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    liability_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    actual_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="reserved")
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    price_unit: Mapped[str] = mapped_column(
        String(40), nullable=False, default="currency", server_default="currency"
    )
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConfigurationModel(MutableRow, Base):
    __tablename__ = "configurations"
    __table_args__ = (
        UniqueConstraint("kind", "key", name="uq_configurations_kind_key"),
        {"schema": CONTROL_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid7)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    current_revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            f"{CONTROL_SCHEMA}.configuration_revisions.id",
            name="fk_configurations_current_revision",
            ondelete="RESTRICT",
            use_alter=True,
        )
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConfigurationRevisionModel(Base):
    __tablename__ = "configuration_revisions"
    __table_args__ = (
        UniqueConstraint("configuration_id", "revision", name="uq_configuration_revision"),
        CheckConstraint("revision > 0", name="revision_positive"),
        CheckConstraint("char_length(content_hash) = 64", name="content_hash_length"),
        {"schema": CONTROL_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid7)
    configuration_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.configurations.id", ondelete="RESTRICT"), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)
    spec_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ConfigurationPrivateRefModel(Base):
    """Opaque locators only, separated from immutable public configuration payloads."""

    __tablename__ = "configuration_private_refs"
    __table_args__ = ({"schema": CONTROL_SCHEMA},)
    revision_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.configuration_revisions.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    secret_ref: Mapped[str | None] = mapped_column(String(220))
    deployment_ref: Mapped[str | None] = mapped_column(String(220))


class ProviderHealthModel(MutableRow, Base):
    __tablename__ = "provider_health"
    __table_args__ = (
        CheckConstraint(
            "status IN ('healthy','degraded','unavailable','misconfigured','unknown')",
            name="status",
        ),
        CheckConstraint("circuit_state IN ('closed','open','half_open')", name="circuit_state"),
        CheckConstraint("failure_count >= 0", name="failure_count"),
        {"schema": CONTROL_SCHEMA},
    )
    revision_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.configuration_revisions.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="unknown")
    circuit_state: Mapped[str] = mapped_column(String(24), nullable=False, default="closed")
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    window_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_probe_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    probe_lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ModelCallModel(Base):
    __tablename__ = "model_calls"
    __table_args__ = (
        UniqueConstraint("correlation_id", "idempotency_key", name="uq_model_calls_request"),
        Index("ix_model_calls_run_created", "run_id", "created_at"),
        {"schema": CONTROL_SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid7)
    profile_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.configuration_revisions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    provider_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.configuration_revisions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    route_revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.configuration_revisions.id", ondelete="RESTRICT"),
    )
    run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.runs.id", ondelete="RESTRICT"),
    )
    management_turn_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.management_turns.id", ondelete="RESTRICT")
    )
    correlation_id: Mapped[str] = mapped_column(String(200), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    record_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class WorkflowTemplateModel(MutableRow, Base):
    __tablename__ = "workflow_templates"
    __table_args__ = ({"schema": CONTROL_SCHEMA},)

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid7)
    key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    owner_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.users.id", ondelete="RESTRICT"), index=True
    )
    current_draft_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            f"{CONTROL_SCHEMA}.workflow_versions.id",
            name="fk_workflow_templates_current_draft_version",
            ondelete="RESTRICT",
            use_alter=True,
        )
    )
    current_published_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            f"{CONTROL_SCHEMA}.workflow_versions.id",
            name="fk_workflow_templates_current_published_version",
            ondelete="RESTRICT",
            use_alter=True,
        )
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkflowVersionModel(Base):
    __tablename__ = "workflow_versions"
    __table_args__ = (
        UniqueConstraint("workflow_template_id", "version", name="uq_workflow_version"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint("char_length(content_hash) = 64", name="content_hash_length"),
        {"schema": CONTROL_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid7)
    workflow_template_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.workflow_templates.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    spec_version: Mapped[str] = mapped_column(String(20), nullable=False)
    compiler_version: Mapped[str] = mapped_column(String(40), nullable=False)
    spec_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    layout_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    resolved_snapshot_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    snapshot_hash: Mapped[str | None] = mapped_column(String(64))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class WorkflowRevisionReferenceModel(Base):
    __tablename__ = "workflow_revision_references"
    __table_args__ = ({"schema": CONTROL_SCHEMA},)

    workflow_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.workflow_versions.id", ondelete="RESTRICT"), primary_key=True
    )
    revision_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.configuration_revisions.id", ondelete="RESTRICT"),
        primary_key=True,
    )


class RunConfigSnapshotModel(Base):
    __tablename__ = "run_config_snapshots"
    __table_args__ = (
        CheckConstraint("char_length(snapshot_hash) = 64", name="snapshot_hash_length"),
        {"schema": CONTROL_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid7)
    workflow_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.workflow_versions.id", ondelete="RESTRICT"), nullable=False
    )
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)
    resolved_revisions_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    effective_spec_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class JobModel(MutableRow, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','queued','active','waiting','completed','failed',"
            "'blocked','cancelled')",
            name="status",
        ),
        {"schema": CONTROL_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid7)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.projects.id", ondelete="RESTRICT"), nullable=False
    )
    thread_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)


class RunModel(MutableRow, Base):
    __tablename__ = "runs"
    __table_args__ = (
        UniqueConstraint("job_id", "run_number", name="uq_runs_job_number"),
        UniqueConstraint("langgraph_thread_id", name="uq_runs_langgraph_thread"),
        CheckConstraint("run_number > 0", name="run_number_positive"),
        CheckConstraint("next_command_sequence >= 0", name="command_sequence_nonnegative"),
        CheckConstraint("last_event_position >= 0", name="last_event_position_nonnegative"),
        CheckConstraint("last_run_sequence >= 0", name="last_run_sequence_nonnegative"),
        CheckConstraint(
            "status IN ('queued','claiming','running','pause_requested','paused',"
            "'approval_required','cancel_requested','completed','failed','blocked','cancelled')",
            name="status",
        ),
        CheckConstraint("desired_state IN ('running','paused','cancelled')", name="desired_state"),
        CheckConstraint("mode IN ('demo','real')", name="mode"),
        CheckConstraint("jsonb_typeof(runtime_json) = 'object'", name="runtime_object"),
        Index("ix_runs_claim_order", "priority", "claimable_at", "created_at", "id"),
        {"schema": CONTROL_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid7)
    job_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.jobs.id", ondelete="RESTRICT"), nullable=False
    )
    run_number: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.runs.id", ondelete="RESTRICT")
    )
    workflow_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.workflow_versions.id", ondelete="RESTRICT"), nullable=False
    )
    config_snapshot_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.run_config_snapshots.id", ondelete="RESTRICT"), nullable=False
    )
    langgraph_thread_id: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    desired_state: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    mode: Mapped[str] = mapped_column(
        String(10), nullable=False, default="demo", server_default="demo"
    )
    runtime_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    result_summary: Mapped[str | None] = mapped_column(String(1024))
    current_node: Mapped[str | None] = mapped_column(String(80))
    claimable_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    next_command_sequence: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    last_event_position: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    last_run_sequence: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TaskModel(MutableRow, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("run_id", "key", name="uq_tasks_run_key"),
        UniqueConstraint("run_id", "id", name="uq_tasks_run_id_id"),
        CheckConstraint("weight > 0", name="weight_positive"),
        CheckConstraint(
            "status IN ('pending','ready','running','waiting','approval_required','succeeded',"
            "'failed','blocked','cancelled','skipped')",
            name="status",
        ),
        {"schema": CONTROL_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid7)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.runs.id", ondelete="RESTRICT"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    acceptance_criteria_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    verification_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class TaskDependencyModel(Base):
    __tablename__ = "task_dependencies"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "task_id"],
            [f"{CONTROL_SCHEMA}.tasks.run_id", f"{CONTROL_SCHEMA}.tasks.id"],
            name="fk_task_dependencies_task",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["run_id", "depends_on_task_id"],
            [f"{CONTROL_SCHEMA}.tasks.run_id", f"{CONTROL_SCHEMA}.tasks.id"],
            name="fk_task_dependencies_depends_on",
            ondelete="RESTRICT",
        ),
        CheckConstraint("task_id <> depends_on_task_id", name="not_self"),
        {"schema": CONTROL_SCHEMA},
    )

    run_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    task_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    depends_on_task_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)


class TaskAttemptModel(Base):
    __tablename__ = "task_attempts"
    __table_args__ = (
        UniqueConstraint("task_id", "attempt_number", name="uq_task_attempt_number"),
        CheckConstraint("attempt_number > 0", name="attempt_number_positive"),
        CheckConstraint(
            "status IN ('queued','running','verifying','reviewing','succeeded','failed',"
            "'cancelled','unknown')",
            name="status",
        ),
        {"schema": CONTROL_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid7)
    task_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.tasks.id", ondelete="RESTRICT"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    worker_revision_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    base_sha: Mapped[str | None] = mapped_column(String(64))
    result_sha: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class NodeExecutionModel(Base):
    __tablename__ = "node_executions"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "workflow_node_id", "execution_number", name="uq_node_execution_number"
        ),
        CheckConstraint("execution_number > 0", name="execution_number_positive"),
        CheckConstraint(
            "status IN ('queued','running','waiting','interrupted','succeeded','failed',"
            "'cancelled','skipped')",
            name="status",
        ),
        {"schema": CONTROL_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid7)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.runs.id", ondelete="RESTRICT"), nullable=False
    )
    task_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.tasks.id", ondelete="RESTRICT")
    )
    task_attempt_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.task_attempts.id", ondelete="RESTRICT")
    )
    workflow_node_id: Mapped[str] = mapped_column(String(80), nullable=False)
    execution_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    input_summary: Mapped[str | None] = mapped_column(String(1_024))
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RunCommandModel(Base):
    __tablename__ = "run_commands"
    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_run_command_sequence"),
        UniqueConstraint("run_id", "idempotency_key", name="uq_run_command_idempotency"),
        CheckConstraint("sequence > 0", name="sequence_positive"),
        CheckConstraint("kind IN ('pause','resume','cancel','instruction','retry')", name="kind"),
        CheckConstraint(
            "status IN ('pending','applying','applied','rejected','superseded')", name="status"
        ),
        {"schema": CONTROL_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid7)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.runs.id", ondelete="RESTRICT"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    expected_run_version: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IdempotencyRecordModel(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("scope", "key", name="uq_idempotency_scope_key"),
        CheckConstraint("state IN ('started','completed','failed')", name="state"),
        {"schema": CONTROL_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid7)
    scope: Mapped[str] = mapped_column(String(120), nullable=False)
    key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OrchestratorInstanceModel(Base):
    __tablename__ = "orchestrator_instances"
    __table_args__ = (
        CheckConstraint("runtime_mode IN ('real','demo','unknown')", name="runtime_mode"),
        {"schema": CONTROL_SCHEMA},
    )

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    draining: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    runtime_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unknown", server_default="unknown"
    )
    runtime_manifest_sha256: Mapped[str | None] = mapped_column(String(64))
    runtime_summary_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )


class RunLeaseModel(Base):
    __tablename__ = "run_leases"
    __table_args__ = (
        UniqueConstraint("run_id", "generation", name="uq_run_lease_generation"),
        CheckConstraint("generation > 0", name="generation_positive"),
        Index(
            "uq_run_leases_active",
            "run_id",
            unique=True,
            postgresql_where=text("released_at IS NULL"),
        ),
        {"schema": CONTROL_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid7)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.runs.id", ondelete="RESTRICT"), nullable=False
    )
    owner_instance_id: Mapped[str] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.orchestrator_instances.id", ondelete="RESTRICT"),
        nullable=False,
    )
    generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkerHealthModel(Base):
    __tablename__ = "worker_health"
    __table_args__ = ({"schema": CONTROL_SCHEMA},)
    revision_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.configuration_revisions.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    report_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkerSlotModel(Base):
    __tablename__ = "worker_slots"
    __table_args__ = (
        UniqueConstraint("worker_id", "slot_number", name="uq_worker_slot_number"),
        UniqueConstraint(
            "physical_resource_id", "slot_number", name="uq_worker_physical_slot_number"
        ),
        CheckConstraint("slot_number >= 0 AND slot_number < 128", name="slot_number"),
        CheckConstraint("generation >= 0", name="generation"),
        {"schema": CONTROL_SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid7)
    worker_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.configurations.id", ondelete="RESTRICT"), nullable=False
    )
    physical_resource_id: Mapped[str] = mapped_column(String(80), nullable=False)
    slot_number: Mapped[int] = mapped_column(Integer, nullable=False)
    generation: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class WorkerLeaseModel(Base):
    __tablename__ = "worker_leases"
    __table_args__ = (
        UniqueConstraint("slot_id", "generation", name="uq_worker_lease_generation"),
        CheckConstraint("generation > 0 AND run_generation > 0", name="generation"),
        Index(
            "uq_worker_leases_active",
            "slot_id",
            unique=True,
            postgresql_where=text("released_at IS NULL"),
        ),
        {"schema": CONTROL_SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid7)
    slot_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.worker_slots.id", ondelete="RESTRICT"), nullable=False
    )
    worker_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.configuration_revisions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.runs.id", ondelete="RESTRICT"), nullable=False
    )
    task_attempt_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.task_attempts.id", ondelete="RESTRICT"), nullable=False
    )
    owner_instance_id: Mapped[str] = mapped_column(String(160), nullable=False)
    generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    run_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    renewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkerInvocationModel(Base):
    __tablename__ = "worker_invocations"
    __table_args__ = (
        UniqueConstraint("effect_id", name="uq_worker_invocation_effect"),
        CheckConstraint("generation > 0", name="generation"),
        {"schema": CONTROL_SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    effect_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.effects.id", ondelete="RESTRICT"), nullable=False
    )
    lease_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.worker_leases.id", ondelete="RESTRICT"), nullable=False
    )
    generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    request_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    diagnostic_result_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    possibly_stalled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class WorkerAssignmentModel(Base):
    """Durable fair-scheduling intent with an immutable eligible-pool snapshot."""

    __tablename__ = "worker_assignments"
    __table_args__ = (
        UniqueConstraint("task_attempt_id", name="uq_worker_assignment_attempt"),
        CheckConstraint(
            "status IN ('queued','reserved','running','completed','failed','cancelled','unknown')",
            name="status",
        ),
        CheckConstraint("fairness_sequence > 0", name="fairness_sequence_positive"),
        Index(
            "ix_worker_assignments_fair_claim",
            "status",
            "priority",
            "mission_id",
            "fairness_sequence",
        ),
        {"schema": CONTROL_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid7)
    mission_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.missions.id", ondelete="RESTRICT"), nullable=False
    )
    team_version_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.mission_team_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.runs.id", ondelete="RESTRICT"), nullable=False
    )
    task_attempt_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.task_attempts.id", ondelete="RESTRICT"), nullable=False
    )
    role_key: Mapped[str] = mapped_column(String(64), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fairness_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    required_capabilities_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    eligible_pool_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    selected_worker_revision_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    worker_lease_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.worker_leases.id", ondelete="RESTRICT")
    )
    queued_reason: Mapped[str | None] = mapped_column(String(240))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EffectModel(MutableRow, Base):
    __tablename__ = "effects"
    __table_args__ = (
        UniqueConstraint("run_id", "idempotency_key", name="uq_effect_run_idempotency"),
        CheckConstraint("fence_generation > 0", name="fence_generation_positive"),
        CheckConstraint(
            "status IN ('prepared','dispatched','running','succeeded','failed',"
            "'cancel_requested','cancelled','unknown')",
            name="status",
        ),
        {"schema": CONTROL_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid7)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.runs.id", ondelete="RESTRICT"), nullable=False
    )
    task_attempt_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.task_attempts.id", ondelete="RESTRICT")
    )
    node_execution_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.node_executions.id", ondelete="RESTRICT")
    )
    kind: Mapped[str] = mapped_column(String(120), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    request_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    fence_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(240))
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FailureModel(Base):
    __tablename__ = "failures"
    __table_args__ = ({"schema": CONTROL_SCHEMA},)

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid7)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.runs.id", ondelete="RESTRICT"), nullable=False
    )
    task_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.tasks.id", ondelete="RESTRICT")
    )
    task_attempt_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.task_attempts.id", ondelete="RESTRICT")
    )
    node_execution_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.node_executions.id", ondelete="RESTRICT")
    )
    failure_class: Mapped[str] = mapped_column(String(80), nullable=False)
    code: Mapped[str] = mapped_column(String(120), nullable=False)
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    budget_scope: Mapped[str] = mapped_column(String(120), nullable=False)
    consumes_semantic_attempt: Mapped[bool] = mapped_column(Boolean, nullable=False)
    summary: Mapped[str] = mapped_column(String(1_024), nullable=False)
    detail_artifact_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RetryCounterModel(MutableRow, Base):
    __tablename__ = "retry_counters"
    __table_args__ = (
        UniqueConstraint("run_id", "scope_key", "failure_class", name="uq_retry_counter_scope"),
        CheckConstraint("consumed >= 0", name="consumed_nonnegative"),
        CheckConstraint("maximum >= 0", name="maximum_nonnegative"),
        {"schema": CONTROL_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid7)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.runs.id", ondelete="RESTRICT"), nullable=False
    )
    scope_key: Mapped[str] = mapped_column(String(200), nullable=False)
    failure_class: Mapped[str] = mapped_column(String(80), nullable=False)
    consumed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    maximum: Mapped[int] = mapped_column(Integer, nullable=False)


class IntegrationHeadModel(Base):
    """Selects a sealed Git generation; run fencing also guards every mutation."""

    __tablename__ = "integration_heads"
    __table_args__ = (
        CheckConstraint("generation >= 0", name="generation"),
        CheckConstraint("char_length(head_sha) = 40 AND char_length(base_sha) = 40", name="sha"),
        {"schema": CONTROL_SCHEMA},
    )
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.runs.id", ondelete="RESTRICT"), primary_key=True
    )
    repository_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    base_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    head_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    branch: Mapped[str] = mapped_column(String(200), nullable=False)
    target_branch: Mapped[str] = mapped_column(String(200), nullable=False, default="main")
    snapshot_artifact_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.artifacts.id", ondelete="RESTRICT")
    )
    generation: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    lease_owner: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.effects.id", ondelete="RESTRICT")
    )
    acquired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    renewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AcceptedTargetHeadModel(Base):
    """Repository/target-branch authority shared by every run and team."""

    __tablename__ = "accepted_target_heads"
    __table_args__ = (
        UniqueConstraint("repository_id", "target_branch", name="uq_accepted_target_branch"),
        CheckConstraint("generation >= 0", name="generation"),
        CheckConstraint("char_length(head_sha) = 40", name="head_sha"),
        {"schema": CONTROL_SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid7)
    repository_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    target_branch: Mapped[str] = mapped_column(String(200), nullable=False)
    head_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    generation: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    lease_owner: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    lease_generation: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MergeCandidateModel(Base):
    """Immutable candidate identity queued for serialized target advancement."""

    __tablename__ = "merge_candidates"
    __table_args__ = (
        UniqueConstraint("task_attempt_id", "candidate_sha", name="uq_merge_candidate_attempt_sha"),
        UniqueConstraint("effect_id", name="uq_merge_candidate_effect"),
        CheckConstraint(
            "status IN ('queued','integrating','accepted','conflicted','rejected','blocked')",
            name="status",
        ),
        CheckConstraint(
            "char_length(base_sha) = 40 AND char_length(candidate_sha) = 40",
            name="sha",
        ),
        Index(
            "ix_merge_candidates_queue", "repository_id", "target_branch", "status", "created_at"
        ),
        {"schema": CONTROL_SCHEMA},
    )
    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid7)
    repository_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    target_branch: Mapped[str] = mapped_column(String(200), nullable=False)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.runs.id", ondelete="RESTRICT"), nullable=False
    )
    effect_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.effects.id", ondelete="RESTRICT"), nullable=False
    )
    task_attempt_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.task_attempts.id", ondelete="RESTRICT"), nullable=False
    )
    profile_revision_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    base_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    candidate_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    verification_identity: Mapped[str] = mapped_column(String(64), nullable=False)
    review_identity: Mapped[str] = mapped_column(String(64), nullable=False)
    directive_identity: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    expected_head_sha: Mapped[str | None] = mapped_column(String(40))
    accepted_generation: Mapped[int | None] = mapped_column(BigInteger)
    conflict_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ArtifactModel(Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        CheckConstraint("size_bytes >= 0", name="size_nonnegative"),
        CheckConstraint("char_length(sha256) = 64", name="sha256_length"),
        CheckConstraint(
            "redaction_classification IN ('public','owner','sensitive','redacted')",
            name="redaction_classification",
        ),
        {"schema": CONTROL_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid7)
    run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.runs.id", ondelete="RESTRICT")
    )
    task_attempt_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.task_attempts.id", ondelete="RESTRICT")
    )
    kind: Mapped[str] = mapped_column(String(120), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1_024), nullable=False, unique=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    media_type: Mapped[str] = mapped_column(String(200), nullable=False)
    redaction_classification: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OperationalAlertModel(Base):
    """Durable deduplicated incident lifecycle; recovery updates the projection."""

    __tablename__ = "operational_alerts"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "deduplication_key", name="uq_operational_alert_dedup"),
        CheckConstraint("severity IN ('warning','critical')", name="severity"),
        CheckConstraint("status IN ('active','recovered')", name="status"),
        Index("ix_operational_alerts_owner_status", "owner_user_id", "status", "last_seen_at"),
        {"schema": CONTROL_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid7)
    owner_user_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.users.id", ondelete="RESTRICT"), nullable=False
    )
    deduplication_key: Mapped[str] = mapped_column(String(240), nullable=False)
    kind: Mapped[str] = mapped_column(String(80), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_id: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(String(1024), nullable=False)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    occurrences: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NotificationOutboxModel(Base):
    """Authorized outbound notification attempts; in-app alerts need no outbox row."""

    __tablename__ = "notification_outbox"
    __table_args__ = (
        UniqueConstraint(
            "destination_id", "deduplication_key", name="uq_notification_outbox_dedup"
        ),
        CheckConstraint("status IN ('pending','delivering','delivered','failed')", name="status"),
        CheckConstraint("attempt_count >= 0 AND max_attempts > 0", name="attempt_bounds"),
        Index("ix_notification_outbox_claim", "status", "next_attempt_at"),
        {"schema": CONTROL_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid7)
    alert_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.operational_alerts.id", ondelete="RESTRICT"), nullable=False
    )
    destination_id: Mapped[str] = mapped_column(String(160), nullable=False)
    deduplication_key: Mapped[str] = mapped_column(String(240), nullable=False)
    redacted_payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_error_code: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RetentionTombstoneModel(Base):
    """Permanent replay identity retained after bounded content cleanup."""

    __tablename__ = "retention_tombstones"
    __table_args__ = (
        UniqueConstraint(
            "identity_scope", "identity_digest", name="uq_retention_tombstone_identity"
        ),
        CheckConstraint("char_length(identity_digest) = 64", name="identity_digest"),
        {"schema": CONTROL_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid7)
    identity_scope: Mapped[str] = mapped_column(String(120), nullable=False)
    identity_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_kind: Mapped[str] = mapped_column(String(80), nullable=False)
    owner_user_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.users.id", ondelete="RESTRICT"), nullable=False
    )
    deleted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class RecoveryGenerationModel(Base):
    __tablename__ = "recovery_generations"
    __table_args__ = (
        CheckConstraint("id = 1", name="singleton"),
        CheckConstraint("generation > 0", name="generation_positive"),
        {"schema": CONTROL_SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    generation: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    automatic_dispatch_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    reason: Mapped[str] = mapped_column(String(1024), nullable=False, default="initial")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BackupManifestModel(Base):
    __tablename__ = "backup_manifests"
    __table_args__ = (
        UniqueConstraint("backup_id", name="uq_backup_manifest_backup_id"),
        CheckConstraint(
            "status IN ('building','complete','invalid','restored','blocked')", name="status"
        ),
        {"schema": CONTROL_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid7)
    backup_id: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="building")
    recovery_generation: Mapped[int] = mapped_column(BigInteger, nullable=False)
    manifest_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    manifest_sha256: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QualificationRunModel(Base):
    __tablename__ = "qualification_runs"
    __table_args__ = (
        CheckConstraint("profile IN ('24h','72h','7d')", name="profile"),
        CheckConstraint("status IN ('running','passed','failed','cancelled')", name="status"),
        {"schema": CONTROL_SCHEMA},
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid7)
    owner_user_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.users.id", ondelete="RESTRICT"), nullable=False
    )
    profile: Mapped[str] = mapped_column(String(8), nullable=False)
    environment_identity: Mapped[str] = mapped_column(String(240), nullable=False)
    release_identity: Mapped[str] = mapped_column(String(240), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observations_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    notes: Mapped[str] = mapped_column(String(2000), nullable=False, default="")


class EventGlobalCounterModel(Base):
    __tablename__ = "event_global_counter"
    __table_args__ = (
        CheckConstraint("id = 1", name="singleton"),
        CheckConstraint("last_position >= 0", name="position_nonnegative"),
        {"schema": EVENT_SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    last_position: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class RunEventCounterModel(Base):
    __tablename__ = "run_event_counters"
    __table_args__ = (
        CheckConstraint("last_sequence >= 0", name="sequence_nonnegative"),
        {"schema": EVENT_SCHEMA},
    )

    run_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.runs.id", ondelete="RESTRICT"), primary_key=True
    )
    last_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class EventModel(Base):
    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_events_event_id"),
        UniqueConstraint("idempotency_scope_key", name="uq_events_idempotency_scope_key"),
        UniqueConstraint("source_dedupe_key", name="uq_events_source_dedupe_key"),
        CheckConstraint("global_position > 0", name="global_position_positive"),
        CheckConstraint("run_sequence IS NULL OR run_sequence > 0", name="run_sequence_positive"),
        CheckConstraint("mode IN ('real','demo')", name="mode"),
        CheckConstraint("visibility IN ('owner','operator','internal')", name="visibility"),
        CheckConstraint(
            "severity IN ('debug','info','success','warning','error','critical')",
            name="severity",
        ),
        CheckConstraint(
            "category IN ('auth','config','thread','job','run','graph','node','task','worker',"
            "'model','tool','file','command','test','review','git','approval','artifact',"
            "'failure','system')",
            name="category",
        ),
        CheckConstraint(
            "(run_id IS NULL AND run_sequence IS NULL) OR "
            "(run_id IS NOT NULL AND run_sequence IS NOT NULL)",
            name="run_sequence_scope",
        ),
        Index(
            "uq_events_run_sequence",
            "run_id",
            "run_sequence",
            unique=True,
            postgresql_where=text("run_id IS NOT NULL"),
        ),
        Index("ix_events_run_recorded", "run_id", "recorded_at"),
        Index("ix_events_category_type", "category", "type"),
        {"schema": EVENT_SCHEMA},
    )

    event_id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)
    global_position: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_sequence: Mapped[int | None] = mapped_column(BigInteger)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    type: Mapped[str] = mapped_column(String(160), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str] = mapped_column(String(1_024), nullable=False)
    mode: Mapped[str] = mapped_column(String(10), nullable=False)
    visibility: Mapped[str] = mapped_column(String(20), nullable=False)
    project_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    thread_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    job_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(f"{CONTROL_SCHEMA}.runs.id", ondelete="RESTRICT")
    )
    task_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    task_attempt_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    workflow_node_id: Mapped[str | None] = mapped_column(String(80))
    node_execution_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    source_kind: Mapped[str] = mapped_column(String(80), nullable=False)
    source_name: Mapped[str] = mapped_column(String(120), nullable=False)
    source_instance_id: Mapped[str | None] = mapped_column(String(160))
    source_host_id: Mapped[str | None] = mapped_column(String(160))
    source_sequence: Mapped[int | None] = mapped_column(BigInteger)
    source_dedupe_key: Mapped[str | None] = mapped_column(String(600))
    correlation_id: Mapped[str] = mapped_column(String(200), nullable=False)
    causation_event_id: Mapped[UUID | None] = mapped_column(PostgreSQLUUID(as_uuid=True))
    idempotency_key: Mapped[str | None] = mapped_column(String(200))
    idempotency_scope_key: Mapped[str | None] = mapped_column(String(500))
    trace_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    data_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    artifact_refs_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
