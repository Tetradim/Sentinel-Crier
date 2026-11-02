"""Mobile-style desktop presentation; callbacks own all account/execution effects."""
import tkinter as tk
from tkinter import ttk


class MobileShell:
    def __init__(self, root, *, navigate, stop, account, bank, add):
        outer=ttk.Frame(root,padding=(18,12,18,10));outer.pack(fill='both',expand=True)
        header=ttk.Frame(outer);header.pack(fill='x',pady=(0,12))
        identity=ttk.Frame(header);identity.pack(side='left',fill='x',expand=True)
        ttk.Label(identity,text='C R I E R',style='Brand.TLabel').pack(anchor='w')
        self.account=tk.StringVar(value='Alpaca account')
        ttk.Label(identity,textvariable=self.account,style='Title.TLabel').pack(anchor='w')
        self.environment=tk.StringVar(value='OFFLINE')
        ttk.Label(header,textvariable=self.environment,style='Accent.TLabel',padding=(12,8)).pack(side='right')
        tools=ttk.Frame(outer);tools.pack(fill='x',pady=(0,10))
        self.stop=ttk.Button(tools,text='Stop all',command=stop,style='Danger.TButton',width=9)
        self.stop.pack(side='right',padx=(5,0))
        for title,callback,width in [('Account',account,7),('ID bank',bank,6),('Add',add,4)]:
            ttk.Button(tools,text=title,command=callback,style='Tertiary.TButton',width=width).pack(side='right',padx=3)
        self.route_holder=ttk.Frame(tools);self.route_holder.pack(side='left',fill='x',expand=True)
        nav=ttk.Frame(outer);nav.pack(side='bottom',fill='x',pady=(10,0))
        self.navigation={}
        for i,name in enumerate(('Home','Markets','Trade','Positions','Orders')):
            button=ttk.Button(nav,text=name,command=lambda n=name:navigate(n),style='Nav.TButton')
            button.grid(row=0,column=i,sticky='ew',padx=2);nav.columnconfigure(i,weight=1,uniform='nav')
            self.navigation[name]=button
        self.section=tk.StringVar(value='Home')
        section=ttk.Frame(outer);section.pack(fill='x')
        ttk.Label(section,textvariable=self.section,style='Section.TLabel').pack(side='left',pady=(0,8))
        self.content=ttk.Frame(outer);self.content.pack(fill='both',expand=True)

    def select(self,name):
        self.section.set(name)
        for title,button in self.navigation.items():
            button.state(['selected'] if title==name else ['!selected'])

    def render(self,state):
        connected=state.get('connected',False)
        environment=state.get('environment') or state.get('pair',{}).get('environment')
        self.environment.set(environment.upper() if connected and environment in ('paper','live') else 'OFFLINE')
        account=state.get('account')
        self.account.set('Alpaca · '+str(account)[-4:] if connected and account else 'Alpaca account')


