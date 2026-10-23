"""Set the shared public origin before building Android, iOS and Windows."""
import argparse
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit


def validate(value):
    value=value.strip().rstrip('/')
    url=urlsplit(value)
    if url.scheme!='https' or not url.hostname or url.username or url.password or url.path not in ('','/functions/v1/crier') or url.query or url.fragment:
        raise ValueError('Provide an HTTPS origin or exact /functions/v1/crier gateway, without credentials.')
    if url.port is not None and not 1 <= url.port <= 65535:
        raise ValueError('Invalid HTTPS port')
    return value


def probe(value, client=None):
    import httpx
    value=validate(value)
    owned=client is None
    client=client or httpx.Client(timeout=15,trust_env=False,follow_redirects=False)
    try:
        response=client.get(value+'/health',follow_redirects=False)
        response.raise_for_status()
        health=response.json()
        if health.get('status')!='ok' or health.get('protocol')!=1 or health.get('pairing_enabled') is not True:
            raise ValueError('Endpoint must report healthy protocol 1 with pairing enabled')
        return health
    finally:
        if owned: client.close()


def configure(value):
    value=validate(value)
    target=Path(__file__).resolve().parents[1]/'crier'/'connection-service.json'
    target.write_text(json.dumps({'url':value})+'\n',encoding='utf-8')
    return target


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('origin')
    parser.add_argument('--verify',action='store_true',help='Require a successful HTTPS readiness check before saving')
    args=parser.parse_args()
    if args.verify: probe(args.origin)
    print(configure(args.origin))
