import argparse
import base64
import json
import os
import shlex
import subprocess
import uuid

from dotenv import load_dotenv
from openai import OpenAI
from typing_extensions import TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres import PostgresSaver


load_dotenv("/opt/jarvis/.env")


client = OpenAI(
    base_url=os.environ["LLM_BASE_URL"],
    api_key=os.environ["LLM_API_KEY"],
)


class JarvisState(TypedDict, total=False):
    objective: str
    project_slug: str

    architecture: str
    tasks: list

    task_index: int
    current_task: dict

    developer_result: dict
    verification_results: list

    review: dict
    feedback: str

    attempt: int
    status: str


def llm_json(model, system, user):
    last_error = None

    for attempt in range(1, 4):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": system,
                    },
                    {
                        "role": "user",
                        "content": user,
                    },
                ],
                response_format={
                    "type": "json_object"
                },
                reasoning_effort="none",
                temperature=0,
                max_tokens=8192,
            )

            message = response.choices[0].message
            content = message.content

            if content and content.strip():
                return json.loads(content)

            print(
                f"LLM JSON attempt {attempt} returned empty content."
            )

            print(
                "Finish reason:",
                response.choices[0].finish_reason,
            )

            last_error = RuntimeError(
                "LLM returned empty response"
            )

        except Exception as exc:
            print(
                f"LLM JSON attempt {attempt} failed: {exc}"
            )
            last_error = exc

    raise RuntimeError(
        f"LLM JSON generation failed after 3 attempts: {last_error}"
    )


def architect(state: JarvisState):

    result = llm_json(
        os.environ["ARCHITECT_MODEL"],
        """
You are Jarvis Architect.

You design software projects for an autonomous software
development team.

Return ONLY valid JSON using this schema:

{
  "architecture": "clear technical architecture",
  "tasks": [
    {
      "id": "DEV-001",
      "title": "short title",
      "description": "implementation details",
      "acceptance_criteria": [
        "criterion"
      ],
      "verification_commands": [
        "shell command that exits 0 when correct"
      ]
    }
  ]
}

RULES:

1. Break the user's objective into ordered, independently
   reviewable implementation tasks.

2. Tasks must be ordered by dependency.

3. Prefer approximately 3-8 tasks for a small project.

4. Every task must have objective acceptance criteria.

5. Every task must have useful verification commands.

6. Verification commands should test BEHAVIOR whenever possible,
   rather than merely checking whether a file exists.

7. If executable code is created, verify that it imports,
   starts, executes, or otherwise works.

8. If tests are created for a task, run those tests.

9. Tasks are INCREMENTAL.

10. A task should only be judged on that task's acceptance
    criteria. Features intentionally assigned to later tasks
    must NOT be required in earlier tasks.

11. Do not put later-project requirements into earlier task
    acceptance criteria unless they are genuinely required
    dependencies.

12. The final task must perform full-project verification
    against the original user objective.

13. The final task should run the complete test suite.

14. Include documentation and repository hygiene where
    appropriate.

15. Keep the architecture practical. Do not overengineer a
    small project.

16. For Python projects, prefer "python -m pytest" over invoking
    "pytest" directly.

17. Verification runs in a development environment where the
    project worker virtualenv is placed first in PATH.

18. Verification commands must be fully non-interactive and must
    exit non-zero on failure.

19. ALL verification commands execute with the shell already located
    at the ROOT OF THE CURRENT PROJECT REPOSITORY.

20. NEVER use invented absolute project paths such as:
    /app
    /workspace
    /project
    /repo

21. Do NOT begin verification commands with "cd /app",
    "cd /workspace", "cd /project", or similar paths.

22. For a Node/Vite project, use commands such as:
    npm install
    npm test
    npm run build
    npx tsc --noEmit

    Do NOT use:
    cd /app && npm install

23. Verification commands must operate on the actual current
    repository and must not assume Docker container filesystem paths
    unless the project itself explicitly creates such a container.
""",
        state["objective"],
    )

    return {
        "architecture": result["architecture"],
        "tasks": result["tasks"],
        "task_index": 0,
        "status": "working",
    }


