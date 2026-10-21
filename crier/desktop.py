"""Native Windows desktop for the shared iOS/Android/PC intent protocol."""
import argparse
import json
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import ttk, messagebox
import webbrowser

from .desktop_runtime import DesktopWorker, data_directory
from .lock import AlreadyRunningError, single_process


class DesktopApp:
    def __init__(self, root, worker):
        self.root, self.worker = root, worker
        self.pending = []
        self.poll = None
        self.connected = False
        self.closing = False
        self.latest = {}
        root.title('Sentinel Crier • Desktop')
        root.geometry('1080x780')
        root.minsize(850, 680)
        style = ttk.Style(root)
        if 'vista' in style.theme_names():
            style.theme_use('vista')
        style.configure('Title.TLabel', font=('Segoe UI', 22, 'bold'))
        style.configure('Subtitle.TLabel', font=('Segoe UI', 10))
        outer = ttk.Frame(root, padding=20)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='Sentinel Crier', style='Title.TLabel').pack(anchor='w')
        ttk.Label(outer, text='Your iPhone trades. Your PC follows.', style='Subtitle.TLabel').pack(anchor='w', pady=(0,12))
        self.summary = tk.StringVar(value='Disconnected • Connect starts new entries paused')
        ttk.Label(outer, textvariable=self.summary, wraplength=1000).pack(anchor='w', pady=(0,12))
        tabs = ttk.Notebook(outer)
        tabs.pack(fill='both', expand=True)
        self.activity = ttk.Frame(tabs, padding=14)
        setup = ttk.Frame(tabs, padding=14)
        tabs.add(self.activity, text='Trading & activity')
        tabs.add(setup, text='Connection & pricing')
        tabs.select(setup)
        self._setup(setup)
        self._activity(self.activity)
        self.notice = tk.StringVar(value='Paste the follower pairing from the same channel used by your iPhone.')
        ttk.Label(outer, textvariable=self.notice, wraplength=1000).pack(anchor='w', pady=(12,0))
        ttk.Label(outer, text='Keep this PC awake and Crier running. Closing stops mirroring; existing broker orders remain.',
                  style='Subtitle.TLabel').pack(anchor='w', pady=(6,0))
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(100, self.refresh)

    def _entry(self, frame, label, value='', masked=False):
        row = ttk.Frame(frame)
        row.pack(fill='x', pady=4)
        ttk.Label(row, text=label, width=25).pack(side='left')
        variable = tk.StringVar(value=value)
        entry = ttk.Entry(row, textvariable=variable, show='•' if masked else '')
        entry.pack(side='left', fill='x', expand=True)
        return variable

    def _setup(self, frame):
        ttk.Label(frame, text='Connect to the iPhone channel', font=('Segoe UI',12,'bold')).pack(anchor='w')
        ttk.Label(frame, text='Use follower pairing here when the iPhone is the host. Leave fields blank to reuse saved credentials.').pack(anchor='w', pady=6)
        self.pairing = self._entry(frame, 'Pairing JSON', masked=True)
        self.key = self._entry(frame, 'Alpaca API key', masked=True)
        self.secret = self._entry(frame, 'Alpaca API secret', masked=True)
        self.live = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text='Allow connection to a live-money account', variable=self.live).pack(anchor='w', pady=6)
        buttons = ttk.Frame(frame)
        buttons.pack(fill='x', pady=6)
        self.connect_button = ttk.Button(buttons, text='Connect / reuse saved', command=self.connect)
        self.connect_button.pack(side='left')
        ttk.Button(buttons, text='Disconnect', command=lambda: self.submit('disconnect')).pack(side='left', padx=8)
        ttk.Button(buttons, text='Pairing & setup guide', command=lambda: webbrowser.open(
            'https://github.com/Tetradim/Sentinel-Crier/blob/main/desktop/README.md')).pack(side='left')
        ttk.Separator(frame).pack(fill='x', pady=14)
        ttk.Label(frame, text='Local execution settings', font=('Segoe UI',12,'bold')).pack(anchor='w')
        row = ttk.Frame(frame); row.pack(fill='x', pady=6)
        ttk.Label(row, text='Price policy', width=25).pack(side='left')
        self.mode = tk.StringVar(value='exact_limit')
        ttk.Combobox(row, textvariable=self.mode, state='readonly',
                     values=('exact_limit','bounded_limit','market')).pack(side='left')
        self.slippage = self._entry(frame, 'Maximum slippage ($)', '0.02')
        self.bps = self._entry(frame, 'Maximum slippage (bps)', '100')
        self.age = self._entry(frame, 'Maximum entry age (sec)', '10')
        self.quantity_cap = self._entry(frame, 'Maximum entry quantity', '1000')
        ttk.Label(frame, text='Bounded limit uses the smaller allowance. Market orders have no price bound.').pack(anchor='w', pady=4)
        ttk.Button(frame, text='Save pricing settings', command=self.save_settings).pack(anchor='w', pady=6)

    def _activity(self, frame):
        controls = ttk.Frame(frame); controls.pack(fill='x', pady=(0,10))
        ttk.Button(controls, text='Enable new entries', command=lambda: self.submit('settings', {'enabled': True})).pack(side='left')
        ttk.Button(controls, text='Pause new entries', command=lambda: self.submit('settings', {'enabled': False})).pack(side='left', padx=8)
        ttk.Label(frame, text='Cancel and exit instructions continue while new entries are paused.').pack(anchor='w')
        ttk.Label(frame, text='Tracked trades — select one to replace, cancel or exit as host').pack(anchor='w', pady=(12,4))
        columns = ('symbol','action','quantity','limit','revision','state')
        self.trades = ttk.Treeview(frame, columns=columns, show='headings', height=6, selectmode='browse')
        for column in columns:
            self.trades.heading(column, text=column.title())
            self.trades.column(column, width=100 if column != 'symbol' else 220, stretch=True)
        self.trades.pack(fill='x')
        ttk.Label(frame, text='Broker orders — cumulative fills reported by your account').pack(anchor='w', pady=(12,4))
        self.orders = ttk.Treeview(frame, columns=('symbol','side','qty','filled','status','broker_id'), show='headings', height=5)
        for col in self.orders['columns']:
            self.orders.heading(col, text=col.replace('_',' ').title())
            self.orders.column(col, width=110, stretch=True)
        self.orders.pack(fill='both', expand=True)
        host = ttk.LabelFrame(frame, text='Host controls (only available with a host pairing)', padding=8)
        host.pack(fill='x', pady=(12,0))
        self.symbol = self._entry(host, 'Symbol / full OCC contract')
        self.order_qty = self._entry(host, 'Quantity', '1')
        self.price = self._entry(host, 'Limit price', '0.20')
        row = ttk.Frame(host); row.pack(fill='x', pady=4)
        self.asset = tk.StringVar(value='option')
        ttk.Combobox(row, textvariable=self.asset, values=('option','stock'), state='readonly', width=10).pack(side='left')
        self.host_buttons = []
        for label, action in [('Buy','enter'),('Replace selected','replace'),('Cancel selected','cancel'),('Exit selected','exit')]:
            button = ttk.Button(row, text=label, command=lambda a=action: self.command(a))
            button.pack(side='left', padx=4)
            button.configure(state='disabled')
            self.host_buttons.append(button)

    def submit(self, method, *args, callback=None, **kwargs):
        if self.closing:
            return
        self.notice.set('Working…')
        self.pending.append((self.worker.call(method, *args, **kwargs), callback))

    def connect(self):
        self.connect_button.configure(state='disabled')
        def connected(result):
            self.pairing.set(''); self.key.set(''); self.secret.set('')
            settings = result['execution']['settings']
            for var, name in [(self.mode,'mode'),(self.slippage,'max_slippage_amount'),
                              (self.bps,'max_slippage_bps'),(self.age,'max_age_seconds'),(self.quantity_cap,'max_quantity')]:
                var.set(str(settings[name]))
            self.render(result)
        self.submit('connect', self.pairing.get(), self.key.get(), self.secret.get(), allow_live=self.live.get(), callback=connected)

    def save_settings(self):
        try:
            value = dict(mode=self.mode.get(), max_slippage_amount=self.slippage.get(),
                         max_slippage_bps=int(self.bps.get()), max_age_seconds=int(self.age.get()),
                         max_quantity=int(self.quantity_cap.get()))
            self.submit('settings', value)
        except ValueError:
            self.notice.set('Age, quantity and basis points must be whole numbers.')

    def command(self, action):
        try:
            values = {}
            if action != 'enter':
                selected = self.trades.selection()
                if not selected:
                    raise ValueError('Select a tracked trade first.')
                values['trade_id'] = selected[0]
            if action != 'cancel':
                values.update(quantity=int(self.order_qty.get()), limit_price=self.price.get())
            if action == 'enter':
                values.update(symbol=self.symbol.get().strip().upper(), asset=self.asset.get())
            self.submit('command', action, **values)
        except ValueError as exc:
            self.notice.set(str(exc))

    def render(self, state):
        self.latest = state
        self.connected = state['connected']
        self.connect_button.configure(state='disabled' if self.connected else 'normal')
        pair = state['pair']
        execution = state['execution'] or {}
        enabled = execution.get('settings', {}).get('enabled', False)
        if self.connected:
            self.summary.set(f"{pair['environment'].upper()} • {pair['role'].title()} • Account {state['account']} • "
                             + ('Entries enabled' if enabled else 'New entries paused') + '\n' + state['message'])
        else:
            self.summary.set('Disconnected • ' + ('Saved connection available' if state['saved'] else 'Set up a connection to begin'))
        host = self.connected and pair.get('role') == 'host'
        for button in self.host_buttons:
            button.configure(state='normal' if host else 'disabled')
        trades = execution.get('trades', [])
        symbols = {row['id']: row['event']['symbol'] for row in trades}
        ids = set()
        for row in trades:
            e = row['event']; ids.add(row['id'])
            values = (e['symbol'],e['action'],e['quantity'],e['limit_price'],e['sequence'],
                      'Skipped' if row['skipped'] else 'Invalidated' if row['invalid'] else 'Tracked')
            if self.trades.exists(row['id']): self.trades.item(row['id'], values=values)
            else: self.trades.insert('', 'end', iid=row['id'], values=values)
        for iid in self.trades.get_children():
            if iid not in ids: self.trades.delete(iid)
        for iid in self.orders.get_children(): self.orders.delete(iid)
        for order in execution.get('orders', []):
            self.orders.insert('', 'end', values=(symbols.get(order['trade_id'], ''), order['side'],
                order['qty'], order['filled'], order['status'], order['broker_id'] or 'Awaiting reconciliation'))

    def refresh(self):
        if self.closing:
            return
        remaining = []
        for future, callback in self.pending:
            if not future.done():
                remaining.append((future, callback)); continue
            try:
                result = future.result()
                if callback: callback(result)
                self.notice.set('Saved / completed. Check activity for actual broker status.')
            except Exception as exc:
                self.notice.set(str(exc) if isinstance(exc, ValueError) else 'Operation failed. Check connection and local journal.')
                if not self.connected: self.connect_button.configure(state='normal')
        self.pending = remaining
        if self.poll is None:
            self.poll = self.worker.call('status')
        elif self.poll.done():
            try: self.render(self.poll.result())
            except Exception: self.notice.set('Cannot read local status.')
            self.poll = None
        self.root.after(250, self.refresh)

    def close(self):
        if self.closing:
            return
        if self.connected and not messagebox.askokcancel('Close Crier',
                'Mirroring will stop. Existing broker orders remain active. Close Crier?', parent=self.root):
            return
        self.closing = True
        self.notice.set('Stopping receiver and waiting for in-flight broker work…')
        future = self.worker.call('disconnect')
        def finish():
            if not future.done():
                self.root.after(100, finish); return
            try:
                future.result()
            except Exception:
                self.closing = False
                self.notice.set('Shutdown failed. Inspect broker orders and try disconnecting again.')
                self.root.after(250, self.refresh)
                return
            self.worker.close()
            self.root.destroy()
        finish()


