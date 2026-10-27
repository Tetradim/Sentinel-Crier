import json
import pytest
from desktop.self_test_entry import run


def test_windowed_self_test_failure_returns_safe_report_instead_of_error_dialog(tmp_path):
    path=tmp_path/'failure.json'
    def fail():raise RuntimeError('SECRET_KEY')
    with pytest.raises(SystemExit) as failure:run(fail,['--self-test','--report',str(path)])
    assert failure.value.code==1
    content=path.read_text(encoding='utf-8')
    assert 'SECRET_KEY' not in content
    report=json.loads(content)
    assert report['ok'] is False and report['exception_type']=='RuntimeError'
    assert report['stack'][-1]['file']=='test_self_test_entry.py'


def test_normal_application_failure_is_not_swallowed_by_self_test_entry():
    def fail():raise ValueError('failure')
    with pytest.raises(ValueError):run(fail,[])
