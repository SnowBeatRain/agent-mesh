# Update Flow Design: M7 Read-only Update Check

## Goal

M7 adds a local-only preflight command for future skill updates:

```bash
am skills update-check
am skills update-check --json
```

The command answers: “which registry skills have enough source identity for a future update flow?” It does not decide trust, download remote content, or apply changes.

## Non-goals

- No network access.
- No downloads.
- No implicit token or credential reads.
- No update apply.
- No marketplace or signature trust model.

## Source identity

Package imports record minimal source identity in `agentmesh.asset.yaml`:

```yaml
source:
  kind: agentmesh-package
  package_path: /path/to/package.zip
  package_sha256: sha256:<zip-sha256>
  imported_at: <timestamp>
  original_hash: <imported-skill-tree-hash>
```

Manual/native imports without this block remain valid, but update-check treats them as skipped until a future migration supplies comparable identity.

## Status matrix

| Status | Condition | Meaning |
| --- | --- | --- |
| `candidate` | Reserved for future local/remote comparison that proves a possible update. | M7 never emits this. |
| `unknown` | Supported source identity exists, but M7 cannot compare because network is disabled. | The skill is update-flow eligible later. |
| `skipped` | No source identity or unsupported source kind. | The skill cannot participate in update-check yet. |

Every item includes `remote_checked: false` in M7.

## JSON contract

`skills update-check --json` uses `agentmesh.update-check/v1` envelope. The payload includes:

```json
{
  "network": "disabled",
  "summary": {"total": 1, "candidate": 0, "unknown": 1, "skipped": 0},
  "skills": [
    {
      "name": "demo-skill",
      "status": "unknown",
      "reason": "network-disabled",
      "remote_checked": false,
      "source": {
        "kind": "agentmesh-package",
        "package_path": "/path/to/package.zip",
        "package_sha256": "sha256:...",
        "imported_at": "...",
        "original_hash": "..."
      }
    }
  ]
}
```

## Safety

The service only reads registry manifests under the AgentMesh home. It does not inspect remote URLs, open package paths, access credentials, or mutate registry/runtime state.
