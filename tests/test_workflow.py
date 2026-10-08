import hashlib
import hmac
import json
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from issue_agent.api import create_app
from issue_agent.config import Settings
from issue_agent.domain import DomainError, TaskRequest
from issue_agent.engine import Engine
from issue_agent.policy import RepositoryPolicy
from issue_agent.store import Store
from issue_agent.worker import WorkerLease, run_job
from issue_agent.workflow_store import WorkflowStore
from tests.helpers import DirectTools, ModifiedModel, mutate_final
from tests.test_api import wait_task


def payload(settings, number=2):
    return {**TaskRequest(issue_number=number, propose_actions=True).model_dump(),
            "repository": settings.repository, "tool_mode": settings.tool_mode,
            "policy": RepositoryPolicy().model_dump()}


def make_engine(settings, **kwargs):
    return Engine(settings, tools=DirectTools(settings), **kwargs)


async def test_edit_plan_rejects_old_approval_executes_exact_new_version(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path)
    async with make_engine(settings) as e:
        task = await e.create(TaskRequest(issue_number=2, propose_actions=True))
        edited = e.store.edit_plan(task['id'], task['digest'], [
            {"kind": "comment", "body": "请补充操作系统版本和启动命令。", "labels": []}])
        assert edited['plan_version'] == 2 and edited['digest'] != task['digest']
        with pytest.raises(DomainError, match='stale_approval'):
            await e.approve(task['id'], task['digest'], 'approve')
        done = await e.approve(task['id'], edited['digest'], 'approve')
        assert done['status'] == 'completed'
        comments = await e.remote.list_comments(2)
        assert len(comments) == 1 and comments[0]['body'].startswith('请补充操作系统版本和启动命令。')
        assert (await e.remote.get_issue(2))['labels'] == []
        history = e.store.plan_history(task['id'])
        assert len(history['plans']) == 2 and len(history['decisions']) == 1


async def test_new_comment_invalidates_approved_input(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path)
    async with make_engine(settings) as e:
        task = await e.create(TaskRequest(issue_number=2, propose_actions=True))
        with e.remote.connect() as db:
            db.execute("INSERT INTO comments(issue_number,body) VALUES (2,'环境: Windows 11')")
        result = await e.approve(task['id'], task['digest'], 'approve')
        assert result['status'] == 'needs_review' and result['error'] == 'input_changed'
        assert len(await e.remote.list_comments(2)) == 1
        assert result['actions'] == []


async def test_policy_change_invalidates_approval(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path)
    async with make_engine(settings) as e:
        task = await e.create(TaskRequest(issue_number=2, propose_actions=True))
        config = tmp_path / 'policy.toml'
        config.write_text('version = "2"\n', encoding='utf-8')
        settings.policy_path = config
        result = await e.approve(task['id'], task['digest'], 'approve')
        assert result['status'] == 'needs_review' and result['error'] == 'policy_changed'
        assert await e.remote.list_comments(2) == []


async def test_custom_fields_and_labels_are_used(tmp_path):
    config = tmp_path / 'policy.toml'
    config.write_text('''required_fields = ["environment"]
allowed_labels = ["defect", "feature", "waiting", "review"]
[label_mapping]
bug = "defect"
enhancement = "feature"
needs-info = "waiting"
uncertain = "review"
''', encoding='utf-8')
    settings = Settings(_env_file=None, data_dir=tmp_path, policy_path=config)
    async with make_engine(settings) as e:
        task = await e.create(TaskRequest(issue_number=2, propose_actions=True))
        assert task['result']['missing_fields'] == ['environment']
        assert task['result']['actions'][-1]['labels'] == ['waiting']
        result = await e.approve(task['id'], task['digest'], 'approve')
        assert result['status'] == 'completed'
        assert (await e.remote.get_issue(2))['labels'] == ['waiting']


