import base64
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

from openhands.sdk import LLM, Agent, Conversation, Tool
from openhands.tools.file_editor import FileEditorTool
from openhands.tools.task_tracker import TaskTrackerTool
from openhands.tools.terminal import TerminalTool


load_dotenv("/opt/jarvis-worker/.env")


def shell(args, cwd=None):
    result = subprocess.run(
        args,
        cwd=cwd,
        text=True,
        capture_output=True,
    )

    return result


def git(args, cwd):
    return shell(
        ["git", *args],
        cwd=cwd,
    )


payload = json.loads(
    base64.b64decode(
        sys.argv[1]
    ).decode()
)


slug = re.sub(
    r"[^a-zA-Z0-9_.-]",
    "-",
    payload["project_slug"],
)

task = payload["task"]
architecture = payload.get("architecture", "")
feedback = payload.get("feedback", "")


workspace = (
    Path("/opt/jarvis-worker/workspaces")
    / slug
)

workspace.mkdir(
    parents=True,
    exist_ok=True,
)


if not (workspace / ".git").exists():

    git(
        ["init", "-b", "main"],
        workspace,
    )

    git(
        ["config", "user.name", "Jarvis Developer"],
        workspace,
    )

    git(
        ["config", "user.email", "jarvis@local"],
        workspace,
    )

    git(
        [
            "commit",
            "--allow-empty",
            "-m",
            "chore: initialize project",
        ],
        workspace,
    )


start_head_result = git(
    ["rev-parse", "HEAD"],
    workspace,
)

start_head = (
    start_head_result.stdout.strip()
)


llm = LLM(
    model=os.environ["LLM_MODEL"],
    api_key=os.environ["LLM_API_KEY"],
    base_url=os.environ["LLM_BASE_URL"],
)


agent = Agent(
    llm=llm,
    tools=[
        Tool(name=TerminalTool.name),
        Tool(name=FileEditorTool.name),
        Tool(name=TaskTrackerTool.name),
    ],
)


persist_dir = (
    Path("/opt/jarvis-worker/persistence")
    / slug
    / task["id"]
)

persist_dir.mkdir(
    parents=True,
    exist_ok=True,
)


conversation = Conversation(
    agent=agent,
    workspace=str(workspace),
    persistence_dir=str(persist_dir),
    max_iteration_per_run=100,
)


prompt = f"""
You are Jarvis Developer, an autonomous senior software engineer.

PROJECT OBJECTIVE:
{payload["objective"]}

PROJECT ARCHITECTURE:
{architecture}

CURRENT TASK:
ID: {task["id"]}
TITLE: {task["title"]}

DESCRIPTION:
{task["description"]}

ACCEPTANCE CRITERIA:
{json.dumps(task["acceptance_criteria"], indent=2)}

EXPECTED VERIFICATION COMMANDS:
{json.dumps(task.get("verification_commands", []), indent=2)}

REVIEW FEEDBACK FROM PREVIOUS ATTEMPT:
{feedback or "None"}

Rules:

1. Inspect the ENTIRE existing repository before changing anything.

2. The repository may contain work from previous attempts.
   Preserve correct existing files.

3. The latest review feedback refers to the CURRENT repository state,
   not just the most recent diff.

4. Implement the CURRENT TASK and its acceptance criteria.

5. Do not unnecessarily implement features that are explicitly
   assigned to later project tasks.

6. Integrate your work correctly with all existing code.

7. When correcting a failed review, inspect the current files before
   deciding something is missing.

8. Never delete or replace correct existing implementation merely
   because it was created during an earlier attempt.

9. You have sudo access on this disposable development VM if required.

10. Install project dependencies when needed.

11. Run relevant builds and tests yourself.

12. Fix errors you encounter.

13. Do not claim success without actually testing your work.

14. Keep the repository in a usable state.

15. Do not delete unrelated existing work.

16. Add appropriate .gitignore entries for generated runtime files,
    caches, virtual environments, databases, and build artifacts.

17. Do not commit generated runtime artifacts such as __pycache__,
    temporary SQLite databases, or virtual environments.

18. Finish the task rather than merely explaining how to do it.

19. Your Conversation workspace is the PROJECT ROOT.

20. Work inside the supplied workspace. Never assume the project is
    located at /app, /workspace, /project, or /repo.

21. When running project commands such as npm, pytest, builds, or
    compilers, run them from the actual current repository.

22. Do not create a second copy of the project somewhere else on
    the machine.
"""


conversation.send_message(prompt)


error = None

try:
    conversation.run()

except Exception as exc:
    error = repr(exc)


status_result = git(
    ["status", "--short"],
    workspace,
)


if status_result.stdout.strip():

    git(
        ["add", "-A"],
        workspace,
    )

    git(
        [
            "commit",
            "-m",
            f"agent: {task['id']} {task['title']}",
        ],
        workspace,
    )


end_head_result = git(
    ["rev-parse", "HEAD"],
    workspace,
)

end_head = (
    end_head_result.stdout.strip()
)


diff_stat = git(
    [
        "diff",
        "--stat",
        f"{start_head}..{end_head}",
    ],
    workspace,
).stdout


result = {
    "task_id": task["id"],
    "workspace": str(workspace),
    "start_head": start_head,
    "end_head": end_head,
    "diff_stat": diff_stat,
    "error": error,
    "execution_status": str(
        conversation.state.execution_status
    ),
}


print(
    "JARVIS_RESULT_JSON="
    + json.dumps(result)
)
