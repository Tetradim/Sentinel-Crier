"""Real Tk checks for the shared presentation layer (no broker/session needed)."""
import ast
from pathlib import Path
import tkinter as tk
from tkinter import ttk


def test_shared_palette_and_readable_readonly_controls(desktop_tk_root):
    from crier.desktop_theme import install_theme, PALETTE

    root = desktop_tk_root
    style = install_theme(root)
    assert style.theme_use() == 'clam'
    assert PALETTE['bg'] == '#0c1017'
    assert PALETTE['surface'] == '#181f2a'
    assert PALETTE['ink'] == '#ebf0f8'
    assert style.lookup('TFrame', 'background') == PALETTE['bg']
    assert style.lookup('TCombobox', 'fieldbackground', ('readonly',)) == PALETTE['surface']
    assert style.lookup('TCombobox', 'foreground', ('readonly',)) == PALETTE['ink']
    assert style.lookup('Treeview', 'background', ('selected',)) == PALETTE['accent']
    assert style.lookup('Treeview', 'foreground', ('selected',)) == PALETTE['bg']
    assert style.lookup('TButton', 'foreground', ('disabled',)) == PALETTE['muted']


def test_mobile_notebook_hides_only_shell_tabs(desktop_tk_root):
    from crier.desktop_theme import install_theme

    style = install_theme(desktop_tk_root)
    shell = ttk.Notebook(desktop_tk_root, style='Mobile.TNotebook', height=50)
    nested = ttk.Notebook(desktop_tk_root, height=50)
    for notebook in (shell, nested):
        notebook.add(ttk.Frame(notebook), text='Account setup')
    desktop_tk_root.update_idletasks()
    assert shell.winfo_reqheight() < nested.winfo_reqheight()
    assert style.layout('TNotebook.Tab')
    assert style.lookup('Nav.TButton', 'foreground', ('selected',)) == '#40a5ff'
    assert style.lookup('Card.TLabel', 'background') == '#181f2a'


def test_existing_native_text_gets_dark_selection_without_changing_data(desktop_tk_root):
    from crier.desktop_theme import install_theme, PALETTE

    text = tk.Text(desktop_tk_root)
    text.insert('1.0', 'Account unavailable\nNo quotes connected')
    text.configure(state='disabled')
    install_theme(desktop_tk_root)
    assert text.cget('background') == PALETTE['surface']
    assert text.cget('foreground') == PALETTE['ink']
    assert text.cget('selectbackground') == PALETTE['accent']
    assert text.cget('insertbackground') == PALETTE['ink']
    assert text.cget('state') == 'disabled'
    assert text.get('1.0', 'end-1c') == 'Account unavailable\nNo quotes connected'


def test_late_dialog_widgets_inherit_theme_but_keep_explicit_colors(desktop_tk_root):
    from crier.desktop_theme import install_theme, PALETTE

    root = desktop_tk_root
    install_theme(root)
    dialog = tk.Toplevel(root)
    text = tk.Text(dialog)
    text.pack()
    canvas = tk.Canvas(dialog)
    canvas.pack()
    custom = tk.Text(dialog, foreground='#ff707a', background='#112233')
    custom.pack()
    root.update()
    assert text.cget('background') == PALETTE['surface']
    assert text.cget('foreground') == PALETTE['ink']
    assert canvas.cget('background') == PALETTE['bg']
    assert custom.cget('foreground') == '#ff707a'
    assert custom.cget('background') == '#112233'
    combo = ttk.Combobox(dialog, values=('Paper', 'Live'), state='readonly')
    popup = combo.tk.call('ttk::combobox::PopdownWindow', str(combo))
    assert combo.tk.call(str(popup) + '.f.l', 'cget', '-background') == PALETTE['surface']
    assert combo.tk.call(str(popup) + '.f.l', 'cget', '-foreground') == PALETTE['ink']


def test_theme_install_is_idempotent_and_preserves_map_handlers(desktop_tk_root):
    from crier.desktop_theme import install_theme

    root = desktop_tk_root
    events = []
    root.bind_all('<Map>', lambda event: events.append(str(event.widget)), add='+')
    install_theme(root)
    first_binding = root.bind_all('<Map>')
    install_theme(root)
    assert root.bind_all('<Map>') == first_binding
    dialog = tk.Toplevel(root)
    dialog.update()
    assert str(dialog) in events


def test_theme_depends_only_on_tkinter():
    import crier.desktop_theme as theme

    tree = ast.parse(Path(theme.__file__).read_text(encoding='utf-8'))
    imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
    assert imports
    for node in imports:
        modules = [name.name for name in node.names] if isinstance(node, ast.Import) else [node.module]
        assert all(module == 'tkinter' or module.startswith('tkinter.') for module in modules)


def test_balance_label_matches_its_card_and_uses_large_type(desktop_tk_root):
    from crier.desktop_theme import install_theme, PALETTE
    from tkinter import font

    style = install_theme(desktop_tk_root)
    assert style.lookup('Balance.TLabel', 'background') == PALETTE['surface']
    assert style.lookup('Balance.TLabel', 'foreground') == PALETTE['ink']
    actual = font.Font(desktop_tk_root, font=style.lookup('Balance.TLabel', 'font')).actual()
    assert actual['family'] == 'Segoe UI'
    assert actual['size'] == 32
    assert actual['weight'] == 'bold'
