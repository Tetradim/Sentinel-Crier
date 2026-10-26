from concurrent.futures import Future
import tkinter as tk
from tkinter import ttk
import pytest
from crier.desktop import DesktopApp


class Worker:
    def __init__(self): self.calls=[]
    def call(self,method,*args,**kwargs):
        future=Future(); self.calls.append((method,args,kwargs,future)); return future


def descendants(parent):
    for child in parent.winfo_children():
        yield child
        yield from descendants(child)


def test_policy_editor_explicitly_saves_paused_without_connecting(desktop_tk_root):
    root=tk.Toplevel(desktop_tk_root); root.withdraw(); worker=Worker()
    app=DesktopApp(root,worker)
    try:
        app.latest={'connected':True,'pair':{'role':'follower'},'execution':{'settings':{'execution_policy':None}}}
        app.edit_execution_policy()
        dialog=next(w for w in root.winfo_children() if isinstance(w,tk.Toplevel))
        widgets=list(descendants(dialog))
        sizing=next(w for w in widgets if isinstance(w,ttk.Combobox))
        sizing.set('source')
        next(w for w in widgets if isinstance(w,ttk.Button) and w.cget('text')=='Save policy and pause new entries').invoke()
        method,args,_,future=worker.calls[-1]
        assert method=='settings' and args[0]['enabled'] is False
        assert args[0]['execution_policy']['mode']=='source'
        assert args[0]['execution_policy']['entry_timeout_seconds'] is None
        assert all(call[0] not in ('connect','command') for call in worker.calls)
    finally:
        root.destroy()


def test_host_cannot_open_follower_editor(desktop_tk_root):
    root=tk.Toplevel(desktop_tk_root); root.withdraw(); worker=Worker(); app=DesktopApp(root,worker)
    try:
        app.latest={'connected':True,'pair':{'role':'host'}}
        app.edit_execution_policy()
        assert not any(isinstance(w,tk.Toplevel) for w in root.winfo_children())
        assert not worker.calls
    finally: root.destroy()
