# Current Jarvis Prototype — Integration Context

## Infrastructure

### Jarvis-Core
- Hostname: `Jarvis-Core`
- LAN IP: `192.168.40.105`
- Ubuntu 24.04.x
- Prototype root: `/opt/jarvis`
- Python venv: `/opt/jarvis/venv`
- Supervisor: `/opt/jarvis/app/jarvis_dev.py`
- PostgreSQL 16 container: `jarvis-postgres`
- Compose: `/opt/jarvis/docker-compose.yml`
- PostgreSQL bound to `127.0.0.1:5432`
- LangGraph uses Postgres checkpointing
- GitHub CLI installed
- GitHub supervisor machine account: `IAmMrRed`
- GitHub org: `ClearPointSolutions`
- GitHub secret file: `/opt/jarvis/secrets/github.env` (never copy/commit contents)
- Core->Worker SSH key: `/home/jarvis/.ssh/jarvis_worker`
- Publish helper: `/opt/jarvis/app/publish_project.sh`
- Known packages observed: LangGraph 1.2.11, langgraph-checkpoint-postgres 3.1.2, psycopg 3.3.5, openai 3.8.0

### Jarvis-Worker-01
- Hostname: `Jarvis-Worker-01`
- LAN IP: `192.168.40.106`
- Workspace root: `/opt/jarvis-worker/workspaces`
- Venv: `/opt/jarvis-worker/venv`
- Runner: `/opt/jarvis-worker/developer_task.py`
- OpenHands SDK/tools installed
- Python 3.12.3
- pytest 9.1.1
- Node 20.20.2
- npm/npx 10.8.2
- Git + Docker available
- Worker user has passwordless sudo

### AI Server
- Separate Ubuntu AI server
- Ollama on LAN with OpenAI-compatible endpoint
- GPUs: RTX 3060 12GB + RTX 5060 Ti 16GB
- Open WebUI and related local AI services exist
- AI server URL must be config/env, never hard-coded
- Local models remain first-class even when OpenAI is enabled

## Current working loop

Human objective
-> LangGraph Architect
-> ordered tasks
-> OpenHands Developer on Worker
-> deterministic verification
-> independent Reviewer
-> PASS advances / FAIL retries
-> complete or blocked

The prototype has autonomously completed a multi-task todo project.

## Lessons already learned

1. Verification executes from the real repository root; model-invented paths like `/app` caused failures.
2. Infrastructure/tooling failures must not count as developer-code failures.
3. Retry budgets need configuration by failure class.
4. Reviewer context must include authoritative current repository state, not only the latest diff.
5. Huge logs should stay outside LangGraph state; state stores references/summaries.
6. Runs must be durable/resumable instead of one long HTTP request.
7. Worker execution needs an adapter abstraction so OpenHands can later coexist with Codex/other workers.
8. Git should use task branches/worktrees and merge only after gates pass.
9. Sensitive/destructive operations need durable human approvals.
10. A normalized event layer must drive the UI.

## V1 staging boundary

Install V1 separately at `/opt/jarvis-v1`.
Do not overwrite/delete/mutate `/opt/jarvis`.
The legacy prototype remains rollback/recovery until explicit promotion.
