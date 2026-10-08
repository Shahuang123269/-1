"""Frozen public issue replay. No writes; no accuracy claims without human gold."""
import argparse
import asyncio
import json
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from .config import Settings
from .domain import Assessment, TaskRequest, canonical
from .engine import Engine
from .models import SYSTEM_PROMPT, DeepSeekModel
from .policy import RepositoryPolicy, fingerprint


def load_snapshot(path, cutoff=None):
    snapshot = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    data = snapshot["data"]
    if fingerprint(data) != snapshot["content_sha256"]:
        raise ValueError("snapshot_hash_mismatch")
    def date(value):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timestamp_requires_timezone")
        return parsed
    boundary = date(cutoff or snapshot["fetched_at"])
    issue = data["issue"]
    if date(issue["updated_at"]) > boundary:
        raise ValueError("historical_body_unavailable")
    comments = [c for c in data["comments"]
                if date(c["created_at"]) <= boundary and date(c["updated_at"]) <= boundary]
    return {"id": snapshot["case_id"], "repository": data["repository"],
            "snapshot_hash": snapshot["content_sha256"], "cutoff": boundary.isoformat(),
            "excluded_comments": len(data["comments"]) - len(comments),
            "issue": {"number": issue["number"], "title": issue["title"],
                      "body": issue["body"] or "", "source": issue["html_url"], "labels": []},
            "comments": [{"id": c["id"], "body": c["body"] or "", "source": c["html_url"]}
                         for c in comments]}


class ReplayTools:
    def __init__(self, case):
        self.case = case
        self.schemas = [{"type": "function", "function": {"name": name, "description": name,
                         "parameters": {"type": "object", "properties": {
                             "issue_number": {"type": "integer"}}, "required": ["issue_number"]}}}
                        for name in ["get_issue", "list_issue_comments"]]

    async def call(self, name, args):
        if args != {"issue_number": self.case["issue"]["number"]}:
            raise ValueError("replay_scope_violation")
        if name == "get_issue":
            return self.case["issue"]
        if name == "list_issue_comments":
            return {"comments": self.case["comments"]}
        raise ValueError("replay_tool_unavailable")


def rules(case):
    text = case["issue"]["body"] + "\n" + "\n".join(c["body"] for c in case["comments"])
    aliases = {"reproduction": r"复现步骤|to reproduce|reproduction|steps to reproduce",
               "environment": r"运行环境|环境:|environment|python version|operating system",
               "actual": r"实际结果|actual behavior|actual result|running the above shows",
               "expected": r"期望结果|expected behavior|expected result"}
    category = "enhancement" if re.search(r"功能建议:|feature request", text, re.I) else "bug"
    return {"category": category, "missing_fields": [] if category == "enhancement" else [
        field for field, pattern in aliases.items() if not re.search(pattern, text, re.I)]}


def score(result, gold, snapshot_hash, cutoff):
    if not gold or gold.get("status") != "human_reviewed" or not gold.get("reviewer"):
        return None
    if gold.get("snapshot_hash") != snapshot_hash or gold.get("cutoff") != cutoff:
        raise ValueError("gold_snapshot_or_cutoff_mismatch")
    expected, actual = set(gold["missing_fields"]), set(result.get("missing_fields", []))
    return {"category_correct": result.get("category") == gold["category"],
            "missing_exact": actual == expected, "unnecessary_requests": len(actual - expected),
            "missed_missing_fields": len(expected - actual)}


def validate_single(result, case):
    sources = {case["issue"]["source"]: case["issue"]["title"] + "\n" + case["issue"]["body"],
               **{c["source"]: c["body"] for c in case["comments"]}}
    if result["actions"] or any(e["quote"] not in sources.get(e["source"], "") for e in
            result["evidence"] + [e for f in result["field_findings"] for e in f["evidence"]]):
        raise ValueError("invalid_single_output")
    if result["category"] == "bug":
        findings = result["field_findings"]
        if (len(findings) != 4 or {f["field"] for f in findings} != set(RepositoryPolicy().required_fields)
                or {f["field"] for f in findings if f["status"] == "missing"} != set(result["missing_fields"])):
            raise ValueError("invalid_field_findings")
        for finding in findings:
            count = len({(e["source"], e["quote"]) for e in finding["evidence"]})
            if ((finding["status"] != "missing" and count == 0)
                    or (finding["status"] == "conflicting" and count < 2)
                    or (finding["status"] == "missing" and count > 0)):
                raise ValueError("invalid_field_findings")
    elif result["category"] == "enhancement" and (result["field_findings"] or result["missing_fields"]):
        raise ValueError("invalid_field_findings")


