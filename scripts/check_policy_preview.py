"""Check the H.5 design scenarios. No broker, settings or journal access."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from crier.policy_preview import preview_entry,preview_exit


def check(path):
    fixtures=json.loads(Path(path).read_text(encoding='utf-8'))
    if fixtures.get('version')!=1:
        raise ValueError('Unsupported scenario version')
    total=0
    for kind,function in (('entry',preview_entry),('exit',preview_exit)):
        for case in fixtures[kind]:
            result=function(**case['input'])
            if result['preview_only'] is not True or any(result[key]!=value for key,value in case['expected'].items()):
                raise ValueError('Scenario failed: '+case['id'])
            total+=1
    return dict(preview_only=True,scenarios=total,network_calls=0,orders_submitted=0,settings_written=0)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixtures',type=Path,default=ROOT/'tests/fixtures/policy-preview.json')
    print(json.dumps(check(parser.parse_args().fixtures),sort_keys=True))
