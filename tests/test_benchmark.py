import json

import pytest

from issue_agent.benchmark import load_snapshot, score, validate_single
from issue_agent.policy import fingerprint


def snapshot(tmp_path):
    data = {'repository': 'example/repo', 'issue': {'number': 1, 'title': 'Bug', 'body': 'Actual',
            'html_url': 'https://github.com/example/repo/issues/1', 'updated_at': '2026-10-01T00:00:00Z'},
            'comments': [{'id': 1, 'body': 'Edited after cutoff', 'html_url': 'https://example.test/1',
                          'created_at': '2026-10-01T00:00:00Z', 'updated_at': '2026-10-03T00:00:00Z'}]}
    path = tmp_path / 'snapshot.json'
    path.write_text(json.dumps({'case_id': 'A01', 'data': data, 'content_sha256': fingerprint(data),
                               'fetched_at': '2026-10-04T00:00:00Z'}), encoding='utf-8')
    return path


def test_snapshot_rejects_tampering_and_unavailable_historical_body(tmp_path):
    path = snapshot(tmp_path)
    with pytest.raises(ValueError, match='historical_body_unavailable'):
        load_snapshot(path, '2026-09-30T00:00:00Z')
    content = json.loads(path.read_text())
    content['data']['issue']['body'] = 'tampered'
    path.write_text(json.dumps(content))
    with pytest.raises(ValueError, match='snapshot_hash_mismatch'):
        load_snapshot(path)


def test_future_edited_comments_excluded(tmp_path):
    case = load_snapshot(snapshot(tmp_path), '2026-10-02T00:00:00Z')
    assert case['comments'] == [] and case['excluded_comments'] == 1


def test_unreviewed_or_mismatched_gold_never_becomes_accuracy():
    assert score({}, {}, 'hash', 'cutoff') is None
    assert score({}, {'status': 'pending_human_review'}, 'hash', 'cutoff') is None
    with pytest.raises(ValueError, match='gold_snapshot_or_cutoff_mismatch'):
        score({}, {'status': 'human_reviewed', 'reviewer': 'owner'}, 'hash', 'cutoff')
    result = score({'category': 'bug', 'missing_fields': ['environment', 'actual']},
                   {'status': 'human_reviewed', 'reviewer': 'owner', 'snapshot_hash': 'hash',
                    'cutoff': 'cutoff', 'category': 'bug', 'missing_fields': ['environment']},
                   'hash', 'cutoff')
    assert result['unnecessary_requests'] == 1 and not result['missing_exact']


def test_single_baseline_enforces_field_evidence(tmp_path):
    case = load_snapshot(snapshot(tmp_path))
    with pytest.raises(ValueError, match='invalid_field_findings'):
        validate_single({'actions': [], 'evidence': [], 'field_findings': [],
                         'category': 'bug', 'missing_fields': []}, case)
