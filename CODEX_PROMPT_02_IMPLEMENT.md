# Prompt 02 — Implement Jarvis V1 Locally

Read `AGENTS.md` and all architecture/plan/status docs first.

Implement Jarvis V1 according to the approved architecture.

Work milestone-by-milestone. Use separate worktrees/agents only for milestones marked safely parallel. Keep one coherent set of shared abstractions.

For each milestone:
1. put criteria in `docs/STATUS.md`
2. implement real production code, not placeholders
3. update migrations
4. add deterministic tests
5. run relevant backend/frontend tests
6. run type/lint checks
7. browser-test UI flows where relevant
8. review diff for correctness/security/architecture
9. update docs/status
10. commit coherently

Rules:
- continue autonomously through ordinary implementation problems
- diagnose from real logs/tests
- UI scaffolding alone is not feature completion
- required buttons/settings/workflow nodes need real backend behavior
- do not weaken gates just to pass
- distinguish infrastructure vs code/test/review failures
- never fake activity outside explicit demo mode
- never expose chain-of-thought
- never commit secrets
- never touch live `/opt/jarvis`

Create/maintain:
- `scripts/dev.sh`
- `scripts/verify.sh`
- `scripts/demo.sh`
- `scripts/deploy-core.sh`
- `.env.example`
- `deploy/` configuration
- CI workflow(s)

Fresh checkout must be bootable with documented commands.
Demo mode must exercise live graph transitions, logs, approvals, retries, workers, workflow editing, and history.

Do not deploy to real Core yet.

Continue until every non-homelab acceptance test passes locally and `scripts/verify.sh` succeeds.
At the end update `docs/STATUS.md` with readiness, exact verification results, remaining staging tests, known limits, and next commands.
