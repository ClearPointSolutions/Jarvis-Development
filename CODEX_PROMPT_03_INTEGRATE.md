# Prompt 03 — Real Homelab Integration

Local/demo gates have passed. Now integrate against the real homelab while preserving the legacy prototype.

Read all source and deployment/acceptance/status docs first.

Remote targets:
- Core: `jarvis@192.168.40.105`
- Worker-01: `jarvis@192.168.40.106`

Hard boundaries:
- never modify/delete `/opt/jarvis`
- never display/copy `/opt/jarvis/secrets` contents
- V1 staging path `/opt/jarvis-v1`
- do not promote V1 yet
- credentials are runtime env/secret references only

Integration work:
1. validate SSH and non-secret runtime facts
2. validate live existing worker runner contract
3. complete/fix `OpenHandsSshWorkerAdapter`
4. real remote verification from correct workspace
5. worker heartbeat/status + failure classification
6. LangGraph Postgres checkpoint/resume across orchestrator restart
7. real SSE events for node/task/tool/command/test/review transitions
8. harmless approval interrupt/resume
9. GitHub integration against `ClearPointSolutions` using disposable private test repo only
10. provider health for Ollama and optional OpenAI; missing optional provider config must degrade clearly
11. run full real-worker acceptance scenario

Fix defects with tests/commits.
Do not promote/replace legacy.
Stop when real staging tests pass and update `docs/STATUS.md`.
