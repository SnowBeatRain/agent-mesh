from __future__ import annotations

from pathlib import Path

from agentmesh.audit.engine import AuditEngine
from agentmesh.services.registry_service import list_registry_skills
from agentmesh.utils.frontmatter import read_skill_document
from agentmesh.utils.yaml_io import read_yaml


def _finding(skill: str, severity: str, code: str, message: str, path: Path | None = None) -> dict:
    item = {"skill": skill, "severity": severity, "code": code, "message": message}
    if path is not None:
        item["path"] = str(path)
    return item


def validate_registry_skills(agentmesh_home: Path, target: str | None = None) -> dict:
    findings: list[dict] = []
    skills = list_registry_skills(agentmesh_home)
    for skill_dir in skills:
        skill_name = skill_dir.name
        entrypoint = skill_dir / "SKILL.md"
        manifest_path = skill_dir / "agentmesh.asset.yaml"

        if not entrypoint.exists():
            findings.append(
                _finding(skill_name, "error", "missing-entrypoint", "缺少 SKILL.md", entrypoint)
            )
        else:
            doc = read_skill_document(entrypoint)
            frontmatter_name = doc.metadata.get("name")
            if not frontmatter_name:
                findings.append(
                    _finding(
                        skill_name,
                        "error",
                        "missing-frontmatter-name",
                        "SKILL.md frontmatter 缺少 name",
                        entrypoint,
                    )
                )
            elif str(frontmatter_name) != skill_name:
                findings.append(
                    _finding(
                        skill_name,
                        "error",
                        "frontmatter-name-mismatch",
                        "SKILL.md frontmatter name 与目录名不一致",
                        entrypoint,
                    )
                )

        if not manifest_path.exists():
            findings.append(
                _finding(
                    skill_name,
                    "error",
                    "missing-manifest",
                    "缺少 agentmesh.asset.yaml",
                    manifest_path,
                )
            )
        else:
            manifest = read_yaml(manifest_path)
            if manifest.get("name") != skill_name:
                findings.append(
                    _finding(
                        skill_name,
                        "error",
                        "manifest-name-mismatch",
                        "manifest name 与目录名不一致",
                        manifest_path,
                    )
                )
            if manifest.get("kind") != "skill":
                findings.append(
                    _finding(
                        skill_name,
                        "error",
                        "manifest-kind-invalid",
                        "manifest kind 必须为 skill",
                        manifest_path,
                    )
                )

        for audit_finding in AuditEngine().audit_path(skill_dir):
            if audit_finding.severity == "block":
                findings.append(
                    _finding(
                        skill_name,
                        "error",
                        "audit-block",
                        audit_finding.message,
                        Path(audit_finding.path),
                    )
                )
            elif audit_finding.severity == "warn":
                findings.append(
                    _finding(
                        skill_name,
                        "warning",
                        "audit-warning",
                        audit_finding.message,
                        Path(audit_finding.path),
                    )
                )

    errors = sum(1 for item in findings if item["severity"] == "error")
    warnings = sum(1 for item in findings if item["severity"] == "warning")
    return {
        "ok": errors == 0,
        "target": target or "registry",
        "summary": {"skills": len(skills), "errors": errors, "warnings": warnings},
        "findings": findings,
    }
