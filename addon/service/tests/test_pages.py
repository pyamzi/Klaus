"""Tests for legal pages."""
from __future__ import annotations

from fastapi.testclient import TestClient
from klausplus.app import create_app


def test_terms_and_privacy_render_operator_and_promises(settings, now):
    c = TestClient(create_app(settings, upstream=object(), now=lambda: now))
    t = c.get("/terms").text
    assert "Klaus Test" in t and "Testland" in t and "ops@klaus.test" in t and "14 days" in t and "period end" in t.lower()
    p = c.get("/privacy").text
    for word in ("Stripe", "OpenAI", "Anthropic", "Resend", "Fly.io", "not stored", "13 months", "30 days"):
        assert word in p, word
    assert "lecture" in p.lower() and "ops@klaus.test" in p


def test_operator_strings_are_escaped():
    from klausplus import templates
    for html in (templates.terms("<b>x</b>", "<i>e</i>", "<u>c</u>"), templates.privacy("<b>x</b>", "<i>e</i>")):
        assert "<b>x</b>" not in html and "&lt;b&gt;x&lt;/b&gt;" in html
        assert "<i>e</i>" not in html and "&lt;i&gt;e&lt;/i&gt;" in html
    assert "no automated, scripted or bulk use" in templates.terms("o", "e", "c")
