from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path

SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?[^\s'\"]+"),
]
SCRIPT_PATTERNS = ["curl | bash", "wget | sh", "eval ", "sudo ", "rm -rf"]
PLATFORM_REF_PATTERNS = [
    re.compile(r"~?/\.hermes(?:/|\b)"),
    re.compile(r"~?/\.openclaw(?:/|\b)"),
    re.compile(r"~?/\.codex(?:/|\b)"),
    re.compile(r"~?/\.claude(?:/|\b)"),
]


@dataclass(frozen=True)
class Finding:
    severity: str
    kind: str
    path: str
    line: int
    message: str


def _redact_line(line: str) -> str:
    redacted = line
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(lambda m: f"{m.group(1)}=<redacted>", redacted)
    return redacted


class AuditEngine:
    def audit_path(self, root: Path, kinds: set[str] | None = None) -> list[Finding]:
        findings: list[Finding] = []
        if not root.exists():
            return findings
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            for idx, line in enumerate(lines, start=1):
                if any(pattern.search(line) for pattern in SECRET_PATTERNS):
                    findings.append(
                        Finding("block", "secret", str(path), idx, "疑似密钥：<redacted>")
                    )
                if any(pattern in line for pattern in SCRIPT_PATTERNS):
                    findings.append(
                        Finding("warn", "dangerous-script", str(path), idx, "疑似危险脚本模式")
                    )
                if any(pattern.search(line) for pattern in PLATFORM_REF_PATTERNS):
                    findings.append(
                        Finding(
                            "info",
                            "platform-ref",
                            str(path),
                            idx,
                            f"发现平台路径引用：{_redact_line(line)}",
                        )
                    )
        if kinds is not None:
            findings = [finding for finding in findings if finding.kind in kinds]
        return findings

    def report(self, root: Path, kinds: set[str] | None = None) -> dict:
        return {"findings": [asdict(finding) for finding in self.audit_path(root, kinds)]}
