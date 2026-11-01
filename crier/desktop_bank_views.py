"""Account-bank dialogs bound to one immutable route, with no session access."""
from dataclasses import dataclass
from typing import Callable
import tkinter as tk
from tkinter import ttk


@dataclass(frozen=True)
class AccountBankViews:
    root: object
    route_id: str | None
    selected: Callable
    send: Callable
    notice: Callable
    labels: tuple

    def submit(self, method, *args, callback=None):
        if self.selected()!=self.route_id:
            self.notice('Select the original connection and reopen its account ID bank before saving.')
            return
        self.send(method,*args,callback=callback)

    def account_bank(self):
        self.submit('bank_status',callback=self.show_account_bank)

    def show_recovery_assistant(self,report):
        window=tk.Toplevel(self.root);window.title('Recovery assistant');window.geometry('900x650')
        canvas=tk.Canvas(window,highlightthickness=0)
        scroll=ttk.Scrollbar(window,orient='vertical',command=canvas.yview);scroll.pack(side='right',fill='y')
        canvas.pack(fill='both',expand=True);canvas.configure(yscrollcommand=scroll.set)
        frame=ttk.Frame(canvas,padding=16)
        item=canvas.create_window((0,0),window=frame,anchor='nw')
        frame.bind('<Configure>',lambda event:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda event:canvas.itemconfigure(item,width=event.width))
        ttk.Label(frame,text=report['explanation'],wraplength=650).pack(anchor='w',pady=8)
        ttk.Label(frame,text='Broker check: '+str(report.get('check_result','not checked'))+'. Entries are not automatically resumed.',wraplength=650).pack(anchor='w')
        for index,step in enumerate(report['steps'],1):
            ttk.Label(frame,text=str(index)+'. '+step,wraplength=650).pack(anchor='w',pady=4)
        if 'positions' in report:
            ttk.Label(frame,text='Position snapshot: '+report['positions_checked_at'],wraplength=650).pack(anchor='w',pady=8)
            table=ttk.Treeview(frame,columns=('symbol','host','external','expected','broker','difference'),show='headings',height=5)
            for key,title in [('symbol','Symbol'),('host','Host owned'),('external','External'),('expected','Expected'),('broker','Broker'),('difference','Difference')]:
                table.heading(key,text=title);table.column(key,width=105)
            for row in report['positions']:
                table.insert('','end',values=tuple(row[key] for key in ('symbol','host_owned','external_baseline','expected','broker','difference')))
            table.pack(fill='x',pady=4)
        for row in report['ids']:
            ttk.Label(frame,text=f"ID {row['id']} | {row['symbol']} | owned {row['units']} | pending buys {row['pending_buy_units']} | pending exits {row['pending_exit_units']}",wraplength=650).pack(anchor='w',pady=4)
        ordered=sorted(report.get('orders',[]),key=lambda row:row['result'] in ('verified','definite_no_submission'))
        for order in ordered[:100]:
            ttk.Label(frame,text=order['cid']+' · '+order['result']+' · '+order.get('status',''),wraplength=800).pack(anchor='w',pady=2)
        if len(report.get('orders',[]))>100:
            ttk.Label(frame,text='Showing first 100 order results; the check evaluated all retained orders.').pack(anchor='w')
        def check_evidence(method='bank_recovery'):
            if self.selected()!=self.route_id:
                self.notice('Select the original connection and reopen its recovery assistant before checking.')
                return
            self.submit(method,callback=lambda updated:(window.destroy(),self.show_recovery_assistant(updated)))
        ttk.Button(frame,text='Pause entries and check broker evidence',command=check_evidence).pack(anchor='w',pady=8)
        if report.get('flat_repair_candidate'):
            ttk.Label(frame,text='All recorded holdings appear flat. Repair rechecks every original order and fresh funds, rebuilds local cash capacity and retains IDs/history. Entries stay paused.',wraplength=800).pack(anchor='w',pady=8)
            ttk.Button(frame,text='Recheck and repair verified-flat ledger',command=lambda:check_evidence('bank_repair')).pack(anchor='w',pady=8)

    def show_account_bank(self,result):
        def bank_action(method,*args,callback=None):
            if self.selected()!=self.route_id:
                self.notice('Select the original connection and reopen its account ID bank before saving.')
                return
            self.submit(method,*args,callback=callback)
        window=tk.Toplevel(self.root)
        window.title('Account ID bank')
        window.geometry('850x560')
        frame=ttk.Frame(window,padding=16);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='Shared Alpaca account • '+result['environment'].upper(),font=('Segoe UI',14,'bold')).pack(anchor='w')
        if not result['enabled']:
            ttk.Label(frame,text='Enable separate host IDs for this account. Setup disconnects all routes and checks that older Crier orders and holdings are fully reconciled and closed. Reconnect afterward; orders remain paused. Each host starts with zero allocation.',wraplength=780).pack(anchor='w',pady=16)
            ttk.Button(frame,text='Set up account ID bank',command=lambda:bank_action('bank_enable',callback=lambda updated:(window.destroy(),self.show_account_bank(updated)))).pack(anchor='w')
            return
        blocked=result['balance'].get('blocked')
        if result.get('recovery'):
            ttk.Button(frame,text='Recovery assistant',command=lambda:self.show_recovery_assistant(result['recovery'])).pack(anchor='w',pady=4)
        ttk.Label(frame,text='New entries blocked: '+blocked if blocked else 'Account bank enabled. Configure this connection’s reusable pools, then reconnect and explicitly enable orders.',wraplength=780).pack(anchor='w',pady=8)
        for asset in ('stock','option'):
            row=ttk.Frame(frame);row.pack(fill='x',pady=4)
            ttk.Label(row,text=asset.title()+' pool',width=14).pack(side='left')
            policy=result['policies'][asset]
            mode=tk.StringVar(value=policy['mode']);value=tk.StringVar(value=policy['value']);fee=tk.StringVar(value=result['fees'][asset])
            ttk.Combobox(row,textvariable=mode,values=('units','dollars','equity_percent'),state='readonly',width=18).pack(side='left')
            ttk.Entry(row,textvariable=value,width=12).pack(side='left',padx=5)
            ttk.Label(row,text='Fee reserve $').pack(side='left')
            ttk.Entry(row,textvariable=fee,width=8).pack(side='left',padx=5)
            ttk.Button(row,text='Save pool',command=lambda a=asset,m=mode,v=value,f=fee:bank_action('bank_configure',a,m.get(),v.get(),f.get(),callback=lambda updated:(window.destroy(),self.show_account_bank(updated)))).pack(side='left')
        ttk.Label(frame,text='Limit orders only. Units = aggregate shares/contracts held + pending. Dollars and equity % include held cost and pending buy limits. Fees are reserved per order. Lowering a pool never sells a position.',wraplength=780).pack(anchor='w',pady=8)
        table=ttk.Treeview(frame,columns=('id','host','symbol','units','buy','sell','state'),show='headings',height=10)
        for name in table['columns']:
            table.heading(name,text=name.title());table.column(name,width=95 if name!='symbol' else 180)
        table.pack(fill='both',expand=True)
        active={row['id'] for row in result['active']}
        labels=dict(self.labels)
        rows=result['active']+[row for row in result['history'] if row['id'] not in active]
        for row in rows:
            table.insert('','end',values=(row['id'],labels.get(row['route'],row['route']),row['symbol'],row['units'],row['pending_buy_units'],row['pending_exit_units'],'Active' if row['id'] in active else 'Archived'))
        ttk.Label(frame,text='Showing the latest 100 IDs. Empty sold/canceled IDs archive automatically. Unknown orders and partial fills retain their IDs. IDs and audit history are never reused or erased.',wraplength=780).pack(anchor='w',pady=8)
        ttk.Button(frame,text='Refresh',command=lambda:(window.destroy(),self.account_bank())).pack(anchor='e')
