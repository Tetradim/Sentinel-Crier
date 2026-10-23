"""Provision an isolated synthetic PAPER transport channel, then revoke its receivers.

No broker client, trading credentials, Discord destination or real orders are used.
Credentials remain in memory and are never included in the aggregate report.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import time
from uuid import uuid4
import httpx


def check(base):
    report={'endpoint':base,'checked_at':datetime.now(timezone.utc).isoformat(),
            'scope':'synthetic paper relay only; no broker connections', 'checks':{}}
    receivers=[]
    host=None
    with httpx.Client(base_url=base.rstrip('/')+'/',timeout=35,trust_env=False,follow_redirects=False) as client:
        def request(method,path,token=None,body=None,expected=200):
            response=client.request(method,path,headers={'Authorization':'Bearer '+token} if token else {},json=body)
            if response.status_code!=expected:
                raise RuntimeError(f'{method} {path.split("?")[0]} returned {response.status_code}; expected {expected}')
            return response.json()
        try:
            health=request('GET','health')
            assert health=={'status':'ok','pairing_enabled':True,'protocol':1}
            report['checks']['health']=True
            host=request('POST','api/connect/host',body={'name':'Synthetic transport check - no brokerage','environment':'paper'})['token']
            for _ in range(2):
                code=request('POST','api/connect/invite',host)['code']
                receivers.append(request('POST','api/connect/receive',body={'code':code,'environment':'paper'})['token'])
            report['checks']['independent_pairing']=True
            request('GET','api/sync/events?after=0&wait=0',expected=401)
            request('GET','api/sync/events?after=0&wait=0',host,expected=401)
            report['checks']['authentication_and_role_isolation']=True
            now=datetime.now(timezone.utc)
            event=dict(version=1,event_id=str(uuid4()),trade_id=str(uuid4()),sequence=1,
                       action='enter',environment='paper',symbol='AAPL',asset='stock',quantity=1,
                       limit_price='0.01',created_at=now.isoformat(),expires_at=(now+timedelta(seconds=20)).isoformat())
            started=time.perf_counter()
            published=request('POST','api/sync/events',host,event)
            duplicate=request('POST','api/sync/events',host,event)
            assert duplicate['cursor']==published['cursor']
            for receiver in receivers:
                read=request('GET','api/sync/events?after=0&wait=0',receiver)
                assert len(read['events'])==1 and read['events'][0]['event']==event
                assert read['events'][0]['cursor']==published['cursor']
            report['checks']['exact_payload_and_idempotency']=True
            report['publish_duplicate_and_two_reads_ms']=round((time.perf_counter()-started)*1000,3)
            rows=request('GET','api/connect/receivers',host)
            request('POST','api/connect/receivers/'+rows[0]['id']+'/revoke',host)
            codes=[client.get('api/sync/events?after=0&wait=0',headers={'Authorization':'Bearer '+token}).status_code for token in receivers]
            assert sorted(codes)==[200,401]
            report['checks']['independent_revocation']=True
        finally:
            if host:
                for row in request('GET','api/connect/receivers',host):
                    request('POST','api/connect/receivers/'+row['id']+'/revoke',host)
                report['test_receivers_revoked']=True
    report['passed']=True
    return report


def main():
    from scripts.configure_connection_service import validate
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('endpoint')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    try:
        report=check(validate(args.endpoint))
    except Exception as error:
        report={'passed':False,'error_type':type(error).__name__}
    text=json.dumps(report,indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(text+'\n',encoding='utf-8')
    print(text)
    return 0 if report['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
