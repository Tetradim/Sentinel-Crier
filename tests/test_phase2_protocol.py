"""Language-independent wire examples used by each native client."""
import json
from pathlib import Path
import pytest
from crier.intent_protocol import IntentEvent

FIXTURES=json.loads((Path(__file__).parent/'fixtures/phase2-protocol.json').read_text())

@pytest.mark.parametrize('case',FIXTURES['cases'],ids=lambda c:c['name'])
def test_shared_wire_contract(case):
    event=dict(FIXTURES['base'],**case['changes'])
    if case['valid']:
        IntentEvent.model_validate(event)
    else:
        with pytest.raises(ValueError):
            IntentEvent.model_validate(event)
