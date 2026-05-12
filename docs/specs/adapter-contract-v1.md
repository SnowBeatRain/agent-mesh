# Adapter Contract v1

Status: minimal local contract declaration. This is not a new writer, renderer, HTTP server, or runtime auto-load implementation.

## Goal

`agentmesh.adapter-contract/v1` gives every AgentMesh adapter a shared way to describe which local integration slots exist today and which slots are only declared for future work.

A local CLI consumer can inspect the declaration with:

```bash
am agents contract --json
```

This command only returns the declaration. It does not enable writes, network access, HTTP serving, or Dashboard UI.

This keeps P2 lightweight and local-first: callers can ask each adapter what it supports without enabling hidden writes, network access, or target-agent native LoadPlan consumption.

## Current v1 Slots

| Slot | Current status | Notes |
| --- | --- | --- |
| `detect` | `implemented` | Read-only local runtime detection. |
| `scan` | `implemented` | Read-only local skill scan. |
| `capabilities` | `implemented` | Adapter capabilities and safety guards. |
| `classify` | `unsupported` | Declared but not implemented in v1. |
| `render_plan` | `unsupported` | Declared but not implemented in v1. Does not write files. |
| `validate_projection` | `unsupported` | Declared but not implemented in v1. |
| `audit_hints` | `unsupported` | Declared but not implemented in v1. |

Unsupported slots use:

```text
adapter contract v1 slot declared but not implemented
```

## Safety Rules

The v1 contract declaration is read-only:

- `write_operations_enabled` is `false`.
- `network_required` is `false`.
- It does not call apply, sync apply, install, delete, or mutate registry state.
- It does not start an HTTP server.
- It does not implement Dashboard UI.
- It does not claim Runtime Auto-Load is production-ready.
- It does not claim target agents natively consume LoadPlan.

Adapter-specific safety values must remain visible:

- Codex keeps `.system` in `protected_paths` and `exclude_system_skills` in `safety_guards`.
- Claude Code keeps `mode: export-only`, `writable: false`, and `no_auto_install`.

## Example Shape

```json
{
  "schema": "agentmesh.adapter-contract/v1",
  "contract_version": "v1",
  "name": "codex",
  "mode": "read-write",
  "writable": true,
  "capabilities": ["detect", "scan", "import", "dry_run_sync"],
  "safety_guards": ["path_guard", "dry_run_default", "secret_redaction", "exclude_system_skills"],
  "protected_paths": [".system"],
  "slots": {
    "detect": "implemented",
    "scan": "implemented",
    "capabilities": "implemented",
    "classify": "unsupported",
    "render_plan": "unsupported",
    "validate_projection": "unsupported",
    "audit_hints": "unsupported"
  },
  "write_operations_enabled": false,
  "network_required": false,
  "unsupported_reason": "adapter contract v1 slot declared but not implemented"
}
```