async def test_forged_field_evidence_rejected(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path)
    def change(result):
        result['field_findings'][0]['status'] = 'present'
        result['field_findings'][0]['evidence'] = [{'source': 'fake', 'quote': 'fake'}]
    async with make_engine(settings, model=ModifiedModel(mutate_final(change))) as e:
        task = await e.create(TaskRequest(issue_number=2))
        assert task['error'] == 'unsupported_evidence'


async def test_approval_queue_full_rolls_back_decision(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path)
    async with make_engine(settings) as e:
        task = await e.create(TaskRequest(issue_number=2, propose_actions=True))
        e.store.submit(payload(settings), limit=1)
        with pytest.raises(DomainError, match='queue_full'):
            e.store.enqueue_approval(task['id'], task['digest'], 'approve', limit=1)
        assert e.store.decision(task['id'], task['digest']) is None
        assert e.store.task(task['id'])['status'] == 'awaiting_approval'


async def test_edit_after_enqueued_approval_is_forbidden(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path)
    async with make_engine(settings) as e:
        task = await e.create(TaskRequest(issue_number=2, propose_actions=True))
        e.store.enqueue_approval(task['id'], task['digest'], 'approve')
        with pytest.raises(DomainError, match='stale_approval'):
            e.store.edit_plan(task['id'], task['digest'], task['result']['actions'])
        e.store.enqueue_approval(task['id'], task['digest'], 'approve')
        assert e.store.queue_stats() == {'queued': 1}
        await run_job(e, e.store.claim())
        assert e.store.task(task['id'])['status'] == 'completed'


async def test_durable_queue_survives_worker_restart(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path)
    store = WorkflowStore(tmp_path / 'tasks.sqlite')
    task_id = store.submit(payload(settings), key='durable')
    first = store.claim()  # Process dies after claiming, before graph invocation.
    assert first['task_id'] == task_id
    async with make_engine(settings) as e:
        e.store.recover_jobs()
        await run_job(e, e.store.claim())
        task = e.store.task(task_id)
        assert task['status'] == 'awaiting_approval'
        e.store.enqueue_approval(task_id, task['digest'], 'approve')
        e.store.claim()  # Another process death after the decision transaction commits.
    async with make_engine(settings) as e:
        e.store.recover_jobs()
        await run_job(e, e.store.claim())
        assert e.store.task(task_id)['status'] == 'completed'
        assert len(await e.remote.list_comments(2)) == 1
        assert e.store.submit(payload(settings), key='durable') == task_id


def test_queue_concurrent_claim_and_backpressure(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path)
    store = WorkflowStore(tmp_path / 'tasks.sqlite')
    store.submit(payload(settings), limit=1)
    with pytest.raises(DomainError, match='queue_full'):
        store.submit(payload(settings), limit=1)
    assert len(store.list_tasks()) == 1
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: store.claim(), range(2)))
    assert sum(r is not None for r in results) == 1


def test_worker_lock_prevents_second_graph_owner(tmp_path):
    with WorkerLease(tmp_path):
        with pytest.raises(DomainError, match='worker_already_running'):
            with WorkerLease(tmp_path):
                pass
    with WorkerLease(tmp_path):
        pass


def test_existing_database_preserved_but_old_approval_not_executable(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path)
    legacy = Store(tmp_path / 'tasks.sqlite')
    tid, _ = legacy.create(payload(settings))
    legacy.update(tid, 'awaiting_approval', result={'actions': []}, digest='a' * 64)
    modern = WorkflowStore(tmp_path / 'tasks.sqlite')
    assert modern.task(tid)['digest'] == 'a' * 64
    with pytest.raises(DomainError, match='legacy_plan_requires_reanalysis'):
        modern.approve(tid, 'a' * 64, 'approve')
    assert modern.task(tid)['result'] == {'actions': []}


def webhook_client(tmp_path):
    return TestClient(create_app(Settings(_env_file=None, data_dir=tmp_path,
        tool_mode='github', embedded_worker=False, api_token='private', webhook_secret='test-secret')))


