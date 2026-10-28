"""Native Windows desktop for the shared iOS/Android/PC intent protocol."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import webbrowser
from concurrent.futures import ThreadPoolExecutor

from .desktop_runtime import DesktopWorker, data_directory
from .connection_client import default_origin
from .lock import AlreadyRunningError, single_process
from .desktop_setup import SetupProgress
from .desktop_practice import PracticeWindow, readonly_traversal


class DesktopApp:
    def __init__(self, root, worker, *, presence=None, startup=False, check_updates=True):
        self.root, self.worker = root, worker
        self.practice_window = None
        self.presence = presence
        self.pending = []
        self.connection_jobs = set()
        self.poll = None
        self.connected = False
        self.provider_purpose = 'alerts'
        self.provider_available = set()
        self.closing = False
        self.latest = {}
        self.support_window=None
        from .startup_notice import StartupNotice
        self.startup_notice=StartupNotice()
        self.update_requested = False
        self.update_pool = ThreadPoolExecutor(max_workers=1,thread_name_prefix='Crier updates')
        self.update_future = None
        self.setup_progress = SetupProgress()
        self.setup_dirty = False
        self.rendering_setup = False
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
        ttk.Label(outer, text='Fill alerts, trade sharing and following — choose your setup.', style='Subtitle.TLabel').pack(anchor='w', pady=(0,12))
        self.summary = tk.StringVar(value='Disconnected • Choose a setup to begin')
        self.connection_title=tk.StringVar(value='Disconnected')
        self.connection_detail=tk.StringVar(value='Connect an account and pairing to begin.')
        ttk.Label(outer,textvariable=self.connection_title,font=('Segoe UI',14,'bold')).pack(anchor='w')
        ttk.Label(outer,textvariable=self.connection_detail,wraplength=1000).pack(anchor='w',pady=(0,4))
        ttk.Label(outer, textvariable=self.summary, wraplength=1000).pack(anchor='w', pady=(0,12))
        ttk.Button(outer,text='Support',command=self.open_support).pack(anchor='e',pady=(0,4))
        self.update_banner=ttk.Frame(outer,padding=8)
        self.startup_update_text=tk.StringVar(value='')
        ttk.Label(self.update_banner,textvariable=self.startup_update_text).pack(side='left')
        ttk.Button(self.update_banner,text='Review update',command=self.review_startup_update).pack(side='left',padx=8)
        ttk.Button(self.update_banner,text='Dismiss',command=self.dismiss_startup_update).pack(side='left')
        tabs = self.tabs = ttk.Notebook(outer)
        tabs.pack(fill='both', expand=True)
        start = ttk.Frame(tabs, padding=14)
        self.alerts_tab = ttk.Frame(tabs, padding=14)
        tabs.add(start, text='Start here')
        tabs.add(self.alerts_tab, text='Alerts setup')
        self.activity = ttk.Frame(tabs, padding=14)
        setup = ttk.Frame(tabs, padding=14)
        pricing = ttk.Frame(tabs, padding=14)
        tabs.add(self.activity, text='Trading & activity')
        copy_tab=ttk.Frame(tabs,padding=14)
        tabs.add(copy_tab,text='Copy dashboard')
        ttk.Label(copy_tab,text='Sharing a channel shares tracked trade quantities, fills and connection status with its host. This view cannot place orders.',wraplength=1000).pack(anchor='w')
        self.copy_dashboard=tk.Text(copy_tab,wrap='word',state='disabled')
        self.copy_dashboard.pack(fill='both',expand=True,pady=8)
        tabs.add(setup, text='Host / Receive')
        tabs.add(pricing, text='Pricing')
        delivery = ttk.Frame(tabs, padding=14)
        self.delivery_tab=delivery
        tabs.add(delivery, text='Discord & receivers')
        self.build_delivery(delivery)
        diagnostics = ttk.Frame(tabs, padding=14)
        self.health_tab=diagnostics
        tabs.add(diagnostics, text='Health')
        self.setup_tab = setup
        tabs.select(start)
        self._start(start)
        if self.presence is not None:
            self._presence_controls(start)
        customer = ttk.Frame(tabs,padding=14)
        tabs.add(customer,text='Provider sign-in')
        self._customer(customer)
        self._alerts_setup(self.alerts_tab)
        self._setup(setup)
        self._pricing(pricing)
        self._activity(self.activity)
        health_sections=ttk.Notebook(diagnostics); health_sections.pack(fill='both',expand=True)
        self.health_sections=health_sections
        connection_health=ttk.Frame(health_sections,padding=8)
        timeline=ttk.Frame(health_sections,padding=8)
        health_sections.add(connection_health,text='Connections')
        health_sections.add(timeline,text='Trade timeline')
        updates=ttk.Frame(health_sections,padding=8)
        self.updates_tab=updates
        health_sections.add(updates,text='Updates & recovery')
        self.build_updates(updates)
        self._health(connection_health)
        self._diagnostics(timeline)
        self.notice = tk.StringVar(value='Choose Send my fills to Discord, Trade/share trades, or Follow trades in Start here.')
        root.report_callback_exception=self.report_callback_error
        ttk.Label(outer, textvariable=self.notice, wraplength=1000).pack(anchor='w', pady=(12,0))
        ttk.Label(outer, text='Keep this PC awake. Closing stops Crier unless tray mode is enabled. Quit stops monitoring; broker orders remain.',
                  style='Subtitle.TLabel').pack(anchor='w', pady=(6,0))
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.bind('<F1>',lambda event:self.open_practice())
        if self.presence is not None:
            self.presence.start()
            if self.presence.error:
                self.notice.set(self.presence.error)
            if startup and self.presence.tray_ready:
                root.withdraw()
        root.after(100, self.refresh)
        root.after(250, self.provider_inbox)
        if check_updates and self.updater is not None:
            root.after(750,self.check_startup_updates)

    def _start(self, frame):
        ttk.Label(frame, text='What would you like to do?', font=('Segoe UI', 16, 'bold')).pack(anchor='w', pady=12)
        ttk.Label(frame, text='Choose a journey. Connections always require your explicit action.').pack(anchor='w', pady=8)
        for label, purpose in [('Send my fills to Discord', 'alerts'), ('Trade/share trades', 'trade'), ('Follow trades', 'follow')]:
            ttk.Button(frame, text=label, command=lambda p=purpose: self.choose_purpose(p)).pack(anchor='w', pady=8)
        ttk.Label(frame, text='Other tools and existing recovery evidence remain available in the tabs above.', wraplength=700).pack(anchor='w', pady=12)
        ttk.Button(frame,text='Optional paper practice / support (F1)',command=self.open_practice).pack(anchor='w',pady=4)
        ttk.Button(frame,text='Test my connection (read-only)',command=self.test_connection).pack(anchor='w',pady=5)

    def test_connection(self):
        current=getattr(self,'connection_test_job',None)
        if self.closing or (current is not None and not current.done()):return
        self.notice.set('Checking selected account and relay access; no test order is submitted…')
        self.connection_test_job=self.worker.call('connection_test')
        self.pending.append((self.connection_test_job,self.show_connection_test))

    def show_connection_test(self,result):
        descriptions={'connect_first':'Connect your selected account first.','account_verified':'Selected broker account and environment verified.',
                      'account_verification_failed':'Broker account verification failed; check account, credentials and environment.',
                      'pairing_not_configured':'No trade pairing configured.','relay_verified':'Authenticated relay message response verified.',
                      'relay_timeout':'Relay did not respond in time.','relay_verification_failed':'Relay/pairing could not be verified.'}
        lines=[str(result.get('environment','')).upper()+' • Read-only connection checks']
        for row in result.get('rows',[]):
            lines.append(row['component'].title()+': '+descriptions.get(row['code'],'Connection could not be verified.'))
        lines.append('No order or Discord message was sent. Trade/peer delivery was not exercised.')
        messagebox.showinfo('Connection test', '\n\n'.join(lines),parent=self.root)

    def open_support(self):
        if self.closing:return
        if self.support_window is not None and self.support_window.winfo_exists():
            self.support_window.deiconify();self.support_window.lift();return
        from .customer_support import support_details
        details=support_details()
        window=self.support_window=tk.Toplevel(self.root)
        window.title('Crier support');window.transient(self.root)
        frame=ttk.Frame(window,padding=18);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='Crier '+details['version'],font=('Segoe UI',16,'bold')).pack(anchor='w')
        ttk.Label(frame,text='Platform: '+details['platform']+'\nSource: '+details['source'],wraplength=550).pack(anchor='w',pady=10)
        ttk.Label(frame,text='Export a sanitized technical support bundle, review it, then share it through the support page. Do not post API keys, pairing invitations or raw account databases. Nothing is uploaded automatically.',wraplength=550).pack(anchor='w',pady=8)
        ttk.Button(frame,text='Export support bundle…',command=self.save_support_bundle).pack(anchor='w',pady=5)
        ttk.Button(frame,text='Open support page',command=lambda:webbrowser.open(details['url'])).pack(anchor='w',pady=5)
        ttk.Button(frame,text='Close',command=window.destroy).pack(anchor='e',pady=8)

    def open_practice(self):
        try:
            if self.practice_window is not None and self.practice_window.window.winfo_exists():
                self.practice_window.window.deiconify(); self.practice_window.window.lift()
            else:
                self.practice_window=PracticeWindow(self.root)
            return self.practice_window
        except (OSError,ValueError):
            self.notice.set('Practice guide unavailable. See the project README and support page; account controls remain available.')

    def choose_purpose(self, purpose):
        if self.connected:
            self.notice.set('Disconnect before changing setup purpose. Existing orders and recovery records remain saved.')
            return
        self.provider_purpose = 'alerts' if purpose == 'alerts' else 'trade'
        self.tabs.select(self.alerts_tab if purpose == 'alerts' else self.setup_tab)
        self.notice.set('Verify your account, then configure Discord.' if purpose == 'alerts' else
                        'Choose Host to share trades.' if purpose == 'trade' else 'Choose Receive to follow trades.')

    def _customer(self, frame):
        ttk.Label(frame,text='Crier customer account',font=('Segoe UI',16,'bold')).pack(anchor='w')
        ttk.Label(frame,text='Choose your journey in Start here. Provider approval saves credentials; reconnect separately.',wraplength=850).pack(anchor='w',pady=8)
        self.customer_email=self._entry(frame,'Email')
        self.customer_password=self._entry(frame,'Password',masked=True)
        row=ttk.Frame(frame); row.pack(anchor='w',pady=8)
        ttk.Button(row,text='Check provider availability',command=self.check_providers).pack(side='left')
        ttk.Button(row,text='Sign in',command=lambda:self.customer_login(False)).pack(side='left')
        ttk.Button(row,text='Renew session',command=lambda:self.submit('customer_refresh',callback=self.provider_message)).pack(side='left')
        ttk.Button(row,text='Create account',command=lambda:self.customer_login(True)).pack(side='left')
        ttk.Button(row,text='Sign out and disconnect',command=lambda:self.submit('customer_logout',callback=self.provider_message)).pack(side='left')
        self.provider_environment=tk.StringVar(value='paper')
        ttk.Combobox(frame,textvariable=self.provider_environment,values=('paper','live'),state='readonly').pack(anchor='w',pady=8)
        self.provider_buttons={}
        for provider,label in [('alpaca','Authorize Alpaca in browser'),('discord','Authorize Discord in browser')]:
            button=ttk.Button(frame,text=label,state='disabled',command=lambda p=provider:self.begin_provider(p))
            button.pack(anchor='w',pady=6); self.provider_buttons[provider]=button
        self.provider_return=self._entry(frame,'Return URL (manual recovery)')
        ttk.Button(frame,text='Continue provider return',command=self.complete_provider).pack(anchor='w',pady=6)
        ttk.Button(frame,text='Cancel pending connection',command=lambda:self.submit('provider_cancel',callback=self.provider_message)).pack(anchor='w')
        self.provider_status=tk.StringVar(value='Provider connections unavailable until the configured service verifies its capabilities.')
        ttk.Label(frame,textvariable=self.provider_status,wraplength=850).pack(anchor='w',pady=12)

    def provider_message(self, result):
        self.provider_status.set(result.get('message','Request completed.'))

    def check_providers(self):
        def ready(result):
            self.provider_available=set(result['providers'])
            for provider,button in self.provider_buttons.items():
                button.configure(state='normal' if provider in self.provider_available else 'disabled')
            self.provider_status.set('Provider service verified. Sign in, then authorize your selected provider.')
        self.submit('provider_capabilities',callback=ready)

    def customer_login(self, signup):
        email,password=self.customer_email.get(),self.customer_password.get()
        self.customer_password.set('')
        self.submit('customer_login',email,password,signup,callback=self.provider_message)

    def begin_provider(self, provider):
        purpose=self.provider_purpose
        self.submit('provider_begin',provider,purpose,self.provider_environment.get(),callback=lambda url:webbrowser.open(url))

    def complete_provider(self, uri=None):
        uri=uri or self.provider_return.get()
        self.provider_return.set('')
        self.submit('provider_complete',uri,callback=self.provider_message)

    def provider_inbox(self):
        if self.closing: return
        from .desktop_oauth_return import take_returns
        if not hasattr(self.worker,'session'): return
        try:
            for uri in take_returns(self.worker.session.folder):
                self.complete_provider(uri)
        except OSError:
            self.notice.set('Provider return inbox busy; retrying shortly.')
        finally:
            if not self.closing: self.root.after(500,self.provider_inbox)

    def _alerts_setup(self, frame):
        ttk.Label(frame, text='1. Connect your account for fill alerts', font=('Segoe UI', 14, 'bold')).pack(anchor='w', pady=8)
        ttk.Label(frame, text='Read-only fill monitoring. No Host or Receive connection is needed.', wraplength=750).pack(anchor='w', pady=8)
        row = ttk.Frame(frame); row.pack(fill='x', pady=8)
        ttk.Label(row, text='Alpaca environment', width=25).pack(side='left')
        self.alerts_environment = tk.StringVar(value='paper')
        ttk.Combobox(row, textvariable=self.alerts_environment, values=('paper', 'live'), state='readonly').pack(side='left')
        self.alerts_key = self._entry(frame, 'Alpaca API key', masked=True)
        self.alerts_secret = self._entry(frame, 'Alpaca API secret', masked=True)
        ttk.Label(frame, text='Leave both blank to reuse saved alerts keys for the same environment and account.').pack(anchor='w', pady=8)
        self.alerts_live = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text='Allow read access to my live-money account', variable=self.alerts_live).pack(anchor='w', pady=8)
        self.alerts_connect = ttk.Button(frame, text='Connect / use saved keys', command=self.connect_alerts)
        self.alerts_connect.pack(anchor='w', pady=8)
        ttk.Button(frame, text='Disconnect', command=lambda: self.submit('disconnect')).pack(anchor='w', pady=4)
        self.alerts_result = tk.StringVar(value='Account not verified. Connect to check read access.')
        ttk.Label(frame, textvariable=self.alerts_result, wraplength=750).pack(anchor='w', pady=12)
        self.alerts_next = ttk.Button(frame, text='2. Set up Discord: preview, test, enable', state='disabled',
                                     command=lambda: self.tabs.select(self.delivery_tab))
        self.alerts_next.pack(anchor='w', pady=8)

    def connect_alerts(self):
        if self.connected:
            self.notice.set('Disconnect before changing connection settings.')
            return
        self.alerts_connect.configure(state='disabled')
        self.alerts_next.configure(state='disabled')
        self.alerts_result.set('Verifying account read access…')
        def completed(result):
            self.alerts_key.set(''); self.alerts_secret.set('')
            self.render(result)
            self.refresh_delivery_history()
        self.submit('connect_alerts', self.alerts_environment.get(), self.alerts_key.get(), self.alerts_secret.get(),
                    allow_live=self.alerts_live.get(), callback=completed)

    def build_delivery(self, frame):
        self.delivery_tab = frame
        self.delivery_canvas = tk.Canvas(frame, highlightthickness=0)
        scroll = ttk.Scrollbar(frame, orient='vertical', command=self.delivery_canvas.yview)
        self.delivery_canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.delivery_canvas.pack(side='left', fill='both', expand=True)
        content = ttk.Frame(self.delivery_canvas)
        window = self.delivery_canvas.create_window((0, 0), window=content, anchor='nw')
        content.bind('<Configure>', lambda event: self.delivery_canvas.configure(
            scrollregion=self.delivery_canvas.bbox('all')))
        self.delivery_canvas.bind('<Configure>', lambda event: self.delivery_canvas.itemconfigure(
            window, width=event.width))
        frame = content
        self.delivery_generation = {'alerts': 0, 'receivers': 0}
        self.delivery_rows = {'alerts': {}, 'receivers': {}}
        guided = ttk.LabelFrame(frame, text='Discord setup — account, destination, preview, test, enable', padding=8)
        guided.pack(fill='x', pady=(0,8))
        self.setup_message = tk.StringVar(value=self.setup_progress.message)
        ttk.Label(guided, textvariable=self.setup_message, wraplength=720).pack(anchor='w')
        row = ttk.Frame(guided); row.pack(fill='x', pady=6)
        self.guided_preview = ttk.Button(row, text='Preview saved format', state='disabled', command=self.setup_preview)
        self.guided_test = ttk.Button(row, text='Send labeled test', state='disabled', command=self.setup_test)
        self.guided_enable = ttk.Button(row, text='Enable real alerts', state='disabled', command=lambda: self.setup_delivery(True))
        self.guided_disable = ttk.Button(row, text='Disable real alerts', state='disabled', command=lambda: self.setup_delivery(False))
        for button in (self.guided_preview, self.guided_test, self.guided_enable, self.guided_disable):
            button.pack(side='left', padx=(0,6))
        settings = ttk.LabelFrame(frame, text='Discord delivery', padding=8)
        settings.pack(fill='x')
        self.delivery_webhook = self._entry(settings, 'Webhook (blank reuses saved)', masked=True)
        self.delivery_enabled = tk.BooleanVar(value=False)
        ttk.Checkbutton(settings, text='Enable Discord delivery', variable=self.delivery_enabled).pack(anchor='w')
        row = ttk.Frame(settings); row.pack(fill='x')
        self.delivery_style = tk.StringVar(value='card')
        ttk.Combobox(row, textvariable=self.delivery_style, values=('card','text','homebrew','echo'),
                     state='readonly', width=12).pack(side='left')
        self.delivery_quantity = tk.BooleanVar(value=True)
        self.delivery_timestamp = tk.BooleanVar(value=True)
        ttk.Checkbutton(row, text='Show quantity', variable=self.delivery_quantity).pack(side='left')
        ttk.Checkbutton(row, text='Show broker time', variable=self.delivery_timestamp).pack(side='left')
        ttk.Button(row, text='Save destination', command=self.save_delivery_destination).pack(side='left', padx=4)
        ttk.Button(row, text='Save format / fields', command=self.save_delivery_style).pack(side='left')

        ttk.Label(frame, text='Delivery history — select an alert to inspect and resolve').pack(anchor='w', pady=(8,2))
        self.delivery_alerts = self._delivery_table(frame, ('created', 'contract', 'side', 'quantity', 'status'), 4)
        self.delivery_alerts.bind('<<TreeviewSelect>>', lambda event: self.delivery_selection_changed('alerts'))
        row = ttk.Frame(frame); row.pack(fill='x', pady=4)
        ttk.Button(row, text='Refresh history / settings', command=self.refresh_delivery_history).pack(side='left')
        self.retry_delivery_button = ttk.Button(row, text='Retry selected alert', state='disabled',
                                               command=lambda: self.delivery_action('discord_retry'))
        self.retry_delivery_button.pack(side='left', padx=4)
        self.close_delivery_button = ttk.Button(row, text='Close inspected delivery', state='disabled',
                                               command=lambda: self.delivery_action('discord_close'))
        self.close_delivery_button.pack(side='left')
        ttk.Button(row, text='Retry rejected relay instructions',
                   command=lambda: self.submit('retry_rejected', callback=self.show_delivery_details)).pack(side='left', padx=4)
        ttk.Label(frame, text='Paired receivers — Host connection required').pack(anchor='w', pady=(8,2))
        self.delivery_receivers = self._delivery_table(frame, ('receiver', 'created', 'status'), 3)
        self.delivery_receivers.bind('<<TreeviewSelect>>', lambda event: self.delivery_selection_changed('receivers'))
        row = ttk.Frame(frame); row.pack(fill='x', pady=4)
        ttk.Button(row, text='Refresh receivers', command=self.refresh_receivers).pack(side='left')
        self.revoke_receiver_button = ttk.Button(row, text='Revoke selected receiver', state='disabled',
                                                command=lambda: self.delivery_action('revoke_receiver'))
        self.revoke_receiver_button.pack(side='left', padx=4)
        advanced = ttk.LabelFrame(frame, text='Advanced: preview and record details', padding=6)
        advanced.pack(fill='both', expand=True, pady=(8,0))
        row = ttk.Frame(advanced); row.pack(fill='x')
        ttk.Button(row, text='Preview saved alert', command=self.setup_preview).pack(side='left')
        ttk.Button(row, text='Send labeled test message', command=self.setup_test).pack(side='left', padx=4)
        self.delivery_details = tk.Text(advanced, height=4, wrap='word', state='disabled')
        readonly_traversal(self.delivery_details)
        self.delivery_details.pack(fill='both', expand=True)
        for value in (self.delivery_webhook, self.delivery_style, self.delivery_quantity, self.delivery_timestamp):
            value.trace_add('write', self.setup_edited)

    def setup_edited(self, *_):
        if self.rendering_setup:
            return
        self.setup_dirty = True
        self.setup_progress.invalidate()
        self.clear_delivery_list('alerts')
        self.render_setup_progress()

    def render_setup_progress(self):
        self.setup_message.set('Save destination / format changes before preview, test or enable.' if self.setup_dirty else self.setup_progress.message)
        ready = self.setup_progress.can_publish and not self.setup_dirty
        for button in (self.guided_preview, self.guided_test, self.guided_enable, self.guided_disable):
            button.configure(state='normal' if ready else 'disabled')

    def setup_callback(self, callback):
        token = self.setup_progress.token
        def current(value):
            if token == self.setup_progress.token and not self.setup_dirty:
                callback(value, token)
        return current

    def setup_preview(self):
        if not self.setup_progress.can_publish or self.setup_dirty:
            self.notice.set('Verify an account and save the Discord destination / format first.')
            return
        def completed(value, token):
            self.setup_progress.preview(token)
            self.show_delivery_details(value)
            self.render_setup_progress()
        self.submit('discord_preview', callback=self.setup_callback(completed))

    def setup_test(self):
        if not self.setup_progress.can_publish or self.setup_dirty:
            self.notice.set('Verify an account and save the Discord destination / format first.')
            return
        def completed(value, token):
            self.setup_progress.test(token, value.get('status'))
            self.delivery_test_completed(value)
            self.render_setup_progress()
        self.submit('discord_test', callback=self.setup_callback(completed))

    def setup_delivery(self, enabled):
        if not self.setup_progress.can_publish or self.setup_dirty:
            return
        # Empty destination deliberately reuses the saved secret; draft input is never sent.
        self.clear_delivery_list('alerts')
        current = self.delivery_list_callback('alerts', self.render_delivery_status)
        self.submit('discord_configure', '', enabled, callback=self.setup_callback(
            lambda value, token: current(value)))

    def _delivery_table(self, frame, columns, height):
        row = ttk.Frame(frame); row.pack(fill='x')
        tree = ttk.Treeview(row, columns=columns, show='headings', height=height, selectmode='browse')
        for column in columns:
            tree.heading(column, text=column.title())
            tree.column(column, width=140 if column in ('created', 'contract', 'receiver') else 85, stretch=True)
        scroll = ttk.Scrollbar(row, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side='left', fill='x', expand=True); scroll.pack(side='right', fill='y')
        return tree

    def show_delivery_details(self, value):
        self.delivery_details.configure(state='normal')
        self.delivery_details.delete('1.0', 'end')
        self.delivery_details.insert('1.0', json.dumps(value, indent=2, default=str))
        self.delivery_details.configure(state='disabled')

    def clear_delivery_list(self, kind):
        self.delivery_generation[kind] += 1
        self.delivery_rows[kind] = {}
        tree = self.delivery_alerts if kind == 'alerts' else self.delivery_receivers
        for iid in tree.get_children():
            tree.delete(iid)
        self.delivery_selection_changed(kind)

    def selected_delivery_record(self, kind):
        tree = self.delivery_alerts if kind == 'alerts' else self.delivery_receivers
        selected = tree.selection()
        return self.delivery_rows[kind].get(selected[0]) if len(selected) == 1 else None

    def delivery_selection_changed(self, kind):
        record = self.selected_delivery_record(kind)
        if kind == 'alerts':
            state = record.get('status') if record else None
            self.retry_delivery_button.configure(state='normal' if state == 'failed' else 'disabled')
            self.close_delivery_button.configure(state='normal' if state in ('pending','failed','uncertain','review') else 'disabled')
        else:
            self.revoke_receiver_button.configure(state='normal' if record and not record['revoked'] else 'disabled')
        if record:
            self.show_delivery_details(record)

    @staticmethod
    def delivery_time(timestamp):
        return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')

    def render_delivery_status(self, value):
        self.clear_delivery_list('alerts')
        self.delivery_enabled.set(value['enabled'])
        settings = value['settings']
        self.rendering_setup = True
        try:
            self.delivery_style.set(settings['format'])
            self.delivery_quantity.set(settings['show_quantity'])
            self.delivery_timestamp.set(settings['show_time'])
            self.delivery_webhook.set('')
        finally:
            self.rendering_setup = False
        self.setup_dirty = False
        self.setup_progress.destination(value.get('revision', ''), configured=value.get('configured', False),
                                        enabled=value['enabled'], paused=settings.get('paused', False))
        self.render_setup_progress()
        for record in value['history']:
            self.delivery_rows['alerts'][record['id']] = dict(record)
            fill = record['fill']
            self.delivery_alerts.insert('', 'end', iid=record['id'], values=(self.delivery_time(record['created']),
                fill.get('contract', ''), fill.get('side', ''), fill.get('quantity', ''), record['status']))
        self.show_delivery_details(value)

    def render_receivers(self, records):
        self.clear_delivery_list('receivers')
        for index, record in enumerate(records, 1):
            self.delivery_rows['receivers'][record['id']] = dict(record)
            self.delivery_receivers.insert('', 'end', iid=record['id'], values=(
                f"Receiver {index} ({record['id'][:8]})", self.delivery_time(record['created']),
                'Revoked' if record['revoked'] else 'Paired'))

    def delivery_list_callback(self, kind, callback):
        generation = self.delivery_generation[kind]
        def current(value):
            if generation == self.delivery_generation[kind]:
                callback(value)
        return current

    def refresh_delivery_history(self):
        self.clear_delivery_list('alerts')
        self.submit('discord_status', callback=self.delivery_list_callback('alerts', self.render_delivery_status))

    def refresh_receivers(self):
        self.clear_delivery_list('receivers')
        self.submit('receivers', callback=self.delivery_list_callback('receivers', self.render_receivers))

    def save_delivery_destination(self):
        if not self.connected:
            self.notice.set('Connect and verify the intended account before saving its destination.')
            return
        self.clear_delivery_list('alerts')
        self.submit('discord_configure', self.delivery_webhook.get(), self.delivery_enabled.get(),
                    callback=self.delivery_list_callback('alerts', self.render_delivery_status))

    def save_delivery_style(self):
        if not self.connected:
            self.notice.set('Connect and verify the intended account before saving its format.')
            return
        values = dict(format=self.delivery_style.get(), show_quantity=self.delivery_quantity.get(),
                      show_time=self.delivery_timestamp.get())
        def saved(value):
            self.show_delivery_details(value)
            self.refresh_delivery_history()
        self.clear_delivery_list('alerts')
        generation = self.delivery_generation['alerts']
        def current(value):
            if generation == self.delivery_generation['alerts']:
                self.submit('discord_settings', dict(value['settings'], **values),
                            callback=self.delivery_list_callback('alerts', saved))
        self.submit('discord_status', callback=current)

    def delivery_test_completed(self, value):
        self.show_delivery_details(value)
        self.refresh_delivery_history()

    def delivery_action(self, method):
        kind = 'receivers' if method == 'revoke_receiver' else 'alerts'
        record = self.selected_delivery_record(kind)
        if not record:
            return
        if method == 'discord_retry' and record['status'] != 'failed':
            return
        if method == 'discord_close' and record['status'] not in ('pending','failed','uncertain','review'):
            return
        if method == 'revoke_receiver' and record['revoked']:
            return
        identity = record['id']
        generation = self.delivery_generation[kind]
        title, prompt = {
            'discord_retry': ('Retry delivery', 'Check Discord first. Retrying an uncertain delivery can create a duplicate. Retry this alert?'),
            'discord_close': ('Close delivery after inspection', 'Close this alert without sending it? Its original evidence will remain in history.'),
            'revoke_receiver': ('Revoke receiver', 'Stop future transport to this receiver? Existing broker orders and positions remain; revoking does not cancel orders or close positions.'),
        }[method]
        if not messagebox.askyesno(title, prompt, parent=self.root):
            return
        # The modal dialog processes UI events: a refresh may have invalidated its row.
        current = self.selected_delivery_record(kind)
        if generation != self.delivery_generation[kind] or not current or current['id'] != identity:
            return
        self.clear_delivery_list(kind)
        def completed(value):
            self.show_delivery_details(value)
            if kind == 'alerts':
                self.refresh_delivery_history()
            else:
                self.refresh_receivers()
        self.submit(method, identity, callback=self.delivery_list_callback(kind, completed))

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
        self.age = self._entry(frame, 'Entry submit age (sec)', '10')
        self.quantity_cap = self._entry(frame, 'Source quantity cap', '1000')
        ttk.Label(frame, text='Bounded limit uses the smaller allowance. Market orders have no price bound.').pack(anchor='w', pady=4)
        ttk.Label(frame, text='The cap rejects larger source instructions; it does not set each order size. Following uses source units.\n'
                  'Entry age is checked before submission. Day orders may remain working afterward.\n'
                  'Pausing new entries leaves cancel and exit instructions active; existing broker orders remain.',
                  wraplength=700).pack(anchor='w', pady=6)
        ttk.Button(frame, text='Save pricing settings', command=self.save_settings).pack(anchor='w', pady=6)
        self.policy_button=ttk.Button(frame,text='Follower sizing, exits & timeout…',command=self.edit_execution_policy,state='disabled')
        self.policy_button.pack(anchor='w',pady=6)
        ttk.Label(frame,text='Optional follower policies apply to new trades only. Saving a policy pauses new entries.\n'
                  'Existing trades retain their recorded policy. Host order quantities are never scaled.',wraplength=700).pack(anchor='w')

    def edit_execution_policy(self):
        state=self.latest
        if not state.get('connected') or (state.get('pair') or {}).get('role')!='follower':
            self.notice.set('Connect as a receiver to configure a follower policy.'); return
        selected=(state.get('execution') or {}).get('settings',{}).get('execution_policy')
        current=selected or {}
        dialog=tk.Toplevel(self.root); dialog.title('Follower execution policy')
        dialog.transient(self.root)
        ttk.Label(dialog,text='New trades only • saving leaves entries paused',font=('Segoe UI',11,'bold')).pack(anchor='w',padx=12,pady=8)
        form=ttk.Frame(dialog,padding=12); form.pack(fill='both',expand=True)
        mode=tk.StringVar(value=current.get('mode','source') if selected is not None else 'legacy')
        exits=tk.StringVar(value=current.get('exit_mode','requested'))
        def choice(label,variable,values):
            row=ttk.Frame(form); row.pack(fill='x',pady=3)
            ttk.Label(row,text=label,width=29).pack(side='left')
            ttk.Combobox(row,textvariable=variable,values=values,state='readonly',width=25).pack(side='left')
        choice('Entry sizing',mode,('legacy','source','fixed','ratio','budget'))
        fixed=self._entry(form,'Fixed whole units',str(current.get('fixed_quantity') or 1))
        ratio=self._entry(form,'Source ratio (basis points)',str(current.get('ratio_bps') or 10000))
        budget=self._entry(form,'Entry budget USD',current.get('budget') or '')
        source=self._entry(form,'Policy source quantity cap',str(current.get('max_source_quantity',1000)))
        local=self._entry(form,'Local target quantity cap',str(current.get('max_local_quantity',1000)))
        notional=self._entry(form,'Entry notional cap USD (optional)',current.get('max_entry_notional') or '')
        choice('Exit sizing',exits,('requested','proportional','close_tracked'))
        timeout=self._entry(form,'Entry timeout seconds (optional)',str(current.get('entry_timeout_seconds') or ''))
        ttk.Label(form,text='Ratio: 10000 = 100%, 5000 = 50%. Budget/cap exclude fees and require limit pricing.\n'
                  'Proportional source intents requires complete history; it does not match host fills.\n'
                  'Close tracked sells all locally tracked holdings when an exit arrives.\n'
                  'Timed buys cancel on restart/reconnect after reconciliation; racing fills remain holdings.\n'
                  'Suspension or loss of network can delay cancellation.',wraplength=560).pack(anchor='w',pady=8)
        error=tk.StringVar(); ttk.Label(form,textvariable=error,wraplength=560).pack(anchor='w')
        def save():
            try:
                policy=None
                if mode.get()!='legacy':
                    from dataclasses import asdict
                    from .execution_policy import ExecutionPolicy
                    value=dict(mode=mode.get(),exit_mode=exits.get(),max_source_quantity=int(source.get()),max_local_quantity=int(local.get()),
                               max_entry_notional=notional.get().strip() or None,
                               entry_timeout_seconds=int(timeout.get()) if timeout.get().strip() else None)
                    if mode.get()=='fixed': value['fixed_quantity']=int(fixed.get())
                    elif mode.get()=='ratio': value['ratio_bps']=int(ratio.get())
                    elif mode.get()=='budget': value['budget']=budget.get().strip()
                    policy=asdict(ExecutionPolicy.parse(value))
                self.submit('settings',{'enabled':False,'execution_policy':policy},callback=lambda _:dialog.destroy())
            except ValueError as exc: error.set(str(exc))
        ttk.Button(form,text='Save policy and pause new entries',command=save).pack(anchor='w',pady=6)

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
        self.execution_buttons = []
        for label, enabled in [('Enable new entries', True), ('Pause new entries', False)]:
            button = ttk.Button(controls, text=label, state='disabled',
                                command=lambda e=enabled: self.submit('settings', {'enabled': e}))
            button.pack(side='left', padx=4)
            self.execution_buttons.append(button)
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

    def _health(self, frame):
        ttk.Label(frame,text='Connection health',font=('Segoe UI',14,'bold')).pack(anchor='w')
        ttk.Label(frame,text='Last successes are evidence, not permission to trade. Reconnect after restart to verify again.',wraplength=700).pack(anchor='w',pady=8)
        self.health_rows=ttk.Treeview(frame,columns=('component','state','success','recovery'),show='headings',height=6,selectmode='browse')
        for column,title,width in [('component','Component',120),('state','State',105),('success','Last success (local)',160),('recovery','Recovery',325)]:
            self.health_rows.heading(column,text=title); self.health_rows.column(column,width=width,minwidth=65,stretch=True)
        self.health_rows.pack(fill='x',pady=8)
        self.health_notice=tk.StringVar(value='No current health evidence. Connect the intended account to begin.')
        self.health_data={}
        self.health_rows.bind('<<TreeviewSelect>>',lambda event:self.show_health_detail())
        ttk.Label(frame,textvariable=self.health_notice,wraplength=700).pack(anchor='w',pady=8)
        actions=ttk.Frame(frame); actions.pack(anchor='w',pady=8)
        ttk.Button(actions,text='Account setup',command=lambda:self.tabs.select(self.alerts_tab if self.latest.get('mode')=='alerts' else self.setup_tab)).pack(side='left',padx=3)
        self.health_activity_button=ttk.Button(actions,text='Order activity',command=lambda:self.tabs.select(self.activity))
        self.health_activity_button.pack(side='left',padx=3)
        ttk.Button(actions,text='Discord history',command=lambda:self.tabs.select(self.delivery_tab)).pack(side='left',padx=3)
        ttk.Button(actions,text='Disconnect',command=lambda:self.submit('disconnect')).pack(side='left',padx=3)
        ttk.Button(actions,text='Export support bundle',command=self.save_support_bundle).pack(side='left',padx=3)
        self.log_notice=tk.StringVar(value='Technical log status unavailable.')
        ttk.Label(frame,textvariable=self.log_notice,wraplength=700).pack(anchor='w',pady=4)
        ttk.Label(frame,text='Idle means no queued work; it does not prove the remote service is reachable. Inspect uncertain orders or messages before retrying.',wraplength=700).pack(anchor='w',pady=8)

    def report_callback_error(self, kind, error, trace):
        from .error_log import emit_error
        emit_error(getattr(self.worker,'error_log',None),'desktop.interface_failed',error)
        self.notice.set('Interface error. Use Health to inspect diagnostic status and export a support bundle.')

    def save_support_bundle(self):
        path=filedialog.asksaveasfilename(parent=self.root,defaultextension='.zip',initialfile='crier-support-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.zip',filetypes=[('ZIP','*.zip')])
        if not path:return
        self.submit('support_bundle',path,callback=lambda result:self.notice.set('Support bundle saved. It contains technical IDs and stack locations; review before sharing.'))

    def show_health_detail(self):
        selected=self.health_rows.selection()
        row=self.health_data.get(selected[0]) if selected else None
        if row:
            reason=(row.get('reason') or 'No check in this connection').replace('_',' ')
            self.health_notice.set(f"{row['label']}: {reason}. {row['recovery']}")

    def render_health(self, rows, unavailable=False):
        self.health_data={row['component']:row for row in rows}
        for row in rows:
            timestamp=row.get('last_success')
            try: success=datetime.fromtimestamp(timestamp,timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M:%S') if timestamp is not None else 'Never confirmed'
            except (ValueError,TypeError,OSError,OverflowError): success='Timestamp unavailable'
            values=(row['label'],row['state'].replace('_',' ').title(),success,row['recovery'])
            if self.health_rows.exists(row['component']): self.health_rows.item(row['component'],values=values)
            else: self.health_rows.insert('','end',iid=row['component'],values=values)
        for identity in self.health_rows.get_children():
            if identity not in self.health_data: self.health_rows.delete(identity)
        if unavailable:
            self.health_notice.set('Health history unavailable; statuses may be incomplete. Trading and delivery journals are retained.')
        else:
            self.health_notice.set('Select a component for details. Stopped components require explicit reconnect or enable.')
            self.show_health_detail()

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
        readonly_traversal(self.diagnostic_text)
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
                 'Observed market data and synchronized relay evidence.',
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
        lifecycle = method in ('connect', 'connect_alerts', 'disconnect', 'host', 'receive')
        if lifecycle:
            self.setup_progress.account(None)
            self.setup_dirty = False
            self.render_setup_progress()
            self.poll = None
            self.clear_delivery_list('alerts')
            self.clear_delivery_list('receivers')
        self.notice.set('Working…')
        future = self.worker.call(method, *args, **kwargs)
        if lifecycle:
            self.connection_jobs.add(future)
        self.pending.append((future, callback))

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
        from .customer_readiness import connection_summary
        readiness=connection_summary(state)
        self.connection_title.set(readiness['title'])
        self.connection_detail.set(readiness['detail']+' '+readiness['action'])
        from .copy_dashboard import dashboard_text
        try: copy_text=dashboard_text(state.get('dashboard') if state.get('connected') else None)
        except (ValueError,KeyError,TypeError): copy_text='Dashboard evidence is unavailable. Trading controls are independent.'
        self.copy_dashboard.configure(state='normal')
        self.copy_dashboard.delete('1.0','end'); self.copy_dashboard.insert('1.0',copy_text)
        self.copy_dashboard.configure(state='disabled')
        self.render_health(state.get('health',[]),state.get('health_error',False))
        logging_state=state.get('technical_logging') or {}
        self.log_notice.set(('Technical logs available.' if logging_state.get('available') else 'Technical logging unavailable; existing execution journals remain separate.')+
                            ' Dropped records: '+str(logging_state.get('dropped',0))+'. Repeated errors suppressed: '+str(logging_state.get('suppressed',0))+'.')
        if self.connected != state['connected']:
            self.clear_delivery_list('alerts')
            self.clear_delivery_list('receivers')
        self.connected = state['connected']
        self.connect_button.configure(state='disabled' if self.connected else 'normal')
        pair = state['pair']
        execution = state['execution'] or {}
        enabled = execution.get('settings', {}).get('enabled', False)
        alerts_mode = state.get('mode') == 'alerts'
        scope = (state.get('mode', 'intent'), state.get('environment', pair.get('environment')),
                 state.get('account'), pair.get('token')) if self.connected and not self.connection_jobs else None
        self.setup_progress.account(scope)
        self.render_setup_progress()
        self.alerts_connect.configure(state='disabled' if self.connected else 'normal')
        self.alerts_next.configure(state='normal' if self.connected and alerts_mode and not self.connection_jobs else 'disabled')
        if self.connected and alerts_mode:
            account = '…' + state['account'][-4:]
            monitor = state.get('alerts', {}).get('state', 'connecting')
            self.alerts_result.set(f"Verified {state['environment'].upper()} account {account}. Fill monitor: {monitor}. Discord delivery requires its own explicit setup.")
            self.summary.set(f"{state['environment'].upper()} • Alerts only • Account {account} • Fill monitor: {monitor}")
        elif self.connected:
            self.summary.set(f"{pair['environment'].upper()} • {pair['role'].title()} • Account {state['account']} • "
                             + ('Entries enabled' if enabled else 'New entries paused') + '\n' + state['message'])
        else:
            self.alerts_result.set('Account not verified. Connect to check read access.')
            self.summary.set('Disconnected • ' + ('Saved connection available' if state['saved'] or state.get('saved_alerts') else 'Set up a connection to begin'))
        host = self.connected and not self.connection_jobs and pair.get('role') == 'host'
        self.policy_button.configure(state='normal' if self.connected and not self.connection_jobs and pair.get('role')=='follower' else 'disabled')
        for button in self.execution_buttons:
            button.configure(state='normal' if self.connected and not alerts_mode and not self.connection_jobs else 'disabled')
        for button in self.host_buttons:
            button.configure(state='normal' if host else 'disabled')
        trades = execution.get('trades', [])
        symbols = {row['id']: row['event']['symbol'] for row in trades}
        ids = set()
        for row in trades:
            e = row['event']; ids.add(row['id'])
            values = (e['symbol'],e['action'],e['quantity'],e['limit_price'],e['sequence'],
                      'Skipped' if row['skipped'] else 'Invalidated' if row['invalid'] else 'Tracked')
            plan=execution.get('plans',{}).get(e['event_id'])
            if plan: values=values[:-1]+(values[-1]+f" • local target {plan['target']}",)
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
        self.poll_presence()
        if self.closing:
            return
        remaining = []
        for future, callback in self.pending:
            if not future.done():
                remaining.append((future, callback)); continue
            self.connection_jobs.discard(future)
            try:
                result = future.result()
                if callback: callback(result)
                self.notice.set('Saved / completed. Check activity for actual broker status.')
            except Exception as exc:
                self.notice.set(str(exc) if isinstance(exc, ValueError) else 'Operation failed. Check connection and local journal.')
                if not self.connected:
                    self.connect_button.configure(state='normal')
                    self.alerts_connect.configure(state='normal')
        self.pending = remaining
        if self.poll is None:
            self.poll = self.worker.call('status')
        elif self.poll.done():
            try: self.render(self.poll.result())
            except Exception: self.notice.set('Cannot read local status.')
            self.poll = None
        self.root.after(250, self.refresh)

    def _presence_controls(self, frame):
        options = ttk.LabelFrame(frame, text='Windows background options', padding=10)
        options.pack(fill='x', pady=12)
        self.tray_choice = tk.BooleanVar(value=self.presence.tray_enabled)
        ttk.Checkbutton(options, text='Keep Crier running in the tray when I close its window',
                        variable=self.tray_choice, command=self.toggle_tray).pack(anchor='w')
        self.startup_choice = tk.BooleanVar(value=False)
        self.startup_button = ttk.Checkbutton(options, text='Open Crier at Windows sign-in (disconnected)',
                            variable=self.startup_choice, command=self.toggle_startup)
        self.startup_button.pack(anchor='w', pady=6)
        try:
            self.startup_choice.set(self.presence.startup.enabled)
            if not self.presence.startup.available:
                self.startup_button.configure(state='disabled')
        except OSError:
            self.startup_button.configure(state='disabled')
        ttk.Label(options, text='Sign-in never connects or enables entries. Use Show Crier in the tray to reconnect.\n'
                  'Startup requires the packaged Windows app. Quit Crier stops monitoring; existing broker orders remain.',
                  wraplength=700).pack(anchor='w')

    def show_window(self):
        self.root.deiconify()
        self.root.lift()

    def toggle_tray(self):
        try:
            self.presence.set_tray(self.tray_choice.get())
            self.notice.set('Tray preference saved. Quit Crier stops monitoring and mirroring.')
        except ValueError as exc:
            self.notice.set(str(exc))
        self.tray_choice.set(self.presence.tray_enabled)
        if not self.presence.tray_ready:
            self.show_window()

    def toggle_startup(self):
        try:
            self.presence.startup.set_enabled(self.startup_choice.get())
            self.notice.set('Windows sign-in preference saved. Crier always starts disconnected.')
        except (OSError, ValueError) as exc:
            self.notice.set(str(exc) if isinstance(exc, ValueError) else 'Cannot update Windows startup registration.')
        try:
            self.startup_choice.set(self.presence.startup.enabled)
        except OSError:
            self.startup_choice.set(False)

    def poll_presence(self):
        if self.presence is None:
            return
        for action in self.presence.poll():
            if self.closing:
                break
            if action == 'pause':
                self.submit('settings', {'enabled':False})
            elif action == 'show':
                self.show_window()
            elif action == 'quit':
                self.show_window()
                self.close(quit=True)
        if self.presence.error:
            self.notice.set(self.presence.error)

    def build_updates(self,frame):
        from .desktop_updates import DesktopUpdates
        ttk.Label(frame,text='Crier updates',style='Title.TLabel').pack(anchor='w')
        profile=getattr(getattr(self.worker,'session',None),'folder',None)
        if profile is None:
            self.updater=None
            ttk.Label(frame,text='Updates require the installed desktop profile.').pack(anchor='w')
            return
        self.updater=DesktopUpdates(profile)
        self.update_notice=tk.StringVar(value='Check for a signed release. Updates preserve your profile and never restart trading automatically.')
        ttk.Label(frame,textvariable=self.update_notice,wraplength=780).pack(anchor='w',pady=12)
        self.update_notes=tk.StringVar(value='')
        ttk.Label(frame,textvariable=self.update_notes,wraplength=780).pack(anchor='w',pady=8)
        self.update_button=ttk.Button(frame,text='Check for updates',command=self.update_action)
        self.update_button.pack(anchor='w',pady=8)
        ttk.Button(frame,text='Cancel update download',command=lambda:self.updater.cancel()).pack(anchor='w',pady=5)
        ttk.Button(frame,text='Verify recovery backup…',command=self.verify_recovery).pack(anchor='w',pady=5)
        ttk.Button(frame,text='Restore backup to a new folder…',command=self.restore_recovery).pack(anchor='w',pady=5)
        ttk.Label(frame,text='Backups contain private account and pairing data. Restoration never overwrites your active profile or reconnects a broker. Keep the original profile until recovery is verified.',wraplength=780).pack(anchor='w',pady=12)

    def run_update_job(self,operation,callback,*,quiet=False):
        if self.closing:return
        if self.update_future is not None and not self.update_future.done():return
        self.update_button.configure(state='disabled')
        self.update_future=self.update_pool.submit(operation)
        def finish():
            if not self.update_future.done():self.root.after(100,finish);return
            try:
                result=self.update_future.result()
                if not self.closing:callback(result)
            except Exception:
                if not quiet and not self.closing:self.update_notice.set('Update/recovery failed safely. No installer was started; keep the original profile.')
            self.update_button.configure(state='normal')
        self.root.after(100,finish)

    def update_action(self):
        status=self.updater.state.get('status')
        if status=='ready':
            if not messagebox.askokcancel('Install verified update','Crier will disconnect and wait for broker work, save a private recovery backup, then close and open the installer. Existing broker orders remain active. Trading will not restart automatically.',parent=self.root):return
            self.close(quit=True,update=True)
            return
        self.update_notice.set('Verifying release…' if status!='available' else 'Downloading and verifying installer…')
        self.run_update_job(self.updater.download if status=='available' else self.updater.check,self.render_update_result)

    def render_update_result(self,result):
        messages={'unconfigured':'Update signing is not activated for this build. Use the reviewed manual installer until the publisher provisions release trust.',
                  'up_to_date':'This version is current.','available':'A signed compatible update is available.',
                  'no_release':'No signed public update has been published yet.',
                  'ready':'Installer verified. Install update will create a private backup and close Crier.'}
        self.update_notice.set(messages.get(result['status'],'Check the release information.'))
        self.update_notes.set(result.get('notes',''))
        self.update_button.configure(text={'available':'Download verified update','ready':'Install update'}.get(result['status'],'Check for updates'))

    def check_startup_updates(self):
        if self.closing or self.updater is None or not self.startup_notice.begin():return
        if self.update_future is not None and not self.update_future.done():
            self.startup_notice.complete(None);return
        def completed(result):
            notice=self.startup_notice.complete(result)
            if notice is None:return
            self.render_update_result(result)
            self.startup_update_text.set('Crier '+notice['version']+' is available.')
            self.update_banner.pack(fill='x',before=self.tabs,pady=(0,8))
        self.run_update_job(self.updater.check,completed,quiet=True)

    def dismiss_startup_update(self):
        self.startup_notice.dismiss();self.update_banner.pack_forget()

    def review_startup_update(self):
        self.tabs.select(self.health_tab);self.health_sections.select(self.updates_tab)

    def verify_recovery(self):
        path=filedialog.askdirectory(parent=self.root,title='Choose a Crier recovery backup')
        if path:self.run_update_job(lambda:self.updater.inspect_backup(path),lambda _:self.update_notice.set('Backup integrity verified. Credentials remain bound to the original Windows user.'))

    def restore_recovery(self):
        source=filedialog.askdirectory(parent=self.root,title='Choose a Crier recovery backup')
        if not source:return
        parent=filedialog.askdirectory(parent=self.root,title='Choose a private parent folder for a new restored profile')
        if parent:self.run_update_job(lambda:self.updater.recover(source,parent),lambda row:self.update_notice.set('Restored to '+row['path']+'. Your active profile was not changed. Follow the recovery guide before replacing any data.'))

    def finish_update(self):
        self.notice.set('Saving and verifying private recovery backup…')
        future=self.update_pool.submit(lambda:self.updater.prepare(worker_closed=True))
        def finish():
            if not future.done():self.root.after(100,finish);return
            try:
                from .update_install import launch
                launch(future.result())
            except Exception:
                messagebox.showerror('Update not installed','Backup or installer verification failed. Your original profile was preserved. Restart Crier and inspect the release before retrying.',parent=self.root)
            self.update_pool.shutdown(wait=False,cancel_futures=True)
            self.root.destroy()
        finish()

    def close(self, *, quit=False, update=False):
        if self.closing:
            return
        if not quit and self.presence is not None and self.presence.tray_enabled and self.presence.tray_ready:
            self.root.withdraw()
            self.notice.set('Crier is still running. Use Show Crier or Quit Crier in the tray.')
            return
        if self.connected and not update and not messagebox.askokcancel('Close Crier',
                'Mirroring will stop. Existing broker orders remain active. Close Crier?', parent=self.root):
            return
        self.update_requested=update
        self.closing = True
        if hasattr(self,'startup_notice'):self.startup_notice.close()
        if not update and getattr(self,'updater',None):
            cancel=getattr(self.updater,'cancel',None)
            if cancel:cancel()
        self.notice.set('Stopping receiver and waiting for in-flight broker work…')
        future = self.worker.call('disconnect')
        def finish():
            if not future.done():
                self.root.after(100, finish); return
            try:
                future.result()
            except Exception:
                self.closing = False
                self.update_requested = False
                self.notice.set('Shutdown failed. Inspect broker orders and try disconnecting again.')
                self.root.after(250, self.refresh)
                return
            if self.presence is not None:
                self.presence.stop()
            self.worker.close()
            if getattr(self,'update_requested',False):
                self.finish_update()
                return
            if hasattr(self,'update_pool'):
                def stop_updates():
                    if self.update_future is not None and not self.update_future.done():
                        self.notice.set('Broker work stopped. Waiting for the canceled update download to close…')
                        self.root.after(100,stop_updates);return
                    self.update_pool.shutdown(wait=False,cancel_futures=True)
                    self.root.destroy()
                stop_updates()
            else:self.root.destroy()
        finish()


def smoke_test(report=None):
    import os
    import sys
    from .device_secrets import save_secret, load_secret
    from .customer_guide import load_guide
    assert len(load_guide().journeys)==3, 'Missing bundled customer practice guide'
    tray_result = 'not_requested'
    assert Path(__file__).with_name('connection-service.json').exists(), 'Missing bundled connection-service resource'
    from .desktop_updates import load_policy
    update_policy=load_policy()
    assert update_policy['repository']=='Tetradim/Sentinel-Crier', 'Missing pinned update trust policy'
    with tempfile.TemporaryDirectory(prefix='crier-desktop-smoke-') as folder:
        path = Path(folder)
        save_secret(path/'test.secret', 'offline-smoke')
        assert load_secret(path/'test.secret') == 'offline-smoke'
        root = tk.Tk(); root.withdraw()
        worker = DesktopWorker(path)
        try:
            from .desktop_presence import Presence
            app = DesktopApp(root, worker, presence=Presence(path),check_updates=False)
            state = worker.call('status').result(timeout=5)
            assert not state['connected']
            app.render(state)
            app.render_diagnostics({'trade_id': 'offline-smoke', 'timeline': [],
                                    'premium_movement': {'status': 'unavailable'}})
            assert 'offline-smoke' in app.diagnostic_text.get('1.0', 'end')
            import zipfile
            from .error_log import read_build_info
            support=path/'support.zip'
            worker.call('support_bundle',support).result(timeout=10)
            with zipfile.ZipFile(support) as archive:
                assert sorted(archive.namelist())==['diagnostics/error-log.jsonl','manifest.json']
                manifest=json.loads(archive.read('manifest.json'))
                assert manifest['includes_credentials'] is False
                if getattr(sys,'frozen',False):
                    build=read_build_info(Path(__file__).with_name('build-info.json'))
                    assert build and len(build['commit'])==40, 'Missing packaged public source revision'
                    assert manifest['build']==build
                    records=[json.loads(line) for line in archive.read('diagnostics/error-log.jsonl').splitlines()]
                    assert records and all(record.get('build_commit')==build['commit'] for record in records)
            root.update_idletasks()
        finally:
            worker.call('disconnect').result(timeout=5)
            worker.close()
            root.destroy()
    if sys.platform == 'win32' and os.getenv('GITHUB_ACTIONS') == 'true' and os.getenv('RUNNER_ENVIRONMENT') == 'github-hosted':
        from .windows_tray import WindowsTray
        tray = WindowsTray(lambda action: None)
        try:
            assert tray.start(), 'Packaged notification-area icon failed to become ready'
        finally:
            tray.stop()
        assert not tray.alive, 'Packaged notification-area thread failed to stop'
        tray_result = 'ready_and_stopped'
    if report:
        Path(report).write_text(json.dumps({'ok':True,'network_calls':0,'ui':'Tk','credentials':'round-trip passed','tray':tray_result,'support_bundle':'validated'}), encoding='utf-8')


def show_profile_error():
    root=tk.Tk();root.withdraw()
    messagebox.showerror('Crier profile cannot be opened','This profile has an unsupported format. No broker was connected. Keep the original data and use the matching release or a verified recovery backup.',parent=root)
    root.destroy()


def main():
    parser = argparse.ArgumentParser(description='Sentinel Crier desktop')
    launch = parser.add_mutually_exclusive_group()
    launch.add_argument('--oauth-return')
    launch.add_argument('--startup', action='store_true')
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--report')
    args = parser.parse_args()
    if args.self_test:
        smoke_test(args.report)
        return
    folder = data_directory(); folder.mkdir(parents=True, exist_ok=True)
    if args.oauth_return:
        from .desktop_oauth_return import enqueue_return
        try: enqueue_return(folder,args.oauth_return)
        except ValueError: return
    try:
        with single_process(folder/'desktop.lock'):
            from .update_recovery import ensure_profile_compatible
            try:ensure_profile_compatible(folder)
            except ValueError:
                show_profile_error()
                raise SystemExit(1)
            root = tk.Tk()
            worker = DesktopWorker(folder)
            from .desktop_presence import Presence
            DesktopApp(root, worker, presence=Presence(folder), startup=args.startup)
            try:
                root.mainloop()
            except Exception as exc:
                from .error_log import emit_error
                emit_error(worker.error_log,'desktop.process_failed',exc)
                worker.error_log.flush()
                try:
                    # Reuse normal shutdown: pause entries and drain in-flight
                    # mutations before stopping the non-daemon execution loop.
                    worker.close()
                except Exception as shutdown_error:
                    emit_error(worker.error_log,'desktop.shutdown_failed',shutdown_error)
                raise
    except AlreadyRunningError:
        if args.oauth_return or args.startup: return
        root = tk.Tk(); root.withdraw()
        messagebox.showinfo('Sentinel Crier', 'Crier desktop is already running.', parent=root)
        root.destroy()


if __name__ == '__main__':
    main()
