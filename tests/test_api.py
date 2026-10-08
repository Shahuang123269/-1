import time

from fastapi.testclient import TestClient

from issue_agent.api import create_app
from issue_agent.config import Settings


def wait_task(client, task, headers=None):
    until = time.monotonic() + 15
    while time.monotonic() < until:
        task = client.get(f"/tasks/{task['id']}", headers=headers or {}).json()
        if task["status"] in {"completed", "awaiting_approval", "failed", "cancelled"}:
            return task
        time.sleep(0.02)
    raise AssertionError("task did not settle")


def test_api_task_approval_events_and_sse(tmp_path):
    with TestClient(create_app(Settings(_env_file=None, data_dir=tmp_path))) as client:
        assert client.get("/health").json()["tool_mode"] == "fixture"
        assert client.post("/tasks", json={"issue_number": -1}).status_code == 422
        task = client.post("/tasks", json={"issue_number": 2, "propose_actions": True}).json()
        task = wait_task(client, task)
        assert task["status"] == "awaiting_approval"
        stale = client.post(
            f"/tasks/{task['id']}/approval", json={"digest": "0" * 64, "decision": "approve"}
        )
        assert stale.status_code == 409
        completed = client.post(
            f"/tasks/{task['id']}/approval", json={"digest": task["digest"], "decision": "approve"}
        ).json()
        completed = wait_task(client, completed)
        assert completed["status"] == "completed"
        response = client.get(f"/tasks/{task['id']}/stream")
        assert response.headers["content-type"].startswith("text/event-stream")
        assert "action_verified" in response.text
        assert client.get("/tasks/nonexistent").status_code == 404
        assert client.get("/").status_code == 200
        headers = {"Idempotency-Key": "api-submission-1"}
        first = client.post("/tasks", json={"issue_number": 1}, headers=headers).json()
        second = client.post("/tasks", json={"issue_number": 1}, headers=headers).json()
        assert first["id"] == second["id"]


def test_auth_and_cross_origin_protection(tmp_path):
    app = create_app(Settings(_env_file=None, data_dir=tmp_path, api_token="test-only-api-token"))
    with TestClient(app) as client:
        assert client.post("/tasks", json={"issue_number": 1}).status_code == 401
        auth = {"Authorization": "Bearer test-only-api-token"}
        assert (
            wait_task(client, client.post("/tasks", json={"issue_number": 1}, headers=auth).json(), auth)["status"]
            == "completed"
        )
        assert (
            client.post(
                "/tasks",
                json={"issue_number": 1},
                headers={**auth, "Origin": "https://evil.example"},
            ).status_code
            == 403
        )
