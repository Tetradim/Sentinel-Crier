import tkinter as tk

from crier.desktop_decisions import DecisionPanel


def state(account='one', trade='alice'):
    return dict(connected=True,account=account,environment='paper',execution=dict(trades=[dict(id=trade,event=dict(symbol='SPY',created_at='2026-11-02T10:00:00Z',sequence=1))]))


def panel(root):
    window=tk.Toplevel(root);window.withdraw();calls=[];epoch=[0]
    view=DecisionPanel(window,send=lambda *args,**kwargs:calls.append((args,kwargs)),epoch=lambda:epoch[0],details=lambda trade:None)
    return window,view,calls,epoch


def test_decisions_require_explicit_read_and_only_request_local_diagnostics(desktop_tk_root):
    window,view,calls,epoch=panel(desktop_tk_root)
    try:
        view.render_state(state())
        assert calls==[]
        view.load()
        assert calls[0][0]==('diagnostics','alice')
        calls[0][1]['callback'](dict(trade_id='alice',timeline=[dict(stage='broker_submit_started',details={})]))
        assert 'not confirmed' in view.summary.get().lower()
        assert 'sent' not in [args[0] for args,kw in calls]
    finally:window.destroy()


def test_other_account_or_selected_trade_cannot_receive_late_summary(desktop_tk_root):
    window,view,calls,epoch=panel(desktop_tk_root)
    try:
        view.render_state(state());view.load();callback=calls[-1][1]['callback']
        view.render_state(state(account='two',trade='bob'))
        callback(dict(trade_id='alice',timeline=[dict(stage='broker_submit_rejected',details={})]))
        assert 'rejected' not in view.summary.get().lower()
        view.load();callback=calls[-1][1]['callback'];epoch[0]+=1
        callback(dict(trade_id='bob',timeline=[dict(stage='broker_submit_rejected',details={})]))
        assert 'rejected' not in view.summary.get().lower()
    finally:window.destroy()


def test_unavailable_and_mismatched_evidence_clear_previous_result(desktop_tk_root):
    window,view,calls,epoch=panel(desktop_tk_root)
    try:
        view.render_state(state());view.load()
        calls[-1][1]['callback'](dict(trade_id='bob',timeline=[dict(stage='broker_submit_rejected',details={})]))
        assert 'rejected' not in view.summary.get().lower()
        view.render_state(dict(connected=False))
        view.load()
        assert len(calls)==1
        assert 'reconnect' in view.summary.get().lower()
        assert view.choice.get()==''
    finally:window.destroy()


def test_selection_change_rejects_old_read_even_within_one_account(desktop_tk_root):
    window,view,calls,epoch=panel(desktop_tk_root)
    try:
        value=state(); value['execution']['trades'].append(dict(id='bob',event=dict(symbol='QQQ',created_at='2026-11-02T09:00:00Z')))
        view.render_state(value);view.load();callback=calls[-1][1]['callback']
        view.choice.current(1);view.select()
        callback(dict(trade_id='alice',timeline=[dict(stage='broker_submit_rejected',details={})]))
        assert 'refused' not in view.summary.get().lower()
        view.load(); assert calls[-1][0]==('diagnostics','bob')
    finally:window.destroy()


def test_home_and_account_offer_readonly_decision_navigation(desktop_tk_root):
    from crier.desktop import DesktopApp
    from test_desktop_policy_ui import Worker,descendants
    from tkinter import ttk
    window=tk.Toplevel(desktop_tk_root);window.withdraw();worker=Worker()
    app=DesktopApp(window,worker,check_updates=False)
    try:
        worker.calls.clear()
        home=next(widget for widget in descendants(app.start_tab) if isinstance(widget,ttk.Button) and widget['text']=='What happened?')
        home.invoke()
        assert app.tabs.select()==str(app.health_tab)
        assert app.health_sections.select()==str(app.decision_tab)
        assert worker.calls==[]
        app.reset_route_view()
        assert app.decision_panel.selected is None
    finally:window.destroy()


def test_detailed_evidence_is_cleared_on_new_read_and_route_change(desktop_tk_root):
    from crier.desktop import DesktopApp
    from test_desktop_policy_ui import Worker
    window=tk.Toplevel(desktop_tk_root);window.withdraw();worker=Worker()
    app=DesktopApp(window,worker,check_updates=False)
    try:
        app.trades.insert('', 'end', iid='alice', values=('SPY',))
        app.trades.insert('', 'end', iid='bob', values=('QQQ',))
        app.trades.selection_set('alice')
        app.diagnostic_text.configure(state='normal');app.diagnostic_text.insert('1.0','OLD_ACCOUNT_EVIDENCE')
        app.diagnostic_text.configure(state='disabled')
        app.load_diagnostics(); callback=app.pending[-1][1]
        assert 'OLD_ACCOUNT' not in app.diagnostic_text.get('1.0','end')
        app.trades.selection_set('bob')
        callback(dict(trade_id='alice',premium_movement={},timeline=[]))
        assert 'Trade: alice' not in app.diagnostic_text.get('1.0','end')
        app.load_diagnostics();callback=app.pending[-1][1]
        app.reset_route_view()
        callback(dict(trade_id='bob',premium_movement={},timeline=[]))
        assert 'Trade: bob' not in app.diagnostic_text.get('1.0','end')
        assert 'current connection' in app.diagnostic_text.get('1.0','end')
    finally:window.destroy()
