"""Set the shared public origin before building iOS and Windows distributions."""
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit


def configure(value):
    value=value.strip().rstrip('/')
    url=urlsplit(value)
    if url.scheme!='https' or not url.hostname or url.username or url.password or url.path or url.query or url.fragment:
        raise ValueError('Provide the deployed HTTPS origin, without a path or credentials.')
    target=Path(__file__).resolve().parents[1]/'crier'/'connection-service.json'
    target.write_text(json.dumps({'url':value})+'\n',encoding='utf-8')
    return target


if __name__=='__main__':
    if len(sys.argv)!=2: raise SystemExit('Usage: python scripts/configure_connection_service.py https://your-service-host')
    print(configure(sys.argv[1]))
