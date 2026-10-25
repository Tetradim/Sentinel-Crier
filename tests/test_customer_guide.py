import copy
import json
from pathlib import Path
import pytest
from crier.customer_guide import load_guide, parse_guide


def test_bundled_guide_covers_three_purposes_without_permission_state():
    guide=load_guide()
    assert [journey.id for journey in guide.journeys]==['alerts','trade','follow']
    assert all(3<=len(j.steps)<=8 for j in guide.journeys)
    assert 'optional' in guide.notice.lower()
    assert 'API keys' in guide.privacy
    assert 'suppressed baseline' in guide.text('alerts')
    assert 'design-only' in guide.text('follow')
    assert not hasattr(guide,'enabled') and not hasattr(guide,'completed')


@pytest.mark.parametrize('change',[lambda v:v.update(version=True),lambda v:v.update(version=2),lambda v:v.update(enabled=True),lambda v:v['journeys'].pop(),lambda v:v['journeys'][1].update(id='alerts'),lambda v:v['journeys'][0]['steps'][0].update(body=42),lambda v:v['journeys'][0]['steps'][0].update(action='submit'),lambda v:v['journeys'][0].update(steps=[])])
def test_invalid_guide_cannot_be_interpreted_as_an_action_or_partial_setup(change):
    value=json.loads(Path('crier/customer-practice.json').read_text())
    change(value)
    with pytest.raises(ValueError): parse_guide(json.dumps(value))


def test_guide_formatting_does_not_mutate_input_or_create_unknown_purpose():
    value=json.loads(Path('crier/customer-practice.json').read_text()); original=copy.deepcopy(value)
    guide=parse_guide(json.dumps(value)); assert '1. Connect a paper account' in guide.text('alerts')
    assert value==original
    with pytest.raises(ValueError): guide.text('execute')
