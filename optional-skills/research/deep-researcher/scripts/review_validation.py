"""Review coverage and explicit limitations; these checks cannot establish semantic truth."""
from __future__ import annotations

import json
from pathlib import Path
import re

from review_signals import SIGNALS, normalized

LIMITATION = re.compile(r'\b(unverified|unknown|uncertain|limited|unsupported|unresolved|not established|not confirmed|not verified|not final|no independent|single[- ](?:source|origin))\b', re.IGNORECASE)
FINAL_LIMIT = re.compile(r'\b(final(?:ity| status)?|definitive)\b.{0,65}\b(unverified|unknown|uncertain|not established|not confirmed|not verified)\b|\bnot\b.{0,35}\b(final|definitive)\b', re.IGNORECASE)
INDEPENDENCE_LIMIT = re.compile(r'single[- ](?:origin|source)|no independent|not independently|independen\w*.{0,40}(?:unverified|unknown|not established|not confirmed)', re.IGNORECASE)


def _qualification(item: dict, qualification: str, report: str) -> None:
    kind = item.get('kind')
    if not LIMITATION.search(qualification):
        raise ValueError('Qualification must explicitly disclose a limitation, not repeat the assertion')
    if kind == 'finality' and not FINAL_LIMIT.search(qualification):
        raise ValueError('Finality needs an explicit unverified/unknown final-status limitation; otherwise revise the report')
    if kind == 'independence' and not INDEPENDENCE_LIMIT.search(qualification):
        raise ValueError('Independence needs an explicit single-origin or unverified-independence limitation')
    if kind == 'entity' and normalized(item['text']) not in normalized(qualification):
        raise ValueError('Entity qualification must name the unverified entity')
    if kind in {'entity', 'finality'}:
        paragraphs = report.split('\n\n')
        if not any(normalized(item['context']) in normalized(p) and normalized(qualification) in normalized(p) for p in paragraphs):
            raise ValueError('Place this explicit limitation in the same report paragraph as the assertion')


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
    if item['status'] == 'qualified':
        _qualification(item, qualification, report)
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



def _identity(expected: dict, review) -> None:
    if not isinstance(review, dict):
        raise ValueError('Semantic review must be a JSON object')
    for key in ('kind', 'report_sha256', 'ledger_sha256', 'report', 'evidence'):
        if review.get(key) != expected[key]:
            raise ValueError('Semantic review is stale or source material changed; prepare RUN --replace, then review again')


def item_errors(original: dict, decision: dict, expected: dict, label: str) -> list[str]:
    try:
        ids = _decision(decision, expected['report'], expected['evidence'])
        if label == 'claim':
            if set(ids) - set(original.get('evidence_ids', [])):
                raise ValueError('Use evidence linked to this claim')
            if re.search(r'\d', original['text']):
                scope = decision.get('scope_note')
                if not isinstance(scope, str) or len(scope.strip()) < 20:
                    raise ValueError('Numeric scope_note must explain period, population/geography, units and any denominator/comparison')
            if decision['status'] == 'verified':
                for kind, pattern in SIGNALS.items():
                    match = pattern.search(original['text'])
                    if match:
                        _assertion_support({**decision, 'kind': kind, 'text': match.group()}, ids, expected['evidence'])
        else:
            _assertion_support(decision, ids, expected['evidence'])
    except ValueError as exc:
        return [f"{original['id']} ({original.get('kind', label)}: {original['text'][:80]}): {exc}"]
    return []


def review_errors(expected: dict, review: dict, allow_pending: bool = False) -> list[str]:
    from semantic_review import CHECKS
    _identity(expected, review)
    errors = []
    if not isinstance(review.get('reviewer'), str) or not review['reviewer'].strip():
        errors.append('reviewer: name the person or model performing the review')
    checks = review.get('checks')
    if not isinstance(checks, dict) or set(checks) != set(CHECKS):
        errors.append('checks: review finality, independence, entities and numbers; prepare again after helper upgrades')
    else:
        for key, value in checks.items():
            if allow_pending and isinstance(value, dict) and value.get('status') == 'pending':
                continue
            if not isinstance(value, dict) or value.get('status') != 'checked' or not isinstance(value.get('note'), str) or not value['note'].strip():
                errors.append(f'{key}: checked status and a specific review note are required')
    for label in ('claim', 'assertion'):
        try:
            pairs = _decisions(expected[label + 's'], review.get(label + 's'), label)
        except ValueError as exc:
            errors.append(f'{label}s: {exc}')
            continue
        for original, decision in pairs:
            if allow_pending and decision.get('status') == 'pending':
                continue
            errors.extend(item_errors(original, decision, expected, label))
    return errors


def inspect_review(root: Path) -> tuple[dict, dict, list[str]]:
    from research_run import safe_path
    from semantic_review import packet
    expected, _ = packet(root)
    review = json.loads(safe_path(root, 'semantic-review.json').read_text(encoding='utf-8'))
    return expected, review, review_errors(expected, review)
