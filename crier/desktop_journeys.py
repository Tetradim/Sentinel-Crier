"""Desktop setup journeys composed around the existing app and callback contract.

The app owns workers, pending futures, route identity, and global Stop. This view
coordinator always dispatches through app.submit so those fences remain shared.
"""
import json
import tkinter as tk
import webbrowser
from tkinter import ttk
from .connection_client import default_origin


class DesktopJourneys:
    def __init__(self, app):
        self.app = app

    def _start(self, frame):
        app = self.app
        from .desktop_mobile_shell import AccountHome
        app.home_overview=AccountHome(frame,purpose=app.choose_purpose,navigate=app.show_mobile_page,
                                       practice=app.open_practice,test_connection=app.test_connection)

    def show_mobile_page(self,name):
        app = self.app
        if name == 'Decisions':
            app.tabs.select(app.health_tab)
            app.health_sections.select(app.decision_tab)
            app.mobile_shell.select('Account')
            return
        if name in ('Trade','Positions','Orders'):
            app.tabs.select(app.activity)
            app.trading_navigation.select(('Trade','Positions','Orders').index(name))
        else:
            app.tabs.select({'Home':app.start_tab,'Markets':app.markets_tab,'Account':app.account_tab}[name])
        app.mobile_shell.select(name)

    def sync_mobile_navigation(self):
        app = self.app
        current=app.tabs.select()
        if current==str(app.activity):
            app.mobile_shell.select(('Trade','Positions','Orders')[app.trading_navigation.index('current')])
        elif current==str(app.start_tab): app.mobile_shell.select('Home')
        elif current==str(app.markets_tab): app.mobile_shell.select('Markets')
        else:
            app.mobile_shell.select('Account')
            if current!=str(app.account_tab):app.mobile_shell.section.set(app.tabs.tab(current,'text'))

    def build_account_hub(self,copy_tab,pricing,customer):
        app = self.app
        frame=app.account_content
        ttk.Label(frame,text='Account & connections',style='Title.TLabel').pack(anchor='w',pady=(0,10))
        ttk.Label(frame,textvariable=app.connection_title,style='Section.TLabel').pack(anchor='w')
        ttk.Label(frame,textvariable=app.connection_detail,wraplength=700,style='Muted.TLabel').pack(anchor='w',pady=(0,12))
        grid=ttk.Frame(frame);grid.pack(fill='x')
        app.account_links={}
        for i,(title,page) in enumerate([('Alerts setup',app.alerts_tab),('Host / Receive',app.setup_tab),('Pricing & allocation',pricing),
                                       ('Copy dashboard',copy_tab),('Discord & receivers',app.delivery_tab),('Health & recovery',app.health_tab),('Provider sign-in',customer)]):
            button=ttk.Button(grid,text=title,command=lambda p=page:app.tabs.select(p),style='Tertiary.TButton')
            button.grid(row=i//2,column=i%2,sticky='ew',padx=(0,8),pady=4);grid.columnconfigure(i%2,weight=1)
            app.account_links[title]=button
        utilities=ttk.Frame(frame);utilities.pack(fill='x',pady=12)
        ttk.Button(utilities,text='Updates & private backups',command=lambda:(app.tabs.select(app.health_tab),app.health_sections.select(app.updates_tab)),style='Tertiary.TButton').pack(side='left',padx=(0,8))
        ttk.Button(utilities,text='What happened?',command=lambda:app.show_mobile_page('Decisions'),style='Tertiary.TButton').pack(side='left',padx=(0,8))
        ttk.Button(utilities,text='Support',command=app.open_support,style='Tertiary.TButton').pack(side='left')
        ttk.Label(frame,text='Keep this PC awake. Quit stops Crier; existing broker orders remain active.',wraplength=700,style='Muted.TLabel').pack(anchor='w',pady=8)

    def choose_purpose(self, purpose):
        app = self.app
        if app.connected:
            app.notice.set('Disconnect before changing setup purpose. Existing orders and recovery records remain saved.')
            return
        app.provider_purpose = 'alerts' if purpose == 'alerts' else 'trade'
        app.tabs.select(app.alerts_tab if purpose == 'alerts' else app.setup_tab)
        app.notice.set('Verify your account, then configure Discord.' if purpose == 'alerts' else
                        'Choose Host to share trades.' if purpose == 'trade' else 'Choose Receive to follow trades.')

    def _alerts_setup(self, frame):
        app = self.app
        ttk.Label(frame, text='1. Connect your account for fill alerts', font=('Segoe UI', 14, 'bold')).pack(anchor='w', pady=8)
        ttk.Label(frame, text='Read-only fill monitoring. No Host or Receive connection is needed.', wraplength=750).pack(anchor='w', pady=8)
        row = ttk.Frame(frame); row.pack(fill='x', pady=8)
        ttk.Label(row, text='Alpaca environment', width=25).pack(side='left')
        app.alerts_environment = tk.StringVar(value='paper')
        ttk.Combobox(row, textvariable=app.alerts_environment, values=('paper', 'live'), state='readonly').pack(side='left')
        app.alerts_key = app._entry(frame, 'Alpaca API key', masked=True)
        app.alerts_secret = app._entry(frame, 'Alpaca API secret', masked=True)
        ttk.Label(frame, text='Leave both blank to reuse saved alerts keys for the same environment and account.').pack(anchor='w', pady=8)
        app.alerts_live = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text='Allow read access to my live-money account', variable=app.alerts_live).pack(anchor='w', pady=8)
        app.alerts_connect = ttk.Button(frame, text='Connect / use saved keys', command=app.connect_alerts)
        app.alerts_connect.pack(anchor='w', pady=8)
        ttk.Button(frame, text='Disconnect', command=lambda: app.submit('disconnect')).pack(anchor='w', pady=4)
        app.alerts_result = tk.StringVar(value='Account not verified. Connect to check read access.')
        ttk.Label(frame, textvariable=app.alerts_result, wraplength=750).pack(anchor='w', pady=12)
        app.alerts_next = ttk.Button(frame, text='2. Set up Discord: preview, test, enable', state='disabled',
                                     command=lambda: app.tabs.select(app.delivery_tab))
        app.alerts_next.pack(anchor='w', pady=8)

    def connect_alerts(self):
        app = self.app
        if app.connected:
            app.notice.set('Disconnect before changing connection settings.')
            return
        app.alerts_connect.configure(state='disabled')
        app.alerts_next.configure(state='disabled')
        app.alerts_result.set('Verifying account read access…')
        def completed(result):
            app.alerts_key.set(''); app.alerts_secret.set('')
            app.render(result)
            app.refresh_delivery_history()
        app.submit('connect_alerts', app.alerts_environment.get(), app.alerts_key.get(), app.alerts_secret.get(),
                    allow_live=app.alerts_live.get(), callback=completed)

    def _setup(self, frame):
        app = self.app
        ttk.Label(frame, text='Connect across networks', font=('Segoe UI',12,'bold')).pack(anchor='w')
        ttk.Label(frame, text='Choose Host to share your trades, or Receive to follow a paired host.').pack(anchor='w', pady=6)
        app.service = app._entry(frame, 'Service (host setup)', default_origin())
        app.invitation = app._entry(frame, 'Host invitation / code', masked=True)
        row=ttk.Frame(frame); row.pack(fill='x', pady=8)
        app.host_environment=tk.StringVar(value='paper')
        ttk.Combobox(row, textvariable=app.host_environment, values=('paper','live'), state='readonly', width=8).pack(side='left')
        ttk.Button(row,text='Host / invite receiver',command=lambda:app.quick_connect('host')).pack(side='left',padx=8)
        ttk.Button(row,text='Receive / reconnect',command=lambda:app.quick_connect('receive')).pack(side='left')
        app.share=app._entry(frame, 'Invitation to share')
        ttk.Button(frame,text='Copy invitation',command=app.copy_invitation).pack(anchor='w')
        ttk.Label(frame,text='Each invitation joins one receiver and expires in 10 minutes. Generate another for each additional receiver.').pack(anchor='w',pady=6)
        ttk.Separator(frame).pack(fill='x',pady=10)
        ttk.Label(frame,text='Your brokerage account • leave both blank to reuse saved credentials').pack(anchor='w')
        app.key = app._entry(frame, 'Alpaca API key', masked=True)
        app.secret = app._entry(frame, 'Alpaca API secret', masked=True)
        app.live = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text='Allow connection to a live-money account', variable=app.live).pack(anchor='w', pady=6)
        buttons = ttk.Frame(frame)
        buttons.pack(fill='x', pady=6)
        app.connect_button = ttk.Button(buttons, text='Connect / reuse saved', command=app.connect)
        app.connect_button.pack(side='left')
        ttk.Button(buttons, text='Disconnect', command=lambda: app.submit('disconnect')).pack(side='left', padx=8)
        ttk.Button(buttons, text='Pairing & setup guide', command=lambda: webbrowser.open(
            'https://github.com/Tetradim/Sentinel-Crier/blob/main/desktop/README.md')).pack(side='left')
        app.pairing = app._entry(frame, 'Advanced: pairing JSON', masked=True)

    def quick_connect(self, role):
        app = self.app
        epoch=app.action_epoch
        def ready(result):
            if epoch!=app.action_epoch or app.closing or app.stopping_all():return
            app.pairing.set(json.dumps(result['pair']))
            app.service.set(result['pair']['url'])
            app.host_environment.set(result['pair']['environment'])
            app.invitation.set('')
            app.share.set(result.get('invitation',''))
            if not app.connected:
                # Pairing is already durable if broker credentials are not available yet.
                app.root.after(0,lambda:app.connect() if epoch==app.action_epoch and not app.closing and not app.stopping_all() else None)
            else:
                app.pairing.set('')
        if role=='host':
            app.submit('host',app.service.get(),app.host_environment.get(),callback=ready)
        else:
            app.submit('receive',app.invitation.get(),app.service.get(),callback=ready)

    def connect(self):
        app = self.app
        app.connect_button.configure(state='disabled')
        def connected(result):
            app.pairing.set(''); app.key.set(''); app.secret.set('')
            settings = result['execution']['settings']
            for var, name in [(app.mode,'mode'),(app.slippage,'max_slippage_amount'),
                              (app.bps,'max_slippage_bps'),(app.age,'max_age_seconds'),(app.quantity_cap,'max_quantity')]:
                var.set(str(settings[name]))
            app.render(result)
        app.submit('connect', app.pairing.get(), app.key.get(), app.secret.get(), allow_live=app.live.get(), callback=connected)

