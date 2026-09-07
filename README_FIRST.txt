JARVIS V1 CODEX BOOTSTRAP PACK

1. Put these files into the root of your empty GitHub repository.
2. Populate docs/reference/legacy/ WITHOUT secrets:
   Core /opt/jarvis/app/jarvis_dev.py -> docs/reference/legacy/jarvis_dev.py
   Core /opt/jarvis/docker-compose.yml -> docs/reference/legacy/core-docker-compose.yml
   Worker /opt/jarvis-worker/developer_task.py -> docs/reference/legacy/developer_task.py
3. Commit the bootstrap/reference files.
4. Use CODEX_PROMPT_01_ARCHITECTURE.md first.
5. Review its architecture commit.
6. Use CODEX_PROMPT_02_IMPLEMENT.md.
7. After local gates pass, use CODEX_PROMPT_03_INTEGRATE.md.
8. After staging passes, use CODEX_PROMPT_04_DEPLOY.md.

NEVER copy `/opt/jarvis/.env`, `/opt/jarvis/secrets`, SSH private keys, DB passwords,
GitHub tokens, or OpenAI keys into this repository.
