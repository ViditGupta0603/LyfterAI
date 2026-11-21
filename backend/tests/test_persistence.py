"""History and cache survive a restart (same DATABASE_URL / CACHE_DIR, new process state)."""

from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import chat


def test_history_and_cache_survive_restart(provider, make_settings):
    settings = make_settings()
    with TestClient(create_app(settings)) as c:
        first = chat(c, "persist", "remember this").json()

    with TestClient(create_app(settings)) as c:  # "container restart"
        history = c.get("/sessions/persist/messages").json()["messages"]
        assert [m["content"] for m in history] == ["remember this", first["reply"]]
        again = chat(c, "fresh", "remember this").json()
        assert again["metadata"]["resolution_source"] == "LLM_CACHE"
        assert again["reply"] == first["reply"]


def test_schema_is_created_on_startup(provider, make_settings, tmp_path):
    settings = make_settings(DATABASE_URL=f"sqlite:///{tmp_path / 'new' / 'dir' / 'app.db'}")
    with TestClient(create_app(settings)) as c:
        assert c.get("/health").status_code == 200
    assert (tmp_path / "new" / "dir" / "app.db").exists()
