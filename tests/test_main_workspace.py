"""Presentation A compatibility checks; native UI cases are explicitly opt-in."""

import configparser
import os
import pathlib
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch
from types import SimpleNamespace

from src.ui_widgets import FileTable, file_kind
from src.RemoteBorneManager import RemoteBorneApp

ROOT = pathlib.Path(__file__).resolve().parents[1]


class TestFileKinds(unittest.TestCase):
    def test_file_types_do_not_require_remote_metadata(self):
        cases = {
            "GC/": "Folder",
            "[.] (Parent)": "Folder",
            "[DIR] test/": "Folder",
            "test file.py": "Script",
            "power.sh": "Script",
            "GridCodes.properties": "Config",
            "GC_Test": "GridCode",
            "a.pcap.gz": "File",
            "[No match]": "",
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(file_kind(name), expected)


@unittest.skipUnless(
    os.environ.get("RBM_UI_TESTS") == "1",
    "Set RBM_UI_TESTS=1 with a display for native UI checks",
)
class TestMainWorkspace(unittest.TestCase):
    ACTIONS = {
        "btn_connect": "force_reconnect",
        "btn_disconnect": "_manual_disconnect",
        "btn_exit": "on_exit",
        "btn_go": "_go_to_path",
        "btn_up": "_go_parent",
        "btn_root": "_go_root",
        "btn_refresh": "refresh_file_list",
        "btn_find": "_apply_file_filter_from_entry",
        "btn_clear_find": "_clear_file_filter",
        "btn_download": "_menu_download",
        "btn_edit": "_menu_edit",
        "btn_upload": "upload_files_to_current_path",
        "btn_print": "_menu_print",
        "btn_copy_panel": "copy_selected_to_gridcodes",
        "btn_edit_current_properties": "edit_current_gridcodes_properties",
        "btn_netlogger": "open_netlogger_download",
        "btn_read_pn": "read_pn_from_gridcodes_properties",
        "btn_read_last_active_power": "read_last_active_power_from_energy_log",
        "btn_monitor": "update_monitor",
        "btn_send_power": "send_power_command",
        "btn_send_cosphi": "send_cosphi_command",
        "btn_restart_services": "restart_initd_services",
        "btn_reboot": "reboot_device",
    }

    @classmethod
    def setUpClass(cls):
        cls.stack = ExitStack()
        cls.stack.enter_context(patch("src.RemoteBorneManager.SSHManager.start"))
        cls.handlers = {
            name: cls.stack.enter_context(
                patch.object(RemoteBorneApp, name, autospec=True)
            )
            for name in set(cls.ACTIONS.values())
            | {"open_terminal", "open_file_editor", "_search_files_in_subfolders"}
        }
        config = configparser.ConfigParser(interpolation=None)
        config.read(ROOT / "config/config.example.ini")
        cls.app = RemoteBorneApp(config)
        cls.app.ssh_queue.stop()
        cls.app.ssh_queue = Mock()
        cls.app.root.update()

    @classmethod
    def tearDownClass(cls):
        cls.app.root.destroy()
        cls.stack.close()

    def setUp(self):
        self.app.connected = self.app.ssh.connected = True
        self.app._sequence_modal_open = False
        self.app._recursive_search_active = False
        self.app._navigation_locked = False
        self.app.current_path = self.app.default_path
        self.app._file_list_path = self.app.current_path
        self.app.use_cosphi_var.set(False)
        self.app._update_controls_state()
        for handler in self.handlers.values():
            handler.reset_mock()
        self.app.file_list.delete(0, "end")

    def test_all_23_main_actions_still_call_the_original_handlers(self):
        for attribute, name in self.ACTIONS.items():
            with self.subTest(action=attribute):
                self.handlers[name].reset_mock()
                action = getattr(self.app, attribute)
                action.configure(state="normal")
                action.invoke()
                self.handlers[name].assert_called_once_with(self.app)
        self.app._update_controls_state()

    def test_splitters_keep_operator_adjustments(self):
        self.app.root.update()
        workspace = self.app.workspace_panes
        before_x, before_y = workspace.sash_coord(0)
        workspace.sash_place(0, before_x + 30, before_y)
        self.app.root.update()
        self.assertEqual(workspace.sash_coord(0)[0], before_x + 30)
        workspace.sash_place(0, before_x, before_y)
        logs = self.app.main_panes
        log_x, log_y = logs.sash_coord(0)
        logs.sash_place(0, log_x, log_y - 15)
        self.app.root.update()
        self.assertEqual(logs.sash_coord(0)[1], log_y - 15)
        logs.sash_place(0, log_x, log_y)

    def test_light_and_dark_themes_keep_the_workspace_usable(self):
        with patch.object(self.app, "_popup_error") as error:
            for theme in ("darkly", "flatly"):
                self.app._apply_theme(theme)
                self.app.root.update()
                self.app.file_list.insert("end", "GridCodes.properties")
                self.assertEqual(self.app.file_list.get("end"), "GridCodes.properties")
                self.app.file_list.delete(0, "end")
            error.assert_not_called()

    def test_table_preserves_raw_names_indices_and_selection(self):
        table = self.app.file_list
        self.assertIsInstance(table, FileTable)
        rows = ("GC with spaces/", "GC_FR_Test", "GridCodes.properties", "test file.py")
        for row in rows:
            table.insert("end", row)
        self.assertEqual(table.get(0, "end"), rows)
        table.selection_set(2)
        self.assertEqual(table.curselection(), (2,))
        self.assertEqual(
            self.app._selected_remote_file(),
            self.app.current_path + "/GridCodes.properties",
        )
        table.delete(1)
        self.assertEqual(table.get(0, "end"), (rows[0], rows[2], rows[3]))
        table.selection_clear(0, "end")
        self.assertEqual(table.curselection(), ())

    def test_folder_double_click_keeps_navigation_and_script_prefill(self):
        table = self.app.file_list
        table.insert("end", "folder with spaces/")
        table.insert("end", "test file.py")
        table.selection_set(0)
        self.app._navigation_in_progress = False
        original = self.app.current_path
        self.app.on_file_double_click(None)
        self.assertEqual(self.app.current_path, original + "/folder with spaces")
        self.handlers["refresh_file_list"].assert_called_once_with(
            self.app, navigation=True
        )
        self.app.current_path = original
        self.app._file_list_path = original
        self.app._finish_navigation()
        table.selection_set(1)
        self.app.on_file_double_click(None)
        self.handlers["open_terminal"].assert_called_once_with(
            self.app, initial_command=f"python3 '{original}/test file.py'"
        )

    def test_recursive_results_keep_the_original_full_paths(self):
        self.app._recursive_search_active = True
        path = self.app.current_path + "/sub folder/test file.py"
        self.app._render_recursive_search_results([path], self.app.current_path)
        self.app.file_list.selection_set(1)
        self.assertEqual(self.app._selected_recursive_search_target(), ("file", path))
        self.assertEqual(self.app._selected_remote_file(), path)
        self.app.on_file_double_click(None)
        self.handlers["open_terminal"].assert_called_once_with(
            self.app, initial_command=f"python3 '{path}'"
        )

    def test_column_heading_double_click_does_not_open_the_selected_file(self):
        table = self.app.file_list
        table.insert("end", "GridCodes.properties")
        table.selection_set(0)
        self.app.root.update()
        table._open_row(SimpleNamespace(keysym="", y=0))
        self.handlers["open_file_editor"].assert_not_called()
        self.handlers["open_terminal"].assert_not_called()

    def test_disabled_browser_does_not_change_selection_on_click(self):
        table = self.app.file_list
        table.insert("end", "a.properties")
        table.insert("end", "b.properties")
        table.selection_set(0)
        self.app.root.update()
        bounds = table.bbox(table.get_children()[1])
        self.assertTrue(bounds)
        x, y, _width, height = bounds
        self.assertEqual(table.nearest(y + height // 2), 1)
        self.assertIsNone(table.nearest(0))  # Column heading is not a file.
        table.configure(state="disabled")
        table.event_generate("<Button-1>", x=x + 10, y=y + height // 2, time=1000)
        self.app.root.update()
        self.assertEqual(table.curselection(), (0,))
        table.configure(state="normal")
        table.event_generate("<Button-1>", x=x + 10, y=y + height // 2, time=2000)
        self.app.root.update()
        self.assertEqual(table.curselection(), (1,))

    def test_disconnected_and_sequence_states_keep_actions_locked(self):
        for connected, sequence in ((False, False), (True, True)):
            self.app.connected = connected
            self.app._sequence_modal_open = sequence
            self.app._update_controls_state()
            for attribute in (
                "btn_download",
                "btn_edit",
                "btn_upload",
                "btn_print",
                "btn_copy_panel",
                "btn_edit_current_properties",
                "btn_netlogger",
                "btn_more_file_actions",
            ):
                with self.subTest(
                    connected=connected, sequence=sequence, action=attribute
                ):
                    self.assertEqual(
                        str(getattr(self.app, attribute).cget("state")), "disabled"
                    )
            self.assertTrue(self.app.file_list.instate(("disabled",)))

    def test_cosphi_mode_and_simulation_banner_still_work(self):
        self.app.use_cosphi_var.set(True)
        self.app._on_cosphi_toggle()
        self.assertEqual(str(self.app.btn_send_power.cget("state")), "disabled")
        self.assertEqual(str(self.app.btn_send_cosphi.cget("state")), "normal")
        self.assertEqual(self.app.cosphi_entry.get(), "1")
        self.app._set_simulation_mode(True)
        self.app.root.update()
        self.assertTrue(self.app.simulation_banner.winfo_ismapped())
        self.app._set_simulation_mode(False)
        self.app.root.update()
        self.assertFalse(self.app.simulation_banner.winfo_ismapped())
        self.app.btn_print.configure(text="Printing…")
        self.assertEqual(self.app.btn_print.cget("text"), "Printing…")
        self.app.btn_print.configure(text="Print")
