from concurrent.futures import ThreadPoolExecutor

from tests.conftest import chat


def test_parallel_requests_in_one_session_keep_history_consistent(client):
    with ThreadPoolExecutor(max_workers=5) as pool:
        codes = list(pool.map(lambda i: chat(client, "conc", f"parallel {i}").status_code, range(5)))
    assert codes == [200] * 5
    history = client.get("/sessions/conc/messages").json()["messages"]
    assert len(history) == 10
    assert [m["role"] for m in history] == ["user", "assistant"] * 5