async def run_method(case, method, args, settings):
    start = time.monotonic()
    if method == "rules":
        return {"result": rules(case), "model_calls": 0, "total_tokens": 0,
                "elapsed_ms": round((time.monotonic() - start) * 1000), "error": None}
    if method == "single":
        model = DeepSeekModel(settings)
        try:
            prompt = SYSTEM_PROMPT + "\n本次是单次阅读基线，完整只读资料已附在请求中，无查询工具。直接 submit_assessment。"
            message, usage = await model.complete([
                {"role": "system", "content": prompt},
                {"role": "user", "content": canonical({"propose_actions": False,
                    "policy": RepositoryPolicy().model_dump(), "issue": case["issue"],
                    "comments": case["comments"]})}], [{"type": "function", "function": {
                    "name": "submit_assessment", "description": "Submit assessment",
                    "parameters": Assessment.model_json_schema()}}])
            calls = message.get("tool_calls", [])
            if len(calls) != 1 or calls[0]["function"]["name"] != "submit_assessment":
                raise ValueError("invalid_model_protocol")
            result = Assessment.model_validate_json(calls[0]["function"]["arguments"]).model_dump()
            validate_single(result, case)
            return {"result": result, "model_calls": 1, "total_tokens": usage.get("total_tokens", 0),
                    "elapsed_ms": round((time.monotonic() - start) * 1000), "error": None}
        finally:
            await model.close()
    work = Path(args.work_dir)
    work.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=work) as directory:
        options = settings.model_copy(update={"data_dir": Path(directory), "tool_mode": "fixture",
            "repository": case["repository"], "allow_remote_writes": False, "policy_path": None})
        async with Engine(options, tools=ReplayTools(case)) as engine:
            task = await engine.create(TaskRequest(issue_number=case["issue"]["number"]))
            events = engine.store.events(task["id"])
            calls = [e for e in events if e["kind"] == "model_call"]
            return {"result": task["result"] or {}, "error": task["error"],
                    "model_calls": len(calls),
                    "total_tokens": sum(e["payload"]["usage"].get("total_tokens", 0) for e in calls),
                    "elapsed_ms": round((time.monotonic() - start) * 1000)}


async def evaluate(args):
    if args.model == "fixture" and "single" in args.methods:
        raise ValueError("single_baseline_requires_real_model")
    settings = Settings(model_mode=args.model, max_model_calls=6, allow_remote_writes=False)
    annotations = json.loads(Path(args.gold).read_text(encoding="utf-8")) if args.gold else {}
    rows = []
    paths = sorted(Path(args.snapshots).glob("*.json"))[:args.limit]
    if not paths:
        raise ValueError("no_snapshots")
    for path in paths:
        case = load_snapshot(path, args.cutoff)
        for method in args.methods:
            try:
                result = await run_method(case, method, args, settings)
            except Exception as exc:
                result = {"result": {}, "error": getattr(exc, "code", type(exc).__name__),
                          "model_calls": None, "total_tokens": None, "elapsed_ms": None}
            measured = score(result["result"], annotations.get(case["id"]), case["snapshot_hash"], case["cutoff"])
            rows.append({"case": case["id"], "source": case["issue"]["source"],
                         "snapshot_hash": case["snapshot_hash"], "cutoff": case["cutoff"],
                         "excluded_comments": case["excluded_comments"], "method": method,
                         **result, "human_gold_scores": measured})
            print(case["id"], method, result["error"] or "completed", flush=True)
    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "model_mode": args.model,
              "model": settings.deepseek_model if args.model == "deepseek" else "fixture",
              "prompt_sha256": fingerprint(SYSTEM_PROMPT), "remote_writes": False,
              "input_mode": "frozen_public_snapshot_replay", "rows": rows,
              "reviewed_case_count": len({r["case"] for r in rows if r["human_gold_scores"] is not None}),
              "note": "Unreviewed data contributes no accuracy. Current snapshot is not historical initial triage. Same inputs; agent has a larger call budget. Failed-call token usage may be unknown."}
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if any(r["error"] for r in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshots", default="data/public-issues")
    parser.add_argument("--methods", nargs="+", choices=["rules", "single", "agent"], default=["rules", "agent"])
    parser.add_argument("--model", choices=["fixture", "deepseek"], default="fixture")
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument("--cutoff")
    parser.add_argument("--gold")
    parser.add_argument("--work-dir", default=".test-runs/replay")
    parser.add_argument("--report", default="reports/local-comparison.json")
    asyncio.run(evaluate(parser.parse_args()))
