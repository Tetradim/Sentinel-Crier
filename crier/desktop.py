"""Native Windows desktop for the shared iOS/Android/PC intent protocol."""
import argparse
import json
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import webbrowser

from .desktop_runtime import DesktopWorker, data_directory
from .connection_client import default_origin
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
        pricing = ttk.Frame(tabs, padding=14)
        tabs.add(self.activity, text='Trading & activity')
        tabs.add(setup, text='Host / Receive')
        tabs.add(pricing, text='Pricing')
        diagnostics = ttk.Frame(tabs, padding=14)
        tabs.add(diagnostics, text='Diagnostics')
        tabs.select(setup)
        self._setup(setup)
        self._pricing(pricing)
        self._activity(self.activity)
        self._diagnostics(diagnostics)
        self.notice = tk.StringVar(value='Host shares an invitation. Receive joins it. Saved devices reconnect with the same button.')
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
        ttk.Label(frame, text='Connect across networks', font=('Segoe UI',12,'bold')).pack(anchor='w')
        ttk.Label(frame, text='Choose Host to share your trades, or Receive to follow a paired host.').pack(anchor='w', pady=6)
        self.service = self._entry(frame, 'Service (host setup)', default_origin())
        self.invitation = self._entry(frame, 'Host invitation / code', masked=True)
        row=ttk.Frame(frame); row.pack(fill='x', pady=8)
        self.host_environment=tk.StringVar(value='paper')
        ttk.Combobox(row, textvariable=self.host_environment, values=('paper','live'), state='readonly', width=8).pack(side='left')
        ttk.Button(row,text='Host / invite receiver',command=lambda:self.quick_connect('host')).pack(side='left',padx=8)
        ttk.Button(row,text='Receive / reconnect',command=lambda:self.quick_connect('receive')).pack(side='left')
        self.share=self._entry(frame, 'Invitation to share')
        ttk.Button(frame,text='Copy invitation',command=self.copy_invitation).pack(anchor='w')
        ttk.Label(frame,text='Each invitation joins one receiver and expires in 10 minutes. Generate another for each additional receiver.').pack(anchor='w',pady=6)
        ttk.Separator(frame).pack(fill='x',pady=10)
        ttk.Label(frame,text='Your brokerage account • leave both blank to reuse saved credentials').pack(anchor='w')
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
        self.pairing = self._entry(frame, 'Advanced: pairing JSON', masked=True)

    def _pricing(self, frame):
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

    def copy_invitation(self):
        if self.share.get():
            self.root.clipboard_clear(); self.root.clipboard_append(self.share.get())
            self.notice.set('Invitation copied. Send it only to the intended receiver.')

    def quick_connect(self, role):
        def ready(result):
            self.pairing.set(json.dumps(result['pair']))
            self.service.set(result['pair']['url'])
            self.host_environment.set(result['pair']['environment'])
            self.invitation.set('')
            self.share.set(result.get('invitation',''))
            if not self.connected:
                # Pairing is already durable if broker credentials are not available yet.
                self.root.after(0,self.connect)
            else:
                self.pairing.set('')
        if role=='host':
            self.submit('host',self.service.get(),self.host_environment.get(),callback=ready)
        else:
            self.submit('receive',self.invitation.get(),self.service.get(),callback=ready)

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

    def _diagnostics(self, frame):
        ttk.Label(frame, text='Execution evidence', font=('Segoe UI', 12, 'bold')).pack(anchor='w')
        ttk.Label(frame, text='Select a trade in Trading & activity, then load its local timeline. Remote device records are not merged.',
                  wraplength=950).pack(anchor='w', pady=6)
        controls = ttk.Frame(frame)
        controls.pack(fill='x', pady=6)
        self.diagnostic_side = tk.StringVar(value='buy')
        ttk.Combobox(controls, textvariable=self.diagnostic_side, values=('buy', 'sell'),
                     state='readonly', width=8).pack(side='left')
        ttk.Button(controls, text='Load selected trade', command=self.load_diagnostics).pack(side='left', padx=8)
        for format in ('json', 'csv'):
            ttk.Button(controls, text='Export ' + format.upper(),
                       command=lambda f=format: self.save_diagnostics(f)).pack(side='left', padx=4)
        self.diagnostic_text = tk.Text(frame, wrap='word', state='disabled', font=('Consolas', 10))
        self.diagnostic_text.pack(fill='both', expand=True)

    def selected_diagnostic_trade(self):
        selected = self.trades.selection()
        if not selected:
            self.notice.set('Select a tracked trade in Trading & activity first.')
            return None
        return selected[0]

    def load_diagnostics(self):
        trade_id = self.selected_diagnostic_trade()
        if trade_id:
            self.submit('diagnostics', trade_id, self.diagnostic_side.get(), callback=self.render_diagnostics)

    def render_diagnostics(self, report):
        premium = report['premium_movement']
        lines = [f"Trade: {report['trade_id'] or 'No recorded events'}",
                 'Local evidence only. Quotes require a connected data source.',
                 'Premium comparison: ' + json.dumps(premium),
                 'Cross-device latency: unavailable — verified clock synchronization required.', '']
        for event in report['timeline']:
            lines.extend([f"{event['timestamp']}  {event['stage']}",
                          json.dumps(event['details'], sort_keys=True), ''])
        self.diagnostic_text.configure(state='normal')
        self.diagnostic_text.delete('1.0', 'end')
        self.diagnostic_text.insert('1.0', '\n'.join(lines))
        self.diagnostic_text.configure(state='disabled')

    def save_diagnostics(self, format):
        trade_id = self.selected_diagnostic_trade()
        if not trade_id:
            return
        path = filedialog.asksaveasfilename(parent=self.root, defaultextension='.' + format,
            initialfile='crier-' + trade_id + '.' + format,
            filetypes=[(format.upper(), '*.' + format)])
        if not path:
            return
        def save(content):
            try:
                with open(path, 'w', encoding='utf-8', newline='') as stream:
                    stream.write(content)
            except OSError:
                messagebox.showerror('Export failed', 'Cannot write the selected file.', parent=self.root)
        self.submit('export_diagnostics', trade_id, format, self.diagnostic_side.get(), callback=save)

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
    assert Path(__file__).with_name('connection-service.json').exists(), 'Missing bundled connection-service resource'
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
            app.render_diagnostics({'trade_id': 'offline-smoke', 'timeline': [],
                                    'premium_movement': {'status': 'unavailable'}})
            assert 'offline-smoke' in app.diagnostic_text.get('1.0', 'end')
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
