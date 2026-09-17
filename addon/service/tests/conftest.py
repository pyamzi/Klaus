from __future__ import annotations
import time
import pytest
from klausplus.config import Settings
from klausplus.db import Store, connect


@pytest.fixture
def settings(tmp_path):
    return Settings(database_path=str(tmp_path / "k.sqlite3"), stripe_secret_key="sk_test_x",
                    stripe_webhook_secret="whsec_x", stripe_price_monthly="price_m", stripe_price_yearly="price_y",
                    openai_api_key="oa", anthropic_api_key="an", public_base_url="https://klaus.test",
                    operator_name="Klaus Test", operator_email="ops@klaus.test", operator_country="Testland")


@pytest.fixture
def store(settings):
    return Store(connect(settings.database_path))


@pytest.fixture
def now():
    return float(time.mktime((2026, 9, 16, 12, 0, 0, 0, 0, 0)))
