# AGENTS.md — Jarvis V1 Repository Constitution

## Mission

Build Jarvis V1 / Jarvis Mission Control: the primary human interface and durable orchestration control plane for the user's autonomous LangGraph development system.

Human Supervisor -> Jarvis Mission Control -> LangGraph Supervisor -> Workers -> Tools/Git/GitHub/Infrastructure

## Sources of truth

Before making architectural changes, read:
- `docs/reference/JARVIS_MISSION_CONTROL_BASE_IDEA.txt`
- `docs/reference/CURRENT_PROTOTYPE.md`
- everything under `docs/reference/legacy/`

Legacy files are read-only reference material.

## Non-negotiable principles

1. LangGraph is the orchestration source of truth. The UI visualizes/controls runtime state; it is not a second workflow engine.
2. Every meaningful observable action emits a normalized structured event.
3. Events are append-only, persisted, replayable, and streamed to the browser.
4. Show observable state/actions/results, never hidden chain-of-thought.
5. Workers, providers, model profiles, workflows, retry policies, permissions, and project settings are configuration/data, not hard-coded branches.
6. OpenAI and Ollama are first-class providers.
7. Secrets and infrastructure credentials never reach the browser.
8. Required UI controls must have real backend/runtime behavior. No fake buttons or decorative workflow nodes.
9. Human approvals use real durable workflow interruption/resume behavior.
10. Project/run state must survive API/orchestrator restarts.
11. Infrastructure failures are separate from code/test/review failures and must not burn the wrong retry budget.
12. Keep the current prototype intact as recovery until V1 is proven.
13. Deploy V1 side-by-side at `/opt/jarvis-v1`; never overwrite `/opt/jarvis` during development/staging.
14. No secrets in Git history, fixtures, screenshots, logs, or frontend bundles.
15. No unauthenticated arbitrary shell endpoint.
16. Addresses, paths, models, hosts, and credentials are configuration-driven.
17. Keep the repository highly legible to future coding agents.

## Target stack

Frontend:
- Next.js
- React
- TypeScript
- Tailwind CSS
- shadcn/ui or equivalent
- React Flow
- TanStack Query
- Zustand only where useful
- xterm.js for read-only/live terminal presentation

Backend:
- Python 3.12+
- FastAPI
- Pydantic
- SQLAlchemy 2.x
- Alembic
- PostgreSQL
- LangGraph
- langgraph-checkpoint-postgres
- asyncio

Realtime:
- SSE first
- HTTP commands for control
- add WebSockets later only if justified

Testing:
- pytest
- frontend unit/component tests
- Playwright
- type checks
- linting

Deployment:
- Docker Compose on Jarvis-Core
- V1 path `/opt/jarvis-v1`
- legacy `/opt/jarvis` stays untouched

## Development workflow

Before a milestone:
- read architecture/plan/status docs
- inspect existing code/tests
- state milestone criteria in `docs/STATUS.md`

Before milestone completion:
- run affected tests
- run type/lint checks
- browser-test affected UI
- check serious console errors
- review diff
- update docs/status
- commit coherently

Whole-project ready gate:
- `scripts/verify.sh` passes
- backend/frontend tests pass
- Playwright passes
- production builds succeed
- demo mode works
- real Jarvis-Worker-01 staging works
- no secrets committed
- deployment is reproducible/documented
