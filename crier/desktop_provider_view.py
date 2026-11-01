"""Provider sign-in panel, isolated from trading and route sessions."""
import tkinter as tk
from tkinter import ttk
import webbrowser


class ProviderSignInView:
    def __init__(self, frame, *, send, entry, purpose, return_method='provider_complete'):
        self.submit,self._entry,self.purpose=send,entry,purpose
        self.return_method=return_method
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
        purpose=self.purpose()
        self.submit('provider_begin',provider,purpose,self.provider_environment.get(),callback=lambda url:webbrowser.open(url))

    def complete_provider(self, uri=None):
        uri=uri or self.provider_return.get()
        self.provider_return.set('')
        self.submit(self.return_method,uri,callback=self.provider_message)
