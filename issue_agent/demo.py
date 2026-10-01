import asyncio
import json
import tempfile
from pathlib import Path

from .config import Settings
from .domain import TaskRequest
from .engine import Engine


async def demo():
    with tempfile.TemporaryDirectory() as directory:
        settings = Settings(_env_file=None, data_dir=Path(directory))
        async with Engine(settings) as engine:
            task = await engine.create(TaskRequest(issue_number=2, propose_actions=True))
            task_id = task["id"]
            print(
                json.dumps({"phase": "before_approval", "task": task}, ensure_ascii=False, indent=2)
            )
        # New host and new MCP subprocess, same durable records/checkpoints.
        async with Engine(settings) as restarted:
            completed = await restarted.approve(task_id, task["digest"], "approve")
            print(
                json.dumps(
                    {"phase": "after_restart_and_approval", "task": completed},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            if completed["status"] != "completed":
                raise RuntimeError("demo_failed")


if __name__ == "__main__":
    asyncio.run(demo())
