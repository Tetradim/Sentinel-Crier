"""Run intercepted-HTTP customer acceptance; never measures real customer latency."""
import argparse
import json
import math
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
REQUIRED={
 'test_customer_alerts_first_receipt_exact_option_values_and_reconnect',
 'test_customer_uncertain_receipt_survives_reconnect_without_resend',
 'test_customer_live_read_consent_does_not_require_completing_paper_practice',
}


def summarize(path,returncode):
    cases=list(ET.parse(path).getroot().iter('testcase'))
    passed=failures=errors=skipped=0; timings={}; confirmed=set()
    for case in cases:
        seconds=float(case.get('time','0'))
        if not math.isfinite(seconds) or seconds<0: raise ValueError('Invalid duration evidence')
        if case.find('failure') is not None: failures+=1
        elif case.find('error') is not None: errors+=1
        elif case.find('skipped') is not None: skipped+=1
        else:
            passed+=1; confirmed.add(case.get('name',''))
            if case.get('name') in REQUIRED: timings[case.get('name')]=seconds
    missing=sorted(REQUIRED-confirmed)
    status='failed' if returncode or failures or errors or missing else 'passed_with_skips' if skipped else 'passed'
    return dict(status=status,passed=passed,failures=failures,errors=errors,skipped=skipped,
                missing_required=missing,timing_scope='offline_intercepted_http_test_cases',
                offline_case_seconds=timings,real_customer_first_success='not_measured',
                real_broker_requests=0,real_discord_messages=0,physical_acceptance=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(); output=args.output.resolve(); output.mkdir(parents=True,exist_ok=True)
    try:
        source=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True,stderr=subprocess.DEVNULL).strip()
        clean=not subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()
    except (OSError,subprocess.CalledProcessError): source='unavailable'; clean=False
    xml=output/'customer-acceptance.xml'
    started=time.monotonic()
    result=subprocess.run([sys.executable,'-m','pytest','tests/test_customer_acceptance.py','tests/test_customer_guide_ui.py','-q',f'--junitxml={xml}'],cwd=ROOT,check=False)
    report=summarize(xml,result.returncode)
    report.update(source_commit=source,source_clean_at_start=clean,offline_runner_seconds=time.monotonic()-started)
    (output/'customer-acceptance.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,sort_keys=True))
    return 1 if report['status']=='failed' else 0


if __name__=='__main__': raise SystemExit(main())
