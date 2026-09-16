import logging
from fastapi.testclient import TestClient
from klausplus import keys
from klausplus.app import create_app


def test_logs_carry_no_body_and_no_key(settings, now, caplog):
    class Up:
        async def openai_json(self, path, body):
            import httpx
            return httpx.Response(200, json={"data": [], "usage": {"total_tokens": 3}})
    app = create_app(settings, upstream=Up(), now=lambda: now)
    cid = app.state.store.upsert_customer("cus_1", "", now)
    key = keys.mint()
    app.state.store.set_key_hash(cid, keys.hash_key(key))
    app.state.store.set_subscription("cus_1", "active", int(now) + 86400, False, now)
    with caplog.at_level(logging.INFO, logger="klausplus"):
        TestClient(app).post("/v1/embeddings", json={"input": ["SECRET LECTURE TEXT"]},
                             headers={"Authorization": f"Bearer {key}", "X-Klaus-Purpose": "embed", "X-Klaus-Client": "0.2.0"})
        TestClient(app).post("/v1/embeddings", json={"input": ["SECRET-BODY-MARKER"]},
                             headers={"Authorization": "Bearer kp_" + "0" * 32, "X-Klaus-Purpose": "embed", "X-Klaus-Client": "0.2.0"})
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "POST /v1/embeddings 200" in text and keys.hash_key(key)[:8] in text
    assert "POST /v1/embeddings 401 key=-" in text
    assert "SECRET" not in text and key not in text
    assert "SECRET-BODY-MARKER" not in text


def test_unknown_route_404_uses_error_envelope(settings):
    app = create_app(settings, upstream=object())
    r = TestClient(app).get("/nope")
    assert r.status_code == 404
    assert r.json()["error"]["message"]