def select_task(state: JarvisState):

    task = state["tasks"][state["task_index"]]

    print(
        f"\n=== STARTING {task['id']} ==="
    )
    print(task["title"])

    return {
        "current_task": task,
        "attempt": 0,
        "feedback": "",
    }


def call_worker(payload):

    encoded = base64.b64encode(
        json.dumps(payload).encode()
    ).decode()

    remote_command = (
        "source /opt/jarvis-worker/venv/bin/activate "
        "&& python "
        "/opt/jarvis-worker/developer_task.py "
        + shlex.quote(encoded)
    )

    result = subprocess.run(
        [
            "ssh",
            "-i",
            os.environ["WORKER_KEY"],
            "-o",
            "StrictHostKeyChecking=accept-new",
            os.environ["WORKER_HOST"],
            remote_command,
        ],
        text=True,
        capture_output=True,
        timeout=7200,
    )

    for line in reversed(result.stdout.splitlines()):
        if line.startswith("JARVIS_RESULT_JSON="):
            return json.loads(
                line.split("=", 1)[1]
            )

    return {
        "error": (
            "Worker returned no structured result.\n\nSTDOUT:\n"
            + result.stdout[-5000:]
            + "\n\nSTDERR:\n"
            + result.stderr[-5000:]
        )
    }


def developer(state: JarvisState):

    attempt = state.get("attempt", 0) + 1

    print(
        f"\nDeveloper attempt {attempt}"
    )

    result = call_worker(
        {
            "project_slug":
                state["project_slug"],

            "objective":
                state["objective"],

            "architecture":
                state["architecture"],

            "task":
                state["current_task"],

            "feedback":
                state.get("feedback", ""),
        }
    )

    return {
        "developer_result": result,
        "attempt": attempt,
    }


def run_remote(project_slug, command):

    workspace = (
        "/opt/jarvis-worker/workspaces/"
        + project_slug
    )

    wrapped_command = (
        "export PATH=/opt/jarvis-worker/venv/bin:$PATH; "
        + command
    )

    remote = (
        "cd "
        + shlex.quote(workspace)
        + " && bash -lc "
        + shlex.quote(wrapped_command)
    )

    result = subprocess.run(
        [
            "ssh",
            "-i",
            os.environ["WORKER_KEY"],
            "-o",
            "StrictHostKeyChecking=accept-new",
            os.environ["WORKER_HOST"],
            remote,
        ],
        text=True,
        capture_output=True,
        timeout=1200,
    )

    return {
        "command": command,
        "exit_code": result.returncode,
        "stdout": result.stdout[-15000:],
        "stderr": result.stderr[-15000:],
    }



def normalize_verification_command(command):
    """
    Verification already executes from the project's real workspace.

    Local coding agents sometimes invent container-style paths such as
    /app or /workspace. Strip those leading cd commands so verification
    runs against the actual Jarvis workspace.
    """

    command = command.strip()

    bad_prefixes = [
        "cd /app && ",
        "cd /workspace && ",
        "cd /project && ",
        "cd /repo && ",
        "cd /workspaces && ",
    ]

    for prefix in bad_prefixes:
        if command.startswith(prefix):
            fixed = command[len(prefix):]

            print(
                f"NORMALIZED VERIFY COMMAND:\n"
                f"  FROM: {command}\n"
                f"  TO:   {fixed}"
            )

            return fixed

    return command

def verify(state: JarvisState):

    commands = state["current_task"].get(
        "verification_commands",
        [],
    )

    results = []

    if not commands:
        results.append(
            {
                "command": "(no verification command)",
                "exit_code": 1,
                "stdout": "",
                "stderr":
                    "Architect provided no deterministic "
                    "verification command.",
            }
        )

        return {
            "verification_results": results
        }

    for raw_command in commands:

        command = normalize_verification_command(
            raw_command
        )

        print(
            f"\nVERIFY: {command}"
        )

        result = run_remote(
            state["project_slug"],
            command,
        )

        print(
            f"exit={result['exit_code']}"
        )

        if result["stdout"]:
            print(
                result["stdout"][-2000:]
            )

        if result["stderr"]:
            print(
                result["stderr"][-2000:]
            )

        results.append(result)

    return {
        "verification_results": results
    }


