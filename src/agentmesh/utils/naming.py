import re

_SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def validate_skill_name(name: str) -> str:
    if not _SKILL_NAME_RE.fullmatch(name):
        raise ValueError("skill 名称必须匹配 ^[a-z0-9][a-z0-9_-]{0,63}$")
    return name
