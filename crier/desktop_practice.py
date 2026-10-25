"""Optional help window. This module has no worker or account reference."""
import tkinter as tk
from tkinter import ttk
import webbrowser
from .customer_guide import load_guide, SUPPORT_URL


def readonly_traversal(widget):
    def move(event,back=False):
        target=event.widget.tk_focusPrev() if back else event.widget.tk_focusNext()
        if target is not None: target.focus_set()
        return 'break'
    widget.configure(takefocus=True)
    widget.bind('<Tab>',move)
    widget.bind('<Shift-Tab>',lambda event:move(event,True))
    if widget.tk.call('tk','windowingsystem')=='x11':
        widget.bind('<ISO_Left_Tab>',lambda event:move(event,True))


class PracticeWindow:
    def __init__(self,parent):
        self.guide=load_guide()
        self.window=tk.Toplevel(parent)
        self.window.title('Optional paper practice')
        self.window.geometry('760x560'); self.window.minsize(520,360)
        frame=ttk.Frame(self.window,padding=16); frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='Optional paper practice',font=('Segoe UI',16,'bold')).pack(anchor='w',pady=(0,8))
        ttk.Label(frame,text='Choose a guide. No connection, publishing or order action is performed.').pack(anchor='w')
        self.selector=ttk.Combobox(frame,state='readonly',values=[j.title for j in self.guide.journeys])
        self.selector.pack(fill='x',pady=8); self.selector.current(0)
        area=ttk.Frame(frame); area.pack(fill='both',expand=True)
        self.body=tk.Text(area,wrap='word',state='disabled',padx=8,pady=8)
        scroll=ttk.Scrollbar(area,orient='vertical',command=self.body.yview)
        self.body.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y'); self.body.pack(side='left',fill='both',expand=True)
        readonly_traversal(self.body)
        actions=ttk.Frame(frame); actions.pack(fill='x',pady=(10,0))
        self.support=ttk.Button(actions,text='Open support (GitHub Issues)',command=lambda:webbrowser.open(SUPPORT_URL))
        self.support.pack(side='left')
        ttk.Button(actions,text='Return to Crier',command=self.window.destroy).pack(side='right')
        self.selector.bind('<<ComboboxSelected>>',lambda event:self.render())
        self.window.bind('<Escape>',lambda event:self.window.destroy())
        self.render(); self.selector.focus_set()

    def render(self):
        purpose=self.guide.journeys[self.selector.current()].id
        self.body.configure(state='normal'); self.body.delete('1.0','end')
        self.body.insert('1.0',self.guide.text(purpose)); self.body.configure(state='disabled')
        self.body.yview_moveto(0)