def get_repo_snapshot(state: JarvisState):

    tree = run_remote(
        state["project_slug"],
        """
find . -maxdepth 4 -type f \
  ! -path './.git/*' \
  ! -path './.venv/*' \
  ! -path '*/__pycache__/*' \
  | sort
""",
    )

    status = run_remote(
        state["project_slug"],
        "git status --short",
    )

    log = run_remote(
        state["project_slug"],
        "git --no-pager log --oneline -10",
    )

    return {
        "files":
            tree["stdout"][:20000],

        "git_status":
            status["stdout"][:5000],

        "recent_commits":
            log["stdout"][:5000],
    }


def get_source_snapshot(state: JarvisState):

    command = r'''
find . -maxdepth 4 -type f \
  ! -path './.git/*' \
  ! -path './.venv/*' \
  ! -path '*/__pycache__/*' \
  \( \
    -name '*.py' \
    -o -name '*.md' \
    -o -name '*.txt' \
    -o -name '*.toml' \
    -o -name '*.ini' \
    -o -name '*.yml' \
    -o -name '*.yaml' \
    -o -name '*.json' \
  \) \
  -print0 |
while IFS= read -r -d '' f; do
    echo
    echo "===== $f ====="
    sed -n '1,300p' "$f"
done
'''

    result = run_remote(
        state["project_slug"],
        command,
    )

    return result["stdout"][:60000]


def get_latest_diff(state: JarvisState):

    dev = state.get(
        "developer_result",
        {},
    )

    start = dev.get("start_head")
    end = dev.get("end_head")

    if not start or not end:
        return ""

    result = run_remote(
        state["project_slug"],
        (
            "git diff --unified=3 "
            + shlex.quote(start)
            + ".."
            + shlex.quote(end)
        ),
    )

    return result["stdout"][:40000]


def reviewer(state: JarvisState):

    failed_commands = [
        item
        for item in state["verification_results"]
        if item["exit_code"] != 0
    ]

    if failed_commands:

        feedback = (
            "Deterministic verification failed.\n\n"
            + json.dumps(
                failed_commands,
                indent=2,
            )
        )

        print("\nREVIEW: FAIL")
        print(feedback)

        return {
            "review": {
                "verdict": "FAIL",
                "feedback": feedback,
            },
            "feedback": feedback,
        }

    repo_snapshot = get_repo_snapshot(state)
    source_snapshot = get_source_snapshot(state)
    latest_diff = get_latest_diff(state)

    result = llm_json(
        os.environ["REVIEWER_MODEL"],
        """
You are Jarvis Reviewer.

You are an independent senior software engineer.

You DID NOT write this implementation.

Your job is to review ONLY THE CURRENT TASK.

CRITICAL RULES:

1. Judge the implementation primarily against the CURRENT TASK
   and its acceptance criteria.

2. Do NOT fail an early task merely because later project
   features have not yet been implemented.

3. The overall project objective is context, not a requirement
   that every individual task must complete the entire project.

4. The architecture is context. Fail only when the current task
   genuinely violates or damages the architecture.

5. The latest code diff represents ONLY THE MOST RECENT
   developer attempt.

6. A file missing from the latest diff may already exist in the
   repository from an earlier attempt.

7. The CURRENT REPOSITORY FILE LIST and CURRENT SOURCE SNAPSHOT
   are authoritative for the present repository state.

8. Deterministic verification commands have already passed.
   Treat that as strong evidence.

9. Do not contradict passing deterministic verification unless
   you can identify a concrete defect that the verification
   failed to cover.

10. FAIL only for a real issue with the CURRENT TASK such as:
    - acceptance criterion not actually satisfied
    - broken implementation
    - serious security problem
    - architecture-breaking decision
    - required current-task tests missing
    - clearly unusable or unmaintainable implementation

11. Do not invent missing files. Inspect the repository snapshot.

12. Do not require future-task features.

Return ONLY valid JSON:

{
  "verdict": "PASS" or "FAIL",
  "feedback": "specific explanation"
}
""",
        json.dumps(
            {
                "project_objective":
                    state["objective"],

                "project_architecture":
                    state["architecture"],

                "current_task":
                    state["current_task"],

                "developer_result":
                    state["developer_result"],

                "verification_results":
                    state["verification_results"],

                "current_repository":
                    repo_snapshot,

                "current_source_snapshot":
                    source_snapshot,

                "latest_attempt_diff":
                    latest_diff,
            },
            indent=2,
        ),
    )

    verdict = (
        result.get("verdict", "")
        .strip()
        .upper()
    )

    if verdict not in {
        "PASS",
        "FAIL",
    }:
        verdict = "FAIL"
        result["feedback"] = (
            "Reviewer returned invalid verdict. "
            + result.get("feedback", "")
        )

    result["verdict"] = verdict

    print(
        "\nREVIEW:",
        verdict,
    )

    print(
        result.get("feedback", "")
    )

    return {
        "review": result,
        "feedback": result.get(
            "feedback",
            "",
        ),
    }


