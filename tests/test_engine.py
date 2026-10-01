import json

import pytest

from issue_agent.config import Settings
from issue_agent.connectors import FixtureConnector
from issue_agent.domain import DomainError, TaskRequest
from issue_agent.engine import Engine

from .helpers import DirectTools, ModifiedModel, mutate_final


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, data_dir=tmp_path)


def engine(settings, **kwargs):
    return Engine(settings, tools=DirectTools(settings), **kwargs)


async def test_read_task_requires_no_approval(settings):
    async with engine(settings) as e:
        task = await e.create(TaskRequest(issue_number=1))
        assert task["status"] == "completed"
        assert task["result"]["missing_fields"] == []
        assert task["actions"] == []
        assert [x["kind"] for x in e.store.events(task["id"])].count("tool_call") == 2


async def test_no_write_before_approval_then_exact_actions(settings):
    async with engine(settings) as e:
        task = await e.create(TaskRequest(issue_number=2, propose_actions=True))
        assert task["status"] == "awaiting_approval"
        assert await e.remote.list_comments(2) == []
        task = await e.approve(task["id"], task["digest"], "approve")
        assert task["status"] == "completed"
        assert len(await e.remote.list_comments(2)) == 1
        assert "needs-info" in (await e.remote.get_issue(2))["labels"]
        assert all(a["status"] == "verified" for a in task["actions"])


async def test_reject_has_no_side_effect_and_cannot_be_overridden(settings):
    async with engine(settings) as e:
        task = await e.create(TaskRequest(issue_number=2, propose_actions=True))
        result = await e.approve(task["id"], task["digest"], "reject")
        assert result["status"] == "cancelled"
        assert await e.remote.list_comments(2) == []
        with pytest.raises(DomainError, match="approval_conflict"):
            await e.approve(task["id"], task["digest"], "approve")


async def test_restart_pending_approval(settings):
    async with engine(settings) as e:
        task = await e.create(TaskRequest(issue_number=2, propose_actions=True))
    async with engine(settings) as restarted:
        assert restarted.store.task(task["id"])["status"] == "awaiting_approval"
        completed = await restarted.approve(task["id"], task["digest"], "approve")
        assert completed["status"] == "completed"


async def test_duplicate_approval_does_not_duplicate_comment(settings):
    async with engine(settings) as e:
        task = await e.create(TaskRequest(issue_number=2, propose_actions=True))
        for _ in range(2):
            task = await e.approve(task["id"], task["digest"], "approve")
        assert len(await e.remote.list_comments(2)) == 1


async def test_idempotent_submission_survives_restart(settings):
    request = TaskRequest(issue_number=2, propose_actions=True)
    async with engine(settings) as e:
        task = await e.create(request, "submission-1")
        completed = await e.approve(task["id"], task["digest"], "approve")
        assert completed["status"] == "completed"
    async with engine(settings) as restarted:
        replay = await restarted.create(request, "submission-1")
        assert replay["id"] == task["id"] and replay["status"] == "completed"
        assert len(await restarted.remote.list_comments(2)) == 1
        with pytest.raises(DomainError, match="submission_conflict"):
            await restarted.create(TaskRequest(issue_number=1), "submission-1")


async def test_stale_digest_rejected(settings):
    async with engine(settings) as e:
        task = await e.create(TaskRequest(issue_number=2, propose_actions=True))
        with pytest.raises(DomainError, match="stale_approval"):
            await e.approve(task["id"], "0" * 64, "approve")
        assert await e.remote.list_comments(2) == []


async def test_repository_change_invalidates_old_task(settings):
    async with engine(settings) as e:
        task = await e.create(TaskRequest(issue_number=2, propose_actions=True))
    settings.repository = "other/repo"
    async with engine(settings) as e:
        with pytest.raises(DomainError, match="task_scope_changed"):
            await e.approve(task["id"], task["digest"], "approve")
        assert await e.remote.list_comments(2) == []


async def test_tampered_plan_cannot_reuse_approval(settings):
    async with engine(settings) as e:
        task = await e.create(TaskRequest(issue_number=2, propose_actions=True))
        e.store.approve(task["id"], task["digest"], "approve")
        snapshot = await e.graph.aget_state(e.config(task["id"]))
        result = snapshot.values["result"]
        result["actions"][0]["body"] = "不同的未批准内容"
        await e.graph.aupdate_state(
            e.config(task["id"]), {"result": result, "approved": True}, as_node="approval"
        )
        completed = await e.resume(task["id"])
        assert completed["error"] == "approval_required"
        assert await e.remote.list_comments(2) == []


