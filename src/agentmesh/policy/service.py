from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from agentmesh.audit.engine import AuditEngine, Finding


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    blocked_count: int
    warning_count: int
    info_count: int
    reasons: list[dict]

    def to_dict(self) -> dict:
        return asdict(self)


def evaluate_findings(root: Path, findings: list[Finding] | None = None) -> PolicyDecision:
    audit_findings = findings if findings is not None else AuditEngine().audit_path(root)
    blocked = [finding for finding in audit_findings if finding.severity == "block"]
    warnings = [finding for finding in audit_findings if finding.severity == "warn"]
    infos = [finding for finding in audit_findings if finding.severity == "info"]
    return PolicyDecision(
        allowed=not blocked,
        blocked_count=len(blocked),
        warning_count=len(warnings),
        info_count=len(infos),
        reasons=[asdict(finding) for finding in audit_findings],
    )
