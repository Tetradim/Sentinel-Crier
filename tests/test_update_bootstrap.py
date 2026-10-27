import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def load():
    path=Path(__file__).resolve().parents[1]/'scripts/provision-update-signing.py'
    spec=importlib.util.spec_from_file_location('update_bootstrap',path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result


def test_bootstrap_keeps_private_values_out_of_policy_and_arguments(tmp_path,monkeypatch):
    module=load();root=tmp_path/'repo';(root/'crier').mkdir(parents=True)
    policy=root/'crier/update-policy.json';policy.write_text(json.dumps({'enabled':False,'public_keys':{}}))
    protected=[];commands=[]
    monkeypatch.setattr(module,'save_secret',lambda path,text:protected.append(json.loads(text)))
    def run(command,**kwargs):
        commands.append((command,kwargs.get('input')))
        return SimpleNamespace(stdout=b'[]')
    result=module.provision(root,tmp_path/'private',run=run)
    public=policy.read_text()
    assert result['configured'] and len(protected)==1
    assert protected[0]['password'] not in public and 'PRIVATE KEY' not in public
    assert len(commands)==4
    for command,secret in commands[1:]:
        assert secret and secret.decode() not in ' '.join(command)


def test_bootstrap_refuses_existing_authority_before_generating_key(tmp_path):
    module=load()
    def run(command,**kwargs):return SimpleNamespace(stdout=json.dumps([{'name':module.NAMES[0]}]).encode())
    with pytest.raises(ValueError,match='rotated explicitly'):module.provision(tmp_path/'repo',tmp_path/'private',run=run)
    assert not (tmp_path/'private').exists()
