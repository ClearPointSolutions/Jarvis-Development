# Jarvis V1 Security Model

Status: normative V1 threat model and controls

## 1. Security posture

Mission Control is an administrative code-execution control plane. V1 is private-LAN/VPN only, authenticated, least-privileged, deny-by-default, and designed so compromise of the browser does not directly yield database, SSH, model-provider, GitHub, or host credentials.

No public exposure, unauthenticated shell endpoint, secret-bearing frontend bundle, or trust in model/worker output is acceptable.

## 2. Assets

- Owner account, session and CSRF tokens.
- Provider/GitHub credentials, SSH private keys, database credentials, password hashes, and TLS keys.
- Source repositories, branches, commits, diffs, and proprietary prompts/artifacts.
- Workflow/configuration integrity, approval decisions, event/audit history, and LangGraph checkpoints.
- Jarvis-Core, Jarvis-Worker-01, AI server, database, and downstream GitHub repositories.
- Ability to execute commands, write files, push code, deploy, restart services, or use paid APIs.

## 3. Trust boundaries and threats

| Boundary | Principal threats | Required controls |
|---|---|---|
| Browser -> reverse proxy/API | credential theft, CSRF, XSS, brute force, IDOR, replay | TLS/private network, secure session cookie, CSRF/origin validation, CSP, rate limits, object authorization, idempotency |
| API -> database | injection, excessive privilege, event tampering | parameterized ORM/SQL, separate roles, migrations, append-only grants/trigger, backup/audit |
| Orchestrator -> providers/GitHub | secret leakage, SSRF, excessive scopes, cost abuse | server-only secret resolution, egress allowlists, typed adapters, quotas/policy, least scopes |
| Orchestrator -> Worker-01 | MITM, command injection, privilege escalation, duplicate effects | pinned host key, dedicated key, fixed commands/quoting, leases/fencing/idempotency, approvals |
| Models/workers/repos -> system | prompt injection, malicious output/files/logs, path traversal | treat all output as data, schema validation, sandbox/worktree boundaries, path containment, escaping/redaction |
| Artifact download/render | stored XSS, MIME confusion, secret exposure | authorization, safe content disposition, MIME allowlist/sniff prevention, CSP/sandbox, redaction |
| Internal service network | lateral movement, exposed ports | Compose network isolation, loopback/private bindings, no Docker socket, non-root/read-only containers |

## 4. Authentication

- Initial owner creation is an explicit local CLI/bootstrap operation and becomes disabled after first setup unless reset locally.
- Passwords are hashed with Argon2id using implementation-time OWASP-aligned parameters and per-password salts. Login responses do not reveal account existence.
- Login is rate-limited by account and network source with audited exponential delay. Repeated failures do not log submitted passwords.
- Sessions use at least 256 bits of random entropy. The browser receives an opaque cookie; PostgreSQL stores only its hash.
- Cookie flags: `HttpOnly`, `Secure` under HTTPS, `SameSite=Strict`, narrow path, no domain widening. Session rotation occurs on login/privilege-sensitive changes.
- Idle and absolute expiry are configurable. Logout/revocation is immediate server-side. Sensitive actions may require recent authentication.

## 5. Authorization and CSRF

Every endpoint performs server-side authorization on the target object's owner/scope and typed action. V1 role is `owner`; read-only display access, if enabled, uses a separate least-privileged role/session.

State-changing methods require:

- a valid same-origin session;
- exact allowed `Origin`/`Host` checks;
- a per-session CSRF token in a custom header, not a URL;
- JSON content type and endpoint schema;
- idempotency key for commands/effects;
- permission-policy decision and audit.

SSE is GET-only, same-origin, cookie-authenticated, origin-checked, and returns only authorized redacted events. CORS is disabled by default. Clickjacking is blocked with CSP `frame-ancestors 'none'` (or a narrowly documented display exception).

## 6. Browser and frontend controls

- Strict Content Security Policy with nonce/hash for scripts, no unsafe inline script/eval, and explicit connect/image/style sources.
- React output is escaped; Markdown is sanitized with raw HTML disabled. ANSI terminal output is rendered as text through a safe parser.
- No secret is embedded in `NEXT_PUBLIC_*`, build args, source maps, hydration data, browser storage, URL/query strings, or error reporting.
- Authentication tokens are not stored in `localStorage` or readable JavaScript cookies.
- Artifact previews use sandboxed rendering or forced download for active content; `X-Content-Type-Options: nosniff` and safe `Content-Disposition` apply.
- UI confirmation is not authorization. Every backend action independently evaluates policy.

## 7. Secret boundaries

```text
Browser / Next.js:              no infrastructure secrets
FastAPI:                        session/CSRF secrets; artifact access; no routine worker/provider use
Orchestrator:                   resolves provider, SSH, GitHub refs just-in-time
PostgreSQL:                     opaque secret refs and configured status, never values
Worker-01:                      only its local runner/model secrets and task-scoped lease/request
Logs/events/traces/artifacts:   redacted before persistence/export
```

Production secrets are injected as restrictive read-only files, Docker secrets, or environment references managed outside Git. `.env.example` contains names/placeholders only. File ownership/mode limits access to the service identity. Secret rotation updates a reference/version and invalidates relevant connection pools; no historical snapshot contains the value.

Secret values known at runtime seed exact-value redaction in addition to structural rules. Redaction occurs before event/database/log/trace writes. Security tests use synthetic canaries and scan Git history, built frontend assets, API payloads, events, artifacts, and container logs.

## 8. Command and worker safety

