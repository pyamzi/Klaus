from __future__ import annotations
from klausplus.config import Settings


def test_secrets_excluded_from_repr():
    settings = Settings(openai_api_key="sk-test")
    assert "sk-test" not in repr(settings)
