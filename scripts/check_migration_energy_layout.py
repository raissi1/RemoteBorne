"""Offline functional/layout audit for Migration and Energy Manager.

Use --scale 1.3333, 2 or 2.6667 in separate processes for fresh DPI styles.
All SSH actions are mocked. Migration files are temporary.
"""
import argparse
import configparser
import pathlib
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock, patch
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import ttkbootstrap as ttk
from src.RemoteBorneManager import RemoteBorneApp
from src.energy_manager import EnergyManagerWindow
from src.gridcodes_migration_ui import GridCodesMigrationWindow

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--scale', type=float, default=1.3333)
args = parser.parse_args()
root = ttk.Window()
root.tk.call('tk', 'scaling', args.scale)
errors = []
root.report_callback_exception = lambda kind, value, tb: errors.append(str(value))
cfg = configparser.ConfigParser(interpolation=None)
cfg.read(pathlib.Path(__file__).resolve().parents[1] / 'config/config.example.ini')
with patch('src.RemoteBorneManager.ttk.Window', return_value=root), patch('src.RemoteBorneManager.SSHManager.start'):
    app = RemoteBorneApp(cfg)
app.ssh_queue.stop()
app.ssh_queue = Mock()
app.ssh_queue.execute.return_value = True
app.connected = app.ssh.connected = True
root.withdraw()


def inside(widget, window):
    root.update()
    assert widget.winfo_ismapped(), str(widget)
    x, y = widget.winfo_rootx(), widget.winfo_rooty()
    right, bottom = x + widget.winfo_width(), y + widget.winfo_height()
    ancestor = widget.master
    while ancestor is not None:
        assert x >= ancestor.winfo_rootx() and y >= ancestor.winfo_rooty(), ('clipped start', str(widget))
        assert right <= ancestor.winfo_rootx() + ancestor.winfo_width() + 1, ('clipped right', str(widget))
        assert bottom <= ancestor.winfo_rooty() + ancestor.winfo_height() + 1, ('clipped bottom', str(widget))
        if ancestor is window:
            break
        ancestor = ancestor.master


def tree_rows(tree, count=2):
    tree.yview_moveto(0)
    root.update()
    for row in tree.get_children()[:count]:
        bounds = tree.bbox(row)
        assert bounds and bounds[1] + bounds[3] <= tree.winfo_height(), ('clipped rows', bounds, tree.winfo_height())


for theme in ('flatly', 'darkly'):
    app._apply_theme(theme)
    for width, height in ((1920, 1080), (1024, 600)):
        with patch('src.utils_ui.screen_work_area', return_value=(0, 0, width, height)):
            energy = EnergyManagerWindow(root, app.ssh, app.ssh_queue, pn_limit_provider=lambda: 11000)
            energy.history.extend(('12:00', 'P/Q', 'Example setpoint', 'OK') for _ in range(6))
            energy.update_history_table()
            energy.monitor_text.insert('end', 'Energy Manager: example status\nReady\n')
            inside(energy.table, energy.win)
            inside(energy.monitor_text, energy.win)
            tree_rows(energy.table, 4 if height >= 1000 else 2)
            energy.p_var.set('1000')
            energy.q_var.set('0')
            with patch.object(energy, '_popup_info'):
                energy.send_pq()
                queued = app.ssh_queue.execute.call_args
                assert '--power 1000' in queued.args[0]
                queued.kwargs['callback']({'success': True, 'out': 'OK', 'err': ''})
                root.update()
            assert energy.history[-1][-1] == 'OK'
            energy.win.geometry(f'{min(1000, width-24)}x{min(650, height-48)}')
            inside(energy.table, energy.win)
            inside(energy.monitor_text, energy.win)
            tree_rows(energy.table)
            for entry in energy._descendants(energy._energy_main):
                if entry.winfo_class() == 'TEntry':
                    energy._energy_scroll._focus(SimpleNamespace(widget=entry))
                    inside(entry, energy.win)
            inside(energy.table, energy.win)
            inside(energy.monitor_text, energy.win)
            energy.close()

            with tempfile.TemporaryDirectory() as directory:
                base = pathlib.Path(directory)
                source = base / 'source'
                source.mkdir()
                for index in range(6):
                    (source / f'GC_{index}.properties').write_text('Country=FR\nPower=100\n', encoding='utf-8')
                template = base / 'template.properties'
                template.write_text('Country=DE\nPower=200\nAdded=1\n', encoding='utf-8')
                migration = GridCodesMigrationWindow(root, directory, lambda: False, Mock(), Mock())
                migration.source_var.set(str(source))
                migration.template_var.set(str(template))
                migration.output_var.set(str(base / 'output'))
                with patch('src.gridcodes_migration_ui.threading.Thread', side_effect=lambda target, **kw: Mock(start=target)), \
                     patch('src.gridcodes_migration_ui.messagebox.showerror') as error:
                    migration.analyze()
                    root.update()
                    assert not error.called, error.call_args
                assert len(migration.tree.get_children()) == 6
                assert 'Source:' in migration.details.get('1.0', 'end')
                inside(migration.tree, migration.window)
                inside(migration.details, migration.window)
                tree_rows(migration.tree, 4 if height >= 1000 else 2)
                with patch('src.gridcodes_migration_ui.messagebox.askyesno', return_value=True), \
                     patch('src.gridcodes_migration_ui.messagebox.showinfo'):
                    migration.export()
                assert migration.export_dir is not None
                for index in range(6):
                    assert (source / f'GC_{index}.properties').read_text(encoding='utf-8') == 'Country=FR\nPower=100\n'
                    assert (migration.export_dir / f'GC_{index}.properties').exists()
                migration.window.geometry(f'{min(1000, width-24)}x{min(650, height-48)}')
                inside(migration.tree, migration.window)
                inside(migration.details, migration.window)
                tree_rows(migration.tree)
                for group in migration._path_fields:
                    for widget in group:
                        migration._migration_scroll._focus(SimpleNamespace(widget=widget))
                        inside(widget, migration.window)
                inside(migration.tree, migration.window)
                inside(migration.details, migration.window)
                assert migration._migration_scroll.canvas.xview() == (0.0, 1.0), "Migration form should reflow without horizontal clipping"
                migration.close()
            print(theme, args.scale, (width, height), 'Energy/history/monitor and migration/preview/details/export: OK')
assert not errors, errors
root.destroy()
