"""Windows update controller; broker shutdown remains owned by DesktopApp."""
import json
from pathlib import Path
from uuid import uuid4

from .relay_backup import _private_directory
from .updates import UpdateClient, UpdateError
from .update_install import prepare_install
from .update_recovery import restore_backup, validate_backup


def load_policy():
    path=Path(__file__).with_name('update-policy.json')
    if path.stat().st_size > 65536:
        raise UpdateError('Invalid update trust configuration')
    return json.loads(path.read_text(encoding='utf-8'))


def current_version():
    import sys
    from .error_log import read_build_info
    info=read_build_info(Path(__file__).with_name('build-info.json')) or {}
    if info.get('version'):
        return info['version']
    if getattr(sys,'frozen',False):
        raise UpdateError('Cannot identify installed build')
    from importlib.metadata import version
    return version('sentinel-crier')


class DesktopUpdates:
    def __init__(self,profile,version=None,*,policy=None):
        self.profile=Path(profile)
        self.policy=load_policy() if policy is None else policy
        self.root=self.profile.parent/'Updates'
        self.backups=self.profile.parent/'Recovery'
        self.client=UpdateClient(self.policy,version or current_version(),staging_root=self.root)
        self.state={'status':'unchecked'}

    def check(self):
        try:
            self.state=self.client.check()
            return dict(self.state)
        except Exception:
            self.state={'status':'error'}
            raise UpdateError('Cannot authenticate an update. Nothing was installed.') from None

    def download(self):
        if self.state.get('status')!='available':
            raise UpdateError('Check for an authenticated update first')
        try:
            _private_directory(self.root)
            self.client.download()
            self.state={**self.state,'status':'ready'}
            return dict(self.state)
        except Exception:
            self.state={'status':'error'}
            raise UpdateError('Update download failed verification. Nothing was installed.') from None

    def prepare(self,*,worker_closed=False):
        if not worker_closed or self.state.get('status')!='ready':
            raise UpdateError('Close and drain broker workers before installing an update')
        _private_directory(self.root)
        return prepare_install(self.client,self.profile,self.backups,self.policy.get('publisher_thumbprints',[]),
                               self.root/('install-'+uuid4().hex+'.json'),locked_profile=True)

    def cancel(self):
        self.client.cancel()

    def inspect_backup(self,path):
        manifest=validate_backup(Path(path))
        return {'status':'backup_valid','files':len(manifest.get('files',[]))}

    def recover(self,backup,parent):
        destination=Path(parent)/('Crier-restored-'+uuid4().hex[:12])
        restore_backup(Path(backup),destination)
        return {'status':'restored','path':str(destination)}
