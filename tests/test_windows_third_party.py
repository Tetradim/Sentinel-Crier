import importlib.util
from pathlib import Path
from types import SimpleNamespace
import pytest


def helper():
    spec=importlib.util.spec_from_file_location('third_party',Path(__file__).resolve().parents[1]/'desktop/third_party.py')
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def distributions(tmp_path):
    roots={}
    for name,version,file in [('pystray','0.19.5','pystray/__init__.py'),('pillow','13.0.0','pillow.dist-info/licenses/LICENSE'),('six','1.17.0','six.dist-info/LICENSE')]:
        root=tmp_path/name; path=root/file; path.parent.mkdir(parents=True); path.write_text('original '+name)
        roots[name]=SimpleNamespace(version=version,files=[Path(file)],locate_file=lambda p,root=root:root/p)
    return roots


def test_package_includes_exact_sources_build_files_and_licenses(tmp_path):
    module=helper(); deps=distributions(tmp_path); out=tmp_path/'out'
    module.bundle(out,distribution=deps.__getitem__)
    assert (out/'pystray/lib/pystray/__init__.py').read_text()=='original pystray'
    assert (out/'pystray/COPYING.LGPL').is_file() and (out/'pystray/COPYING').is_file()
    assert (out/'pystray/setup.py').is_file()
    assert (out/'pillow/LICENSE').read_text()=='original pillow'
    assert (out/'six/LICENSE').read_text()=='original six'


def test_mismatched_tray_version_cannot_ship_with_the_wrong_source_build_files(tmp_path):
    module=helper(); deps=distributions(tmp_path); deps['pystray'].version='9.0.0'
    with pytest.raises(ValueError,match='version'): module.bundle(tmp_path/'out',distribution=deps.__getitem__)


def test_missing_source_cannot_silently_produce_an_incomplete_bundle(tmp_path):
    module=helper(); deps=distributions(tmp_path); deps['pystray'].files=[]
    with pytest.raises(ValueError,match='source'): module.bundle(tmp_path/'out',distribution=deps.__getitem__)
