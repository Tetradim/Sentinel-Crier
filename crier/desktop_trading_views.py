"""Native trading workspace. Owns widgets; receives only explicit action callbacks."""
import tkinter as tk
from tkinter import ttk


class TradingWorkspace:
    def __init__(self, frame, *, send, command, entry):
        self.submit=send
        self.command=command
        self._entry=entry
        controls = ttk.Frame(frame); controls.pack(fill='x', pady=(0,10))
        self.execution_buttons = []
        for label, enabled in [('Enable new entries', True), ('Pause new entries', False)]:
            button = ttk.Button(controls, text=label, state='disabled',
                                command=lambda e=enabled: self.submit('settings', {'enabled': e}))
            button.pack(side='left', padx=4)
            self.execution_buttons.append(button)
        ttk.Label(frame, text='Cancel and exit instructions continue while new entries are paused.').pack(anchor='w')
        self.navigation=ttk.Notebook(frame)
        self.navigation.pack(fill='both',expand=True)
        order=self.scrollable(self.navigation,'Order')
        positions=ttk.Frame(self.navigation,padding=8)
        activity=ttk.Frame(self.navigation,padding=8)
        self.navigation.add(positions,text='Positions')
        self.navigation.add(activity,text='Activity')
        frame=positions
        ttk.Label(frame,text='Crier tracked trades and quantities; this is not your complete broker portfolio.',wraplength=750).pack(anchor='w',pady=4)
        ttk.Label(frame, text='Tracked trades — select one to replace, cancel or exit as host').pack(anchor='w', pady=(12,4))
        columns = ('symbol','action','quantity','limit','revision','state')
        self.trades = ttk.Treeview(frame, columns=columns, show='headings', height=6, selectmode='browse')
        for column in columns:
            self.trades.heading(column, text=column.title())
            self.trades.column(column, width=100 if column != 'symbol' else 220, stretch=True)
        self.trades.pack(fill='both',expand=True)
        self.horizontal_scroll(frame,self.trades)
        frame=activity
        ttk.Label(frame, text='Broker orders — cumulative fills reported by your account').pack(anchor='w', pady=(12,4))
        self.orders = ttk.Treeview(frame, columns=('symbol','side','qty','filled','status','broker_id'), show='headings', height=5)
        for col in self.orders['columns']:
            self.orders.heading(col, text=col.replace('_',' ').title())
            self.orders.column(col, width=110, stretch=True)
        self.orders.pack(fill='both', expand=True)
        self.horizontal_scroll(frame,self.orders)
        frame=order
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

    @staticmethod
    def horizontal_scroll(frame,table):
        scroll=ttk.Scrollbar(frame,orient='horizontal',command=table.xview)
        scroll.pack(fill='x')
        table.configure(xscrollcommand=scroll.set)

    @staticmethod
    def scrollable(notebook,title):
        page=ttk.Frame(notebook,padding=8)
        notebook.add(page,text=title)
        canvas=tk.Canvas(page,highlightthickness=0)
        scroll=ttk.Scrollbar(page,orient='vertical',command=canvas.yview)
        scroll.pack(side='right',fill='y')
        canvas.pack(fill='both',expand=True)
        canvas.configure(yscrollcommand=scroll.set)
        content=ttk.Frame(canvas)
        item=canvas.create_window((0,0),window=content,anchor='nw')
        content.bind('<Configure>',lambda event:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda event:canvas.itemconfigure(item,width=event.width))
        return content