- There is no general `/shell`, terminal input, arbitrary command, arbitrary SSH, or arbitrary URL endpoint.
- Commands come only from versioned validated workflow/task specs and typed adapter operations. Preferred form is argv; legacy shell strings are constrained, redacted, length/time limited, and never sourced directly from a browser field.
- Execution cwd is an adapter-resolved repository/worktree root. Paths are resolved and checked for containment; symlink escapes and credentialed Git URLs are rejected.
- Worker SSH uses a dedicated key, pinned `known_hosts`, fixed configured program paths, bounded output/runtime, and a restricted account where feasible.
- Worker-01 currently has passwordless sudo. Default permission policy denies privileged commands. Any permitted privileged action requires a typed action schema, narrow command policy, durable approval, and auditable result.
- Process cancellation targets only the recorded invocation process group. Cleanup/deletion is a separate approval-controlled effect.

The long-term hardening recommendation is a dedicated restricted worker service account/container and command broker. V1 staging must document the residual sudo risk.

## 9. Approval security

Policy decisions are `allow`, `deny`, or `require_approval`. Unknown actions deny. Default approval-required actions include delete, remote push/PR when configured, merge, deployment, service restart, firewall/system changes, privileged command, external communication, paid purchase, and destructive database action.

Routine calls to an explicitly enabled paid provider may be pre-authorized only inside configured per-call/per-run request, token, and cost ceilings. Exceeding a ceiling, enabling a new paid route, or performing a purchase requires denial or durable approval according to policy.

Approval requests show redacted exact target, action, reason, risk, and parameter digest. The owner decision is authenticated, CSRF protected, idempotent, append-only, and bound to run/node/interrupt/effect request digest. A grant cannot authorize changed parameters, another run, or an expired/cancelled request. The protected effect checks the grant again immediately before dispatch.

LangGraph interrupt payloads contain only JSON-safe IDs/summaries. Work before the interrupt is read-only or idempotent because the node restarts on resume.

## 10. Provider and network safety

- Provider/base URLs are configuration but restricted to approved schemes, hosts/IP ranges, ports, and DNS behavior. Redirects are disabled or revalidated to prevent SSRF.
- Local endpoints such as Ollama are explicitly allowlisted. Cloud egress is explicit per provider and project data policy.
- HTTP clients set connect/read/total timeouts, response/body limits, TLS verification, and sanitized errors.
- GitHub uses a GitHub App with minimal repository permissions when available. The existing machine account/`gh` secret may be supported in staging through a server-side adapter, scoped to configured organizations/repositories and never exposed. GitHub recommends selecting only the minimum GitHub App permissions: [GitHub App permissions](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/choosing-permissions-for-a-github-app).
- Webhooks, if later accepted, require signature verification, replay protection, event allowlists, and delivery-ID deduplication. Polling is sufficient for initial CI status.

## 11. Database and service hardening

- Dedicated V1 database and roles: migrator (DDL), API (authorized CRUD/read events), orchestrator (runtime/effect/event writer), and optional read-only diagnostics.
- Event/audit tables deny application update/delete; backups are access controlled and restore-tested.
- Containers run as non-root, drop capabilities, use read-only roots and tmpfs where practical, set resource limits, and mount only required paths/secrets.
- Web has no secret or host mounts. API has no SSH key. Orchestrator does not expose a public port.
- Docker socket is not mounted. Host/service metrics use narrow collectors/endpoints rather than unrestricted Docker control.
- Dependency lockfiles, vulnerability/license scanning, provenance-aware images, and pinned base image digests are release gates.

## 12. Audit and incident response

Security-relevant facts are append-only normalized events: auth attempts, session changes, policy decisions, approvals, config publication, secret-reference changes, commands, worker effects, GitHub actions, redaction triggers, and administrative exports.

Audit records use database time, actor/session, request correlation, target, outcome, and client metadata without credentials. Clock/retention/backup policy is documented. The operator can revoke all sessions, disable workers/providers/routes, drain the orchestrator, cancel runs, rotate secrets, and export a redacted incident bundle.

## 13. Availability and abuse controls

Bounded request bodies, pagination, SSE connection limits, per-user job/call quotas, workflow node/fanout limits, worker capacity, provider budgets, command timeouts, log rate limits, artifact quotas, and circuit breakers prevent accidental resource exhaustion. Queue priority does not bypass authorization or capacity.

## 14. Security acceptance gates

- Unauthenticated access is denied except minimal liveness; authorization/IDOR and CSRF tests pass.
- Synthetic secrets never appear in API/SSE, database events, artifacts, logs, traces, screenshots, frontend output, or Git history.
- Workflow predicates/config cannot execute arbitrary code or reach an arbitrary URL/path.
- Browser cannot submit a shell command; protected effects fail without a matching live approval.
- SSH rejects host-key mismatch and path/slug traversal.
- Stale lease results and duplicate approval/command/effect requests cannot advance state twice.
- Legacy `/opt/jarvis` is never mounted writable or mutated by V1 deployment.

## 15. Residual risks

- The existing OpenHands worker is highly privileged and not intrinsically idempotent; isolation plus the V1 invocation wrapper and staging reconciliation tests are required before production trust.
- Model/repository prompt injection cannot be eliminated. Typed tools, least privilege, approval, and deterministic verification limit impact.
- Same-database checkpoints and events are not one distributed transaction with arbitrary external effects. The effect ledger and fencing provide recovery, not magical exactly-once execution.
- Single-owner authentication lacks enterprise identity controls. Public or multi-user exposure requires a new identity/authorization review.
