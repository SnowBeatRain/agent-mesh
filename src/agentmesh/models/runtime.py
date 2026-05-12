import dataclasses
from dataclasses import dataclass
from pathlib import Path

ADAPTER_CONTRACT_V1_SLOTS = {
    "detect": "implemented",
    "scan": "implemented",
    "capabilities": "implemented",
    "classify": "unsupported",
    "render_plan": "unsupported",
    "validate_projection": "unsupported",
    "audit_hints": "unsupported",
}

CONTRACT_SCHEMA = "agentmesh.adapter-contract/v1"
CAPABILITIES_SCHEMA = "agentmesh.adapter-capabilities/v1"
UNSUPPORTED_REASON_DEFAULT = "adapter contract v1 slot declared but not implemented"


@dataclass(frozen=True)
class RuntimeInfo:
    name: str
    installed: bool
    skill_dir: Path
    mode: str
    writable: bool
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class AdapterCapabilities:
    name: str
    skill_dir: Path
    mode: str
    writable: bool
    capabilities: tuple[str, ...]
    safety_guards: tuple[str, ...]
    protected_paths: tuple[str, ...] = ()
    schema: str = CAPABILITIES_SCHEMA

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "name": self.name,
            "skill_dir": str(self.skill_dir),
            "mode": self.mode,
            "writable": self.writable,
            "capabilities": list(self.capabilities),
            "safety_guards": list(self.safety_guards),
            "protected_paths": list(self.protected_paths),
        }


@dataclass(frozen=True)
class AdapterContract:
    """Formalized adapter contract declaration (schema: agentmesh.adapter-contract/v1)."""

    name: str
    skill_dir: Path
    mode: str
    writable: bool
    capabilities: tuple[str, ...]
    safety_guards: tuple[str, ...]
    protected_paths: tuple[str, ...] = ()
    schema: str = CONTRACT_SCHEMA
    contract_version: str = "v1"
    slots: dict[str, str] = dataclasses.field(
        default_factory=lambda: dict(ADAPTER_CONTRACT_V1_SLOTS)
    )
    write_operations_enabled: bool = False
    network_required: bool = False
    unsupported_reason: str = UNSUPPORTED_REASON_DEFAULT

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "name": self.name,
            "skill_dir": str(self.skill_dir),
            "mode": self.mode,
            "writable": self.writable,
            "capabilities": list(self.capabilities),
            "safety_guards": list(self.safety_guards),
            "protected_paths": list(self.protected_paths),
            "contract_version": self.contract_version,
            "slots": dict(self.slots),
            "write_operations_enabled": self.write_operations_enabled,
            "network_required": self.network_required,
            "unsupported_reason": self.unsupported_reason,
        }
