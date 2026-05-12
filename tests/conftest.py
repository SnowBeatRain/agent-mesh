from __future__ import annotations

import pytest

from agentmesh.config import loader


@pytest.fixture()
def fake_home(tmp_path, monkeypatch):
    monkeypatch.setattr(loader, "user_home", lambda: tmp_path)
    return tmp_path
