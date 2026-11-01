import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace
from crier.desktop import DesktopApp
from test_desktop_policy_ui import Worker,descendants


def test_trading_activity_has_scrollable_controls(desktop_tk_root):
    root=tk.Toplevel(desktop_tk_root);root.withdraw()
    try:
        app=DesktopApp(root,Worker())
        widgets=list(descendants(app.activity))
        assert any(isinstance(w,tk.Canvas) for w in widgets)
        assert any(isinstance(w,ttk.Scrollbar) for w in widgets)
    finally:root.destroy()


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


def test_bank_pool_save_refuses_changed_selection(desktop_tk_root):
    root=tk.Toplevel(desktop_tk_root);root.withdraw();worker=Worker();app=DesktopApp(root,worker)
    worker.connections=SimpleNamespace(selected='alice',routes=lambda:[dict(id='alice',label='Alice')])
    try:
        app.show_account_bank(dict(enabled=True,environment='paper',balance={},active=[],history=[],
            policies={a:dict(mode='dollars',value='100') for a in ('stock','option')},fees={'stock':'1','option':'2'}))
        dialog=next(w for w in root.winfo_children() if isinstance(w,tk.Toplevel))
        worker.connections.selected='dave'
        next(w for w in descendants(dialog) if isinstance(w,ttk.Button) and w.cget('text')=='Save pool').invoke()
        assert not worker.calls
        assert 'original connection' in app.notice.get()
    finally:root.destroy()


def test_trading_workspace_navigation_and_commands_at_scaled_window(desktop_tk_root):
    root=tk.Toplevel(desktop_tk_root);root.withdraw();worker=Worker();app=DesktopApp(root,worker)
    scale=root.tk.call('tk','scaling')
    try:
        root.tk.call('tk','scaling',2.0)
        root.geometry('1080x780');root.deiconify();app.tabs.select(app.activity);root.update()
        navigation=app.trading_navigation
        assert [navigation.tab(tab,'text') for tab in navigation.tabs()]==['Order','Positions','Activity']
        for tab in navigation.tabs():
            navigation.select(tab);root.update()
            assert navigation.winfo_ismapped()
        assert all(str(button['state'])=='disabled' for button in app.host_buttons)
        navigation.select(navigation.tabs()[0]);root.update()
        worker.calls.clear()
        # Disconnected entry controls cannot submit an instruction.
        app.host_buttons[0].invoke()
        assert not worker.calls
        # The original host command guard also protects direct invocations.
        app.command('cancel')
        assert not worker.calls
    finally:
        root.tk.call('tk','scaling',scale)
        root.destroy()


def test_manual_provider_return_uses_pending_origin_dispatch_after_route_switch(desktop_tk_root):
    root=tk.Toplevel(desktop_tk_root);root.withdraw();worker=Worker()
    worker.connections=SimpleNamespace(selected='alice',routes=lambda:[dict(id='alice',label='Alice'),dict(id='dave',label='Dave')])
    app=DesktopApp(root,worker)
    try:
        worker.connections.selected='dave'
        uri='sentinelcrier://oauth/complete?flow='+'x'*43
        app.provider_return.set(uri)
        app.complete_provider()
        assert worker.calls[-1][:2]==('provider_return',(uri,))
        assert app.provider_return.get()==''
    finally:root.destroy()
