"""M7 worker slots and invocation identity. Existing effects remain lifecycle authority."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "worker_health",
        sa.Column(
            "revision_id",
            sa.UUID(),
            sa.ForeignKey("control.configuration_revisions.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("report_json", JSONB(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        schema="control",
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON control.worker_health TO jarvis_v1_orchestrator")
    op.execute("GRANT SELECT ON control.worker_health TO jarvis_v1_api")
    op.execute(
        """
CREATE TABLE control.worker_slots (
    id UUID NOT NULL,
    worker_id UUID NOT NULL,
    slot_number INTEGER NOT NULL,
    generation BIGINT NOT NULL,
    CONSTRAINT pk_worker_slots PRIMARY KEY (id),
    CONSTRAINT uq_worker_slot_number UNIQUE (worker_id, slot_number),
    CONSTRAINT ck_worker_slots_slot_number CHECK (slot_number >= 0 AND slot_number < 128),
    CONSTRAINT ck_worker_slots_generation CHECK (generation >= 0),
    CONSTRAINT fk_worker_slots_worker_id_configurations FOREIGN KEY(worker_id) REFERENCES control.configurations (id) ON DELETE RESTRICT
)
"""
    )
    op.execute(
        """
CREATE TABLE control.worker_leases (
    id UUID NOT NULL,
    slot_id UUID NOT NULL,
    worker_revision_id UUID NOT NULL,
    run_id UUID NOT NULL,
    task_attempt_id UUID NOT NULL,
    owner_instance_id VARCHAR(160) NOT NULL,
    generation BIGINT NOT NULL,
    run_generation BIGINT NOT NULL,
    token_hash VARCHAR(64) NOT NULL,
    acquired_at TIMESTAMP WITH TIME ZONE NOT NULL,
    renewed_at TIMESTAMP WITH TIME ZONE NOT NULL,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    released_at TIMESTAMP WITH TIME ZONE,
    CONSTRAINT pk_worker_leases PRIMARY KEY (id),
    CONSTRAINT uq_worker_lease_generation UNIQUE (slot_id, generation),
    CONSTRAINT ck_worker_leases_generation CHECK (generation > 0 AND run_generation > 0),
    CONSTRAINT fk_worker_leases_slot_id_worker_slots FOREIGN KEY(slot_id) REFERENCES control.worker_slots (id) ON DELETE RESTRICT,
    CONSTRAINT fk_worker_leases_worker_revision_id_configuration_revisions FOREIGN KEY(worker_revision_id) REFERENCES control.configuration_revisions (id) ON DELETE RESTRICT,
    CONSTRAINT fk_worker_leases_run_id_runs FOREIGN KEY(run_id) REFERENCES control.runs (id) ON DELETE RESTRICT,
    CONSTRAINT fk_worker_leases_task_attempt_id_task_attempts FOREIGN KEY(task_attempt_id) REFERENCES control.task_attempts (id) ON DELETE RESTRICT
)
"""
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_worker_leases_active ON control.worker_leases (slot_id) WHERE released_at IS NULL"
    )
    op.execute(
        """
