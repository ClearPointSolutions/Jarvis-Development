# Worker compatibility wrapper protocol 1.0

This directory is a versioned source package entrypoint, backed by
`jarvis_orchestrator.workers.wrapper` in the pinned `jarvis-v1` Python package.
The wheel also installs `jarvis-worker-wrapper-v1`. M7 tests run it locally.
Nothing in this directory has been deployed to Worker-01.

## Future authorized staging procedure

These are instructions for a later authorized staging task, not commands executed
by M7. Preserve `/opt/jarvis`, the existing worker runner, its virtual environment,
and its model environment. Never install this project's dependencies into the
legacy OpenHands environment.

1. Review the selected commit, build its wheel, record its SHA-256, and transfer
   the wheel, pinned requirements and this entrypoint through the authorized
   staging channel. Verify checksums at the destination.
2. Create a dedicated Python 3.12 virtual environment under a configured V1
   wrapper directory. Install the pinned requirements and the exact wheel there.
   Place this entrypoint at the configured `wrapper_path`; set `python_path` to
   the new environment's Python. Set `runner_python_path` to the existing
   OpenHands environment's Python and `runner_path` to the unchanged runner.
3. Create a private invocation directory owned by the worker service account
   (0700). Configure it as `invocation_root`. Keep invocation records until the
   controller has reconciled them; expiry does not authorize deleting them.
4. Configure a server-only `OpenHandsDeployment` for the immutable worker
   revision. Resolve key references to protected private-key and known-host files.
   Obtain the host key through an independent trusted channel. Supply the exact
   host allowlist to `OpenSSHTransport`; never use TOFU or disable strict checking.
5. Bind the revision with `configured_worker_registry`, a durable task request
   source, a protected artifact root, and the transport factory. Inject that
   registry into `OrchestratorService`. The default entrypoint has no implicit
   real-worker binding. Missing configuration blocks worker execution.
6. Keep the compatibility worker at `max_concurrency=1`, exclusive workspace
   policy and one worker-managed model profile. The legacy runner always derives
   its workspace from its existing root and the validated project slug. An
   arbitrary worktree root is not supported by that runner. Isolated worktree
   creation is a separately tested generic capability, not advertised by this
   compatibility adapter.
7. After explicit staging authorization, run health, a disposable task, reconnect,
   cancellation and restart checks. Confirm repository root/branch/base before
   dispatch and independent HEAD/status/diff/manifest evidence after completion.
   Compare the configured worker-managed model with the actual worker environment.
   A successful M7 fake transport test is not evidence of Worker-01 compatibility.

## Protocol and recovery

The entrypoint accepts one bounded base64 JSON argument. Operations are health,
repository, start, inspect, collect and cancel; supervise is an internal detached
process operation. UUID-directory reservation and digest checks prevent duplicate
launch. A separate supervisor owns the runner process group, drains bounded logs,
writes redacted artifacts, and atomically replaces status. Output activity and
supervisor liveness are separate timestamps. There is no arbitrary shell listener.

A missing status inside a reserved directory, lost supervisor heartbeat, or
unprovable cancellation reports unknown. Never retry such an invocation with a
new identity until its process/workspace ownership is reconciled. Restart reads
the existing identity. Remote process metadata is evidence, not authority to
advance a task: the controller must still validate its active generation fence.

POSIX cancellation targets the invocation process group. The local Windows
fixture deliberately reports unknown after parent termination because it cannot
prove whole-tree termination. Later Linux staging must verify the POSIX behavior.
Logs are bounded in private memory during capture; only redacted complete output
is atomically published to disk. The independent bounded sentinel channel keeps
the final structured result even when the log prefix has been truncated.