class CrashAfterRemoteWrite(FixtureConnector):
    async def write(self, number, action, marker):
        await super().write(number, action, marker)
        raise RuntimeError("simulated host crash before local success record")


async def test_remote_success_local_failure_reconciles_after_restart(settings):
    async with engine(settings, remote=CrashAfterRemoteWrite(settings)) as e:
        task = await e.create(TaskRequest(issue_number=2, propose_actions=True))
        task = await e.approve(task["id"], task["digest"], "approve")
        assert task["status"] == "reconciliation_needed"
        assert len(await e.remote.list_comments(2)) == 1
    async with engine(settings) as restarted:
        completed = await restarted.resume(task["id"])
        assert completed["status"] == "completed"
        assert len(await restarted.remote.list_comments(2)) == 1


class UnknownWrite(FixtureConnector):
    async def write(self, number, action, marker):
        raise DomainError("write_uncertain")


async def test_uncertain_absent_result_is_not_retried(settings):
    remote = UnknownWrite(settings)
    calls = 0
    original = remote.write

    async def counted(*args):
        nonlocal calls
        calls += 1
        return await original(*args)

    remote.write = counted
    async with engine(settings, remote=remote) as e:
        task = await e.create(TaskRequest(issue_number=2, propose_actions=True))
        task = await e.approve(task["id"], task["digest"], "approve")
        task = await e.resume(task["id"])
        assert task["status"] == "reconciliation_needed"
        assert calls == 1


@pytest.mark.parametrize(
    "change,error",
    [
        (lambda r: r["evidence"][0].update(quote="原文并不存在这个结论"), "unsupported_evidence"),
        (lambda r: r["evidence"][0].update(source="https://evil.example"), "unsupported_evidence"),
        (
            lambda r: r.update(actions=[{"kind": "comment", "body": "未授权", "labels": []}]),
            "writes_out_of_scope",
        ),
        (lambda r: r.update(category="invented"), "invalid_assessment"),
    ],
)
async def test_invalid_results_fail_before_write(settings, change, error):
    async with engine(settings, model=ModifiedModel(mutate_final(change))) as e:
        task = await e.create(TaskRequest(issue_number=2))
        assert task["status"] == "failed" and task["error"] == error
        assert await e.remote.list_comments(2) == []


async def test_invalid_evidence_can_be_repaired_with_bounded_feedback(settings):
    attempts = 0

    def change_once(result):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            result["evidence"][0]["quote"] = '"title":"启动后页面白屏"'

    async with engine(settings, model=ModifiedModel(mutate_final(change_once))) as e:
        task = await e.create(TaskRequest(issue_number=2))
        assert task["status"] == "completed"
        assert attempts == 2
        assert any(event["kind"] == "assessment_rejected" for event in e.store.events(task["id"]))


@pytest.mark.parametrize(
    "name,args,error",
    [
        ("delete_repository", {}, "tool_not_allowed"),
        ("get_issue", {"issue_number": 99}, "tool_scope_violation"),
        ("get_issue", {"issue_number": 2, "repository": "other/repo"}, "tool_scope_violation"),
    ],
)
async def test_model_cannot_expand_permissions(settings, name, args, error):
    def mutate(message):
        message["tool_calls"][0]["function"] = {"name": name, "arguments": json.dumps(args)}

    async with engine(settings, model=ModifiedModel(mutate)) as e:
        task = await e.create(TaskRequest(issue_number=2, propose_actions=True))
        assert task["error"] == error
        assert await e.remote.list_comments(2) == []


async def test_model_budget_stops_infinite_tool_loop(settings):
    def repeat(message):
        message["tool_calls"][0]["function"] = {
            "name": "get_issue",
            "arguments": '{"issue_number":2}',
        }

    async with engine(settings, model=ModifiedModel(repeat)) as e:
        task = await e.create(TaskRequest(issue_number=2))
        assert task["error"] == "model_budget_exceeded"


async def test_tool_budget(settings):
    settings.max_tool_calls = 1
    async with engine(settings) as e:
        task = await e.create(TaskRequest(issue_number=2))
        assert task["error"] == "tool_budget_exceeded"


async def test_approval_cannot_be_bypassed_by_raw_graph_resume(settings):
    from langgraph.types import Command

    async with engine(settings) as e:
        task = await e.create(TaskRequest(issue_number=2, propose_actions=True))
        with pytest.raises(DomainError, match="approval_required"):
            await e.graph.ainvoke(Command(resume="approve"), e.config(task["id"]))
        assert await e.remote.list_comments(2) == []
