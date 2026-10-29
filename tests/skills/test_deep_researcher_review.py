"""Regression contracts from the live research review, exercised through the CLI."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / 'optional-skills/research/deep-researcher/scripts'


def cli(*args, ok=True):
    result = subprocess.run([sys.executable, str(SCRIPTS / 'semantic_review.py'), *map(str, args)],
                            capture_output=True, text=True, check=False)
    assert (result.returncode == 0) == ok, result.stdout + result.stderr
    return result


@pytest.fixture
def dossier(tmp_path):
    from tests.skills.test_deep_researcher_workflow import init, add_batch, draft
    root = init(tmp_path)
    add_batch(root)
    draft(root)
    return root


def prepare(root, text=None):
    if text:
        (root / 'report.md').write_text(text + '\n\n## References\n1. [Dataset](https://example.org/data)\n')
    cli('prepare', root, '--replace')
    return json.loads((root / 'semantic-review.json').read_text())


def ready(packet):
    packet['reviewer'] = 'Fixture reviewer'
    for check in packet['checks'].values():
        check.update(status='checked', note='Compared the synthetic report with retained passages.')
    for item in packet['claims']:
        item.update(status='verified', note='Passage reports the stated growth.',
                    scope_note='Growth in the observed sample; source period unspecified; percentage, no cross-series denominator.')
    return packet


def save(root, packet):
    (root / 'semantic-review.json').write_text(json.dumps(packet), encoding='utf-8')


def test_repeated_same_line_entity_has_one_stable_review_id(dossier):
    packet = prepare(dossier, 'The dataset mentions Cyprus twice: Cyprus is unverified; Cyprus remains unverified. [1]')
    ids = [i['id'] for i in packet['assertions']]
    assert len(ids) == len(set(ids))
    entries = [i for i in packet['assertions'] if i['text'] == 'Cyprus']
    assert len(entries) == 1
    again = prepare(dossier)
    assert [i['id'] for i in again['assertions']] == ids
    ready(packet)
    for item in packet['assertions']:
        item.update(status='qualified', note='Name was not established from retained passages.',
                    qualification='Cyprus is unverified')
    save(dossier, packet)
    cli('check', dossier)


def test_dates_and_demonyms_do_not_hide_real_organizations(dossier):
    packet = prepare(dossier, 'In June and March, H1 German and French figures mention MCEI and Alpine Research Agency. [1]')
    names = {i['text'] for i in packet['assertions'] if i['kind'] == 'entity'}
    assert not names.intersection({'June', 'March', 'H1', 'German', 'French'})
    assert {'MCEI', 'Alpine Research Agency'} <= names


@pytest.mark.parametrize('qualification', ['Final EHPA figures', 'Single-origin evidence.'])
def test_finality_restatement_or_unrelated_caveat_is_rejected(dossier, qualification):
    packet = ready(prepare(dossier, 'Final EHPA figures show growth. [1]\n\nSingle-origin evidence.'))
    for item in packet['assertions']:
        item.update(status='qualified', note='No source states finality.', qualification=qualification)
    save(dossier, packet)
    result = cli('check', dossier, ok=False)
    assert 'finality' in result.stderr.lower() or 'final' in result.stderr.lower()


def test_explicit_local_finality_limitation_is_accepted(dossier):
    packet = ready(prepare(dossier, 'Final status is unverified; the dataset reports growth of 10%. [1]'))
    for item in packet['assertions']:
        item.update(status='qualified', note='The source does not establish final status.',
                    qualification='Final status is unverified')
    save(dossier, packet)
    cli('check', dossier)


def test_compact_view_and_atomic_decision_application(dossier):
    packet = prepare(dossier)
    view = json.loads(cli('show', dossier, '--max-chars', '3000').stdout)
    assert len(json.dumps(view, ensure_ascii=False)) <= 3000
    assert 'report' not in view and 'evidence' not in view
    assert any(item['id'] == 'C001' for item in view['items'])
    ready(packet)
    payload = {key: packet[key] for key in ['report_sha256', 'ledger_sha256', 'reviewer', 'checks']}
    payload['claims'] = [{key: item[key] for key in ['id', 'status', 'note', 'evidence_ids', 'scope_note']}
                         for item in packet['claims']]
    payload['assertions'] = []
    path = dossier / 'decisions.json'
    path.write_text(json.dumps(payload))
    cli('apply', dossier, path)
    initial = (dossier / 'semantic-review.json').read_bytes()
    cli('apply', dossier, path)
    assert (dossier / 'semantic-review.json').read_bytes() == initial
    cli('check', dossier)
    before = (dossier / 'semantic-review.json').read_bytes()
    payload['claims'].append({'id': 'missing', 'status': 'verified', 'note': 'invalid', 'evidence_ids': ['S1E1']})
    path.write_text(json.dumps(payload))
    cli('apply', dossier, path, ok=False)
    assert (dossier / 'semantic-review.json').read_bytes() == before


def test_apply_rejects_stale_material_without_reusing_approval(dossier):
    packet = prepare(dossier)
    payload = {key: packet[key] for key in ['report_sha256', 'ledger_sha256']}
    payload.update(reviewer='Fixture reviewer', claims=[], assertions=[], checks={})
    path = dossier / 'decisions.json'
    path.write_text(json.dumps(payload))
    before = (dossier / 'semantic-review.json').read_bytes()
    with (dossier / 'report.md').open('a') as stream:
        stream.write('\nNew interpretation.\n')
    cli('apply', dossier, path, ok=False)
    assert (dossier / 'semantic-review.json').read_bytes() == before
    fresh = prepare(dossier)
    assert all(i['status'] == 'pending' for i in fresh['claims'])


def test_check_reports_all_unresolved_items_and_numeric_scope(dossier):
    packet = ready(prepare(dossier))
    packet['claims'][0]['scope_note'] = ''
    packet['checks']['finality']['status'] = 'pending'
    packet['checks']['entities']['status'] = 'pending'
    save(dossier, packet)
    result = cli('check', dossier, ok=False)
    assert all(word in result.stderr for word in ['finality', 'entities', 'C001', 'scope'])


def test_same_entity_on_distinct_lines_keeps_distinct_contexts(dossier):
    packet = prepare(dossier, 'The dataset names Cyprus. [1]\nAnother text names Cyprus. [1]')
    entries = [i for i in packet['assertions'] if i['text'] == 'Cyprus']
    assert len(entries) == 2 and entries[0]['id'] != entries[1]['id']


def test_selected_view_shows_passages_and_reports_omissions(dossier):
    prepare(dossier)
    view = json.loads(cli('show', dossier, '--ids', 'C001', '--max-chars', '5000').stdout)
    assert [i['id'] for i in view['items']] == ['C001']
    assert view['passages'][0]['id'] == 'S1E1'
    assert '10%' in view['passages'][0]['excerpt']
    assert 'numeric_review' in view['items'][0]


def test_apply_valid_partial_decision_leaves_other_requirements_pending(dossier):
    packet = prepare(dossier)
    payload = {key: packet[key] for key in ['report_sha256', 'ledger_sha256']}
    payload.update(reviewer='Fixture reviewer', checks={'numbers': {'status': 'checked', 'note': 'Reviewed sample percentage scope.'}})
    path = dossier / 'partial.json'
    path.write_text(json.dumps(payload))
    result = json.loads(cli('apply', dossier, path).stdout)
    assert result['saved'] and not result['ready']
    cli('check', dossier, ok=False)


def test_article_prefix_keeps_known_names_known_and_flags_unknown_agency(dossier):
    packet = prepare(dossier, 'The Dataset reports growth. The Alpine Research Agency disagrees. [1]')
    names = {i['text'] for i in packet['assertions'] if i['kind'] == 'entity'}
    assert 'Dataset' not in names and 'The Dataset' not in names
    assert 'Alpine Research Agency' in names
