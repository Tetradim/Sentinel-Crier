import importlib.util
from pathlib import Path
import pytest


def module():
    spec=importlib.util.spec_from_file_location('customer_acceptance',Path('scripts/customer_acceptance.py'))
    value=importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value


def xml(tmp_path,extra=''):
    names=('test_customer_alerts_first_receipt_exact_option_values_and_reconnect','test_customer_uncertain_receipt_survives_reconnect_without_resend','test_customer_live_read_consent_does_not_require_completing_paper_practice')
    path=tmp_path/'results.xml'
    path.write_text('<testsuites><testsuite>'+''.join(f'<testcase name="{n}" time="0.25"/>' for n in names)+extra+'</testsuite></testsuites>')
    return path


def test_report_names_timing_scope_and_does_not_claim_real_first_success(tmp_path):
    report=module().summarize(xml(tmp_path),0)
    assert report['status']=='passed' and report['passed']==3
    assert report['timing_scope']=='offline_intercepted_http_test_cases'
    assert report['real_customer_first_success']=='not_measured'
    assert set(report['offline_case_seconds'].values())=={0.25}


def test_skips_and_failures_are_not_counted_as_passes(tmp_path):
    report=module().summarize(xml(tmp_path,'<testcase name="gui" time="0"><skipped/></testcase>'),0)
    assert report['status']=='passed_with_skips' and report['skipped']==1 and report['passed']==3
    report=module().summarize(xml(tmp_path,'<testcase name="gui" time="0"><failure/></testcase>'),1)
    assert report['status']=='failed' and report['failures']==1


def test_empty_or_invalid_duration_evidence_cannot_report_success(tmp_path):
    value=module(); path=tmp_path/'results.xml'; path.write_text('<testsuites/>')
    assert value.summarize(path,0)['status']=='failed'
    path=xml(tmp_path,'<testcase name="bad" time="NaN"/>')
    with pytest.raises(ValueError): value.summarize(path,0)
