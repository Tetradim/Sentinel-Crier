"""Bundle source/build files and notices for the optional Windows tray dependencies."""
import argparse
from importlib import metadata
import json
from pathlib import Path
import shutil


def bundle(destination, *, distribution=metadata.distribution):
    destination=Path(destination)
    tray=distribution('pystray')
    if tray.version!='0.19.5':
        raise ValueError('Tray version does not match the bundled upstream build files')
    sources=[Path(f) for f in tray.files or [] if Path(f).parts[0]=='pystray' and Path(f).suffix=='.py' and '..' not in Path(f).parts]
    if not sources:
        raise ValueError('Missing tray source files')
    assets=Path(__file__).with_name('third-party')/'pystray'
    target=destination/'pystray'
    shutil.copytree(assets,target,dirs_exist_ok=True)
    for file in sources:
        output=target/'lib'/file
        output.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(tray.locate_file(file),output)
    versions={'pystray':tray.version}
    for name in ('pillow','six'):
        dependency=distribution(name)
        licenses=[f for f in dependency.files or [] if Path(f).name=='LICENSE' and '.dist-info' in str(f)]
        if not licenses:
            raise ValueError(f'Missing {name} license')
        output=destination/name/'LICENSE'; output.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(dependency.locate_file(licenses[0]),output)
        versions[name]=dependency.version
    shutil.copyfile(Path(__file__).with_name('THIRD_PARTY_NOTICES.md'),destination/'README.md')
    (destination/'bundle.json').write_text(json.dumps({'versions':versions,'tray_source_files':len(sources)},indent=2),encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('destination',type=Path)
    bundle(parser.parse_args().destination)
