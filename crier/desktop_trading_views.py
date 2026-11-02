"""Native trading workspace. Owns widgets; receives only explicit action callbacks."""
import tkinter as tk
from tkinter import ttk


class TradingWorkspace:
    def __init__(self, frame, *, send, command, entry):
        self.submit = send
        self.command = command
        self._entry = entry
        controls = ttk.Frame(frame)
        controls.pack(fill='x', pady=(0, 8))
        self.execution_buttons = []
        for label, enabled in [('Enable new entries', True), ('Pause new entries', False)]:
            button = ttk.Button(controls, text=label, state='disabled',
                                command=lambda e=enabled: self.submit('settings', {'enabled': e}))
            button.pack(side='left', padx=(0, 8))
            self.execution_buttons.append(button)
        ttk.Label(frame, style='Muted.TLabel',
                  text='Cancel and exit instructions continue while new entries are paused.',
                  wraplength=620).pack(anchor='w', pady=(0, 8))
        self.navigation = ttk.Notebook(frame)
        self.navigation.pack(fill='both', expand=True)
        order = self.scrollable(self.navigation, 'Order')
        positions = ttk.Frame(self.navigation, padding=12)
        activity = ttk.Frame(self.navigation, padding=12)
        self.navigation.add(positions, text='Positions')
        self.navigation.add(activity, text='Activity')

        ttk.Label(positions, text='Tracked positions', style='Title.TLabel').pack(anchor='w')
        ttk.Label(positions, style='Muted.TLabel', wraplength=620,
                  text='Crier tracked trades and quantities; this is not your complete broker portfolio.').pack(anchor='w', pady=(6, 12))
        ttk.Label(positions, text='Select a trade, then use Trade to replace, cancel or exit as host.',
                  wraplength=620).pack(anchor='w', pady=(0, 10))
        self.trades = self.table(positions, ('symbol', 'action', 'quantity', 'limit', 'revision', 'state'))

        ttk.Label(activity, text='Order activity', style='Title.TLabel').pack(anchor='w')
        ttk.Label(activity, style='Muted.TLabel', wraplength=620,
                  text='Broker orders and cumulative fills reported by your account.').pack(anchor='w', pady=(6, 12))
        self.orders = self.table(activity, ('symbol', 'side', 'qty', 'filled', 'status', 'broker_id'))

        host = ttk.Frame(order, style='Card.TFrame', padding=16)
        host.pack(fill='x', pady=(0, 10))
        ttk.Label(host, text='Buy order', style='Card.TLabel', font=('Segoe UI', 16, 'bold')).pack(anchor='w')
        ttk.Label(host, text='Host pairing required', style='Card.TLabel').pack(anchor='w', pady=(4, 12))
        self.asset = tk.StringVar(value='option')
        segments = ttk.Frame(host, style='Card.TFrame')
        segments.pack(fill='x', pady=(0, 12))
        self.asset_selectors = {}
        for label, value in [('Stocks', 'stock'), ('Options', 'option')]:
            button = ttk.Radiobutton(segments, text=label, variable=self.asset, value=value,
                                     style='Segmented.TRadiobutton')
            button.pack(side='left', fill='x', expand=True, padx=(0, 4))
            self.asset_selectors[value] = button
        self.symbol = self.field(host, 'Symbol / full OCC contract')
        details = ttk.Frame(host, style='Card.TFrame')
        details.pack(fill='x', pady=(8, 0))
        details.columnconfigure((0, 1), weight=1, uniform='ticket')
        quantity = ttk.Frame(details, style='Card.TFrame')
        quantity.grid(row=0, column=0, sticky='ew', padx=(0, 6))
        price = ttk.Frame(details, style='Card.TFrame')
        price.grid(row=0, column=1, sticky='ew', padx=(6, 0))
        self.order_qty = self.field(quantity, 'Quantity', '1')
        self.price = self.field(price, 'Limit price', '0.20')
        self.preview = tk.StringVar()
        preview_label = ttk.Label(host, textvariable=self.preview, style='Card.TLabel',
                                  wraplength=580, justify='left')
        preview_label.pack(fill='x', pady=(16, 12))
        preview_label.bind('<Configure>', lambda event: preview_label.configure(wraplength=max(100, event.width)))
        for variable in (self.symbol, self.order_qty, self.price, self.asset):
            variable.trace_add('write', self.update_preview)
        self.update_preview()
        self.host_buttons = []
        buy = ttk.Button(host, text='Buy', style='Accent.TButton', state='disabled',
                         command=lambda: self.command('enter'))
        buy.pack(fill='x')
        self.host_buttons.append(buy)

        management = ttk.Frame(order, style='Card.TFrame', padding=16)
        management.pack(fill='x', pady=(0, 8))
        ttk.Label(management, text='Manage selected trade', style='Card.TLabel',
                  font=('Segoe UI', 11, 'bold')).pack(anchor='w', pady=(0, 8))
        actions = ttk.Frame(management, style='Card.TFrame')
        actions.pack(fill='x')
        for index, (label, action) in enumerate([('Replace selected', 'replace'), ('Cancel selected', 'cancel'), ('Exit selected', 'exit')]):
            actions.columnconfigure(index, weight=1, uniform='actions')
            button = ttk.Button(actions, text=label, state='disabled',
                                style='Danger.TButton' if action == 'exit' else 'TButton',
                                command=lambda a=action: self.command(a))
            button.grid(row=0, column=index, sticky='ew', padx=(0 if index == 0 else 4, 0))
            self.host_buttons.append(button)

    def field(self, parent, label, value=''):
        """Keep the shared entry factory and variables, with stacked ticket labels."""
        variable = self._entry(parent, label, value)
        row = parent.winfo_children()[-1]
        row.configure(style='Card.TFrame')
        for widget in row.winfo_children():
            widget.pack_forget()
            if isinstance(widget, ttk.Label):
                widget.configure(width=0, style='Card.TLabel')
                widget.pack(anchor='w', pady=(0, 5))
            else:
                widget.pack(fill='x', expand=True)
        return variable

    def update_preview(self, *_):
        symbol = self.symbol.get().strip() or 'symbol / contract'
        asset = 'stock' if self.asset.get() == 'stock' else 'option'
        self.preview.set(f"Buy {self.order_qty.get()} {asset} · {symbol} · Limit {self.price.get()}\nNo live quote. Uses the quantity and limit entered above.")

    @staticmethod
    def table(frame, columns):
        container = ttk.Frame(frame)
        container.pack(fill='both', expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)
        table = ttk.Treeview(container, columns=columns, show='headings', height=8, selectmode='browse')
        for column in columns:
            table.heading(column, text=column.replace('_', ' ').title())
            width = 230 if column in ('symbol', 'broker_id') else 110
            table.column(column, width=width, minwidth=width, stretch=True)
        table.grid(row=0, column=0, sticky='nsew')
        vertical = ttk.Scrollbar(container, orient='vertical', command=table.yview)
        vertical.grid(row=0, column=1, sticky='ns')
        horizontal = ttk.Scrollbar(container, orient='horizontal', command=table.xview)
        horizontal.grid(row=1, column=0, sticky='ew')
        table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        return table

    @staticmethod
    def horizontal_scroll(frame, table):
        scroll = ttk.Scrollbar(frame, orient='horizontal', command=table.xview)
        scroll.pack(fill='x')
        table.configure(xscrollcommand=scroll.set)

    @staticmethod
    def scrollable(notebook, title):
        page = ttk.Frame(notebook, padding=8)
        notebook.add(page, text=title)
        background = ttk.Style(notebook).lookup('TFrame', 'background') or '#11151c'
        canvas = tk.Canvas(page, highlightthickness=0, background=background)
        scroll = ttk.Scrollbar(page, orient='vertical', command=canvas.yview)
        scroll.pack(side='right', fill='y')
        canvas.pack(fill='both', expand=True)
        canvas.configure(yscrollcommand=scroll.set)
        content = ttk.Frame(canvas)
        item = canvas.create_window((0, 0), window=content, anchor='nw')
        content.bind('<Configure>', lambda event: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda event: canvas.itemconfigure(item, width=event.width))
        # Local bindings leave text-entry and other pages' scrolling untouched.
        def wheel(event):
            canvas.yview_scroll(-1 if event.delta > 0 else 1, 'units')
        def bind_children(widget):
            widget.bind('<MouseWheel>', wheel)
            for child in widget.winfo_children():
                bind_children(child)
        content.bind('<Map>', lambda event: bind_children(content), add='+')
        return content
