"""Ticket interaction and scaled layout checks, without broker connections."""
import tkinter as tk
from tkinter import ttk
import pytest

from crier.desktop_trading_views import TradingWorkspace
from crier.desktop_theme import install_theme


class TestMobileTicket:
    @pytest.fixture(autouse=True)
    def workspace(self, desktop_tk_root):
        self.root = tk.Toplevel(desktop_tk_root)
        self.root.tk.call('tk', 'scaling', 2.0)
        self.root.geometry('850x650')
        install_theme(self.root)
        self.frame = ttk.Frame(self.root)
        self.frame.pack(fill='both', expand=True)
        self.commands, self.settings = [], []

        def entry(parent, label, value=''):
            row = ttk.Frame(parent)
            row.pack(fill='x')
            ttk.Label(row, text=label, width=25).pack(side='left')
            variable = tk.StringVar(value=value)
            ttk.Entry(row, textvariable=variable).pack(side='left', fill='x', expand=True)
            return variable

        self.view = TradingWorkspace(self.frame, send=lambda *args: self.settings.append(args),
                                     command=self.commands.append, entry=entry)
        self.root.update()
        yield
        self.root.destroy()

    def test_segmented_asset_selection_preserves_broker_values_and_defaults(self):
        assert self.view.asset.get() == 'option'
        assert self.view.order_qty.get() == '1'
        assert self.view.price.get() == '0.20'
        self.view.asset_selectors['stock'].invoke()
        assert self.view.asset.get() == 'stock'
        self.view.asset_selectors['option'].invoke()
        assert self.view.asset.get() == 'option'

    def test_ticket_preview_describes_only_entered_order(self):
        self.view.symbol.set('AAPL')
        self.view.order_qty.set('3')
        self.view.price.set('12.50')
        self.view.asset_selectors['stock'].invoke()
        assert 'AAPL' in self.view.preview.get()
        assert '3' in self.view.preview.get()
        assert '12.50' in self.view.preview.get()
        assert 'No live quote' in self.view.preview.get()
        assert self.commands == []

    def test_controls_remain_guarded_and_keep_existing_callbacks(self):
        for button in self.view.host_buttons + self.view.execution_buttons:
            assert button.instate(['disabled'])
            button.invoke()
        assert self.commands == []
        assert self.settings == []
        for button in self.view.host_buttons:
            button.state(['!disabled'])
            button.invoke()
        assert self.commands == ['enter', 'replace', 'cancel', 'exit']
        for button in self.view.execution_buttons:
            button.state(['!disabled'])
            button.invoke()
        assert self.settings == [('settings', {'enabled': True}), ('settings', {'enabled': False})]

    def test_scaled_ticket_and_tables_can_reach_all_actions(self):
        assert [self.view.navigation.tab(t, 'text') for t in self.view.navigation.tabs()] == ['Order', 'Positions', 'Activity']
        for button in self.view.host_buttons:
            assert button.winfo_width() > 40
            assert button.winfo_rootx() + button.winfo_width() <= self.root.winfo_rootx() + self.root.winfo_width()
        canvas = self.view.host_buttons[-1].master
        while not isinstance(canvas, tk.Canvas):
            canvas = canvas.master
        canvas.yview_moveto(1.0)
        self.root.update()
        last_action = self.view.host_buttons[-1]
        assert last_action.winfo_rooty() >= canvas.winfo_rooty()
        assert last_action.winfo_rooty() + last_action.winfo_height() <= canvas.winfo_rooty() + canvas.winfo_height()
        for table in (self.view.trades, self.view.orders):
            assert table.cget('yscrollcommand')
            assert table.cget('xscrollcommand')
