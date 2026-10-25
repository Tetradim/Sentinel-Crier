"""Bounded device-local notification inbox; never stores credentials or proof.

Every dequeued URI must still pass the memory-only authenticated pending guard.
Windows LOCALAPPDATA provides the same-user boundary; no network listener.
"""
from pathlib import Path
import os
import secrets
from .oauth_return import parse_oauth_return


def enqueue_return(folder, uri):
    if parse_oauth_return(uri) is None: raise ValueError('Invalid provider return.')
    inbox=Path(folder)/'oauth-returns'
    inbox.mkdir(parents=True,exist_ok=True)
    if len(list(inbox.glob('*.return')))>=16: raise ValueError('Provider return inbox full.')
    identity=secrets.token_hex(16)
    temporary=inbox/(identity+'.pending')
    path=inbox/(identity+'.return')
    try:
        with temporary.open('x',encoding='ascii') as output:
            output.write(uri)
            output.flush()
        os.replace(temporary,path)
    finally:
        temporary.unlink(missing_ok=True)


def take_returns(folder):
    inbox=Path(folder)/'oauth-returns'
    if not inbox.exists(): return []
    result=[]
    for path in list(inbox.glob('*.return'))[:16]:
        try:
            if path.stat().st_size<=128:
                uri=path.read_text(encoding='ascii')
                if parse_oauth_return(uri): result.append(uri)
        except (OSError,UnicodeError): pass
        finally:
            try: path.unlink(missing_ok=True)
            except OSError: pass
    return result
