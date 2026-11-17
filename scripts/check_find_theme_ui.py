"""Offline functional Find/editor/theme checks. Requires a Tk display; no EVSE."""
import configparser
import pathlib
import sys
import tempfile
import tkinter as tk
from unittest.mock import Mock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import ttkbootstrap as ttk
from src.RemoteBorneManager import RemoteBorneApp
from src.debug_logs import DebugLogsWindow


def children(widget):
    for child in widget.winfo_children():
        yield child
        yield from children(child)


def button(window, name):
    return next(w for w in children(window) if w.winfo_class() == 'TButton' and w.cget('text') == name)


cfg = configparser.ConfigParser(interpolation=None)
cfg.read(ROOT / 'config/config.example.ini')
r = ttk.Window(themename='flatly')
errors = []
r.report_callback_exception = lambda kind, value, tb: errors.append(str(value))
with patch('src.RemoteBorneManager.ttk.Window', return_value=r), patch('src.RemoteBorneManager.SSHManager.start'):
    app = RemoteBorneApp(cfg)
app.ssh_queue.stop()
app.ssh_queue = Mock()
app.connected = app.ssh.connected = True
app._update_controls_state()
app._file_entries = ['test.py', 'GridCodes.properties', 'Power/']
app._file_list_path = app.current_path
app._render_file_entries()

with tempfile.TemporaryDirectory() as directory:
    for theme in ('darkly', 'flatly'):
        app._apply_theme(theme)
        r.update()
        app._open_file_find_dialog()
        dialog = app._browser_find_dialog
        entry = next(w for w in children(dialog) if w.winfo_class() == 'TEntry')
        entry.insert(0, 'test')
        button(dialog, 'Find').invoke()
        assert app._file_find_var.get() == 'test', 'Find fields are not synchronized'
        callback = app.ssh_queue.execute.call_args.kwargs['callback']
        path = app.current_path + '/nested/test.py'
        callback({'success': True, 'out': path + '\n'})
        r.update()
        assert ('file', path) in app._recursive_search_rows.values()
        button(dialog, 'Clear').invoke()
        assert not app._recursive_search_active
        assert [row for row in app.file_list.get(0, 'end') if not row.startswith('[.]')] == app._file_entries, (app.file_list.get(0, 'end'), app._file_entries)
        button(dialog, 'Close').invoke()

        local = pathlib.Path(directory) / 'test.properties'
        content = 'Power=1\nPower=2\nénergie=3\n'
        local.write_text(content, encoding='utf-8')
        app._show_file_editor('/grid/test.properties', str(local))
        editor = app._editor_window
        text = next(w for w in children(editor) if w.winfo_class() == 'Text')
        r.update()
        assert text.cget('background') == app.style.lookup('TEntry', 'fieldbackground')
        assert text.cget('insertbackground') == app.style.lookup('TLabel', 'foreground')
        scrollbars = [w for w in children(editor) if w.winfo_class() == 'TScrollbar']
        assert not any(w.winfo_ismapped() for w in scrollbars), 'empty scroll tracks visible'
        text.insert('end', ('long_value=' + 'x' * 500 + '\n') * 100)
        r.update()
        assert all(w.winfo_ismapped() for w in scrollbars), 'overflow cannot be scrolled'
        text.delete('1.0', 'end')
        text.insert('1.0', content)
        r.update()
        assert not any(w.winfo_ismapped() for w in scrollbars)
        button(editor, 'Find').invoke()
        find = app._find_dialog
        query = next(w for w in children(find) if w.winfo_class() == 'TEntry')
        query.insert(0, 'power')
        button(find, 'Find').invoke()
        assert len(text.tag_ranges('find_match')) == 4
        first = text.index('insert')
        button(find, 'Next').invoke()
        assert text.index('insert') != first
        button(find, 'Previous').invoke()
        assert text.index('insert') == first
        find.event_generate('<Escape>')
        r.update()
        assert app._find_dialog is None
        app._apply_theme('flatly' if theme == 'darkly' else 'darkly')
        r.update()
        assert text.cget('background') == app.style.lookup('TEntry', 'fieldbackground')
        assert text.get('1.0', 'end-1c') == content
        with patch.object(app.ssh, 'scp_put', return_value={'success': True, 'out': '', 'err': ''}) as upload, \
             patch.object(app, 'refresh_file_list'), \
             patch('src.RemoteBorneManager.messagebox.askyesno', return_value=True), \
             patch('src.RemoteBorneManager.simpledialog.askstring', return_value='copy.properties'), \
             patch('src.RemoteBorneManager.threading.Thread', side_effect=lambda target, **kw: Mock(start=target)):
            button(editor, 'Save').invoke()
            r.update()
            assert upload.call_args.args[:2] == (str(local), '/grid/test.properties')
            assert local.read_text(encoding='utf-8') == content
            button(editor, 'Save As').invoke()
            app.ssh_queue.execute.call_args.kwargs['callback']({'success': False})
            r.update()
            assert upload.call_args.args[:2] == (str(local), '/grid/copy.properties')
        app._close_editor_window()
        assert not local.exists()
        debug = DebugLogsWindow(r, ('127.0.0.1', 'user', 'test'))
        debug.insert_line('EnergyManager.log', 'INFO Power test')
        debug.global_find_var.set('power')
        debug.find_in_all_logs()
        r.update()
        assert 'Power test' in debug.global_results_text.get('1.0', 'end')
        debug.on_close()
assert not errors, errors
r.destroy()
print('File Find, Clear, recursive script paths, editor Find/Next/Previous, global log Find and live theme changes: OK')
