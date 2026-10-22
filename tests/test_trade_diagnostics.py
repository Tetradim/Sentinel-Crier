import csv
import io
import json

import pytest

from crier.trade_diagnostics import export_trade_csv, export_trade_json
from crier.intent_device import IntentDevice
from crier.intent_engine import IntentEngine


def test_json_export_is_a_complete_document():
    assert json.loads(export_trade_json({'timeline': []})) == {'timeline': []}


@pytest.mark.parametrize('prefix', ['=', '+', '-', '@', '\t', '\r'])
def test_csv_escapes_spreadsheet_control_prefixes(prefix):
    report = {'timeline': [{'stage': prefix + 'formula', 'details': {}}]}
    rows = list(csv.DictReader(io.StringIO(export_trade_csv(report))))
    assert rows[0]['stage'] == "'" + prefix + 'formula'


def test_device_export_combines_local_transport_and_engine_evidence(tmp_path):
    device = IntentDevice(tmp_path)
    device.engine = IntentEngine(tmp_path / 'engine.sqlite3', None)
    device._trace('trade', 'relay_publish_acknowledged', event_id='event', http_status=200)
    device.engine._trace('trade', 'broker_reconciled', 'event', filled_qty='2')
    report = device.trade_report('trade')
    assert {r['stage'] for r in report['timeline']} == {'relay_publish_acknowledged', 'broker_reconciled'}
    assert all(r['event_id'] == 'event' for r in report['timeline'])
    assert json.loads(device.export_trade('trade')) == report
    assert len(list(csv.DictReader(io.StringIO(device.export_trade('trade', 'csv'))))) == 2
    with pytest.raises(ValueError):
        device.export_trade('missing')
    with pytest.raises(ValueError):
        device.export_trade('trade', 'xml')