CREATE TABLE control.worker_invocations (
    id UUID NOT NULL,
    effect_id UUID NOT NULL,
    lease_id UUID NOT NULL,
    generation BIGINT NOT NULL,
    request_digest VARCHAR(64) NOT NULL,
    request_json JSONB NOT NULL,
    result_json JSONB,
    last_activity_at TIMESTAMP WITH TIME ZONE,
    cancellation_requested_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_worker_invocations PRIMARY KEY (id),
    CONSTRAINT uq_worker_invocation_effect UNIQUE (effect_id),
    CONSTRAINT ck_worker_invocations_generation CHECK (generation > 0),
    CONSTRAINT fk_worker_invocations_effect_id_effects FOREIGN KEY(effect_id) REFERENCES control.effects (id) ON DELETE RESTRICT,
    CONSTRAINT fk_worker_invocations_lease_id_worker_leases FOREIGN KEY(lease_id) REFERENCES control.worker_leases (id) ON DELETE RESTRICT
)
"""
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON control.worker_slots TO jarvis_v1_orchestrator")
    op.execute("REVOKE ALL ON control.worker_slots FROM jarvis_v1_api, jarvis_v1_readonly")
    op.execute("GRANT SELECT, INSERT, UPDATE ON control.worker_leases TO jarvis_v1_orchestrator")
    op.execute("REVOKE ALL ON control.worker_leases FROM jarvis_v1_api, jarvis_v1_readonly")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON control.worker_invocations TO jarvis_v1_orchestrator"
    )
    op.execute("REVOKE ALL ON control.worker_invocations FROM jarvis_v1_api, jarvis_v1_readonly")
    op.execute("GRANT SELECT ON control.worker_slots TO jarvis_v1_api")
    op.execute(
        "GRANT SELECT (slot_id, worker_revision_id, renewed_at, released_at) ON control.worker_leases TO jarvis_v1_api"
    )
    op.execute("GRANT SELECT (id) ON control.worker_leases TO jarvis_v1_api")
    op.add_column(
        "worker_invocations",
        sa.Column("possibly_stalled", sa.Boolean(), nullable=False, server_default="false"),
        schema="control",
    )
    op.execute(
        "GRANT SELECT (lease_id, last_activity_at, possibly_stalled) ON control.worker_invocations TO jarvis_v1_api"
    )
    op.add_column(
        "worker_invocations", sa.Column("diagnostic_result_json", JSONB()), schema="control"
    )
    op.execute("""
        CREATE FUNCTION control.guard_worker_identity() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_TABLE_NAME = 'worker_slots' THEN
            IF NEW.id <> OLD.id OR NEW.worker_id <> OLD.worker_id OR
               NEW.slot_number <> OLD.slot_number OR NEW.generation < OLD.generation THEN
              RAISE EXCEPTION 'immutable worker slot identity or decreasing fence';
            END IF;
          ELSIF TG_TABLE_NAME = 'worker_leases' THEN
            IF (to_jsonb(NEW) - ARRAY['renewed_at','expires_at','released_at']) <>
               (to_jsonb(OLD) - ARRAY['renewed_at','expires_at','released_at']) OR
               (OLD.released_at IS NOT NULL AND NEW IS DISTINCT FROM OLD) THEN
              RAISE EXCEPTION 'immutable worker lease identity or released history';
            END IF;
          ELSIF TG_TABLE_NAME = 'worker_invocations' THEN
            IF (to_jsonb(NEW) - ARRAY['result_json','diagnostic_result_json','last_activity_at','cancellation_requested_at','possibly_stalled']) <>
               (to_jsonb(OLD) - ARRAY['result_json','diagnostic_result_json','last_activity_at','cancellation_requested_at','possibly_stalled']) OR
               (OLD.result_json IS NOT NULL AND NEW.result_json IS DISTINCT FROM OLD.result_json) OR
               (OLD.cancellation_requested_at IS NOT NULL AND NEW.cancellation_requested_at IS DISTINCT FROM OLD.cancellation_requested_at) THEN
              RAISE EXCEPTION 'immutable worker invocation identity or terminal result';
            END IF;
          END IF;
          RETURN NEW;
        END $$
    """)
    for name in ("worker_slots", "worker_leases", "worker_invocations"):
        op.execute(
            f"CREATE TRIGGER guard_identity BEFORE UPDATE ON control.{name} FOR EACH ROW EXECUTE FUNCTION control.guard_worker_identity()"
        )


def downgrade() -> None:
    op.drop_table("worker_health", schema="control", if_exists=True)
    op.drop_table("worker_invocations", schema="control")
    op.drop_table("worker_leases", schema="control")
    op.drop_table("worker_slots", schema="control")
    op.execute("DROP FUNCTION IF EXISTS control.guard_worker_identity()")
