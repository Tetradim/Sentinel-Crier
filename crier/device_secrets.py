"""PC pairing secret storage. Windows uses user-bound DPAPI; Unix mode 0600."""
import base64
import ctypes
from ctypes import wintypes
import os
from pathlib import Path

class Blob(ctypes.Structure):
    _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_byte))]

def _crypt(data,decrypt=False):
    buffer=ctypes.create_string_buffer(data)
    source=Blob(len(data),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_byte))); output=Blob()
    function=ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not function(ctypes.byref(source),None,None,None,None,1,ctypes.byref(output)):
        raise OSError('Device credential protection failed')
    try: return ctypes.string_at(output.data,output.size)
    finally: ctypes.windll.kernel32.LocalFree(output.data)

def save_secret(path,text):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    data=text.encode(); prefix=b'plain:'
    if os.name=='nt': data=_crypt(data); prefix=b'dpapi:'
    temp=path.with_suffix('.tmp')
    with temp.open('wb') as file:
        os.chmod(temp,0o600); file.write(prefix+base64.b64encode(data)); file.flush(); os.fsync(file.fileno())
    os.replace(temp,path)

def load_secret(path):
    data=Path(path).read_bytes(); prefix,encoded=data.split(b':',1); raw=base64.b64decode(encoded)
    if prefix==b'dpapi': raw=_crypt(raw,True)
    elif prefix!=b'plain' or os.name=='nt': raise ValueError('Unsupported credential file')
    return raw.decode()
