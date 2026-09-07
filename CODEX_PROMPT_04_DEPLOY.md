# Prompt 04 — Side-by-Side Deployment to Jarvis-Core

Local and staging gates have passed.

You are authorized to deploy Jarvis V1 side-by-side to:
`jarvis@192.168.40.105:/opt/jarvis-v1`

You are NOT authorized to delete, overwrite, rename, stop, or mutate `/opt/jarvis` except read-only compatibility checks.

Before deploy:
- rerun `scripts/verify.sh`
- repo clean
- no tracked secrets
- review deploy config
- confirm every target is under `/opt/jarvis-v1`

Deployment requirements:
- service names avoid legacy collisions
- dedicated V1 database/storage
- healthchecks + restart policies
- authenticated LAN UI
- no public exposure
- no Docker socket unless explicitly justified
- SSH key is server-side/read-only where worker adapter needs it
- GitHub/provider secrets injected at runtime
- logs redact secrets

After deploy:
1. API health
2. web health
3. migrations
4. browser login
5. harmless demo project
6. real Worker-01 project
7. live graph/events
8. pause/resume/cancel
9. approval interrupt/resume
10. history survives service restart
11. update deployment report/status

Do not switch DNS/reverse proxy and do not remove legacy.

Finish with:
- V1 LAN URL
- API health URL
- service names/status
- exact rollback command
- remaining promotion steps.
