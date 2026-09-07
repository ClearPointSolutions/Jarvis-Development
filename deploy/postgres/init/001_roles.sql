-- Local/bootstrap logical roles. They carry no LOGIN and contain no credentials.
DO $roles$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_v1_migrator') THEN
    CREATE ROLE jarvis_v1_migrator NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_v1_api') THEN
    CREATE ROLE jarvis_v1_api NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_v1_orchestrator') THEN
    CREATE ROLE jarvis_v1_orchestrator NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'jarvis_v1_readonly') THEN
    CREATE ROLE jarvis_v1_readonly NOLOGIN;
  END IF;
END
$roles$;

-- The disposable Compose login may assume each logical role for privilege tests.
GRANT jarvis_v1_migrator, jarvis_v1_api, jarvis_v1_orchestrator, jarvis_v1_readonly
  TO jarvis_v1_dev;
