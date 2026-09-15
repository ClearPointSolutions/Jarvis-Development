# Phase 3 handoff

## Identity

- Base SHA: `cb196b3bd5f55f557c4b8b2c85184be017487eee`
- Branch: `phase/03-web-project-profiles`
- Implementation commits: `1011e9f` and `bdff4e4`
- Final branch SHA: the commit containing this handoff; confirm with
  `git rev-parse HEAD` after publication
- Draft PR: UNVERIFIED until authorized publication succeeds
- CI identity: UNVERIFIED until the draft PR check runs against the exact branch tip

## IMPLEMENTED

- Versioned execution-profile contracts, persistence, migration `0014`, registry
  templates, authenticated APIs, and frontend management now cover the retained
  Python path plus Node build/unit and Playwright browser-acceptance profiles.
  Profiles bind immutable image identity, exact supported commands and toolchain,
  resource/time/output limits, source formats and sizes, dependency policy, and
  network policy. Mutable image references must resolve before evidence can pass.
- Projects and published workflows explicitly select profile revisions and
  immutable required acceptance checks. Real-run admission checks that the
  project type, project selections, workflow snapshot, installed profiles, and
  required build/unit/browser checks agree. Unsupported commands and invalid
  project inputs return structured profile/capability failures before dispatch.
- Dependency preparation is a separate broker operation. npm preparation requires
  `package.json`, lockfile v2/v3, package integrity metadata, HTTPS registries
  within the configured allowlist, disabled lifecycle scripts, bounded cache and
  output, no control-plane secrets or Docker socket, and a dedicated preparation
  network. Its digest binds the manifests, lockfile, resolved profile, and image.
- Normal verification is read-only, capability-dropped, resource-bounded, and
  egress-denied. Browser/app processes are identity-owned, reconciled, and cleaned
  after completion, cancellation, or timeout. Tests cover denial of injected
  credentials, Docker authority, host/LAN/metadata/public destinations, and
  preparation-only registry access.
- Verification evidence binds exact source, profile revision/digest, resolved
  image, prepared dependencies, command, required-check set, parsed report, exit
  result, and output-truncation state. Required suites must be non-empty;
  incomplete/truncated/timed-out/unexpected results cannot pass. Required checks
  are reattached from approved configuration and cannot be silently removed or
  replaced. Candidate changes invalidate stale verification/review evidence.
- Deterministic repository context pins one source/tree revision and records the
  bounded repository map, prioritized excerpts, manifests, existing tests,
  project brief, directives, architecture decisions, verified outcomes,
  provenance, line ranges, content digests, selection policy, and omissions.
  Missing required paths or a partial context requested as complete fails closed;
  repository text is explicitly treated as untrusted data. The existing complete
  source-snapshot review path remains authoritative for V1-sized projects.
- Mission/run pages expose project types, selected profiles, required checks,
  profile preflight errors, dependency preparation, and build/unit/browser
  evidence. The profile registry provides the approved immutable templates.
- `tests/fixtures/phase-03-full-stack` is a runnable frontend plus Python HTTP API
  with form validation, SQLite persistence, reload, and a follow-on completion
  change. Its build, Python/Node unit tests, and Playwright create/reload/
  complete/reload journey are part of `scripts/verify.sh`.
- Deployment assets add pinned Node/browser verifier images and a least-privilege
  dependency-preparation broker example. No public preview, arbitrary shell API,
  browser secret, Core-wide package installation, or legacy-path mutation was
  introduced.

## Changed files

