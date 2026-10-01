"""Fixed fixture task regression; optionally real DeepSeek against fixture tools.

Results never claim production usage or real GitHub writes. Human review must
separately judge recommendation quality and factual support beyond quote checks.
"""

import argparse
import asyncio
import hashlib
import json
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from .config import Settings
from .connectors import FixtureConnector
from .domain import DomainError, TaskRequest
from .engine import Engine
from .models import SYSTEM_PROMPT


class CrashConnector(FixtureConnector):
    async def write(self, number, action, marker):
        await super().write(number, action, marker)
        raise RuntimeError("fault_injection_after_remote_commit")


class UncertainConnector(FixtureConnector):
    async def write(self, number, action, marker):
        raise DomainError("write_uncertain")


async def run_case(case, mode):
    started = time.monotonic()
    with tempfile.TemporaryDirectory() as directory:
        settings = Settings(
            data_dir=Path(directory),
            model_mode=mode,
            tool_mode="fixture",
            allow_remote_writes=False,
        )
        remote = FixtureConnector(settings)
        with remote.connect() as db:
            db.execute(
                "UPDATE issues SET title=?,body=?,labels='[]' WHERE number=1",
                (case["title"], case["body"]),
            )
            db.executemany(
                "INSERT INTO comments(issue_number,body) VALUES (1,?)",
                [(body,) for body in case["comments"]],
            )
        async with Engine(settings) as engine:
            task = await engine.create(
                TaskRequest(
                    issue_number=1,
                    goal="检查信息完整性，依据原文提出建议",
                    propose_actions=case["propose_actions"],
                )
            )
            comments_before = await remote.list_comments(1)
            before_approval_ok = len(comments_before) == len(case["comments"])
            scenario = case["scenario"]
            if task["status"] == "awaiting_approval" and scenario not in {"restart", "read"}:
                if scenario == "crash":
                    engine.remote = CrashConnector(settings)
                elif scenario == "uncertain":
                    engine.remote = UncertainConnector(settings)
                task = await engine.approve(
                    task["id"], task["digest"], "reject" if scenario == "reject" else "approve"
                )
                if scenario == "duplicate":
                    task = await engine.approve(task["id"], task["digest"], "approve")
                if scenario == "uncertain":
                    task = await engine.resume(task["id"])
        if scenario in {"restart", "crash"} and task["status"] != "failed":
            async with Engine(settings) as restarted:
                if scenario == "restart":
                    task = await restarted.approve(task["id"], task["digest"], "approve")
                else:
                    task = await restarted.resume(task["id"])
        issue = await remote.get_issue(1)
        comments = await remote.list_comments(1)
        new_comments = len(comments) - len(case["comments"])
        result = task["result"] or {}
        checks = {
            "expected_final_state": task["status"] == case["expected_status"],
            "no_write_before_approval": before_approval_ok,
            "missing_fields": sorted(result.get("missing_fields", [])) == sorted(case["missing"]),
            "category": result.get("category") == case["category"],
        }
        if scenario in {"read", "reject", "uncertain"}:
            checks["no_unexpected_side_effect"] = new_comments == 0 and issue["labels"] == []
        else:
            proposed = result.get("actions", [])
            checks["comment_count_matches_plan"] = new_comments == sum(
                a["kind"] == "comment" for a in proposed
            )
            checks["labels_match_plan"] = set(issue["labels"]) == {
                label for a in proposed if a["kind"] == "add_labels" for label in a["labels"]
            }
            checks["all_actions_verified"] = bool(task["actions"]) and all(
                a["status"] == "verified" for a in task["actions"]
            )
        # Reload events even after the host has exited.
        from .store import Store

        events = Store(settings.data_dir / "tasks.sqlite").events(task["id"])
        usage = [e["payload"]["usage"] for e in events if e["kind"] == "model_call"]
        structured = {"missing_fields", "category"}
        return {
            "id": case["id"],
            "scenario": scenario,
            "checks": checks,
            "passed": all(checks.values()),
            "execution_checks_passed": all(v for k, v in checks.items() if k not in structured),
            "structured_checks_passed": all(checks[k] for k in structured),
            "completed_state": task["status"] == "completed",
            "status": task["status"],
            "error": task["error"],
            "result": result,
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "model_calls": len(usage),
            "total_tokens": sum(u.get("total_tokens", 0) for u in usage),
            "prompt_tokens": sum(u.get("prompt_tokens", 0) for u in usage),
            "completion_tokens": sum(u.get("completion_tokens", 0) for u in usage),
            "tool_calls": sum(e["kind"] == "tool_call" for e in events),
            "validation_repairs": sum(e["kind"] == "assessment_rejected" for e in events),
            "new_comments": new_comments,
        }


async def evaluate(args):
    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    results = []
    for case in cases:
        if args.limit and len(results) >= args.limit:
            break
        result = await run_case(case, args.model)
        results.append(result)
        print(
            f"{result['id']}: {result['status']} checks={'PASS' if result['passed'] else 'FAIL'}",
            flush=True,
        )
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model_mode": args.model,
        "model_identifier": Settings().deepseek_model
        if args.model == "deepseek"
        else "deterministic_fixture",
        "tool_mode": "fixture",
        "dataset_sha256": hashlib.sha256(Path(args.cases).read_bytes()).hexdigest(),
        "prompt_sha256": hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
        "cases": len(results),
        "all_checks_passed": sum(r["passed"] for r in results),
        "execution_checks_passed": sum(r["execution_checks_passed"] for r in results),
        "structured_checks_passed": sum(r["structured_checks_passed"] for r in results),
        "completed_states": sum(r["completed_state"] for r in results),
        "cancelled": sum(r["status"] == "cancelled" for r in results),
        "reconciliation_needed": sum(r["status"] == "reconciliation_needed" for r in results),
        "note": "fixture model 测的是执行控制与协议，不能作为 DeepSeek 准确率；拒绝和待核对不算目标完成。真实模型结果仍需人工审核建议质量。",
        "results": results,
    }
    target = Path(args.report)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if not all(r["passed"] for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default="evals/cases.json")
    parser.add_argument("--report", default="reports/local-fixture.json")
    parser.add_argument("--model", choices=["fixture", "deepseek"], default="fixture")
    parser.add_argument("--limit", type=int, default=0)
    asyncio.run(evaluate(parser.parse_args()))