def send_event(client, body=None, delivery='delivery-1', event='issues', signature=None):
    body = body or {'repository': {'full_name': 'Shahuang123269/-1'},
                    'action': 'opened', 'issue': {'number': 2}}
    data = json.dumps(body).encode()
    sig = signature or 'sha256=' + hmac.new(b'test-secret', data, hashlib.sha256).hexdigest()
    return client.post('/webhooks/github', content=data, headers={
        'X-Hub-Signature-256': sig, 'X-GitHub-Delivery': delivery, 'X-GitHub-Event': event})


def test_signed_webhook_dedup_scope_and_auth(tmp_path):
    with webhook_client(tmp_path) as client:
        assert send_event(client, signature='sha256=bad').status_code == 401
        first = send_event(client)
        assert first.status_code == 202
        assert first.json()['id'] == send_event(client).json()['id']
        assert client.get('/tasks').status_code == 401
        auth = {'Authorization': 'Bearer private'}
        assert len(client.get('/tasks', headers=auth).json()['items']) == 1
        other = {'repository': {'full_name': 'someone/else'}, 'action': 'opened', 'issue': {'number': 2}}
        assert send_event(client, other).status_code == 403
        changed = {'repository': {'full_name': 'Shahuang123269/-1'}, 'action': 'opened', 'issue': {'number': 3}}
        assert send_event(client, changed).status_code == 409
        assert len(client.get('/tasks', headers=auth).json()['items']) == 1


def test_webhook_ignores_pr_bot_and_nontrigger_events(tmp_path):
    with webhook_client(tmp_path) as client:
        for extra in [ {'issue': {'number': 2, 'pull_request': {}}},
                       {'sender': {'type': 'Bot'}}, {'action': 'closed'}]:
            body = {'repository': {'full_name': 'Shahuang123269/-1'}, 'action': 'opened',
                    'issue': {'number': 2}, **extra}
            assert send_event(client, body).json()['status'] == 'ignored'


def test_api_accepts_without_worker_and_resumes_on_startup(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path, embedded_worker=False)
    with TestClient(create_app(settings)) as client:
        r = client.post('/tasks', json={'issue_number': 1})
        assert r.status_code == 202 and r.json()['status'] == 'queued'
        task = r.json()
    settings.embedded_worker = True
    with TestClient(create_app(settings)) as client:
        assert wait_task(client, task)['status'] == 'completed'
        # Task completion is committed just before the job acknowledgement.
        # Observe eventual acknowledgement instead of racing the worker's final SQL.
        deadline = time.monotonic() + 5
        while client.get('/queue').json().get('done', 0) != 1:
            assert time.monotonic() < deadline, 'job was never acknowledged'
            time.sleep(0.02)


async def test_new_webhook_invalidates_pending_plan_and_own_output_detection(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path)
    async with make_engine(settings) as e:
        task = await e.create(TaskRequest(issue_number=2, propose_actions=True))
        tid = e.store.submit(payload(settings), delivery='changed', payload_hash='hash')
        assert e.store.task(task['id'])['status'] == 'needs_review'
        assert tid != task['id']
        with pytest.raises(DomainError, match='stale_approval'):
            e.store.enqueue_approval(task['id'], task['digest'], 'approve')
        assert not e.store.own_comment(2, settings.repository, '<!-- issue-agent:fake -->')

async def test_closed_after_approval_is_stale(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path)
    async with make_engine(settings) as e:
        task = await e.create(TaskRequest(issue_number=2, propose_actions=True))
        original = e.remote.get_issue
        async def closed(number):
            return {**await original(number), 'state': 'closed'}
        e.remote.get_issue = closed
        result = await e.approve(task['id'], task['digest'], 'approve')
        assert result['status'] == 'needs_review'
        assert await e.remote.list_comments(2) == []
