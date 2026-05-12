"""ModelMesh 数据模型：统一模型配置 schema。"""

from __future__ import annotations

from dataclasses import dataclass

MODEL_CONFIG_SCHEMA = "agentmesh.model-config/v1"


@dataclass(frozen=True)
class ModelConfig:
    """统一的模型配置表示（schema: agentmesh.model-config/v1）。"""

    agent: str
    default_model: str
    provider: str = ""
    base_url: str = ""
    context_length: int | None = None
    available_models: tuple[str, ...] = ()
    schema: str = MODEL_CONFIG_SCHEMA

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "agent": self.agent,
            "default_model": self.default_model,
            "provider": self.provider,
            "base_url": self.base_url,
            "context_length": self.context_length,
            "available_models": list(self.available_models),
        }


@dataclass(frozen=True)
class ModelDiff:
    """两个 Agent 之间某个配置字段的差异。"""

    field: str
    agent_a: str
    value_a: object
    agent_b: str
    value_b: object

    def to_dict(self) -> dict[str, object]:
        return {
            "field": self.field,
            "agent_a": self.agent_a,
            "value_a": self.value_a,
            "agent_b": self.agent_b,
            "value_b": self.value_b,
        }
