"""Offline, hidden-window regressions for delivery row actions."""
from concurrent.futures import Future
import tkinter as tk

import pytest

from crier.desktop import DesktopApp


class Worker:
    def __init__(self):
        self.calls = []

    def call(self, method, *args, **kwargs):
        future = Future()
        self.calls.append((method, args, kwargs, future))
        return future


@pytest.fixture(scope='module')
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f'Tk display unavailable: {exc}')
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def app(tk_root):
    window = tk.Toplevel(tk_root)
    window.withdraw()
    desktop = DesktopApp(window, Worker())
    yield desktop
    window.destroy()


def status(*rows):
    return dict(enabled=False, settings=dict(format='card', show_quantity=True, show_time=True), history=list(rows))


def alert(identity, state='failed'):
    return dict(id=identity, created=100, status=state, fill=dict(contract='SPY', side='buy', quantity='2'), note='Inspect delivery')


def select(tree, identity):
    tree.selection_set(identity)
    tree.event_generate('<<TreeviewSelect>>')
    tree.update_idletasks()


def test_retry_uses_selected_history_row_and_refreshes_after_action(app, monkeypatch):
    confirmations = []
    monkeypatch.setattr('crier.desktop.messagebox.askyesno', lambda *a, **k: confirmations.append(a) or True)
    app.render_delivery_status(status(alert('first'), alert('second')))
    select(app.delivery_alerts, 'second')
    app.retry_delivery_button.invoke()
    assert app.worker.calls[-1][:2] == ('discord_retry', ('second',))
    assert confirmations
    assert app.delivery_alerts.selection() == ()
    assert app.retry_delivery_button.instate(['disabled'])
    # Complete the action through the same callback runner used by the app.
    app.worker.calls[-1][3].set_result(alert('second', 'pending'))
    app.refresh()
    assert any(call[0] == 'discord_status' for call in app.worker.calls)


def test_refresh_clears_selection_and_blocks_arbitrary_or_wrong_list_ids(app, monkeypatch):
    monkeypatch.setattr('crier.desktop.messagebox.askyesno', lambda *a, **k: pytest.fail('No valid row to confirm'))
    app.render_delivery_status(status(alert('old')))
    select(app.delivery_alerts, 'old')
    app.render_delivery_status(status(alert('new')))
    app.retry_delivery_button.invoke()
    assert not app.worker.calls
    # A widget row alone is not trusted history, even if inserted by another view.
    app.delivery_alerts.insert('', 'end', iid='receiver-id', values=('Copied text',))
    select(app.delivery_alerts, 'receiver-id')
    app.retry_delivery_button.invoke()
    assert not app.worker.calls


def test_close_and_retry_respect_state_and_cancel(app, monkeypatch):
    monkeypatch.setattr('crier.desktop.messagebox.askyesno', lambda *a, **k: False)
    app.render_delivery_status(status(alert('uncertain', 'uncertain'), alert('sent', 'delivered')))
    select(app.delivery_alerts, 'uncertain')
    assert app.retry_delivery_button.instate(['disabled'])
    assert app.close_delivery_button.instate(['!disabled'])
    app.close_delivery_button.invoke()
    assert not app.worker.calls
    select(app.delivery_alerts, 'sent')
    assert app.retry_delivery_button.instate(['disabled'])
    assert app.close_delivery_button.instate(['disabled'])


def test_receiver_revoke_selects_real_row_confirms_and_refreshes(app, monkeypatch):
    confirmations = []
    monkeypatch.setattr('crier.desktop.messagebox.askyesno', lambda *a, **k: confirmations.append(a) or True)
    app.render_receivers([dict(id='one', created=100, revoked=0), dict(id='two', created=101, revoked=1)])
    select(app.delivery_receivers, 'two')
    assert app.revoke_receiver_button.instate(['disabled'])
    select(app.delivery_receivers, 'one')
    app.revoke_receiver_button.invoke()
    assert app.worker.calls[-1][:2] == ('revoke_receiver', ('one',))
    assert 'future' in confirmations[0][1] and 'positions' in confirmations[0][1]
    app.worker.calls[-1][3].set_result({'revoked': True})
    app.refresh()
    assert any(call[0] == 'receivers' for call in app.worker.calls)


def test_new_connection_rejects_old_list_results(app):
    app.render_receivers([dict(id='original', created=100, revoked=0)])
    select(app.delivery_receivers, 'original')
    app.refresh_receivers()
    old_callback = app.pending[-1][1]
    app.submit('disconnect')
    old_callback([dict(id='old-host-receiver', created=100, revoked=0)])
    assert app.delivery_receivers.get_children() == ()
    assert app.revoke_receiver_button.instate(['disabled'])


def test_modal_refresh_cannot_retarget_confirmed_action(app, monkeypatch):
    app.render_delivery_status(status(alert('first'), alert('second')))
    select(app.delivery_alerts, 'first')
    def refreshed(*args, **kwargs):
        app.render_delivery_status(status(alert('second')))
        select(app.delivery_alerts, 'second')
        return True
    monkeypatch.setattr('crier.desktop.messagebox.askyesno', refreshed)
    app.retry_delivery_button.invoke()
    assert not app.worker.calls


def test_close_submits_selected_uncertain_record_and_retains_evidence(app, monkeypatch):
    monkeypatch.setattr('crier.desktop.messagebox.askyesno', lambda *a, **k: True)
    app.render_delivery_status(status(alert('uncertain', 'uncertain')))
    select(app.delivery_alerts, 'uncertain')
    app.close_delivery_button.invoke()
    assert app.worker.calls[-1][:2] == ('discord_close', ('uncertain',))
    assert app.close_delivery_button.instate(['disabled'])


def test_overlapping_refresh_only_accepts_newest_results(app):
    app.refresh_delivery_history()
    first = app.pending[-1][1]
    app.refresh_delivery_history()
    newest = app.pending[-1][1]
    newest(status(alert('newest')))
    first(status(alert('outdated')))
    assert app.delivery_alerts.get_children() == ('newest',)


def test_changing_selected_row_during_confirmation_never_submits_another_row(app, monkeypatch):
    app.render_delivery_status(status(alert('first'), alert('second')))
    select(app.delivery_alerts, 'first')
    def changed(*args, **kwargs):
        select(app.delivery_alerts, 'second')
        return True
    monkeypatch.setattr('crier.desktop.messagebox.askyesno', changed)
    app.retry_delivery_button.invoke()
    assert not app.worker.calls


def test_minimum_window_can_reach_record_details_and_usable_preview_controls(app):
    app.root.attributes('-alpha', 0)
    app.root.geometry('850x680')
    app.root.deiconify()
    notebook = app.delivery_tab.master
    notebook.select(app.delivery_tab)
    app.root.update()
    # The complete tab can exceed the available height; scroll to its evidence.
    app.delivery_canvas.yview_moveto(1)
    app.root.update_idletasks()
    canvas = app.delivery_canvas
    bottom = canvas.winfo_rooty() + canvas.winfo_height()
    details = app.delivery_details
    assert details.winfo_height() >= 50
    assert details.winfo_rooty() >= canvas.winfo_rooty()
    assert details.winfo_rooty() + details.winfo_height() <= bottom
    preview_controls = details.master.winfo_children()[0].winfo_children()
    for button in preview_controls:
        assert button.winfo_height() >= 20
        assert button.winfo_rooty() >= canvas.winfo_rooty()
        assert button.winfo_rooty() + button.winfo_height() <= bottom
