#!/usr/bin/env python3
"""Prepare and validate an explicit claim/evidence review; never infer semantic truth."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

KIND = 'deep-research-semantic-review-v1'
CHECKS = ('finality', 'independence', 'entities')
SIGNALS = {'finality': re.compile(r'\b(final|finalised|finalized|definitive)\b', re.IGNORECASE),
           'independence': re.compile(r'\b(independen\w*|corroborat\w*)\b', re.IGNORECASE)}
ENTITY = re.compile(r'\b(?:[A-Z][a-z]+(?:/[A-Za-z]+)+|[A-Z][A-Z0-9]{1,}|[A-Z][a-z]{2,}(?:[ -]+[A-Z][a-z]{2,})*)\b')


def normalized(text: str) -> str:
    return ' '.join(text.casefold().split())


def evidence_index(data: dict) -> dict:
    result = {}
    for source in data['sources']:
        for item in source.get('evidence', []):
            result[item['id']] = {**item, 'source_id': source['id'], 'url': source['url'],
                'title': source['title'], 'independence_group': source.get('independence_group'),
                'independence_assessed': source.get('independence_assessed', False),
                'independence_note': source.get('independence_note', '')}
    return result


def assertions(report: str, data: dict) -> list[dict]:
    known = normalized(' '.join(str(source.get(key, '')) for source in data['sources']
                               for key in ('title', 'publisher', 'author')) + ' ' +
                       ' '.join(e['excerpt'] for source in data['sources'] for e in source.get('evidence', [])))
    found = []
    in_fence = False
    for number, line in enumerate(report.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith('```'):
            in_fence = not in_fence
        if stripped.lower() in {'## references', '## citation links', '## bibliography'}:
            break
        if in_fence or stripped.startswith('#'):
            continue
        for kind, pattern in SIGNALS.items():
            matches = list(pattern.finditer(line))
            if matches:
                found.append(_assertion(kind, matches[0].group(), number, line))
        for match in ENTITY.finditer(line):
            text = match.group()
            # Sentence-initial capitalization is not a named-entity assertion.
            initial = not line[:match.start()].strip(' -*|') or line[:match.start()].rstrip().endswith(('.', '!', '?'))
            if re.search(r'(?<!\w)' + re.escape(normalized(text)) + r'(?!\w)', known) or (initial and not text.isupper() and '/' not in text):
                continue
            found.append(_assertion('entity', text, number, line))
    return found


def _assertion(kind: str, text: str, line: int, context: str) -> dict:
    key = hashlib.sha256(f'{kind}\0{line}\0{text}'.encode()).hexdigest()[:16]
    return {'id': key, 'kind': kind, 'text': text, 'line': line, 'context': context,
            'status': 'pending', 'evidence_ids': [], 'note': '', 'qualification': ''}


def packet(root: Path) -> tuple[dict, dict]:
    from evidence_ledger import read_ledger, validate
    from research_run import digest, safe_path
    ledger_path = safe_path(root, 'evidence.json')
    report_path = safe_path(root, 'report.md')
    data = read_ledger(ledger_path)
    errors, _ = validate(data)
    if errors:
        raise ValueError('Fix the ledger before semantic review: ' + '; '.join(errors))
    report = report_path.read_text(encoding='utf-8')
    claims = [{'id': c['id'], 'text': c['text'], 'status': 'pending',
               'evidence_ids': c.get('evidence_ids', []), 'claim_status': c['status'],
               'importance': c.get('importance', 'major'), 'caveat': c.get('caveat', ''),
               'note': '', 'qualification': ''} for c in data['claims']]
    return {'kind': KIND, 'report_sha256': digest(report_path), 'ledger_sha256': digest(ledger_path),
            'reviewer': '', 'report': report, 'evidence': evidence_index(data), 'claims': claims,
            'assertions': assertions(report, data),
            'checks': {key: {'status': 'pending', 'note': ''} for key in CHECKS}}, data


def _decisions(expected: list[dict], actual, label: str) -> list[tuple[dict, dict]]:
    if not isinstance(actual, list) or len(actual) != len(expected):
        raise ValueError(f'Semantic review must cover every {label} exactly once')
    if any(not isinstance(item, dict) or not isinstance(item.get('id'), str) for item in actual):
        raise ValueError(f'Invalid {label} review entries')
    by_id = {item.get('id'): item for item in actual}
    if len(by_id) != len(actual) or set(by_id) != {item['id'] for item in expected}:
        raise ValueError(f'Missing, duplicate or unknown {label} review IDs')
    result = []
    for item in expected:
        decision = by_id[item['id']]
        for key in ('text', 'kind', 'line', 'context', 'claim_status', 'importance', 'caveat'):
            if key in item and decision.get(key) != item[key]:
                raise ValueError(f'Review changed the original {label} statement')
        result.append((item, decision))
    return result


def _decision(item: dict, report: str, evidence: dict) -> list[str]:
    if item.get('status') not in {'verified', 'qualified'} or not isinstance(item.get('note'), str) or not item['note'].strip():
        raise ValueError('Every review item needs verified/qualified status and a substantive note')
    ids = item.get('evidence_ids')
    if not isinstance(ids, list) or any(not isinstance(key, str) or key not in evidence for key in ids):
        raise ValueError('Review references unknown evidence IDs')
    if item['status'] == 'qualified':
        qualification = item.get('qualification', '')
        if not isinstance(qualification, str) or len(qualification.strip()) < 8 or normalized(qualification) not in normalized(report):
            raise ValueError('Qualified findings need their explicit limitation verbatim in the report')
    elif not ids:
        raise ValueError('Verified findings require precise supporting evidence IDs')
    return ids


def _assertion_support(item: dict, ids: list[str], evidence: dict) -> None:
    if item['status'] != 'verified':
        return
    passages = ' '.join(evidence[key]['excerpt'] for key in ids)
    if item['kind'] == 'finality' and not re.search(r'\b' + re.escape(item['text']) + r'\b', passages, re.IGNORECASE):
        raise ValueError('A finality label needs a retained passage that explicitly states that label')
    if item['kind'] == 'entity' and normalized(item['text']) not in normalized(passages):
        raise ValueError('An entity needs a retained passage naming it, or an explicit unverified qualification')
    if item['kind'] == 'independence':
        groups = {evidence[key].get('independence_group') for key in ids
                  if evidence[key].get('independence_assessed') and evidence[key].get('independence_note', '').strip()}
        if len(groups - {None, ''}) < 2:
            raise ValueError('Independent corroboration needs two explicitly assessed origins, or a qualification')


def check(root: Path) -> dict:
    from research_run import safe_path
    expected, data = packet(root)
    review = json.loads(safe_path(root, 'semantic-review.json').read_text(encoding='utf-8'))
    if not isinstance(review, dict):
        raise ValueError('Semantic review must be a JSON object')
    for key in ('kind', 'report_sha256', 'ledger_sha256', 'report', 'evidence'):
        if review.get(key) != expected[key]:
            raise ValueError('Semantic review is stale or its source material was modified; prepare it again')
    if not isinstance(review.get('reviewer'), str) or not review['reviewer'].strip():
        raise ValueError('Name the person or model that performed the semantic review')
    checks = review.get('checks', {})
    if not isinstance(checks, dict) or set(checks) != set(CHECKS):
        raise ValueError('Review finality, source independence and all named entities')
    for value in checks.values():
        if not isinstance(value, dict) or value.get('status') != 'checked' or not isinstance(value.get('note'), str) or not value['note'].strip():
            raise ValueError('Each semantic checklist item needs checked status and a review note')
    claims = {c['id']: c for c in data['claims']}
    for original, decision in _decisions(expected['claims'], review.get('claims'), 'claim'):
        ids = _decision(decision, expected['report'], expected['evidence'])
        if set(ids) - set(claims[original['id']].get('evidence_ids', [])):
            raise ValueError('Claim review must use evidence linked to that claim')
    for _, decision in _decisions(expected['assertions'], review.get('assertions'), 'assertion'):
        ids = _decision(decision, expected['report'], expected['evidence'])
        _assertion_support(decision, ids, expected['evidence'])
    return {'reviewer': review['reviewer'], 'claims_reviewed': len(review['claims']),
            'assertions_reviewed': len(review['assertions']),
            'note': 'Review records are attestations; structural validation cannot establish semantic truth.'}


def main() -> None:
    from research_run import load, safe_path
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'check'))
    parser.add_argument('run', type=Path)
    parser.add_argument('--replace', action='store_true', help='Replace a stale review packet after editing evidence/report')
    args = parser.parse_args()
    try:
        data = load(args.run)
        if data['status'] == 'archived':
            raise ValueError('Restore the run before reviewing it')
        if args.action == 'prepare':
            path = safe_path(args.run, 'semantic-review.json')
            if path.exists() and not args.replace:
                raise ValueError('Review already exists; use --replace to prepare a fresh packet')
            content, _ = packet(args.run)
            with path.open('w' if args.replace else 'x', encoding='utf-8') as stream:
                json.dump(content, stream, indent=2, ensure_ascii=False)
            print(f'Prepared {path}; review the passages and fill decisions and checklist notes. No item was approved automatically.')
        else:
            print(json.dumps(check(args.run), ensure_ascii=False))
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f'ERROR: {exc}\n')


if __name__ == '__main__':
    main()
