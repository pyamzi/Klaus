"""K-249: the env switch that lets the whole service run with no provider
key — local dev, and the add-on's offline end-to-end. `create_app` must
pick `FakeUpstream` only when nothing was injected; every existing test
that hands its own upstream (test_proxy.py's `world`, test_app.py's `Up`
and `object()`) has to keep winning over the environment unchanged."""
from __future__ import annotations

from klausplus.app import create_app
from klausplus.upstream import FakeUpstream, Upstream


def test_fake_upstream_env_selects_fake_upstream(settings, monkeypatch):
    monkeypatch.setenv("KLAUS_PLUS_FAKE_UPSTREAM", "1")
    app = create_app(settings)
    assert isinstance(app.state.upstream, FakeUpstream)


def test_no_env_selects_real_upstream(settings, monkeypatch):
    monkeypatch.delenv("KLAUS_PLUS_FAKE_UPSTREAM", raising=False)
    app = create_app(settings)
    assert isinstance(app.state.upstream, Upstream)


def test_falsy_env_values_also_select_real_upstream(settings, monkeypatch):
    for v in ("0", "false", "no", "off", ""):
        monkeypatch.setenv("KLAUS_PLUS_FAKE_UPSTREAM", v)
        assert isinstance(create_app(settings).state.upstream, Upstream), v


def test_injected_upstream_wins_even_with_the_env_set(settings, monkeypatch):
    monkeypatch.setenv("KLAUS_PLUS_FAKE_UPSTREAM", "1")
    sentinel = object()
    app = create_app(settings, upstream=sentinel)
    assert app.state.upstream is sentinel