def route_review(state: JarvisState):

    if (
        state["review"]["verdict"]
        == "PASS"
    ):
        return "pass"

    if state["attempt"] >= 7:
        return "blocked"

    return "retry"


def advance(state: JarvisState):

    next_index = (
        state["task_index"] + 1
    )

    if next_index >= len(
        state["tasks"]
    ):

        print(
            "\n=== PROJECT COMPLETE ==="
        )

        return {
            "task_index": next_index,
            "current_task": {},
            "status": "complete",
        }

    return {
        "task_index": next_index,
        "current_task": {},
        "feedback": "",
        "attempt": 0,
        "status": "working",
    }


def route_advance(state: JarvisState):

    if state["status"] == "complete":
        return "done"

    return "more"


def blocked(state: JarvisState):

    print(
        "\n=== PROJECT BLOCKED ==="
    )

    print(
        state.get(
            "feedback",
            "",
        )
    )

    return {
        "status": "blocked"
    }


builder = StateGraph(
    JarvisState
)

builder.add_node(
    "architect",
    architect,
)

builder.add_node(
    "select_task",
    select_task,
)

builder.add_node(
    "developer",
    developer,
)

builder.add_node(
    "verify",
    verify,
)

builder.add_node(
    "reviewer",
    reviewer,
)

builder.add_node(
    "advance",
    advance,
)

builder.add_node(
    "blocked",
    blocked,
)


builder.add_edge(
    START,
    "architect",
)

builder.add_edge(
    "architect",
    "select_task",
)

builder.add_edge(
    "select_task",
    "developer",
)

builder.add_edge(
    "developer",
    "verify",
)

builder.add_edge(
    "verify",
    "reviewer",
)


builder.add_conditional_edges(
    "reviewer",
    route_review,
    {
        "pass": "advance",
        "retry": "developer",
        "blocked": "blocked",
    },
)


builder.add_conditional_edges(
    "advance",
    route_advance,
    {
        "more": "select_task",
        "done": END,
    },
)


builder.add_edge(
    "blocked",
    END,
)


parser = argparse.ArgumentParser()

parser.add_argument(
    "--objective",
    required=True,
)

parser.add_argument(
    "--slug",
    required=True,
)

parser.add_argument(
    "--thread",
    default=None,
)

args = parser.parse_args()


thread_id = (
    args.thread
    or str(uuid.uuid4())
)


with PostgresSaver.from_conn_string(
    os.environ["DATABASE_URL"]
) as checkpointer:

    checkpointer.setup()

    graph = builder.compile(
        checkpointer=checkpointer
    )

    print(
        f"Jarvis thread: {thread_id}"
    )

    final = graph.invoke(
        {
            "objective":
                args.objective,

            "project_slug":
                args.slug,

            "status":
                "new",
        },
        {
            "configurable": {
                "thread_id":
                    thread_id
            }
        },
    )

    print(
        "\nFINAL STATUS:",
        final["status"],
    )

    print(
        "THREAD ID:",
        thread_id,
    )
