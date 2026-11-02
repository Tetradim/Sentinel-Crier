"""Explicit local evidence reads; no execution or delivery permissions."""
import re
import tkinter as tk
from tkinter import ttk

from .desktop_practice import readonly_traversal


class DecisionPanel:
    def __init__(self, frame, *, send, epoch, details):
        self.send, self.epoch, self.details = send, epoch, details
        self.context = None
        self.rows = []
        self.selected = None
        self.revision = 0
        self.summary = tk.StringVar(value='Reconnect and select a tracked trade to read its local evidence.')
        ttk.Label(frame, text='What happened?', style='Section.TLabel').pack(anchor='w')
        ttk.Label(frame, text='Recent recorded steps for this connection. These are local observations, not a current broker-health check.',
                  wraplength=650, style='Muted.TLabel').pack(anchor='w', pady=6)
        controls = ttk.Frame(frame)
        controls.pack(fill='x', pady=6)
        self.choice = ttk.Combobox(controls, state='readonly', width=30)
        self.choice.pack(fill='x', expand=True)
        actions = ttk.Frame(controls)
        actions.pack(fill='x', pady=(6,0))
        self.choice.bind('<<ComboboxSelected>>', self.select)
        ttk.Button(actions, text='Read local evidence', command=self.load).pack(side='left', padx=6)
        ttk.Button(actions, text='Detailed timeline', command=self.open_details).pack(side='left')
        body = ttk.Frame(frame)
        body.pack(fill='both', expand=True)
        self.text = tk.Text(body, wrap='word', state='disabled', height=8, font=('Segoe UI', 11))
        scroll = ttk.Scrollbar(body, orient='vertical', command=self.text.yview)
        scroll.pack(side='right', fill='y')
        self.text.pack(fill='both', expand=True)
        self.text.configure(yscrollcommand=scroll.set)
        readonly_traversal(self.text)
        self.summary.trace_add('write', self._render_text)
        self._render_text()

    def _render_text(self, *_):
        self.text.configure(state='normal')
        self.text.delete('1.0', 'end')
        self.text.insert('1.0', self.summary.get())
        self.text.configure(state='disabled')

    def render_state(self, state):
        context = (self.epoch(), state.get('account'), state.get('environment'), state.get('mode'), bool(state.get('connected')))
        execution = state.get('execution') or {}
        rows = execution.get('trades', []) if state.get('connected') else []
        rows = sorted(rows, key=lambda row: str(row.get('event', {}).get('created_at', '')), reverse=True)[:50]
        previous = self.selected
        if context != self.context:
            self.context = context
            previous = None
            self.revision += 1
            self.summary.set('Select a tracked trade, then read its local evidence.' if rows else
                             'Reconnect to read local trade evidence.' if not state.get('connected') else 'No tracked trade evidence is available for this connection.')
        self.rows = rows
        labels = []
        for row in rows:
            symbol = row.get('event', {}).get('symbol', '')
            if not isinstance(symbol, str) or not re.fullmatch(r'[A-Z0-9.]{1,32}', symbol):
                symbol = 'Tracked trade'
            labels.append(symbol + ' · ' + str(row['id'])[:8])
        self.choice.configure(values=labels)
        if rows:
            index = next((i for i, row in enumerate(rows) if row['id'] == previous), 0)
            self.choice.current(index)
            self.selected = rows[index]['id']
        else:
            self.choice.set('')
            self.selected = None
        if previous is not None and previous != self.selected:
            self.revision += 1
            self.summary.set('Select a tracked trade, then read its local evidence.' if rows else 'No tracked trade evidence is available for this connection.')

    def select(self, *_):
        index = self.choice.current()
        self.selected = self.rows[index]['id'] if 0 <= index < len(self.rows) else None
        self.revision += 1
        self.summary.set('Read local evidence for the selected trade.')

    def load(self):
        if self.selected is None:
            return
        self.revision += 1
        ticket = (self.revision, self.epoch(), self.selected)
        def loaded(report):
            if ticket != (self.revision, self.epoch(), self.selected):
                return
            if not isinstance(report, dict) or report.get('trade_id') != self.selected:
                self.summary.set('Matching local evidence is unavailable. Inspect the detailed timeline.')
                return
            from .decision_summary import describe_decisions
            self.summary.set('Recent recorded steps (oldest to newest):\n\n' + '\n\n'.join(describe_decisions(report.get('timeline', []))))
        self.summary.set('Reading local evidence. A failed read is reported in the status bar; you can retry this read.')
        self.send('diagnostics', self.selected, callback=loaded)

    def open_details(self):
        if self.selected is not None:
            self.details(self.selected)
