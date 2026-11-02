"""Shared mobile palette for the native desktop; presentation only, with no I/O."""
import tkinter as tk
from tkinter import ttk


PALETTE = {
    'bg': '#0c1017',
    'surface': '#181f2a',
    'ink': '#ebf0f8',
    'muted': '#9fadc1',
    'accent': '#40a5ff',
    'danger': '#ff707a',
    'border': '#2a3545',
    'active': '#233247',
}


def _native_colors(widget):
    """Color default classic widgets while retaining deliberate status/plot colors."""
    kind = widget.winfo_class()
    colors = {}
    if kind in ('Tk', 'Toplevel', 'Frame', 'Canvas'):
        colors = {'background': PALETTE['bg']}
    elif kind == 'Text':
        colors = {
            'background': PALETTE['surface'], 'foreground': PALETTE['ink'],
            'insertbackground': PALETTE['ink'],
            'selectbackground': PALETTE['accent'], 'selectforeground': PALETTE['bg'],
            'highlightbackground': PALETTE['border'], 'highlightcolor': PALETTE['accent'],
        }
    for option, color in colors.items():
        setting = widget.configure(option)
        # Tk reports the platform default at index 3. An application-provided
        # color has a different current value and must remain meaningful.
        if str(setting[-1]) == str(setting[3]):
            widget.configure(**{option: color})