```text
api/app/jarvis_api/{auth/routes.py,runtime.py,workflows/service.py}
api/migrations/versions/0014_phase_03_web_profiles.py
deploy/{verification-broker.example.json,verification-browser.Dockerfile,
  verification-node.Dockerfile}
docs/{ACCEPTANCE_TESTS.md,ARCHITECTURE.md,DATA_MODEL.md,DEPLOYMENT_PLAN.md,
  EVENT_SCHEMA.md,SECURITY_MODEL.md,STATUS.md,VERIFICATION_EXECUTOR.md}
docs/development/phase-03-handoff.md
orchestrator/app/jarvis_orchestrator/{admin.py,main.py}
orchestrator/app/jarvis_orchestrator/runtime/{composition.py,configuration.py}
orchestrator/app/jarvis_orchestrator/verification/{executor.py,isolated_executor.py,
  isolation_bootstrap.py,isolation_broker.py,isolation_cli.py,isolation_contract.py,
  parsers.py,profiles.py,repository_context.py,runtime.py,service.py}
orchestrator/app/jarvis_orchestrator/workflows/validation.py
packages/contracts/{generated/*,src/jarvis_contracts/*}
packages/persistence/src/jarvis_persistence/models.py
scripts/verify.sh
tests/fixtures/phase-03-full-stack/*
tests/integration/{test_isolation_broker.py,test_phase_03_api.py}
tests/unit/{test_isolation_contract.py,test_phase_03_profiles.py}
web/src/app/(control)/{profiles/page.tsx,registry/page.tsx}
web/src/{components/*,lib/api/runtime.ts}
web/tests/e2e/m2c-shell.spec.ts
```

The exact list is available with
`git diff --name-only cb196b3bd5f55f557c4b8b2c85184be017487eee..HEAD`.
The deployment remains side-by-side at `/opt/jarvis-v1`; `/opt/jarvis` and the
legacy worker environment were not touched.

## LOCALLY VERIFIED

- `ruff format --check`, `ruff check`, and strict `mypy` passed; mypy reported
  `Success: no issues found in 255 source files`.
- Focused Phase 3/profile regressions passed: `86 passed, 6 skipped`. The skips
  were five PostgreSQL cases and one real-container case unavailable on this host.
- Full non-integration Python execution passed: `689 passed, 24 skipped, 200
  deselected`.
- The normal `scripts/verify.sh` rerun reached `703 passed, 10 skipped, 201
  deselected`, then failed at the unchanged 80% coverage gate with 52.86%. This
  is not recorded as a whole-gate pass: `TEST_DATABASE_URL` is absent, so the
  database integration suite that supplies the remaining exercised lines did not
  run. The threshold was not weakened.
- Generated JSON Schema, integrated OpenAPI, and TypeScript contracts are current.
  Prettier, ESLint, TypeScript, and all `14` Vitest files / `54` tests passed.
  The Next.js production build passed and contains `/profiles`; npm audit reported
  zero vulnerabilities.
- Mocked Chromium acceptance passed `7 passed, 6 skipped` using one worker, with
  no serious console errors; the skipped paths require the absent database runner.
- The Phase 3 fixture installed from its lockfile, built three assets, passed two
  Python unit tests and one Node unit test, and passed one Playwright journey that
  proves blank-form rejection, create, persisted reload, follow-on completion,
  and a second persisted reload.
- The repository secret scan was clean. Local Docker is unavailable, so real
  verifier-container isolation, the new Node/browser images, PostgreSQL migration
  roundtrip/roles, and database-backed API/browser paths are not inferred from
  protocol or mocked evidence.

## CI VERIFIED

UNVERIFIED. Publication and exact-tip CI had not occurred when this handoff was
written. A successful draft-PR check must cover PostgreSQL 16 migration
roundtrip/drift/roles, full Python coverage, generated contracts, frontend build
and audit, the mandatory worker protocol fixture, real verifier-container denial
canaries, the Phase 3 full-stack fixture, and database-backed browser paths. Only
a run whose checked SHA equals the final branch SHA can close this section.

## LIVE VERIFIED

UNVERIFIED. No explicitly authorized Jarvis-Core/Jarvis-Worker V1 staging target
was used. No deployment, real-mode full-stack mission, follow-on mission, paid
provider call, public preview, or soak is claimed.

## Remaining gates and exact next action

Push `phase/03-web-project-profiles`, open or update its draft PR, and require the
repository verify workflow to pass against the exact branch tip. If it fails,
fix on this branch and repeat exact-tip CI. Once green, use an explicitly
authorized V1 staging target under `/opt/jarvis-v1` to run a real-mode full-stack
mission and the follow-on change through build, non-empty unit, independent
review, Playwright acceptance, and combined integration while retaining profile,
dependency, source, report, denial-canary, cleanup, event, and restart evidence.
Keep `/opt/jarvis`, the legacy worker, repository protections, and main untouched;
do not merge or deploy from this handoff.
