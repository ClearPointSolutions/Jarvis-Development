# Unattended operations

Phase 5 adds operator evidence; it does not convert a heartbeat or short smoke
test into a reliability claim. All endpoints require the owner session and every
mutation requires the session CSRF token.

## Diagnose and alert

- `GET /api/v1/operations/diagnostics` returns bounded, redacted signals for
  orchestrator freshness, last accepted progress, queue/assignment age, worker
  activity, ambiguous effects, provider health, maximum budget liability,
  approval age, integration backlog, and artifact growth. It identifies the
  runtime as real, demo, or unknown.
- `POST /api/v1/operations/alerts/evaluate` durably opens, refreshes, and recovers
  one incident per owner/signal deduplication key. Repeated observations increment
  the occurrence count rather than producing notification storms.
- `GET /api/v1/operations/alerts` is the default in-app notification channel.
  The durable outbound outbox exists, but no destination is enabled by default.
  A future adapter must use an explicitly allowlisted destination, redacted
  payload, bounded attempts, and a rate-limited next-attempt time.
- Existing paginated run events and artifacts are the supported evidence export.
  They apply owner authorization, schema validation, redaction, and response
  bounds; direct database dumps are not a user-facing export.

The Health page displays the signals and their uncertainty. A fresh heartbeat is
liveness only. Unknown use remains maximum liability, and an unreachable worker
remains an ambiguous effect.

## Control

Mission, team, and global pause/drain/resume/cancel use
`POST /api/v1/missions/{id}/controls`. Run safe-point commands remain durable and
ordered. `POST /api/v1/operations/emergency-stop` requires the literal
confirmation `STOP ALL NEW AND ACTIVE WORK`; it closes global admission,
requests cancellation on owned active runs, increments the recovery generation,
and disables all new dispatch. Remote outcomes remain `pending_evidence`.

Database loss cannot authorize work: effect preparation, dispatch and protected
advancement require a live fenced transaction. Remote wrappers retain their
already-issued time/resource bounds if Core becomes unavailable.

## Retention

`POST /api/v1/operations/retention/preview` is an identity-scoped dry run. It
never lists another owner's artifacts and protects active runs, ambiguous
effects, receipts, source/candidate snapshots, verification and review evidence.
Phase 5 deliberately does not expose arbitrary path deletion. Content cleanup is
not release-qualified until a storage adapter can atomically create a durable
deduplication tombstone, delete the exact digest, and prove that no provenance,
approval, effect, or restore reference remains.

## Backup and recovery

Run `scripts/backup-v1.sh` on Core. Follow the isolated validation/restore steps
in `docs/DEPLOYMENT_RUNBOOK.md`. `POST /api/v1/operations/recovery` with
`begin_restore` fences old authority. `resume_dispatch` is rejected while any
effect is dispatched, running, cancel-requested, or unknown.

Never restore secrets from Git or the ordinary backup. Rotate/provision them via
the existing protected secret workflow.

## Qualification profiles

Create a record with `POST /api/v1/operations/qualifications` using profile
`24h`, `72h`, or `7d`, plus exact environment and release identities. Append
fault/cost/storage/effect observations with
`POST /api/v1/operations/qualifications/{id}` action `observe`. The same endpoint
accepts `complete`, `fail`, or `cancel`. `complete` is rejected until actual UTC
wall-clock duration reaches the profile. Simulated-clock and short smoke tests
cannot satisfy that check.

The disposable canary must cover development, non-empty verification,
independent review, integration, an idle interval with no inference, and the
faults enumerated in the Phase 5 handoff. Keep it outside the Jarvis control-plane
repository.
