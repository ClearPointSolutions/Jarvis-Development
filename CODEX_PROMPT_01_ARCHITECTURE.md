# Prompt 01 — Architecture Only

You are the principal architect for Jarvis V1.

Read every source-of-truth file first:
- `AGENTS.md`
- `docs/reference/JARVIS_MISSION_CONTROL_BASE_IDEA.txt`
- `docs/reference/CURRENT_PROTOTYPE.md`
- everything under `docs/reference/legacy/`

Do not write application code yet.

Jarvis V1 / Mission Control is the primary browser interface and durable LangGraph orchestration control plane between the human supervisor, the agent supervisor, workers, tools, Git/GitHub, and infrastructure.

Mandatory V1 capabilities:
- secure authenticated Mission Control UI
- Organizer chat
- projects/jobs/history
- real-time LangGraph execution graph
- normalized live event/activity feed
- tasks/attempts/retries/failure classes
- worker registry + GUI worker editor
- model provider/profile management
- OpenAI + Ollama routing
- executable visual workflow-template editor using React Flow
- per-node worker/model/retry/verification/approval policy
- durable LangGraph execution compiled from saved workflow config
- configurable retry budgets by failure class
- real human approvals using LangGraph interrupt/resume
- artifacts/files/diffs/commands/tests visibility
- GitHub repo/branch/PR/CI integration
- read-only terminal/log UX
- system/service/worker health
- token/cost accounting infrastructure
- run history/audit trail
- deterministic demo mode
- side-by-side deployment to `/opt/jarvis-v1`
- real integration with Jarvis-Worker-01
- legacy prototype preserved as rollback

Preferred runtime split:
Browser
-> Next.js
-> FastAPI Control API
-> PostgreSQL canonical state/events
-> dedicated Orchestrator service
-> LangGraph + PostgresSaver
-> provider router / worker adapters / GitHub adapter
-> worker pool

Use SSE for server-to-browser events and normal HTTP for commands.

The API must not own hours-long execution in request handlers. Persist/queue runs; the Orchestrator claims and executes them. Prefer PostgreSQL for queue/leases rather than adding Redis unless strongly justified.

Event store is append-only. Consider PostgreSQL LISTEN/NOTIFY for live fanout plus DB replay.

Workflow templates are executable data, not drawings. Define a validated workflow spec compiled into LangGraph nodes/edges.

Initial worker adapter must support the existing OpenHands runner on Jarvis-Worker-01 over SSH, while keeping the adapter generic for future Codex workers.

Deployment constraints:
- V1 path `/opt/jarvis-v1`
- legacy `/opt/jarvis` untouched
- Core `192.168.40.105`
- Worker `192.168.40.106`
- all addresses/paths/keys/endpoints are configuration-driven
- never copy secrets into repo

Create and commit:
- `docs/PRODUCT_SPEC_V1.md`
- `docs/ARCHITECTURE.md`
- `docs/DATA_MODEL.md`
- `docs/EVENT_SCHEMA.md`
- `docs/WORKFLOW_RUNTIME.md`
- `docs/WORKER_PROTOCOL.md`
- `docs/PROVIDER_ROUTING.md`
- `docs/SECURITY_MODEL.md`
- `docs/DEPLOYMENT_PLAN.md`
- `docs/IMPLEMENTATION_PLAN.md`
- `docs/ACCEPTANCE_TESTS.md`
- `docs/DECISIONS.md`
- `docs/STATUS.md`

Implementation plan must be dependency-ordered and label safe parallel milestones/worktrees.

Acceptance tests must include this real E2E:
1. login
2. create/edit worker
3. create/edit executable workflow
4. create project/objective
5. start real LangGraph run
6. graph/events update from real runtime
7. Organizer/Architect creates tasks
8. Developer executes on Worker-01
9. command/test/file events appear
10. verifier runs
11. failure routes correctly without losing state
12. reviewer uses authoritative current repo state
13. approval interrupts/resumes
14. GitHub publishing/PR works when configured/approved
15. history survives service restart

Also define demo-mode E2E tests.

Before finishing architecture:
- trace at least 3 full workflows
- define parallel-job race/concurrency handling
- define worker leases/concurrency
- define process-restart recovery
- define failure classification/retry semantics
- define exactly how visual workflows compile to LangGraph
- define secret boundaries
- define migration/rollback
- flag unresolved rework risks

Do not ask non-blocking questions. Make reasonable documented decisions.
STOP after architecture/docs commit. Do not implement application code in this turn.
