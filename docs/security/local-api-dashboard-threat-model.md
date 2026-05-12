# Local API / Dashboard Threat Model

> Status: design guardrail for the existing Local API contract handler. HTTP server is not implemented. Dashboard UI is not implemented.

## Scope

This document defines the minimum security boundary for any future Local API HTTP server and read-only Dashboard work in AgentMesh.

Current implementation state:

- Local API is a Python read-only contract handler, not a network service.
- HTTP server is not implemented.
- Dashboard UI is not implemented.
- Runtime Auto-Load remains alpha and only has LoadPlan reader / generated loader groundwork.
- target agents do not natively consume LoadPlan in real runtime sessions.

The threat model applies before adding any listener, browser UI, or transport around `agentmesh.local_api.service.handle_readonly_request()`.

## Assets to Protect

- Local skill registries and target agent skill directories.
- AgentMesh configuration and generated LoadPlan files.
- Local file paths, usernames, home directory names, and repository layout.
- CLI safety boundaries such as dry-run defaults, Codex `.system` protection, and Claude Code export-only mode.
- Credentials, API keys, tokens, passwords, environment variables, and connection strings. Responses and logs must contain no secrets.

## Trust Boundaries

### Current boundary

The current contract handler is in-process only. It does not bind a port, accept browser traffic, or expose external access.

### Future HTTP boundary

Any future HTTP server must be localhost-only by default:

- Bind address must default to 127.0.0.1.
- Binding to `0.0.0.0`, LAN addresses, public addresses, or Unix socket paths shared outside the current user session is out of scope for the alpha design.
- Remote bind requires an explicit authenticated design review.
- The server must be disabled by default and only started by an explicit CLI command or user action.

### Future Dashboard boundary

Dashboard must consume the same read-only contract handler as CLI/API tests. It must not bypass Local API allowlists by importing lower-level mutating services directly.

## Initial Route Policy

Use a read-only route allowlist. Only these routes are allowed initially:

- GET /health
- GET /doctor
- GET /agents

All other paths must return an error envelope. All non-GET methods are blocked, including POST, PUT, PATCH, DELETE, OPTIONS mutations, and any tunneling header that attempts to override the method.

No endpoint may call apply, sync apply, install, delete, or mutate registry state.

## Response Contract

Every response must use agentmesh.local-api-response/v1.

The envelope must keep the existing shape:

- `schema`
- `command`
- `status`
- `data`
- `warnings`
- `errors`
- `next_steps`

Errors must be represented through the same error envelope rather than stack traces or raw exception strings.

## CORS Policy

CORS must be deny-by-default.

Recommended initial rules:

- Do not emit `Access-Control-Allow-Origin: *`.
- If the Dashboard is served by the same localhost server, prefer same-origin and no broad CORS.
- If a separate localhost Dashboard origin is required, allow only exact configured localhost origins.
- Do not allow credentials across origins unless there is an explicit authenticated design.
- Preflight requests may report allowed read-only methods, but non-GET methods remain blocked.

## Path Redaction

path redaction is required for any UI or log surface that does not strictly need raw local paths.

Guidelines:

- Replace the user home directory with `~` where possible.
- Avoid exposing absolute registry paths in browser-visible errors unless the user explicitly requests diagnostics.
- Do not reveal target agent private directories beyond the normalized adapter name and documented protected path labels such as `.system`.
- Do not include generated file contents in API responses by default.

## Error Envelope and Log Redaction

error envelope behavior:

- Unknown routes return `status: error` with a stable message.
- Blocked methods return `status: blocked` with a stable message.
- Internal errors must be mapped to sanitized error messages before they reach the API response.

log redaction behavior:

- Do not log secrets, environment variable values, tokens, API keys, passwords, cookies, authorization headers, or connection strings.
- Do not log full request bodies for future write endpoints unless a separate safe logging design exists.
- Prefer route, method, status, schema, and request id over raw payloads.
- Local paths in logs should be redacted or normalized unless verbose diagnostics are explicitly enabled by the user.

## Dashboard Design Constraints

Dashboard is read-only for the alpha phase.

- Dashboard must consume the same read-only contract handler.
- Dashboard may display health, doctor status, and adapter capability summaries.
- Dashboard must not expose apply/sync/install/delete controls.
- Dashboard must preserve Codex `.system` protected path semantics.
- Dashboard must preserve Claude Code export-only and no_auto_install safety guards.
- Dashboard must label Runtime Auto-Load as alpha groundwork, not production-ready automation.
- Dashboard must label LoadPlan target-agent consumption as not native until real session integration exists.

## Non-Goals for This Phase

- no write operations.
- No remote multi-user API.
- No unauthenticated LAN or public server.
- No browser-triggered apply/sync/install/delete.
- No credential management UI.
- No production Runtime Auto-Load claim.
- No claim that target agents natively consume LoadPlan.

## Acceptance Criteria Before Implementing HTTP Server

- Bind address must default to 127.0.0.1.
- Server startup must be disabled by default.
- Remote bind requires an explicit authenticated design review.
- Only GET /health, GET /doctor, and GET /agents are allowed initially.
- Every response must use agentmesh.local-api-response/v1.
- Dashboard must consume the same read-only contract handler.
- No endpoint may call apply, sync apply, install, delete, or mutate registry state.
- CORS must be deny-by-default or exact localhost-origin allowlist only.
- Logs and responses must contain no secrets.
- Browser-visible paths must use path redaction unless explicit diagnostics are requested.
- Error handling must use the stable error envelope.

## Verification Hooks

Existing tests should continue to pass:

```bash
ruff check src/ tests/
python3 -m pytest tests -q
ruff format --check src/ tests/
```

Before adding an HTTP server, add tests that prove:

- Non-localhost binding is rejected by default.
- Server startup is explicit and disabled by default.
- Non-GET methods are blocked at transport and handler layers.
- CORS never returns wildcard origin.
- Sensitive values are redacted from errors and logs.
- Dashboard route code cannot call mutating services.
