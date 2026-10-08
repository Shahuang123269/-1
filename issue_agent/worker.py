"""A single graph owner. API processes only persist commands."""
import asyncio
import os
from contextlib import asynccontextmanager

from .config import Settings
from .domain import DomainError
from .engine import Engine
from .policy import load_policy


class WorkerLease:
    """OS lock is released on process death; no timeout can steal a live worker."""
    def __init__(self, data_dir):
        self.path = data_dir / "worker.lock"
        self.file = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("a+b")
        if self.path.stat().st_size == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise DomainError("worker_already_running") from None
        return self

    def __exit__(self, *args):
        self.file.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
        self.file.close()


async def run_job(engine, job):
    store = engine.store
    try:
        if job["kind"] == "start":
            result = await engine.start_existing(job["task_id"])
        elif job["kind"] == "approve":
            result = await engine.approve(job["task_id"], **job["payload"])
        elif job["kind"] == "resume":
            result = await engine.resume(job["task_id"])
        else:
            raise DomainError("unknown_job")
        store.finish(job["id"], result.get("error"))
    except Exception as exc:
        # Keep raw provider messages / tokens out of storage and logs.
        code = exc.code if isinstance(exc, DomainError) else type(exc).__name__
        task = store.task(job["task_id"])
        if task["status"] not in {"completed", "cancelled", "needs_review", "reconciliation_needed"}:
            store.update(job["task_id"], "failed", error=code)
        store.event(job["task_id"], "job_failed", {"code": code})
        store.finish(job["id"], code)


async def worker_loop(engine, stop):
    while not stop.is_set():
        job = engine.store.claim()
        if job:
            await run_job(engine, job)
        else:
            try:
                await asyncio.wait_for(stop.wait(), engine.settings.worker_poll_seconds)
            except TimeoutError:
                pass


@asynccontextmanager
async def running_worker(settings):
    load_policy(settings.policy_path)  # Invalid operator policy fails before taking any task.
    with WorkerLease(settings.data_dir):
        async with Engine(settings) as engine:
            engine.store.recover_jobs()
            stop = asyncio.Event()
            runner = asyncio.create_task(worker_loop(engine, stop))
            try:
                yield engine
            finally:
                stop.set()
                # Graceful shutdown drains the current job; hard kills leave it recoverable.
                await runner


async def main():
    async with running_worker(Settings()):
        await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
