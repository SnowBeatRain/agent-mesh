from __future__ import annotations

import json
from dataclasses import asdict
from typing import Annotated

import typer
from rich.console import Console

from agentmesh.audit.engine import AuditEngine
from agentmesh.cli.envelope import build_envelope
from agentmesh.config.loader import (
    registry_skills_root,
    resolve_agentmesh_home,
)
from agentmesh.policy.service import evaluate_findings

_cli_response = build_envelope
console = Console()
app = typer.Typer(help="安全审计命令。")


def _audit_report(
    registry: str | None,
    kinds: set[str] | None,
    json_output: bool,
    include_policy: bool = False,
    command: str = "audit all",
) -> None:
    home = resolve_agentmesh_home(registry)
    root = registry_skills_root(home)
    findings = AuditEngine().audit_path(root, kinds)
    report = {"findings": [asdict(f) for f in findings]}
    if include_policy:
        report["policy"] = evaluate_findings(root, findings).to_dict()
    if json_output:
        if command == "audit all":
            status = "blocked" if report.get("policy", {}).get("allowed") is False else "ok"
            typer.echo(
                json.dumps(
                    _cli_response(
                        schema="agentmesh.audit-all/v1",
                        command="audit all",
                        status=status,
                        data={"report": report},
                        warnings=[] if status == "ok" else ["Audit policy has blocked findings."],
                        errors=[] if status == "ok" else ["Audit policy is not allowed."],
                        next_steps=[]
                        if status == "ok"
                        else ["Review blocked findings before running apply operations."],
                    ),
                    ensure_ascii=False,
                )
            )
        else:
            typer.echo(json.dumps(report, ensure_ascii=False))
        return
    console.print(json.dumps(report, ensure_ascii=False, indent=2))


@app.command("all")
def audit_all(
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    _audit_report(registry, None, json_output, include_policy=True)


@app.command("secrets")
def audit_secrets(
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    _audit_report(registry, {"secret"}, json_output, include_policy=True, command="audit secrets")


@app.command("scripts")
def audit_scripts(
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    _audit_report(
        registry, {"dangerous-script"}, json_output, include_policy=True, command="audit scripts"
    )


@app.command("platform-refs")
def audit_platform_refs(
    registry: Annotated[str | None, typer.Option(help="AgentMesh home/registry 根目录。")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    _audit_report(
        registry, {"platform-ref"}, json_output, include_policy=False, command="audit platform-refs"
    )
