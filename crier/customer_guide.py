"""Static, read-only practice content; it has no account or permission state."""
from dataclasses import dataclass
import json
from pathlib import Path

SUPPORT_URL='https://github.com/Tetradim/Sentinel-Crier/issues'


@dataclass(frozen=True)
class PracticeStep:
    title: str
    body: str


@dataclass(frozen=True)
class PracticeJourney:
    id: str
    title: str
    steps: tuple[PracticeStep,...]


@dataclass(frozen=True)
class PracticeGuide:
    notice: str
    privacy: str
    journeys: tuple[PracticeJourney,...]

    def text(self, purpose):
        journey=next((j for j in self.journeys if j.id==purpose),None)
        if journey is None:
            raise ValueError('Unknown practice purpose')
        lines=[self.notice,journey.title]
        for index,step in enumerate(journey.steps,1):
            lines.extend([f'{index}. {step.title}',step.body])
        return '\n\n'.join(lines+[self.privacy])


def _keys(value,expected):
    if not isinstance(value,dict) or set(value)!=set(expected):
        raise ValueError('Invalid practice guide fields')


def _text(value,limit):
    if not isinstance(value,str) or not value.strip() or len(value)>limit or any(ord(c)<32 for c in value):
        raise ValueError('Invalid practice text')
    return value


def parse_guide(text):
    value=json.loads(text)
    _keys(value,('version','notice','privacy','journeys'))
    if type(value['version']) is not int or value['version']!=1 or not isinstance(value['journeys'],list) or len(value['journeys'])!=3:
        raise ValueError('Unsupported practice guide')
    journeys=[]
    for journey in value['journeys']:
        _keys(journey,('id','title','steps'))
        if journey['id'] not in ('alerts','trade','follow') or not isinstance(journey['steps'],list) or not 3<=len(journey['steps'])<=8:
            raise ValueError('Invalid practice journey')
        steps=[]
        for step in journey['steps']:
            _keys(step,('title','body'))
            steps.append(PracticeStep(_text(step['title'],100),_text(step['body'],1200)))
        journeys.append(PracticeJourney(journey['id'],_text(journey['title'],100),tuple(steps)))
    if {j.id for j in journeys}!={'alerts','trade','follow'}:
        raise ValueError('Duplicate practice purpose')
    return PracticeGuide(_text(value['notice'],1200),_text(value['privacy'],1200),tuple(journeys))


def load_guide():
    return parse_guide(Path(__file__).with_name('customer-practice.json').read_text(encoding='utf-8'))
