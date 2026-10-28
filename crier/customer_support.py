"""Public support context; deliberately excludes account/configuration data."""
from pathlib import Path
import platform
from .desktop_updates import current_version
from .error_log import read_build_info


def support_details():
    info=read_build_info(Path(__file__).with_name('build-info.json')) or {}
    return {'version':current_version(),'source':info.get('commit','development build'),
            'platform':platform.system(),'url':'https://github.com/Tetradim/Sentinel-Crier/issues'}
