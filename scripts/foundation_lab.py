"""Small learning exercises: async, SQLite transactions, and fixture-only HTTP.

Run with the project's Python environment. Uses temporary local data, no remote
writes, and no model API calls. All application modes are set explicitly.
"""

import argparse
import asyncio
import sqlite3
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from issue_agent.api import create_app
from issue_agent.config import Settings


async def async_lab():
    async def read_issue():
        print("async: read starts")
        await asyncio.sleep(0.01)
        print("async: read finishes")
        return {"number": 2, "title": "fixture example"}

    print("async: caller starts")
    issue = await read_issue()
    print("async: caller received issue", issue["number"])


def sqlite_lab():
    db = sqlite3.connect(":memory:")
    try:
        db.execute("CREATE TABLE decisions(task_id TEXT PRIMARY KEY, decision TEXT)")
        try:
            with db:
                db.execute("INSERT INTO decisions VALUES (?,?)", ("task-1", "approve"))
                db.execute("INSERT INTO decisions VALUES (?,?)", ("task-1", "reject"))
        except sqlite3.IntegrityError:
            print("sqlite: duplicate key; transaction rolled back")
        print("sqlite: rows after rollback", db.execute("SELECT * FROM decisions").fetchall())
        with db:
            db.execute("INSERT INTO decisions VALUES (?,?)", ("task-1", "approve"))
        print("sqlite: rows after commit", db.execute("SELECT * FROM decisions").fetchall())
    finally:
        db.close()


def api_lab():
    with tempfile.TemporaryDirectory() as directory:
        settings = Settings(
            _env_file=None,
            model_mode="fixture",
            tool_mode="fixture",
            repository="Shahuang123269/-1",
            data_dir=Path(directory),
            deepseek_api_key="",
            github_token="",
            api_token="",
            allow_remote_writes=False,
        )
        with TestClient(create_app(settings)) as client:
            health = client.get("/health")
            print("api: GET /health", health.status_code, health.json()["model_mode"])
            bad = client.post("/tasks", json={"issue_number": -1})
            print("api: invalid issue number", bad.status_code)
            request = {"issue_number": 2, "propose_actions": True}
            task = client.post("/tasks", json=request).json()
            print("api: created task", task["status"])
            rejected = client.post(
                f"/tasks/{task['id']}/approval",
                json={"digest": task["digest"], "decision": "reject"},
            )
            print("api: rejection response", rejected.status_code, rejected.json()["status"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lesson", choices=["async", "sqlite", "api", "all"], nargs="?", default="all")
    args = parser.parse_args()
    if args.lesson in {"async", "all"}:
        asyncio.run(async_lab())
    if args.lesson in {"sqlite", "all"}:
        sqlite_lab()
    if args.lesson in {"api", "all"}:
        api_lab()