class AccountHome:
    def __init__(self,frame,*,purpose,navigate,practice,test_connection):
        frame=scroll_content(frame)
        self.balance=tk.StringVar(value='—');self.trade_count=tk.StringVar(value='0');self.order_count=tk.StringVar(value='0')
        card=ttk.Frame(frame,style='Card.TFrame',padding=18);card.pack(fill='x',pady=(0,12))
        ttk.Label(card,text='TOTAL ACCOUNT VALUE',style='Card.TLabel').pack(anchor='w')
        ttk.Label(card,textvariable=self.balance,style='Balance.TLabel').pack(anchor='w',pady=(8,4))
        ttk.Label(card,text='Buying power   —                  Cash   —',style='Card.TLabel').pack(anchor='w')
        ttk.Label(card,text='Balance feed unavailable. Verify the selected account before trading.',style='Card.TLabel',wraplength=680).pack(anchor='w',pady=(8,0))
        counts=ttk.Frame(frame);counts.pack(fill='x',pady=(0,12))
        for column,(title,value,target) in enumerate([('Tracked trades',self.trade_count,'Positions'),('Saved orders',self.order_count,'Orders')]):
            box=ttk.Frame(counts,style='Card.TFrame',padding=12);box.grid(row=0,column=column,sticky='ew',padx=(0,8));counts.columnconfigure(column,weight=1,uniform='counts')
            ttk.Label(box,text=title,style='Card.TLabel').pack(side='left')
            ttk.Label(box,textvariable=value,style='Card.TLabel').pack(side='right')
            ttk.Button(box,text='Open',style='Tertiary.TButton',command=lambda n=target:navigate(n)).pack(side='right',padx=12)
        ttk.Label(frame,text='Connect your account',style='Section.TLabel').pack(anchor='w',pady=(0,6))
        choices=ttk.Frame(frame);choices.pack(fill='x')
        for i,(title,value) in enumerate([('Send my fills to Discord','alerts'),('Trade/share trades','trade'),('Follow trades','follow')]):
            ttk.Button(choices,text=title,command=lambda p=value:purpose(p),style='Accent.TButton').grid(row=0,column=i,sticky='ew',padx=(0,6));choices.columnconfigure(i,weight=1)
        links=ttk.Frame(frame);links.pack(fill='x',pady=10)
        for title,callback in [('What happened?',lambda:navigate('Decisions')),('Setup & connections',lambda:navigate('Account')),('Optional paper practice / support (F1)',practice),('Test my connection (read-only)',test_connection)]:
            ttk.Button(links,text=title,command=callback,style='Tertiary.TButton').pack(fill='x',pady=3)

    def render(self,state):
        execution=state.get('execution') or {}
        self.trade_count.set(str(len(execution.get('trades',[]))))
        self.order_count.set(str(len(execution.get('orders',[]))))


def markets_view(frame,navigate):
    frame=scroll_content(frame)
    ttk.Label(frame,text='Markets',style='Title.TLabel').pack(anchor='w',pady=(0,16))
    card=ttk.Frame(frame,style='Card.TFrame',padding=24);card.pack(fill='both',expand=True)
    ttk.Label(card,text='Chart unavailable',style='Card.TLabel',font=('Segoe UI',18,'bold')).pack(anchor='center',pady=(35,12))
    ttk.Label(card,text='A live chart feed is not connected.',style='Card.TLabel').pack(anchor='center')
    ttk.Label(card,text='Enter your own stock or exact option limit price in Trade.',style='Card.TLabel',wraplength=600).pack(anchor='center',pady=12)
    ttk.Button(card,text='Open Trade',command=lambda:navigate('Trade'),style='Accent.TButton').pack(pady=18)


def scroll_content(frame):
    canvas=tk.Canvas(frame,highlightthickness=0,takefocus=True)
    bar=ttk.Scrollbar(frame,orient='vertical',command=canvas.yview);bar.pack(side='right',fill='y')
    canvas.pack(fill='both',expand=True);canvas.configure(yscrollcommand=bar.set)
    content=ttk.Frame(canvas);item=canvas.create_window((0,0),window=content,anchor='nw')
    content.bind('<Configure>',lambda event:canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.bind('<Configure>',lambda event:canvas.itemconfigure(item,width=event.width))
    canvas.bind('<MouseWheel>',lambda event:canvas.yview_scroll(-1 if event.delta>0 else 1,'units'))
    def wheel(event):
        widget=event.widget
        while widget is not None:
            if widget is content:
                canvas.yview_scroll(-1 if event.delta>0 else 1,'units')
                return 'break'
            widget=getattr(widget,'master',None)
    frame.winfo_toplevel().bind('<MouseWheel>',wheel,add='+')
    canvas.bind('<Next>',lambda event:canvas.yview_scroll(1,'pages'))
    canvas.bind('<Prior>',lambda event:canvas.yview_scroll(-1,'pages'))
    return content
