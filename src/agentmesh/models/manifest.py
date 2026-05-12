from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agentmesh.utils.naming import validate_skill_name


class AssetManifest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_: Literal["agentmesh.asset/v1"] = Field(default="agentmesh.asset/v1", alias="schema")
    kind: Literal["skill"] = "skill"
    name: str
    description: str = ""
    entrypoint: str = "SKILL.md"
    compatibility: dict[str, str] = Field(default_factory=dict)
    platform: dict[str, dict] = Field(default_factory=dict)
    sync: dict = Field(default_factory=lambda: {"default_mode": "copy", "allow_symlink": False})
    security: dict = Field(
        default_factory=lambda: {
            "allow_scripts": False,
            "requires_secrets": False,
            "network_access": False,
            "risk": "low",
        }
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return validate_skill_name(value)


class SkillManifest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_: Literal["agentmesh.skill/v1"] = Field(default="agentmesh.skill/v1", alias="schema")
    name: str
    description: str = ""
    entrypoint: str = "SKILL.md"

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return validate_skill_name(value)
