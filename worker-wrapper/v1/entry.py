"""Versioned compatibility entrypoint; install jarvis-v1 in a separate wrapper venv."""

from jarvis_orchestrator.workers.wrapper import main

if __name__ == "__main__":
    main()
