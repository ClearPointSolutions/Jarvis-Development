"""Phase 5 truthfulness and wall-clock qualification guards."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from jarvis_api.operations import _qualification_view, _signal
from jarvis_persistence.models import QualificationRunModel

NOW = datetime(2026, 9, 15, 12, tzinfo=UTC)


def test_heartbeat_signal_does_not_claim_productive_work() -> None:
    signal = _signal(
        key="useful_progress",
        count=1,
        observed_at=NOW,
        last_progress_at=NOW - timedelta(hours=1),
        warning_after=60,
        critical_after=600,
        healthy_reason="idle",
        unhealthy_reason="no accepted progress",
        action="reconcile",
    )
    assert signal.status == "critical"
    assert signal.uncertainty and "liveness" in signal.uncertainty
    assert signal.action == "reconcile"


def test_short_observation_never_counts_as_completed_soak() -> None:
    row = QualificationRunModel(
        id=UUID(int=1),
        owner_user_id=UUID(int=2),
        profile="24h",
        environment_identity="staging-a",
        release_identity="sha256:release",
        status="running",
        started_at=NOW,
        observations_json=[{"outcome": "smoke passed"}],
        notes="",
    )
    view = _qualification_view(row, NOW + timedelta(minutes=5))
    assert view.observed_seconds == 300
    assert view.required_seconds == 86_400
    assert view.wall_clock_complete is False


def test_actual_elapsed_wall_clock_is_required() -> None:
    row = QualificationRunModel(
        id=UUID(int=1),
        owner_user_id=UUID(int=2),
        profile="72h",
        environment_identity="staging-a",
        release_identity="sha256:release",
        status="passed",
        started_at=NOW,
        ended_at=NOW + timedelta(hours=72),
        observations_json=[],
        notes="",
    )
    assert _qualification_view(row, NOW).wall_clock_complete is True
