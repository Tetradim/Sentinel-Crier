"""One main-thread Tcl interpreter for desktop tests; do not mask Windows UI failures."""
import gc
import sys
import tkinter as tk
import pytest


@pytest.fixture(scope='session')
def desktop_tk_root():
    try:
        root=tk.Tk()
    except tk.TclError as exc:
        if sys.platform=='win32':
            pytest.fail(f'Windows desktop acceptance requires working Tk: {exc}')
        pytest.skip(f'Tk display unavailable: {exc}')
    root.withdraw()
    yield root
    root.destroy()
    gc.collect()


@pytest.fixture(autouse=True)
def desktop_event_cleanup(request):
    yield
    if 'desktop_tk_root' in request.fixturenames:
        root=request.getfixturevalue('desktop_tk_root')
        for token in root.tk.call('after','info'):
            root.after_cancel(token)
        gc.collect()
