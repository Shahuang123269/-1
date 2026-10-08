import asyncio
import json
import operator
import time
from contextlib import AsyncExitStack
from typing import Annotated

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import ValidationError
from typing_extensions import TypedDict

from .config import Settings
from .connectors import connector, verify_action
from .domain import Assessment, DomainError, TaskRequest, canonical
from .mcp_client import MCPTools
from .models import SYSTEM_PROMPT, DeepSeekModel, FixtureModel
from .policy import RepositoryPolicy, input_snapshot, load_policy, plan_digest
from .workflow_store import WorkflowStore


class State(TypedDict, total=False):
    task_id: str
    request: dict
    messages: Annotated[list[dict], operator.add]
    observations: Annotated[list[dict], operator.add]
    model_calls: int
    tool_calls: int
    result: dict
    digest: str
    approved: bool
    status: str
    validation_attempts: int
    validation_retry: bool


class Engine:
    def __init__(self, settings: Settings, *, model=None, tools=None, remote=None):
        self.settings = settings
        self.store = WorkflowStore(settings.data_dir / "tasks.sqlite")
        self.store.interrupted()
        self.model = model
        self.tools = tools
        self.remote = remote or connector(settings)
        self.lock = asyncio.Lock()
        self.stack = AsyncExitStack()

    async def __aenter__(self):
        try:
            if self.model is None:
                self.model = (
                    FixtureModel()
                    if self.settings.model_mode == "fixture"
                    else DeepSeekModel(self.settings)
                )
            if hasattr(self.model, "close"):
                self.stack.push_async_callback(self.model.close)
            if hasattr(self.remote, "close"):
                self.stack.push_async_callback(self.remote.close)
            if self.tools is None:
                self.tools = await self.stack.enter_async_context(MCPTools(self.settings))
            saver = await self.stack.enter_async_context(
                AsyncSqliteSaver.from_conn_string(
                    str(self.settings.data_dir / "checkpoints.sqlite")
                )
            )
            await saver.setup()
            self.graph = self.build_graph(saver)
        except BaseException:
            await self.stack.aclose()
            raise
        return self

    async def __aexit__(self, *args):
        await self.stack.aclose()

    def config(self, task_id: str):
        return {"configurable": {"thread_id": task_id}, "recursion_limit": 60}

    def build_graph(self, saver):
        graph = StateGraph(State)
        for name in ("model", "tools", "proposal", "approval", "execute"):
            graph.add_node(name, getattr(self, name + "_node"))
        graph.add_edge(START, "model")
        graph.add_conditional_edges("model", self.route, {"tools": "tools", "proposal": "proposal"})
        graph.add_edge("tools", "model")
        graph.add_conditional_edges(
            "proposal",
            lambda s: (
                "model"
                if s.get("validation_retry")
                else "approval"
                if s["result"]["actions"]
                else END
            ),
            {"model": "model", "approval": "approval", END: END},
        )
        graph.add_conditional_edges(
            "approval",
            lambda s: "execute" if s["approved"] else END,
            {"execute": "execute", END: END},
        )
        graph.add_edge("execute", END)
        return graph.compile(checkpointer=saver)

    async def model_node(self, state: State):
        if state.get("model_calls", 0) >= self.settings.max_model_calls:
            raise DomainError("model_budget_exceeded")
        if len(canonical(state["messages"])) > self.settings.max_context_chars:
            raise DomainError("context_budget_exceeded")
        parameters = Assessment.model_json_schema()
        policy = RepositoryPolicy.model_validate(state["request"]["policy"])
        parameters["$defs"]["Action"]["properties"]["labels"]["items"] = {
            "type": "string", "enum": policy.allowed_labels,
        }
        if not state["request"]["propose_actions"]:
            parameters["properties"]["actions"].update(
                maxItems=0, description="Read-only task: must be an empty array."
            )
        schema = {
            "type": "function",
            "function": {
                "name": "submit_assessment",
                "description": "Submit evidence-grounded triage and optional proposed actions.",
                "parameters": parameters,
            },
        }
        started = time.monotonic()
        message, usage = await self.model.complete(state["messages"], [*self.tools.schemas, schema])
        self.store.event(
            state["task_id"],
            "model_call",
            {
                "mode": self.settings.model_mode,
                "model": self.settings.deepseek_model
                if self.settings.model_mode == "deepseek"
                else "deterministic_fixture",
                "elapsed_ms": round((time.monotonic() - started) * 1000),
                "usage": usage,
            },
        )
        return {"messages": [message], "model_calls": state.get("model_calls", 0) + 1}

    def route(self, state: State):
        calls = state["messages"][-1].get("tool_calls", [])
        if not calls or len(calls) > 3:
            raise DomainError("invalid_model_protocol")
        if any(c["function"]["name"] == "submit_assessment" for c in calls):
            if len(calls) != 1:
                raise DomainError("mixed_final_tool_calls")
            return "proposal"
        return "tools"

    async def tools_node(self, state: State):
        outputs, observations = [], []
        calls = state["messages"][-1]["tool_calls"]
        if state.get("tool_calls", 0) + len(calls) > self.settings.max_tool_calls:
            raise DomainError("tool_budget_exceeded")
        for call in calls:
            name = call["function"]["name"]
            try:
                args = json.loads(call["function"]["arguments"])
            except (ValueError, TypeError):
                raise DomainError("invalid_tool_arguments") from None
            if not isinstance(args, dict) or name not in {
                "get_issue",
                "list_issue_comments",
                "list_issues",
            }:
                raise DomainError("tool_not_allowed")
            expected = (
                {} if name == "list_issues" else {"issue_number": state["request"]["issue_number"]}
            )
            if args != expected:
                raise DomainError("tool_scope_violation")
            started = time.monotonic()
            result = await self.tools.call(name, args)
            self.store.event(
                state["task_id"],
                "tool_call",
                {
                    "name": name,
                    "arguments": args,
                    "elapsed_ms": round((time.monotonic() - started) * 1000),
                    "status": "ok",
                },
            )
            outputs.append(
                {"role": "tool", "tool_call_id": call["id"], "content": canonical(result)}
            )
            observations.append({"name": name, "result": result})
        return {
            "messages": outputs,
            "observations": observations,
            "tool_calls": state.get("tool_calls", 0) + len(calls),
        }

    def validation_feedback(self, state: State, code: str, sources: dict | None = None):
        if state.get("validation_attempts", 0) >= 2:
            raise DomainError(code)
        self.store.event(
            state["task_id"],
            "assessment_rejected",
            {"error": code, "attempt": state.get("validation_attempts", 0) + 1},
        )
        supported = {
            source: [line[:300] for line in text.splitlines() if line.strip()][:3]
            for source, text in (sources or {}).items()
        }
        feedback = {
            "error": code,
            "message": "请修正结构化结果。quote 只复制 title/body 字符串值中的原文，不能引用 JSON 属性名或空评论。source 必须与已读来源完全一致。仅修正建议，不执行动作。",
            "supported_sources_and_quote_examples": supported,
        }
        return {
            "messages": [
                {
                    "role": "tool",
                    "tool_call_id": state["messages"][-1]["tool_calls"][0]["id"],
                    "content": canonical(feedback),
                }
            ],
            "validation_retry": True,
            "validation_attempts": state.get("validation_attempts", 0) + 1,
        }

    async def proposal_node(self, state: State):
        try:
            result = Assessment.model_validate_json(
                state["messages"][-1]["tool_calls"][0]["function"]["arguments"]
            ).model_dump()
        except ValidationError:
            return self.validation_feedback(state, "invalid_assessment")
        observations = state.get("observations", [])
        if not {"get_issue", "list_issue_comments"}.issubset({o["name"] for o in observations}):
            raise DomainError("insufficient_investigation")
        sources = {}
        for o in observations:
            if o["name"] == "get_issue":
                r = o["result"]
                if r["number"] != state["request"]["issue_number"]:
                    raise DomainError("wrong_issue_result")
                sources[r["source"]] = r["title"] + "\n" + r["body"]
            if o["name"] == "list_issue_comments":
                sources.update({c["source"]: c["body"] for c in o["result"]["comments"]})
        for evidence in result["evidence"] + [
            e for f in result["field_findings"] for e in f["evidence"]
        ]:
            if evidence["quote"] not in sources.get(evidence["source"], ""):
                return self.validation_feedback(state, "unsupported_evidence", sources)
        if result["actions"] and not state["request"]["propose_actions"]:
            raise DomainError("writes_out_of_scope")
        policy = RepositoryPolicy.model_validate(state["request"]["policy"])
        policy.validate_actions(result["actions"])
        findings = result["field_findings"]
        if result["category"] == "bug":
            if (len(findings) != len(policy.required_fields)
                    or {f["field"] for f in findings} != set(policy.required_fields)
                    or {f["field"] for f in findings if f["status"] == "missing"}
                    != set(result["missing_fields"])):
                return self.validation_feedback(state, "invalid_field_findings", sources)
            for finding in findings:
                count = len({(e["source"], e["quote"]) for e in finding["evidence"]})
                if ((finding["status"] != "missing" and count == 0)
                        or (finding["status"] == "conflicting" and count < 2)
                        or (finding["status"] == "missing" and count > 0)):
                    return self.validation_feedback(state, "invalid_field_findings", sources)
        elif result["category"] == "enhancement" and (findings or result["missing_fields"]):
            return self.validation_feedback(state, "invalid_field_findings", sources)
        if not set(result["missing_fields"]).issubset(policy.required_fields):
            return self.validation_feedback(state, "field_outside_policy", sources)
        issue = next(o["result"] for o in reversed(observations) if o["name"] == "get_issue")
        if issue.get("state") == "closed" and result["actions"]:
            raise DomainError("issue_closed")
        comments = next(o["result"]["comments"] for o in reversed(observations)
                        if o["name"] == "list_issue_comments")
        context = {"input": input_snapshot(issue, comments), "policy": policy.model_dump()}
        plan = self.store.save_plan(state["task_id"], result, context)
        status = "awaiting_approval" if result["actions"] else "completed"
        return {"result": result, "digest": plan["digest"], "status": status,
                "validation_retry": False}

    def validate_checkpoint_plan(self, state):
        try:
            plan = self.store.plan(state["task_id"], state["digest"])
        except DomainError:
            raise DomainError("approval_required") from None
        digest = plan_digest(state["task_id"], plan["version"], state["request"],
                             state["result"], plan["context"])
        if digest != state["digest"] or state["result"] != plan["result"]:
            raise DomainError("approval_required")
        return plan

    async def approval_node(self, state: State):
        decision = interrupt({"task_id": state["task_id"], "digest": state["digest"]})
        # The paused graph may refer to v1; edits create immutable v2 in the business DB.
        # Validate the old checkpoint, then load the precise version approved by the owner.
        self.validate_checkpoint_plan(state)
        task = self.store.task(state["task_id"])
        if task["status"] == "needs_review":
            raise DomainError("input_changed")
        plan = self.store.plan(state["task_id"], task["digest"])
        stored = self.store.decision(state["task_id"], plan["digest"])
        if stored is None or decision != stored:
            raise DomainError("approval_required")
        if stored == "reject":
            self.store.update(state["task_id"], "cancelled")
        return {"approved": stored == "approve", "result": plan["result"],
                "digest": plan["digest"],
                "status": "executing" if stored == "approve" else "cancelled"}

    async def check_freshness(self, task_id, plan):
        if load_policy(self.settings.policy_path).model_dump() != plan["context"]["policy"]:
            raise DomainError("policy_changed")
        task = self.store.task(task_id)
        number = task["request"]["issue_number"]
        own_bodies = [a["action"]["body"] + f"\n\n<!-- issue-agent:{a['operation_id']} -->"
                      for a in task["actions"] if a["action"]["kind"] == "comment"
                      and a["status"] in {"inflight", "uncertain", "verified"}]
        issue = await self.remote.get_issue(number)
        comments = await self.remote.list_comments(number)
        if input_snapshot(issue, comments, own_bodies) != plan["context"]["input"]:
            raise DomainError("input_changed")

    async def execute_node(self, state: State):
        task_id, issue_number = state["task_id"], state["request"]["issue_number"]
        task = self.store.task(task_id)
        actions = state["result"]["actions"]
        plan = self.validate_checkpoint_plan(state)
        digest = plan["digest"]
        if (
            digest != state["digest"]
            or digest != task["digest"]
            or (self.store.decision(task_id, digest) != "approve")
        ):
            raise DomainError("approval_required")
        if task["status"] == "needs_review":
            raise DomainError("input_changed")
        await self.check_freshness(task_id, plan)
        self.store.update(task_id, "executing")
        for index, action in enumerate(actions):
            operation_id = f"{task_id}:{digest[:12]}:{index}"
            marker = f"<!-- issue-agent:{operation_id} -->"
            record = self.store.intent(task_id, operation_id, action)
            if record["status"] == "verified":
                continue
            receipt = await verify_action(self.remote, issue_number, action, marker)
            if receipt:
                self.store.action_status(operation_id, "verified", receipt)
                self.store.event(task_id, "action_reconciled", {"operation_id": operation_id})
                continue
            if record["status"] in {"inflight", "uncertain"}:
                raise DomainError("write_uncertain")
            # Recheck before each new side effect, including after recovery.
            await self.check_freshness(task_id, plan)
            self.store.action_status(operation_id, "inflight")
            try:
                await self.remote.write(issue_number, action, marker)
            except DomainError as e:
                if e.code != "write_uncertain":
                    self.store.action_status(operation_id, "failed")
                    raise
                self.store.action_status(operation_id, "uncertain")
            receipt = await verify_action(self.remote, issue_number, action, marker)
            if not receipt:
                self.store.action_status(operation_id, "uncertain")
                raise DomainError("write_uncertain")
            self.store.action_status(operation_id, "verified", receipt)
            self.store.event(
                task_id, "action_verified", {"operation_id": operation_id, "receipt": receipt}
            )
        self.store.update(task_id, "completed")
        return {"status": "completed"}

    async def drive(self, task_id: str, value):
        try:
            await self.graph.ainvoke(value, self.config(task_id))
        except DomainError as e:
            pending_effect = any(
                a["status"] in {"inflight", "uncertain"}
                for a in self.store.task(task_id)["actions"]
            )
            status = (
                "reconciliation_needed"
                if e.code == "write_uncertain" or pending_effect
                else "failed"
            )
            if e.code in {"input_changed", "policy_changed"} and not pending_effect:
                status = "needs_review"
            self.store.update(task_id, status, error=e.code)
        except Exception as e:
            # A worker crash may leave a remote side effect. Never retry it blindly.
            status = (
                "reconciliation_needed"
                if self.store.task(task_id)["status"] == "executing"
                else "failed"
            )
            self.store.update(task_id, status, error=type(e).__name__)
        return self.store.task(task_id)

    async def create(self, request: TaskRequest, idempotency_key: str | None = None):
        async with self.lock:
            if idempotency_key is not None and (
                not 1 <= len(idempotency_key) <= 128 or not idempotency_key.isascii()
            ):
                raise DomainError("invalid_submission_key")
            payload = request.model_dump()
            payload.update(repository=self.settings.repository, tool_mode=self.settings.tool_mode,
                           policy=load_policy(self.settings.policy_path).model_dump())
            task_id, created = self.store.create(payload, idempotency_key)
            if not created:
                return self.store.task(task_id)
            return await self.start_existing(task_id)

    async def start_existing(self, task_id):
        self.check_scope(task_id)
        task = self.store.task(task_id)
        snapshot = await self.graph.aget_state(self.config(task_id))
        if snapshot.values:
            if task["status"] in {"completed", "cancelled", "failed", "needs_review"}:
                return task
            if any(t.interrupts for t in snapshot.tasks):
                # A crash after proposal persistence may leave the last node to checkpoint.
                return task
            if snapshot.next:
                return await self.drive(task_id, None)
            return task
        payload = task["request"]
        self.store.update(task_id, "running")
        return await self.drive(task_id, {
            "task_id": task_id, "request": payload,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                         {"role": "user", "content": canonical(payload)}],
            "observations": [], "model_calls": 0, "tool_calls": 0,
        })

    async def approve(self, task_id: str, digest: str, decision: str):
        async with self.lock:
            self.check_scope(task_id)
            self.store.approve(task_id, digest, decision)
            if self.store.task(task_id)["status"] in {"completed", "cancelled", "failed"}:
                return self.store.task(task_id)
            snapshot = await self.graph.aget_state(self.config(task_id))
            value = Command(resume=decision) if any(t.interrupts for t in snapshot.tasks) else None
            return await self.drive(task_id, value)

    def check_scope(self, task_id: str):
        request = self.store.task(task_id)["request"]
        if (
            request.get("repository") != self.settings.repository
            or request.get("tool_mode") != self.settings.tool_mode
        ):
            raise DomainError("task_scope_changed")

    async def resume(self, task_id: str):
        async with self.lock:
            self.check_scope(task_id)
            task = self.store.task(task_id)
            if task["status"] in {"completed", "cancelled", "failed"}:
                return task
            snapshot = await self.graph.aget_state(self.config(task_id))
            decision = self.store.decision(task_id, task["digest"]) if task["digest"] else None
            if any(t.interrupts for t in snapshot.tasks):
                if not decision:
                    raise DomainError("approval_required")
                return await self.drive(task_id, Command(resume=decision))
            if snapshot.next:
                return await self.drive(task_id, None)
            raise DomainError("no_resumable_checkpoint")
