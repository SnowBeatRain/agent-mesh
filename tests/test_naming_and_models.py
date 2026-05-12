import pytest
from pydantic import ValidationError

from agentmesh.models.manifest import AssetManifest
from agentmesh.utils.naming import validate_skill_name


def test_skill_name_validation_accepts_expected_names():
    assert validate_skill_name("uniapp-skill") == "uniapp-skill"
    assert validate_skill_name("a_b9") == "a_b9"


def test_skill_name_validation_rejects_bad_names():
    for name in ["Bad", "-bad", "bad.name", "", "a" * 65]:
        with pytest.raises(ValueError):
            validate_skill_name(name)


def test_asset_manifest_requires_valid_skill_name():
    with pytest.raises(ValidationError):
        AssetManifest(schema="agentmesh.asset/v1", kind="skill", name="Bad.Name", description="x")
