# Disposable verification executor

Implementation and acceptance are tracked in `V1_HARDENING_MATRIX.md`.
The initial profile is offline Python 3.12 with pytest. It supports at most
1,000 UTF-8 files and 4 MiB of source, excluding binary, LFS, symlink and submodule
content. Dependencies must be present in the pinned image; tests cannot install
from the network. Other project profiles remain a separate V1 requirement.

Core seals committed source and sends a bounded request containing run,
execution, candidate/tree SHA, files and command. The dedicated broker validates
the request and launches a disposable container with no host mounts or network.
The immutable image has no Core code, credentials, Git or SSH client. Work runs
as UID 10001 with dropped capabilities, no-new-privileges, default seccomp,
read-only root, 64 MiB writable tmpfs, 256 MiB memory, one CPU and 64 PIDs.

The broker's daemon socket and receipt directory stay outside tested code.
The response binds the request digest, identities and immutable image ID. Core
validates those associations and redacts output before publishing evidence.
Completed receipts are reused; exited containers are reconciled after a crash
before receipt publication. Recovered logs explicitly report incompleteness.
Unknown/missing container state is blocked rather than silently rerun.

## Validated disposable local commands

From the repository with its supported Python environment installed:

```sh
docker build -f deploy/verification.Dockerfile -t jarvis-v1-verification:local .
JARVIS_TEST_ISOLATION_IMAGE=jarvis-v1-verification:local \
  python -m pytest tests/integration/test_isolation_broker.py tests/unit/test_isolation_contract.py
```

On PowerShell use `$env:JARVIS_TEST_ISOLATION_IMAGE='jarvis-v1-verification:local'`
and `.venv/Scripts/python.exe`. The acceptance test obtains the immutable image
ID from Docker, creates its own receipt directory, checks actual confinement and
normal project tests, then injects a receipt-publication crash and recovers the
original random output. It also checks timeout and immutable receipt reuse.

The normal-entrypoint fixture provisions a broker configuration automatically.
Its direct local subprocess transport is a disposable test harness. Production
must put the broker on a dedicated executor account/host, with no Core secrets.

## Production configuration contract (target acceptance pending)

Build/install this repository's Python package in the executor account's own
environment and build the verification image there. Record the local image ID
from `docker image inspect --format '{{.Id}}' jarvis-v1-verification:local`.
The broker configuration is private, owned by the executor account and contains:

```json
{
  "docker_executable": "/usr/bin/docker",
  "image_id": "sha256:REPLACE_WITH_VERIFIED_IMAGE_ID",
  "receipt_root": "/opt/jarvis-v1/executor/receipts"
}
```

Use a dedicated SSH key restricted to the fixed command:

```text
restrict,command="/opt/jarvis-v1/executor/venv/bin/python -I -m jarvis_orchestrator.verification.isolation_cli --config /opt/jarvis-v1/executor/broker.json" ssh-ed25519 PUBLIC_KEY
```

The Core manifest's required `verification_isolation` contains the same
`image_id` and a server-owned `broker_argv` invoking an absolute SSH executable
with batch mode, identity-only authentication, strict host-key checking and a
pinned known-hosts file for the explicitly authorized executor target. The
fixed remote command accepts only the bounded stdin protocol. Do not expose a
general shell endpoint or mount the Docker socket into Core or the web/API.

This document does not claim an authorized production installation has run.
Remote transport and full packaging acceptance remain tracked gates. Install
the supplied `deploy/jarvis-verification-reap.service` and `.timer` for the
dedicated executor account, adapting the explicit executable/configuration
paths to its installation. The timer calls the fixed broker `--reap` operation
every 15 seconds. It checks broker-owned intent and container identities before
killing expired workloads; it retains container results for receipt recovery.
The actual-container test terminates the broker process and proves the watchdog
can enforce the deadline independently. The systemd installation itself still
requires the isolated packaging gate; it is not claimed as tested on a live host.
