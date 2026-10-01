import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .domain import DomainError, canonical


class Store:
    """Business records are distinct from LangGraph checkpoints.

    One service process / one executor; SQL transactions still guard approvals.
    """

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS tasks (
                  id TEXT PRIMARY KEY, request TEXT NOT NULL, status TEXT NOT NULL,
                  result TEXT, digest TEXT, error TEXT, created REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS submissions (
                  key TEXT PRIMARY KEY, task_id TEXT NOT NULL, request TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS approvals (
                  task_id TEXT PRIMARY KEY, digest TEXT NOT NULL,
                  decision TEXT NOT NULL, actor TEXT NOT NULL, created REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS actions (
                  operation_id TEXT PRIMARY KEY, task_id TEXT NOT NULL,
                  action TEXT NOT NULL, status TEXT NOT NULL, receipt TEXT
                );
                CREATE TABLE IF NOT EXISTS events (
                  seq INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
                  kind TEXT NOT NULL, payload TEXT NOT NULL, created REAL NOT NULL
                );
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, request: dict, key: str | None = None) -> tuple[str, bool]:
        task_id = uuid.uuid4().hex
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if key:
                previous = db.execute("SELECT * FROM submissions WHERE key=?", (key,)).fetchone()
                if previous:
                    if previous["request"] != canonical(request):
                        raise DomainError("submission_conflict")
                    return previous["task_id"], False
            db.execute(
                "INSERT INTO tasks VALUES (?,?,?,NULL,NULL,NULL,?)",
                (task_id, canonical(request), "pending", time.time()),
            )
            if key:
                db.execute(
                    "INSERT INTO submissions VALUES (?,?,?)", (key, task_id, canonical(request))
                )
        self.event(task_id, "task_created", {"issue_number": request["issue_number"]})
        return task_id, True

    def task(self, task_id: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if row is None:
                raise DomainError("not_found")
            result = dict(row)
            for key in ("request", "result"):
                if result[key]:
                    result[key] = json.loads(result[key])
            result["actions"] = [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM actions WHERE task_id=? ORDER BY operation_id", (task_id,)
                )
            ]
            for action in result["actions"]:
                action["action"] = json.loads(action["action"])
                if action["receipt"]:
                    action["receipt"] = json.loads(action["receipt"])
            return result

    def update(self, task_id: str, status: str, *, result=None, digest=None, error=None):
        with self.connect() as db:
            db.execute(
                """UPDATE tasks SET status=?, result=COALESCE(?,result),
                       digest=COALESCE(?,digest), error=? WHERE id=?""",
                (status, canonical(result) if result is not None else None, digest, error, task_id),
            )
        self.event(task_id, "status", {"status": status, "error": error})

    def event(self, task_id: str, kind: str, payload: dict):
        # Credentials and raw provider exceptions must never be recorded here.
        with self.connect() as db:
            db.execute(
                "INSERT INTO events(task_id,kind,payload,created) VALUES (?,?,?,?)",
                (task_id, kind, canonical(payload), time.time()),
            )

    def events(self, task_id: str, after: int = 0) -> list[dict]:
        self.task(task_id)
        with self.connect() as db:
            return [
                {**dict(row), "payload": json.loads(row["payload"])}
                for row in db.execute(
                    "SELECT * FROM events WHERE task_id=? AND seq>? ORDER BY seq", (task_id, after)
                )
            ]

    def approve(self, task_id: str, digest: str, decision: str, actor: str = "owner"):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            task = db.execute("SELECT status,digest FROM tasks WHERE id=?", (task_id,)).fetchone()
            if task is None:
                raise DomainError("not_found")
            previous = db.execute("SELECT * FROM approvals WHERE task_id=?", (task_id,)).fetchone()
            if previous:
                if previous["digest"] == digest and previous["decision"] == decision:
                    return  # Idempotent submission, never change a past decision.
                raise DomainError("approval_conflict")
            if task["status"] != "awaiting_approval" or task["digest"] != digest:
                raise DomainError("stale_approval")
            db.execute(
                "INSERT INTO approvals VALUES (?,?,?,?,?)",
                (task_id, digest, decision, actor, time.time()),
            )
        self.event(task_id, "approval", {"digest": digest, "decision": decision, "actor": actor})

    def decision(self, task_id: str, digest: str) -> str | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT decision FROM approvals WHERE task_id=? AND digest=?", (task_id, digest)
            ).fetchone()
            return row[0] if row else None

    def intent(self, task_id: str, operation_id: str, action: dict) -> dict:
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO actions VALUES (?,?,?,'prepared',NULL)",
                (operation_id, task_id, canonical(action)),
            )
            row = dict(
                db.execute("SELECT * FROM actions WHERE operation_id=?", (operation_id,)).fetchone()
            )
            if row["task_id"] != task_id or row["action"] != canonical(action):
                raise DomainError("operation_conflict")
            return row

    def action_status(self, operation_id: str, status: str, receipt=None):
        with self.connect() as db:
            db.execute(
                "UPDATE actions SET status=?,receipt=? WHERE operation_id=?",
                (status, canonical(receipt) if receipt is not None else None, operation_id),
            )

    def interrupted(self):
        # Startup does not silently retry writes or bill the model again.
        with self.connect() as db:
            db.execute("UPDATE tasks SET status='reconciliation_needed' WHERE status='executing'")
            db.execute(
                "UPDATE tasks SET status='interrupted' WHERE status IN ('running','pending')"
            )
