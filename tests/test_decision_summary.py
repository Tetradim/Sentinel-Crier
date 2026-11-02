import json
from pathlib import Path
import pytest
from crier.decision_summary import describe_decisions

CASES = json.loads((Path(__file__).parent / 'fixtures/decision-summary.json').read_text())['cases']

@pytest.mark.parametrize('case', CASES, ids=lambda c: c['id'])
def test_shared_decision_summary(case):
    assert describe_decisions(case['timeline'], case.get('limit', 8)) == case['expected']

@pytest.mark.parametrize('limit', [None, True, '999999', float('inf'), {}, [], -10, 0, 999999])
def test_bounds_privacy_and_no_mutation(limit):
    rows = [{'stage': 'sender' if i % 2 else 'receiver', 'details': {'status': 'SECRET'}} for i in range(100)]
    before = json.dumps(rows)
    result = describe_decisions(rows, limit)
    assert 1 <= len(result) <= 20
    assert 'SECRET' not in str(result)
    assert json.dumps(rows) == before

@pytest.mark.parametrize('rows', [None, 17, 'SECRET', [None, {}, 42, {'stage': ['filled']} ]])
def test_malformed_evidence_is_private(rows):
    result = describe_decisions(rows)
    assert result and len(result) <= 8
    assert 'SECRET' not in str(result)
