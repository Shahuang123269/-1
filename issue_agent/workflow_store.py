"""Durable inbox, immutable plans and approvals. SQLite is the source of truth."""
import json
import time
import uuid

from .domain import DomainError, canonical
from .policy import RepositoryPolicy, plan_digest
from .store import Store


class WorkflowStore(Store):
    def __init__(self, path):
        super().__init__(path)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS plans (
                    task_id TEXT NOT NULL, version INTEGER NOT NULL, digest TEXT NOT NULL UNIQUE,
                    result TEXT NOT NULL, context TEXT NOT NULL, actor TEXT NOT NULL,
                    created REAL NOT NULL, PRIMARY KEY(task_id,version)
                );
                CREATE TABLE IF NOT EXISTS decisions (
                    task_id TEXT NOT NULL, digest TEXT NOT NULL, decision TEXT NOT NULL,
                    actor TEXT NOT NULL, created REAL NOT NULL, PRIMARY KEY(task_id,digest)
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
                    kind TEXT NOT NULL, payload TEXT NOT NULL, dedup_key TEXT UNIQUE,
                    status TEXT NOT NULL DEFAULT 'queued', error TEXT, created REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS jobs_ready ON jobs(status,id);
                CREATE TABLE IF NOT EXISTS deliveries (
                    id TEXT PRIMARY KEY, payload_hash TEXT NOT NULL, task_id TEXT NOT NULL,
                    created REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workflow_meta (version INTEGER PRIMARY KEY);
                INSERT OR IGNORE INTO workflow_meta VALUES (1);
            """)

    @staticmethod
    def _event(db, task_id, kind, payload):
        db.execute("INSERT INTO events(task_id,kind,payload,created) VALUES (?,?,?,?)",
                   (task_id, kind, canonical(payload), time.time()))

    def task(self, task_id):
        result = super().task(task_id)
        with self.connect() as db:
            row = db.execute("SELECT version,context FROM plans WHERE task_id=? "
                             "ORDER BY version DESC LIMIT 1", (task_id,)).fetchone()
            result["plan_version"] = row["version"] if row else None
            result["context"] = json.loads(row["context"]) if row else None
        return result

    def list_tasks(self, limit=50, before=None, status=None):
        # Cursor is (created,id): stable even when two tasks have identical timestamps.
        where, args = [], []
        if before:
            item = super().task(before)
            where.append("(created < ? OR (created = ? AND id < ?))")
            args.extend([item["created"], item["created"], before])
        if status:
            where.append("status=?")
            args.append(status)
        query = "SELECT id FROM tasks" + (" WHERE " + " AND ".join(where) if where else "")
        with self.connect() as db:
            ids = [r[0] for r in db.execute(query + " ORDER BY created DESC,id DESC LIMIT ?",
                                          (*args, limit))]
        return [self.task(i) for i in ids]

    def plan(self, task_id, digest=None):
        with self.connect() as db:
            query = "SELECT * FROM plans WHERE task_id=?"
            args = [task_id]
            if digest:
                query += " AND digest=?"
                args.append(digest)
            row = db.execute(query + " ORDER BY version DESC LIMIT 1", args).fetchone()
        if row is None:
            raise DomainError("plan_not_found")
        return {**dict(row), "result": json.loads(row["result"]),
                "context": json.loads(row["context"])}

    def plan_history(self, task_id):
        self.task(task_id)
        with self.connect() as db:
            rows = db.execute("SELECT digest FROM plans WHERE task_id=? ORDER BY version",
                              (task_id,)).fetchall()
            decisions = [dict(r) for r in db.execute(
                "SELECT * FROM decisions WHERE task_id=? ORDER BY created", (task_id,))]
        return {"plans": [self.plan(task_id, r[0]) for r in rows], "decisions": decisions}

    def save_plan(self, task_id, result, context, expected_digest=None, actor="agent"):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            task = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if task is None:
                raise DomainError("not_found")
            previous = db.execute("SELECT * FROM plans WHERE task_id=? ORDER BY version DESC "
                                  "LIMIT 1", (task_id,)).fetchone()
            if expected_digest:
                if task["status"] != "awaiting_approval" or task["digest"] != expected_digest:
                    raise DomainError("stale_approval")
                if db.execute("SELECT 1 FROM decisions WHERE task_id=? AND digest=?",
                              (task_id, expected_digest)).fetchone():
                    raise DomainError("approval_conflict")
            elif previous:
                # Replaying the proposal after a crash must not invent another version.
                if previous["result"] == canonical(result) and previous["context"] == canonical(context):
                    return self._decode_plan(previous)
                raise DomainError("plan_conflict")
            version = previous["version"] + 1 if previous else 1
            digest = plan_digest(task_id, version, json.loads(task["request"]), result, context)
            db.execute("INSERT INTO plans VALUES (?,?,?,?,?,?,?)",
                       (task_id, version, digest, canonical(result), canonical(context), actor, time.time()))
            status = "awaiting_approval" if result["actions"] else "completed"
            db.execute("UPDATE tasks SET status=?,result=?,digest=?,error=NULL WHERE id=?",
                       (status, canonical(result), digest, task_id))
            self._event(db, task_id, "plan_created", {"version": version, "digest": digest,
                                                     "actor": actor})
        return self.plan(task_id, digest)

    @staticmethod
    def _decode_plan(row):
        return {**dict(row), "result": json.loads(row["result"]),
                "context": json.loads(row["context"])}

    def edit_plan(self, task_id, digest, actions):
        previous = self.plan(task_id, digest)
        RepositoryPolicy.model_validate(previous["context"]["policy"]).validate_actions(actions)
        result = {**previous["result"], "actions": actions}
        self.save_plan(task_id, result, previous["context"], digest, actor="owner")
        return self.task(task_id)

    def _approve(self, db, task_id, digest, decision, actor):
        task = db.execute("SELECT status,digest FROM tasks WHERE id=?", (task_id,)).fetchone()
        if task is None:
            raise DomainError("not_found")
        previous = db.execute("SELECT * FROM decisions WHERE task_id=? AND digest=?",
                              (task_id, digest)).fetchone()
        if previous:
            if previous["decision"] == decision:
                return
            raise DomainError("approval_conflict")
        if task["status"] != "awaiting_approval" or task["digest"] != digest:
            raise DomainError("stale_approval")
        # Legacy plans are intentionally not executable after the upgrade.
        if not db.execute("SELECT 1 FROM plans WHERE task_id=? AND digest=?", (task_id, digest)).fetchone():
            raise DomainError("legacy_plan_requires_reanalysis")
        db.execute("INSERT INTO decisions VALUES (?,?,?,?,?)",
                   (task_id, digest, decision, actor, time.time()))
        self._event(db, task_id, "approval", {"digest": digest, "decision": decision, "actor": actor})

    def approve(self, task_id, digest, decision, actor="owner"):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._approve(db, task_id, digest, decision, actor)

    def decision(self, task_id, digest):
        with self.connect() as db:
            row = db.execute("SELECT decision FROM decisions WHERE task_id=? AND digest=?",
                             (task_id, digest)).fetchone()
        return row[0] if row else None

    @staticmethod
    def _capacity(db, limit):
        count = db.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]
        if count >= limit:
            raise DomainError("queue_full")

    def submit(self, payload, key=None, *, limit=64, delivery=None, payload_hash=None):
        if key is not None and (not 1 <= len(key) <= 128 or not key.isascii()):
            raise DomainError("invalid_submission_key")
        task_id = uuid.uuid4().hex
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if delivery:
                prev = db.execute("SELECT * FROM deliveries WHERE id=?", (delivery,)).fetchone()
                if prev:
                    if prev["payload_hash"] != payload_hash:
                        raise DomainError("delivery_conflict")
                    return prev["task_id"]
            if key:
                prev = db.execute("SELECT * FROM submissions WHERE key=?", (key,)).fetchone()
                if prev:
                    if prev["request"] != canonical(payload):
                        raise DomainError("submission_conflict")
                    return prev["task_id"]
            self._capacity(db, limit)
            db.execute("INSERT INTO tasks VALUES (?,?,?,NULL,NULL,NULL,?)",
                       (task_id, canonical(payload), "queued", time.time()))
            if key:
                db.execute("INSERT INTO submissions VALUES (?,?,?)", (key, task_id, canonical(payload)))
            if delivery:
                db.execute("INSERT INTO deliveries VALUES (?,?,?,?)",
                           (delivery, payload_hash, task_id, time.time()))
                # Invalidate pending approval promptly; execution additionally re-reads inputs.
                candidates = db.execute("SELECT id,request FROM tasks WHERE status='awaiting_approval'").fetchall()
                for old in candidates:
                    req = json.loads(old["request"])
                    if (req["repository"], req["issue_number"]) == (payload["repository"], payload["issue_number"]):
                        db.execute("UPDATE tasks SET status='needs_review',error='new_issue_event' WHERE id=?", (old["id"],))
                        self._event(db, old["id"], "superseded", {"new_task_id": task_id})
            db.execute("INSERT INTO jobs(task_id,kind,payload,dedup_key,created) VALUES (?,'start','{}',?,?)",
                       (task_id, 'start:' + task_id, time.time()))
            self._event(db, task_id, "task_queued", {"delivery": delivery})
        return task_id

    def enqueue_approval(self, task_id, digest, decision, limit=64):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            key = f"decision:{task_id}:{digest}"
            prev = db.execute("SELECT payload FROM jobs WHERE dedup_key=?", (key,)).fetchone()
            payload = {"digest": digest, "decision": decision}
            if prev:
                if prev["payload"] != canonical(payload):
                    raise DomainError("approval_conflict")
                return
            self._capacity(db, limit)
            self._approve(db, task_id, digest, decision, "owner")
            db.execute("UPDATE tasks SET status='approval_queued' WHERE id=?", (task_id,))
            db.execute("INSERT INTO jobs(task_id,kind,payload,dedup_key,created) VALUES (?,'approve',?,?,?)",
                       (task_id, canonical(payload), key, time.time()))

    def enqueue_resume(self, task_id, limit=64):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not row:
                raise DomainError("not_found")
            if row[0] not in {"interrupted", "reconciliation_needed"}:
                raise DomainError("not_resumable")
            if db.execute("SELECT 1 FROM jobs WHERE task_id=? AND status IN ('queued','running')", (task_id,)).fetchone():
                return
            self._capacity(db, limit)
            db.execute("INSERT INTO jobs(task_id,kind,payload,created) VALUES (?,'resume','{}',?)", (task_id, time.time()))

    def recover_jobs(self):
        # Caller MUST own the OS worker lock. A running job belonged to the dead owner.
        with self.connect() as db:
            db.execute("UPDATE jobs SET status='queued' WHERE status='running'")

    def claim(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
            if not row:
                return None
            db.execute("UPDATE jobs SET status='running' WHERE id=?", (row["id"],))
            return {**dict(row), "payload": json.loads(row["payload"])}

    def finish(self, job_id, error=None):
        with self.connect() as db:
            db.execute("UPDATE jobs SET status=?,error=? WHERE id=?",
                       ("failed" if error else "done", error, job_id))

    def queue_stats(self):
        with self.connect() as db:
            return {r[0]: r[1] for r in db.execute("SELECT status,count(*) FROM jobs GROUP BY status")}

    def own_comment(self, number, repository, body):
        with self.connect() as db:
            rows = db.execute("SELECT a.operation_id,a.action,t.request FROM actions a JOIN tasks t ON t.id=a.task_id "
                              "WHERE a.status IN ('inflight','uncertain','verified')").fetchall()
        for row in rows:
            req, action = json.loads(row["request"]), json.loads(row["action"])
            if req["issue_number"] == number and req["repository"] == repository and action["kind"] == "comment":
                if body == action["body"] + f"\n\n<!-- issue-agent:{row['operation_id']} -->":
                    return True
        return False
