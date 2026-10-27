"""Explicit release signing. Private keys never enter a manifest or native bundle."""
import argparse
import base64
import getpass
import hashlib
import json
import os
from pathlib import Path
import re

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', value):
        raise ValueError('Invalid update version')
    parts = tuple(map(int, value.split('.')))
    if max(parts) > 65535:
        raise ValueError('Invalid update version')
    return parts


def signed_release(installer, target, commit, minimum, maximum, notes, policy, key, key_id):
    if not (version(minimum) <= version(maximum) < version(target)) or not notes or len(notes) > 4000:
        raise ValueError('Explicit tested source range and migration/recovery notes are required')
    if not re.fullmatch('[a-f0-9]{40}', commit) or not isinstance(key, Ed25519PrivateKey):
        raise ValueError('Invalid signing source')
    public = base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
    if policy.get('enabled') is not True or policy.get('repository') != 'Tetradim/Sentinel-Crier' or policy.get('public_keys', {}).get(key_id) != public:
        raise ValueError('Signing key does not match enabled bundled trust policy')
    installer = Path(installer)
    name = f'SentinelCrier-{target}-Windows-Setup.exe'
    if installer.name != name or installer.is_symlink() or not installer.is_file() or not 0 < installer.stat().st_size <= 512*1024*1024:
        raise ValueError('Invalid installer artifact')
    with installer.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    payload = dict(schema=1, version=target, platform='windows-x64', source_commit=commit,
                   release_tag='v'+target, installer=dict(name=name,
                   url=f'https://github.com/Tetradim/Sentinel-Crier/releases/download/v{target}/{name}',
                   bytes=installer.stat().st_size, sha256=digest),
                   compatibility=dict(min_source_version=minimum,max_source_version=maximum,
                                      profile_generation=1,protocol_generation=1),notes=notes)
    raw = json.dumps(payload,sort_keys=True,separators=(',',':')).encode()
    return dict(schema=1,key_id=key_id,payload=base64.b64encode(raw).decode(),signature=base64.b64encode(key.sign(raw)).decode())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action',required=True)
    generate = sub.add_parser('generate-key')
    generate.add_argument('--output',type=Path,required=True)
    generate.add_argument('--key-id',required=True)
    sign = sub.add_parser('sign')
    for name in ('installer','release-manifest','notes','output'):
        sign.add_argument('--'+name,type=Path,required=True)
    sign.add_argument('--minimum-source',required=True)
    sign.add_argument('--maximum-source',required=True)
    sign.add_argument('--private-key-file',type=Path)
    args = parser.parse_args()
    try:
        if args.action == 'generate-key':
            dest = args.output.resolve()
            if dest.is_relative_to(ROOT) or not re.fullmatch('[A-Za-z0-9_-]{1,64}',args.key_id):
                raise ValueError('Private key must be outside the repository')
            password = getpass.getpass('New release-key password (12+ characters): ')
            if len(password) < 12 or password != getpass.getpass('Repeat password: '):
                raise ValueError('Password confirmation failed')
            key = Ed25519PrivateKey.generate()
            raw = key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.BestAvailableEncryption(password.encode()))
            with dest.open('xb') as stream:
                os.chmod(dest,0o600);stream.write(raw)
            public = base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)).decode()
            print(json.dumps({'public_keys':{args.key_id:public}}))
            return
        policy = json.loads((ROOT/'crier/update-policy.json').read_text())
        raw = args.private_key_file.read_bytes() if args.private_key_file else os.environ.get('CRIER_UPDATE_PRIVATE_KEY_PEM','').encode()
        password = os.environ.get('CRIER_UPDATE_KEY_PASSWORD','')
        if not raw or not password:
            raise ValueError('Protected signing key and password must be configured')
        key = serialization.load_pem_private_key(raw,password.encode())
        release = json.loads(args.release_manifest.read_text(encoding='utf-8-sig'))
        envelope = signed_release(args.installer, release['version'],release['commit'],args.minimum_source,
                                  args.maximum_source,args.notes.read_text(encoding='utf-8'),policy,key,os.environ.get('CRIER_UPDATE_KEY_ID',''))
        with args.output.open('x',encoding='utf-8') as stream:
            json.dump(envelope,stream,sort_keys=True);stream.write('\n')
        print('Signed public update manifest prepared')
    except Exception:
        parser.exit(1,'Release signing failed; inspect public policy, source range and protected signing configuration.\n')


if __name__ == '__main__':
    main()