def smoke_test(report=None):
    from .device_secrets import save_secret, load_secret
    with tempfile.TemporaryDirectory(prefix='crier-desktop-smoke-') as folder:
        path = Path(folder)
        save_secret(path/'test.secret', 'offline-smoke')
        assert load_secret(path/'test.secret') == 'offline-smoke'
        root = tk.Tk(); root.withdraw()
        worker = DesktopWorker(path)
        try:
            app = DesktopApp(root, worker)
            state = worker.call('status').result(timeout=5)
            assert not state['connected']
            app.render(state)
            root.update_idletasks()
        finally:
            worker.call('disconnect').result(timeout=5)
            worker.close()
            root.destroy()
    if report:
        Path(report).write_text(json.dumps({'ok':True,'network_calls':0,'ui':'Tk','credentials':'round-trip passed'}), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description='Sentinel Crier desktop')
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--report')
    args = parser.parse_args()
    if args.self_test:
        smoke_test(args.report)
        return
    folder = data_directory(); folder.mkdir(parents=True, exist_ok=True)
    try:
        with single_process(folder/'desktop.lock'):
            root = tk.Tk()
            worker = DesktopWorker(folder)
            DesktopApp(root, worker)
            root.mainloop()
    except AlreadyRunningError:
        root = tk.Tk(); root.withdraw()
        messagebox.showinfo('Sentinel Crier', 'Crier desktop is already running.', parent=root)
        root.destroy()


if __name__ == '__main__':
    main()
