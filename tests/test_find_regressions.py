"""Functional browser Find regressions, without a real SSH connection."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from src.RemoteBorneManager import RemoteBorneApp


class Value:
    def __init__(self, value=""): self.value = value
    def get(self): return self.value
    def set(self, value): self.value = value


class List:
    def __init__(self): self.rows = []; self.selected = ()
    def delete(self, *args): self.rows.clear()
    def insert(self, _, value): self.rows.append(value)
    def curselection(self): return self.selected
    def get(self, index): return self.rows[index]


class TestBrowserFind(unittest.TestCase):
    def setUp(self):
        self.app = app = RemoteBorneApp.__new__(RemoteBorneApp)
        app.connected = True
        app._closing = False
        app.current_path = app.default_path = app._file_list_path = "/grid"
        app._file_entries = ["test.py", "Power/", "GridCodes.properties"]
        app._file_filter_query = ""
        app._file_find_var = Value()
        app._recursive_search_running = app._recursive_search_active = False
        app._recursive_search_rows = {}
        app._recursive_search_pending_query = None
        app._recursive_search_after_id = None
        app._recursive_search_generation = 0
        app.file_list = List()
        app.log = Mock()
        app._popup_warning = Mock()
        app.root = Mock()
        app.root.after.side_effect = lambda delay, callback: callback() if delay == 0 else 'timer'
        app.ssh_queue = Mock()
        app.ssh_timeout = 30
        app.find_entry = Mock()
        app.open_terminal = Mock()
        app.open_file_editor = Mock()

    def search(self, query):
        self.app._file_find_var.set(query)
        self.app._file_filter_query = query
        self.app._search_files_in_subfolders(query)
        return self.app.ssh_queue.execute.call_args

    def respond(self, call, output):
        call.kwargs['callback']({'success': True, 'out': output, 'err': ''})

    def test_recursive_script_can_open_in_terminal_and_edit_uses_full_path(self):
        call = self.search('test')
        self.respond(call, '/grid/deep/test.py\n/grid/deep/test.properties\n')
        self.app.file_list.selected = (2,)
        self.assertEqual(self.app._selected_remote_file(), '/grid/deep/test.py')
        self.app.on_file_double_click(None)
        self.app.open_terminal.assert_called_once_with(initial_command='python3 /grid/deep/test.py')
        self.app.file_list.selected = (1,)
        self.app.on_file_double_click(None)
        self.app.open_file_editor.assert_called_once_with('/grid/deep/test.properties')

    def test_find_filters_before_limit_and_preserves_spaces_and_case(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for n in range(2010): (root / ('unrelated_' + str(n))).touch()
            (root / 'last dir').mkdir()
            expected = root / 'last dir' / 'Existing TEST.py'
            expected.touch()
            self.app.current_path = self.app._file_list_path = directory
            call = self.search('existing test')
            result = subprocess.run(call.args[0], shell=True, text=True, capture_output=True, check=True)
            self.respond(call, result.stdout)
            self.assertIn(('file', str(expected)), self.app._recursive_search_rows.values())

    def test_clear_discards_pending_reply_and_restores_normal_actions(self):
        call = self.search('test')
        self.app._clear_file_filter()
        rows = list(self.app.file_list.rows)
        self.respond(call, '/grid/deep/test.py\n')
        self.assertEqual(self.app.file_list.rows, rows)
        self.assertFalse(self.app._recursive_search_active)
        self.assertEqual(self.app._recursive_search_rows, {})

    def test_query_changed_away_and_back_does_not_accept_old_response(self):
        call = self.search('test')
        self.app._file_find_var.set('other')
        self.app._on_file_find_changed()
        self.app._file_find_var.set('test')
        self.app._on_file_find_changed()
        self.respond(call, '/grid/stale/test.py\n')
        self.assertNotIn(('file', '/grid/stale/test.py'), self.app._recursive_search_rows.values())

    def test_no_match_row_cannot_be_edited_or_downloaded(self):
        self.respond(self.search('missing'), '')
        self.app.file_list.selected = (0,)
        self.assertIsNone(self.app._selected_remote_file())

    def test_local_render_clears_recursive_mapping(self):
        self.respond(self.search('test'), '/grid/deep/test.py\n')
        self.app._file_filter_query = ''
        self.app._render_file_entries()
        self.assertFalse(self.app._recursive_search_active)
        self.assertEqual(self.app._recursive_search_rows, {})
        self.assertEqual(self.app.file_list.rows, self.app._file_entries)

    def test_matching_directory_is_still_navigable(self):
        self.respond(self.search('Power'), '')
        self.assertIn(('folder', '/grid/Power'), self.app._recursive_search_rows.values())

    def test_wildcard_and_literal_brackets_find(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'test[1].py').touch()
            self.app.current_path = self.app._file_list_path = directory
            for query in ('test[1]', 't*1*py'):
                call = self.search(query)
                result = subprocess.run(call.args[0], shell=True, text=True, capture_output=True, check=True)
                self.respond(call, result.stdout)
                self.assertIn(('file', str(root / 'test[1].py')), self.app._recursive_search_rows.values())

    def test_empty_cached_folder_still_allows_recursive_search(self):
        self.app._file_entries = []
        self.app._file_find_var.set('test')
        self.app._on_file_find_changed()
        self.app.root.after.assert_called_once()