def install_theme(root):
    """Install Crier's dark ttk styles and classic-widget defaults on a Tk root.

    Call before creating the shell. Repeated calls are safe; existing classic
    widgets are also updated, and later dialog widgets inherit the same palette.
    Returns the configured ttk.Style for optional view-specific use.
    """
    p = PALETTE
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('.', background=p['bg'], foreground=p['ink'],
                    font=('Segoe UI', 10), bordercolor=p['border'],
                    lightcolor=p['border'], darkcolor=p['border'],
                    troughcolor=p['bg'], focuscolor=p['accent'])
    style.configure('TFrame', background=p['bg'])
    style.configure('Card.TFrame', background=p['surface'])
    style.configure('TLabel', background=p['bg'], foreground=p['ink'])
    style.configure('Card.TLabel', background=p['surface'])
    style.configure('Balance.TLabel', background=p['surface'], foreground=p['ink'],
                    font=('Segoe UI', 32, 'bold'))
    for name, size in (('Brand', 13), ('Title', 24), ('Section', 16)):
        style.configure(name + '.TLabel', font=('Segoe UI', size, 'bold'))
    style.configure('Subtitle.TLabel', foreground=p['muted'])
    style.configure('Muted.TLabel', foreground=p['muted'])
    style.configure('Accent.TLabel', foreground=p['accent'])
    style.configure('Danger.TLabel', foreground=p['danger'])
    style.configure('TButton', background=p['surface'], foreground=p['ink'],
                    padding=(14, 9), borderwidth=1, relief='flat')
    style.map('TButton', background=[('disabled', p['surface']), ('pressed', p['active']),
                                     ('active', p['active'])],
              foreground=[('disabled', p['muted'])])
    for name, color, foreground in (('Accent', p['accent'], p['bg']),
                                     ('Danger', p['danger'], p['bg'])):
        style.configure(name + '.TButton', background=color, foreground=foreground,
                        font=('Segoe UI', 10, 'bold'))
        style.map(name + '.TButton',
                  background=[('disabled', p['surface']), ('pressed', color), ('active', color)],
                  foreground=[('disabled', p['muted']), ('!disabled', foreground)])
    style.configure('Tertiary.TButton', background=p['bg'], foreground=p['muted'], borderwidth=0)
    style.configure('Nav.TButton', background=p['bg'], foreground=p['muted'],
                    padding=(16, 12), borderwidth=0)
    style.map('Nav.TButton', foreground=[('disabled', p['muted']), ('selected', p['accent']),
                                          ('active', p['ink'])],
              background=[('selected', p['surface']), ('active', p['surface'])])
    for name in ('TEntry', 'TCombobox', 'TSpinbox'):
        style.configure(name, fieldbackground=p['surface'], background=p['surface'],
                        foreground=p['ink'], insertcolor=p['ink'],
                        arrowcolor=p['muted'], padding=7,
                        selectbackground=p['accent'], selectforeground=p['bg'])
        style.map(name,
                  fieldbackground=[('disabled', p['bg']), ('readonly', p['surface'])],
                  foreground=[('disabled', p['muted']), ('readonly', p['ink'])],
                  selectbackground=[('!disabled', p['accent'])],
                  selectforeground=[('!disabled', p['bg'])],
                  bordercolor=[('focus', p['accent'])],
                  arrowcolor=[('disabled', p['border']), ('active', p['accent'])])
    style.configure('Treeview', background=p['surface'], fieldbackground=p['surface'],
                    foreground=p['ink'], rowheight=32, borderwidth=0)
    style.map('Treeview', background=[('selected', p['accent'])],
              foreground=[('selected', p['bg'])])
    style.configure('Treeview.Heading', background=p['bg'], foreground=p['muted'],
                    font=('Segoe UI', 9, 'bold'), relief='flat', padding=(8, 9))
    style.map('Treeview.Heading', background=[('active', p['active'])],
              foreground=[('active', p['ink'])])
    style.configure('TNotebook', background=p['bg'], borderwidth=0, tabmargins=(0, 0, 0, 4))
    style.configure('TNotebook.Tab', background=p['surface'], foreground=p['muted'], padding=(14, 9))
    style.map('TNotebook.Tab', background=[('selected', p['active']), ('active', p['active'])],
              foreground=[('selected', p['ink']), ('active', p['ink'])])
    # Only the outer mobile shell is tabless; nested setup notebooks stay usable.
    style.layout('Mobile.TNotebook.Tab', [])
    style.configure('TLabelframe', background=p['bg'], bordercolor=p['border'], relief='solid')
    style.configure('TLabelframe.Label', background=p['bg'], foreground=p['muted'],
                    font=('Segoe UI', 10, 'bold'))
    for name in ('Vertical.TScrollbar', 'Horizontal.TScrollbar'):
        style.configure(name, background=p['border'], arrowcolor=p['muted'],
                        troughcolor=p['bg'], borderwidth=0, arrowsize=12)
        style.map(name, background=[('active', p['muted']), ('pressed', p['muted'])])
    for name in ('TCheckbutton', 'TRadiobutton', 'Segmented.TRadiobutton'):
        style.configure(name, background=p['bg'], foreground=p['ink'],
                        indicatorbackground=p['surface'], indicatorforeground=p['accent'], padding=6)
        style.map(name, background=[('active', p['surface'])],
                  foreground=[('disabled', p['muted']), ('selected', p['accent'])],
                  indicatorbackground=[('disabled', p['bg']), ('selected', p['accent'])])
    style.configure('TSeparator', background=p['border'])
    style.configure('TProgressbar', background=p['accent'], troughcolor=p['surface'], borderwidth=0)

    # Option-database defaults apply at creation time and never override explicit
    # widget arguments. ttk's popup listbox is a classic Tk Listbox.
    defaults = {
        'Text': {'background': p['surface'], 'foreground': p['ink'],
                 'insertBackground': p['ink'], 'selectBackground': p['accent'],
                 'selectForeground': p['bg'], 'highlightBackground': p['border'],
                 'highlightColor': p['accent']},
        'Canvas': {'background': p['bg'], 'highlightBackground': p['border']},
        'Toplevel': {'background': p['bg']},
    }
    for kind, options in defaults.items():
        for option, value in options.items():
            root.option_add('*' + kind + '.' + option, value, 'widgetDefault')
    for option, value in {'background': p['surface'], 'foreground': p['ink'],
                          'selectBackground': p['accent'], 'selectForeground': p['bg']}.items():
        root.option_add('*TCombobox*Listbox.' + option, value, 'widgetDefault')

    def theme_existing(widget):
        _native_colors(widget)
        for child in widget.winfo_children():
            theme_existing(child)

    theme_existing(root)
    if not getattr(root, '_crier_theme_map_binding', None):
        def on_map(event):
            # Tcl-owned popups can have no Python widget object.
            if isinstance(event.widget, tk.Misc):
                try:
                    _native_colors(event.widget)
                except tk.TclError:
                    pass  # It may have been destroyed by an earlier Map handler.
        root._crier_theme_map_binding = root.bind_all('<Map>', on_map, add='+')
    return style
