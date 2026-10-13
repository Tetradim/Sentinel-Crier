from fastapi.testclient import TestClient
from crier.app import create_app
from crier.config import Config


def client(tmp_path):
    return TestClient(create_app(Config(data_dir=tmp_path, token="a" * 32)))


def test_private_endpoints_require_token(tmp_path):
    with client(tmp_path) as c:
        assert c.get("/").status_code == 200
        for path in ("/api/status", "/api/settings", "/api/history"):
            assert c.get(path).status_code == 401
        assert c.get("/api/status", headers={"Authorization": "Bearer " + "a" * 32}).status_code == 200


def test_preview_cannot_enqueue_and_settings_persist(tmp_path):
    headers = {"Authorization": "Bearer " + "a" * 32}
    with client(tmp_path) as c:
        settings = c.get("/api/settings", headers=headers).json()
        settings["display_name"] = "My Desk"
        assert c.put("/api/settings", headers=headers, json=settings).status_code == 200
        for scenario in ("option_buy", "option_sell", "stock_buy", "partial"):
            r = c.post("/api/preview", headers=headers, json={"scenario": scenario, "settings": settings})
            assert r.status_code == 200
            assert r.json()["sample"] is True
        assert c.get("/api/history", headers=headers).json() == []
    with client(tmp_path) as c:
        assert c.get("/api/settings", headers=headers).json()["display_name"] == "My Desk"


def test_bad_settings_and_no_secret_in_status(tmp_path):
    headers = {"Authorization": "Bearer " + "a" * 32}
    with client(tmp_path) as c:
        assert c.put("/api/settings", headers=headers, json={"display_name":"@everyone"}).status_code == 422
        assert "a" * 32 not in c.get("/api/status", headers=headers).text
        assert c.get("/", headers=headers).headers["content-security-policy"]


def test_live_delivery_requires_explicit_validation(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        Config(data_dir=tmp_path, token="a" * 32, delivery_enabled=True)


def test_second_console_cannot_recover_an_active_senders_jobs(tmp_path):
    import pytest
    from crier.lock import single_process
    with single_process(tmp_path / 'console.lock'):
        with pytest.raises(RuntimeError):
            with client(tmp_path): pass
