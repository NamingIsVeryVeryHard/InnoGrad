"""Tests never inherit local model credentials or contact configured services."""
import pytest

@pytest.fixture(autouse=True)
def isolate_agent_configuration(monkeypatch):
    monkeypatch.setenv('AI_MODE','rules')
    monkeypatch.setenv('REVIEW_WORKFLOW','manual')
    for key in ('AI_API_KEY','AI_BASE_URL','AI_MODEL'):
        monkeypatch.delenv(key,raising=False)
