"""Acceptance check for an already running fixture-only API + separate worker."""
import argparse
import time
import uuid

import httpx


def main(args):
    with httpx.Client(base_url=args.url, timeout=5, trust_env=False,
                      headers={"Authorization": "Bearer " + args.token}) as client:
        deadline = time.monotonic() + 60
        while True:
            try:
                response = client.get('/health')
                response.raise_for_status()
                health = response.json()
                break
            except httpx.HTTPError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(1)
        assert health['tool_mode'] == health['model_mode'] == 'fixture', 'fixture only'
        body = {'issue_number': 2, 'propose_actions': True}
        headers = {'Idempotency-Key': uuid.uuid4().hex}
        created = client.post('/tasks', json=body, headers=headers)
        assert created.status_code == 202
        tid = created.json()['id']
        assert client.post('/tasks', json=body, headers=headers).json()['id'] == tid

        def wait(status):
            until = time.monotonic() + 40
            while time.monotonic() < until:
                task = client.get('/tasks/' + tid).json()
                if task['status'] == status:
                    return task
                assert task['status'] not in {'failed', 'needs_review', 'reconciliation_needed'}, task
                time.sleep(0.2)
            raise AssertionError('worker did not complete the command')

        task = wait('awaiting_approval')
        response = client.post('/tasks/' + tid + '/plan', json={
            'digest': task['digest'], 'actions': [{'kind': 'comment', 'labels': [],
                                                'body': 'Deployment smoke: please provide OS version.'}]})
        response.raise_for_status()
        edited = response.json()
        assert edited['plan_version'] == 2
        assert client.post('/tasks/' + tid + '/approval', json={
            'digest': task['digest'], 'decision': 'approve'}).status_code == 409
        assert client.post('/tasks/' + tid + '/approval', json={
            'digest': edited['digest'], 'decision': 'approve'}).status_code == 202
        final = wait('completed')
        assert len(final['actions']) == 1 and final['actions'][0]['status'] == 'verified'
        print('deployment smoke passed: queue -> worker -> edited plan -> approval -> verified output')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8000')
    parser.add_argument('--token', required=True)
    main(parser.parse_args())
