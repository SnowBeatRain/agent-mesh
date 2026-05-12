# Prompt Target State / Disable Design

## Scope

M6 adds a small PromptMesh lifecycle slice:

```bash
am prompts status --target codex
am prompts status --target codex --json
am prompts disable --target codex --dry-run
am prompts disable --target codex --apply
```

The goal is to answer: “which prompt does AgentMesh believe is active for this target, what live file is involved, and can AgentMesh safely stop declaring management for that target?”

## Non-goals

- No prompt stack or composition.
- No Gemini / OpenCode target support in M6.
- No deletion of user live prompt files.
- No forced repair of drifted live files.
- No network access, token reads, or runtime process control.

## Target model

M6 uses the existing PromptMesh target mapping for supported targets:

| target | live prompt |
| --- | --- |
| `codex` | `AGENTS.md` |
| `claude-code` | `CLAUDE.md` |
| `hermes` | `AGENTS.md` |
| `openclaw` | `AGENTS.md` |

Unsupported targets return a structured error and do not write state.

## `prompts status`

`prompts status` is read-only. It may read registry prompt state and the target live file, but it must not write registry, target files, backups, or history.

The status output includes:

- `target`
- `live_path`
- whether the live file exists
- whether AgentMesh state marks the target as enabled
- active prompt name, when known
- whether live content appears AgentMesh-managed
- drift status based on the recorded live hash when available

If state says enabled but has no recorded live hash, status must return an explicit unknown state such as `drift_unknown` / `state-hash-missing` rather than claiming clean.

JSON output uses:

```text
agentmesh.prompts-status/v1
```

The core payload lives under `data.status`.

## `prompts disable`

`prompts disable` is dry-run by default. Without `--apply`, it only returns the planned state change and next step.

With `--apply`, it updates AgentMesh prompt target state so the target is no longer declared enabled. It does not delete, truncate, or rewrite the live prompt file. This is important because the live prompt may contain user-authored content or a previously imported snapshot.

JSON output uses:

```text
agentmesh.prompts-disable/v1
```

Expected statuses:

- `planned` for dry-run
- `applied` when state is updated
- `error` for unsupported target or invalid state inputs

## Safety rules

- Dry-run must not mutate files.
- Apply mutates only AgentMesh prompt state, not live prompt content.
- Unsupported targets fail before writing.
- Drift is reported, not silently repaired.
- Prompt disable is state management, not deletion. Do not implement it as `rm ~/.codex/AGENTS.md` or equivalent.

## Testing expectations

M6 tests should cover:

- status for enabled target
- status for disabled / missing state
- drift unknown when state hash is missing
- disable dry-run does not write
- disable apply updates state but preserves live file
- unsupported target returns structured error
- JSON schema / command fields are stable
