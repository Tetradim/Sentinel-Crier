import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace
from crier.desktop import DesktopApp
from test_desktop_policy_ui import Worker,descendants


def test_bank_editor_keeps_active_old_ids_and_saved_fee(desktop_tk_root):
    root=tk.Toplevel(desktop_tk_root);root.withdraw();worker=Worker();app=DesktopApp(root,worker)
    worker.connections=SimpleNamespace(routes=lambda:[dict(id='alice',label='Alice')])
    row=dict(id=1,route='alice',symbol='SPY261218C00750000',units=3,pending_buy_units=0,pending_exit_units=0)
    try:
        app.show_account_bank(dict(enabled=True,environment='paper',balance={},active=[row],history=[],
            policies={a:dict(mode='dollars',value='100') for a in ('stock','option')},fees={'stock':'1','option':'2'}))
        dialog=next(w for w in root.winfo_children() if isinstance(w,tk.Toplevel))
        widgets=list(descendants(dialog))
        table=next(w for w in widgets if isinstance(w,ttk.Treeview))
        assert len(table.get_children())==1
        assert 'Alice' in table.item(table.get_children()[0])['values']
        entries=[w.get() for w in widgets if isinstance(w,ttk.Entry)]
        assert '2' in entries
        next(w for w in widgets if isinstance(w,ttk.Button) and w.cget('text')=='Save pool').invoke()
        assert worker.calls[-1][:2]==('bank_configure',('stock','dollars','100','1'))
        assert all(call[0] not in ('command','connect') for call in worker.calls)
    finally:root.destroy()


def test_recovery_shows_difference_and_refuses_check_after_route_switch(desktop_tk_root):
    root=tk.Toplevel(desktop_tk_root);root.withdraw();worker=Worker();app=DesktopApp(root,worker)
    worker.connections=SimpleNamespace(selected='alice')
    try:
        app.show_recovery_assistant(dict(explanation='Unresolved',steps=[],ids=[],positions_checked_at='2026-10-31',
            positions=[dict(symbol='SPY',host_owned=3,external_baseline=0,expected=3,broker=2,difference=-1)]))
        dialog=next(w for w in root.winfo_children() if isinstance(w,tk.Toplevel))
        widgets=list(descendants(dialog))
        table=next(w for w in widgets if isinstance(w,ttk.Treeview))
        assert table.item(table.get_children()[0])['values']==['SPY',3,0,3,2,-1]
        buttons=[w for w in widgets if isinstance(w,ttk.Button)]
        assert len(buttons)==1
        worker.connections.selected='dave'
        buttons[0].invoke()
        assert not worker.calls
    finally:root.destroy()
