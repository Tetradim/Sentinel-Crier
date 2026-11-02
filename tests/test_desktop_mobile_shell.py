import tkinter as tk
from types import SimpleNamespace
from crier.desktop import DesktopApp
from test_desktop_policy_ui import Worker


def app_at(parent):
    root=tk.Toplevel(parent); root.withdraw(); worker=Worker()
    worker.connections=SimpleNamespace(selected='alice',routes=lambda:[dict(id='alice',label='Alice')])
    return root,worker,DesktopApp(root,worker,check_updates=False)


def test_primary_mobile_navigation_selects_real_pages_without_network(desktop_tk_root):
    root,worker,app=app_at(desktop_tk_root)
    try:
        assert list(app.mobile_shell.navigation)==['Home','Markets','Trade','Positions','Orders']
        worker.calls.clear()
        for name,index in [('Trade',0),('Positions',1),('Orders',2)]:
            app.mobile_shell.navigation[name].invoke(); root.update_idletasks()
            assert app.tabs.select()==str(app.activity)
            assert app.trading_navigation.index('current')==index
        app.mobile_shell.navigation['Home'].invoke()
        assert app.tabs.select()==str(app.start_tab)
        app.mobile_shell.navigation['Markets'].invoke()
        assert app.tabs.select()==str(app.markets_tab)
        assert not worker.calls
    finally: root.destroy()


def test_account_hub_keeps_every_secondary_screen_reachable(desktop_tk_root):
    root,worker,app=app_at(desktop_tk_root)
    try:
        worker.calls.clear()
        for label,button in app.account_links.items():
            app.show_mobile_page('Account'); button.invoke()
            assert app.tabs.select()!=str(app.account_tab),label
        assert not worker.calls
    finally: root.destroy()


def test_stop_is_global_and_disables_order_controls_immediately(desktop_tk_root):
    root,worker,app=app_at(desktop_tk_root)
    try:
        app.connected=True
        for button in app.host_buttons+app.execution_buttons: button.configure(state='normal')
        app.mobile_shell.stop.invoke()
        assert worker.calls[-1][0]=='disconnect_all'
        assert all(str(button['state'])=='disabled' for button in app.host_buttons+app.execution_buttons)
        assert worker.calls[-1][-1] in app.connection_jobs
        assert not any(call[0]=='command' for call in worker.calls)
    finally: root.destroy()


def test_home_does_not_invent_balances_and_clears_account_on_route_change(desktop_tk_root):
    root,worker,app=app_at(desktop_tk_root)
    try:
        app.mobile_shell.render(dict(connected=True,environment='paper',account='account-alice'))
        app.home_overview.render(dict(execution=dict(trades=[{'id':'a'}],orders=[{}])))
        assert app.home_overview.balance.get()=='—'
        assert app.home_overview.trade_count.get()=='1'
        assert app.mobile_shell.environment.get()=='PAPER'
        app.reset_route_view()
        assert app.mobile_shell.environment.get()=='OFFLINE'
        assert app.home_overview.trade_count.get()=='0'
        assert 'alice' not in app.mobile_shell.account.get()
    finally: root.destroy()


def test_global_stop_survives_route_change_and_blocks_new_dispatch(desktop_tk_root):
    root,worker,app=app_at(desktop_tk_root)
    try:
        app.stop_all_connections(); stop=worker.calls[-1][-1]
        worker.connections.selected='dave'
        app.reset_route_view()
        assert stop in app.connection_jobs
        assert app.current_route_future(stop)
        before=len(worker.calls)
        app.submit('settings',{'enabled':True})
        app.command('enter')
        app.submit('connect','pair','key','secret')
        app.stop_all_connections()
        assert len(worker.calls)==before
    finally:root.destroy()


PAIR=dict(url='https://relay.example',token='x'*40,role='host',environment='paper')


def test_stop_invalidates_pre_stop_pairing_callback_even_after_shutdown_finishes(desktop_tk_root):
    root,worker,app=app_at(desktop_tk_root)
    try:
        app.quick_connect('host'); worker.calls[-1][-1].set_result({'pair':PAIR})
        app.stop_all_connections(); worker.calls[-1][-1].set_result([])
        app.refresh();root.update()
        assert not any(call[0]=='connect' for call in worker.calls)
    finally:root.destroy()


def test_stop_invalidates_already_queued_connect_continuation(desktop_tk_root):
    root,worker,app=app_at(desktop_tk_root)
    try:
        app.quick_connect('host')
        app.pending[-1][1]({'pair':PAIR})
        app.stop_all_connections(); worker.calls[-1][-1].set_result([])
        root.update()
        assert not any(call[0]=='connect' for call in worker.calls)
    finally:root.destroy()


def test_notice_and_stop_remain_visible_at_minimum_scaled_window(desktop_tk_root):
    root,worker,app=app_at(desktop_tk_root);scale=root.tk.call('tk','scaling')
    try:
        root.tk.call('tk','scaling',2.0);root.geometry('850x680');root.deiconify()
        app.notice.set('Execution paused. Inspect the original broker order before submitting another instruction.')
        root.update()
        assert app.notice_label.winfo_height()>10
        assert app.notice_label.winfo_rooty()+app.notice_label.winfo_height()<=app.mobile_shell.navigation['Home'].winfo_rooty()
        assert app.mobile_shell.stop.winfo_width()>=app.mobile_shell.stop.winfo_reqwidth()
    finally:
        root.tk.call('tk','scaling',scale);root.destroy()
