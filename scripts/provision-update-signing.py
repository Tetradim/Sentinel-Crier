"""Explicit one-time publisher bootstrap. Prints public state only."""
import argparse
import base64
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from crier.device_secrets import save_secret
from crier.relay_backup import _private_directory

REPOSITORY='Tetradim/Sentinel-Crier'
NAMES=('CRIER_UPDATE_PRIVATE_KEY_PEM','CRIER_UPDATE_KEY_PASSWORD','CRIER_UPDATE_KEY_ID')


def provision(root,state_root,*,run=subprocess.run):
    def gh(arguments,*,value=None):
        result=run(['gh',*arguments,'--repo',REPOSITORY],input=value,capture_output=True,check=True)
        return result.stdout
    existing=json.loads(gh(['secret','list','--json','name']))
    if any(item['name'] in NAMES for item in existing):
        raise ValueError('Existing release authority must be rotated explicitly')
    policy_path=Path(root)/'crier/update-policy.json'
    policy=json.loads(policy_path.read_text())
    if policy.get('enabled') or policy.get('public_keys'):
        raise ValueError('Existing update trust must be rotated explicitly')
    directory=_private_directory(state_root)
    backup=directory/'publisher-key.secret'
    if backup.exists():raise ValueError('Publisher backup already exists; inspect it before bootstrap')
    password=secrets.token_urlsafe(48)
    key=Ed25519PrivateKey.generate()
    key_id='crier-'+secrets.token_hex(6)
    private=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.BestAvailableEncryption(password.encode())).decode()
    public=base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)).decode()
    save_secret(backup,json.dumps({'schema':1,'key_id':key_id,'encrypted_private_key_pem':private,'password':password,'public_key':public}))
    # Secret values use stdin, never process arguments, stdout or repository files.
    for name,value in zip(NAMES,(private,password,key_id)):
        gh(['secret','set',name],value=value.encode())
    policy.update(enabled=True,public_keys={key_id:public})
    temporary=policy_path.with_suffix('.new')
    with temporary.open('x',encoding='utf-8') as stream:json.dump(policy,stream,indent=2);stream.write('\n')
    os.replace(temporary,policy_path)
    return {'configured':True,'repository':REPOSITORY,'key_id':key_id,'protected_backup':str(backup)}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply-github',action='store_true',help='Explicitly provision three new repository Actions secrets')
    args=parser.parse_args()
    if not args.apply_github:parser.error('--apply-github is required; no keys were generated')
    if os.name!='nt':parser.error('This bootstrap stores the private backup using Windows DPAPI')
    try:
        root=Path(__file__).resolve().parents[1]
        state=Path(os.environ['LOCALAPPDATA'])/'SentinelCrier/ReleaseSigning'
        print(json.dumps(provision(root,state)))
    except Exception:
        parser.exit(1,'Publisher bootstrap failed. No private material was printed; preserve the protected backup and inspect repository secret names before retrying.\n')
