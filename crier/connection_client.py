"""Host/Receive setup shared by desktop UI and offline integration tests."""
import json
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from .device_secrets import load_secret, save_secret
from .intent_routes import Pair
from .quick_connect import normalize_code


def validate_origin(value):
    value=value.strip()
    parsed=urlsplit(value)
    if (parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in ('','/')):
        raise ValueError('Set the deployed HTTPS connection-service address first.')
    return value.rstrip('/')


def default_origin():
    try:
        value=json.loads(Path(__file__).with_name('connection-service.json').read_text(encoding='utf-8'))['url']
        return validate_origin(value) if value else ''
    except (OSError, ValueError, KeyError):
        return ''


def parse_invitation(text, origin):
    text=text.strip()
    if '://' in text:
        url=urlsplit(text)
        if url.path!='/connect' or url.query or url.username or url.password:
            raise ValueError('Paste the invitation shared by the host.')
        return validate_origin(f'{url.scheme}://{url.netloc}'),normalize_code(url.fragment)
    return validate_origin(origin),normalize_code(text)


class ConnectionClient:
    def __init__(self, path, http=None, existing=None):
        self.path=Path(path)
        self.http=http
        self.existing=existing

    def saved(self):
        return json.loads(load_secret(self.path)) if self.path.exists() else self.existing

    async def request(self, origin, path, body=None, token=None):
        owned=self.http is None
        client=self.http or httpx.AsyncClient(timeout=20,trust_env=False,follow_redirects=False)
        try:
            response=await client.post(validate_origin(origin)+path,json=body,
                headers={'Authorization':'Bearer '+token} if token else {},follow_redirects=False)
            if response.status_code==401:
                raise ValueError('Pairing or invitation is unavailable. Ask the host for a fresh invitation.')
            if response.status_code==429:
                raise ValueError('Too many setup attempts. Try again later.')
            if response.status_code==503:
                raise ValueError('Connection setup is not enabled or available on this service.')
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, json.JSONDecodeError):
            raise ValueError('Cannot reach the connection service. Check its address and your network.') from None
        finally:
            if owned: await client.aclose()

    def store(self, origin, result, role):
        pair=Pair.model_validate(dict(url=validate_origin(origin),**result)).model_dump()
        if pair['role']!=role or not 32<=len(pair['token'])<=256:
            raise ValueError('Connection service returned an invalid pairing.')
        save_secret(self.path,json.dumps(pair))
        return pair

    async def host(self, origin, environment):
        pair=self.saved()
        if pair:
            if pair['role']!='host' or pair['environment']!=environment:
                raise ValueError('This device already has a different role or environment. Reuse its existing pairing.')
        else:
            origin=validate_origin(origin or default_origin())
            result=await self.request(origin,'/api/connect/host',{'name':'Crier host','environment':environment})
            if result.get('environment')!=environment:
                raise ValueError('Connection service environment mismatch.')
            pair=self.store(origin,result,'host')
        invitation=await self.request(pair['url'],'/api/connect/invite',token=pair['token'])
        code=normalize_code(invitation['code'])
        return {'pair':pair,'invitation':pair['url'].rstrip('/')+'/connect#'+code,'expires_at':invitation['expires_at']}

    async def receive(self, text, origin):
        pair=self.saved()
        if pair:
            if pair['role']!='follower' or text.strip():
                raise ValueError('This device is already paired. Clear the invitation field and reuse its saved Receive connection.')
            return {'pair':pair}
        origin,code=parse_invitation(text,origin or default_origin())
        result=await self.request(origin,'/api/connect/receive',{'code':code})
        return {'pair':self.store(origin,result,'follower')}
