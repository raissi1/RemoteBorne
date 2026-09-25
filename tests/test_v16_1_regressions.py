"""Fast, headless regression checks for RBM V16.1 safety rules."""

from __future__ import annotations

import pathlib
import queue
import tempfile
import threading
import unittest
import logging

from src.test_sequence import TestSequenceWindow
from src.RemoteBorneManager import RemoteBorneApp
from src.plink_backend import PlinkBackend
from src.setpoint_validation import (
    validate_active_power,
    validate_cosphi,
    validate_reactive_power,
)
from src.ssh_queue import SSHQueue


ROOT = pathlib.Path(__file__).resolve().parents[1]


class _Value:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


def _sequence_form(mode="P/Q", active="1000", reactive="", cosphi="1", hold="10"):
    """Build only the data required by _form_step; no Tk window is created."""
    sequence = TestSequenceWindow.__new__(TestSequenceWindow)
    sequence.mode_var = _Value(mode)
    sequence.active_var = _Value(active)
    sequence.reactive_var = _Value(reactive)
    sequence.cosphi_var = _Value(cosphi)
    sequence.hold_var = _Value(hold)
    sequence.pn_limit_provider = lambda: 11000
    return sequence


class TestSequenceValidation(unittest.TestCase):
    def test_pq_without_reactive_power_is_supported(self):
        step = _sequence_form()._form_step()
        self.assertEqual(step["active"], 1000)
        self.assertIsNone(step["reactive"])

    def test_active_power_cannot_exceed_pn(self):
        with self.assertRaisesRegex(ValueError, "Pn"):
            _sequence_form(active="11001")._form_step()

    def test_reactive_power_is_limited(self):
        with self.assertRaisesRegex(ValueError, "Reactive Q"):
            _sequence_form(reactive="11001")._form_step()

    def test_cosphi_zero_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "0 is not allowed"):
            _sequence_form(mode="CosPhi", cosphi="0")._form_step()

    def test_cosphi_in_range_is_accepted(self):
        step = _sequence_form(mode="CosPhi", active="-500", cosphi="-0.99")._form_step()
        self.assertEqual(step["cosphi"], -0.99)

    def test_non_numeric_text_is_rejected_during_typing(self):
        self.assertTrue(TestSequenceWindow._is_partial_number("-"))
        self.assertTrue(TestSequenceWindow._is_partial_number("-0.5"))
        self.assertFalse(TestSequenceWindow._is_partial_number("abc"))
        self.assertFalse(TestSequenceWindow._is_partial_number("nan"))

    def test_shared_validation_rejects_non_finite_and_invalid_cosphi(self):
        with self.assertRaisesRegex(ValueError, "finite"):
            validate_active_power("nan", 11000)
        with self.assertRaisesRegex(ValueError, "0 is not allowed"):
            validate_cosphi("0")
        self.assertEqual(validate_cosphi("-0.99"), -0.99)
        self.assertEqual(validate_reactive_power("", optional=True), None)

    def test_csv_import_is_validated_before_any_step_is_returned(self):
        sequence = _sequence_form()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", encoding="utf-8", delete=False) as handle:
            handle.write(
                "step,mode,active_w,reactive_var,cosphi,hold_seconds,status\n"
                "1,P/Q,1000,250,,10,Ready\n"
                "2,CosPhi,-500,,-0.99,5,Ready\n"
            )
            path = handle.name
        try:
            steps = sequence._read_csv_sequence(path)
        finally:
            pathlib.Path(path).unlink(missing_ok=True)
        self.assertEqual(len(steps), 2)
        self.assertEqual(steps[0]["reactive"], 250)
        self.assertEqual(steps[1]["cosphi"], -0.99)


class TestSafetyRegressionGuards(unittest.TestCase):
    def test_stop_can_remove_only_its_pending_sequence_commands(self):
        ssh_queue = SSHQueue.__new__(SSHQueue)
        ssh_queue.q = queue.Queue()
        ssh_queue._pending_keys = {"sequence-step", "operator-command"}
        ssh_queue._pending_keys_lock = threading.Lock()
        ssh_queue.q.put(
            {
                "cmd": "sequence command",
                "cancel_token": "test-sequence:1",
                "dedupe_key": "sequence-step",
            }
        )
        ssh_queue.q.put(
            {
                "cmd": "operator command",
                "cancel_token": None,
                "dedupe_key": "operator-command",
            }
        )

        self.assertEqual(ssh_queue.cancel_pending("test-sequence:1"), 1)
        self.assertEqual(ssh_queue.q.qsize(), 1)
        self.assertEqual(ssh_queue.q.get_nowait()["cmd"], "operator command")
        self.assertNotIn("sequence-step", ssh_queue._pending_keys)
        self.assertIn("operator-command", ssh_queue._pending_keys)

    def test_sequence_commands_use_a_cancellation_token(self):
        source = (ROOT / "src" / "test_sequence.py").read_text(encoding="utf-8")
        self.assertIn("cancel_token=self._active_queue_token", source)
        self.assertIn("cancel_pending(self._active_queue_token)", source)

    def test_relative_export_paths_are_portable(self):
        from src.RemoteBorneManager import _local_export_dir

        expected = (ROOT / "exports").resolve()
        self.assertEqual(pathlib.Path(_local_export_dir("exports")), expected)

    def test_runtime_templates_and_version_are_aligned(self):
        root_template = (ROOT / "config" / "config.example.ini").read_text(
            encoding="utf-8"
        )
        runtime_template = (ROOT / "src" / "config" / "config.example.ini").read_text(
            encoding="utf-8"
        )
        self.assertEqual(root_template, runtime_template)
        self.assertEqual(RemoteBorneApp.__module__, "src.RemoteBorneManager")
        source = (ROOT / "src" / "RemoteBorneManager.py").read_text(encoding="utf-8")
        help_source = (ROOT / "src" / "open_help.py").read_text(encoding="utf-8")
        self.assertIn('APP_VERSION = "16.1.0"', source)
        self.assertIn("V16.1.0", help_source)

    def test_build_artifacts_match_the_v16_runtime(self):
        script = (ROOT / "build_rbm.ps1").read_text(encoding="utf-8")
        spec = (ROOT / "RBM.spec").read_text(encoding="utf-8")
        self.assertNotIn('Copy-Item "src\\logs"', script)
        self.assertNotIn('Copy-Item "src\\exports"', script)
        self.assertIn("tools/simulator", spec)
        self.assertIn('"paramiko"', spec)
        self.assertIn("RBM_V16_", spec)
        self.assertIn('"setpoint_validation"', spec)
        self.assertIn("Build output is incomplete", script)

    def test_energy_manager_uses_shared_setpoint_limits(self):
        source = (ROOT / "src" / "energy_manager.py").read_text(encoding="utf-8")
        main_source = (ROOT / "src" / "RemoteBorneManager.py").read_text(encoding="utf-8")
        self.assertIn("validate_active_power", source)
        self.assertIn("validate_reactive_power", source)
        self.assertIn("validate_cosphi", source)
        self.assertIn("pn_limit_provider=self._get_pn_limit", main_source)

    def test_plink_reports_missing_tools_before_starting_a_process(self):
        backend = PlinkBackend(
            "127.0.0.1",
            "root",
            "secret",
            plink_path="does-not-exist/plink.exe",
            pscp_path="does-not-exist/pscp.exe",
        )
        returncode, _out, error = backend.exec("echo alive")
        self.assertEqual(returncode, 1)
        self.assertIn("plink.exe", error)
        success, _out, error = backend.scp_get("/remote", "local")
        self.assertFalse(success)
        self.assertIn("pscp.exe", error)

    def test_window_keeps_the_ttkbootstrap_default_icon(self):
        source = (ROOT / "src" / "RemoteBorneManager.py").read_text(encoding="utf-8")
        self.assertNotIn("def _set_app_icon", source)
        self.assertNotIn("self.root.iconbitmap", source)

    def _alive_probe_host(self, ssh, ssh_queue):
        app = RemoteBorneApp.__new__(RemoteBorneApp)
        app.ssh = ssh
        app.ssh_queue = ssh_queue
        app._manual_disconnect_mode = False
        app.log = lambda _message: None
        return app

    def test_idle_heartbeat_marks_a_dead_charger_disconnected(self):
        class DeadSsh:
            connected = True
            _reconnect_in_progress = False

            def __init__(self):
                self.losses = []

            def execute_sync(self, *_args, **_kwargs):
                return {"success": False, "out": "", "err": "Connection timed out"}

            def report_connection_lost(self, reason, force_event=False):
                self.losses.append((reason, force_event))

        class IdleQueue:
            busy = False
            pause_monitoring = False

            def __init__(self):
                self.q = queue.Queue()
                self.lock = threading.Lock()

        ssh = DeadSsh()
        app = self._alive_probe_host(ssh, IdleQueue())

        self.assertFalse(app._run_alive_probe(4))
        self.assertEqual(ssh.losses, [("Connection timed out", True)])

    def test_heartbeat_never_delays_an_queued_operator_command(self):
        class LiveSsh:
            connected = True
            _reconnect_in_progress = False

            def __init__(self):
                self.calls = 0

            def execute_sync(self, *_args, **_kwargs):
                self.calls += 1
                return {"success": True, "out": "alive", "err": ""}

        class PendingQueue:
            busy = False
            pause_monitoring = False

            def __init__(self):
                self.q = queue.Queue()
                self.q.put("operator command")
                self.lock = threading.Lock()

        ssh = LiveSsh()
        app = self._alive_probe_host(ssh, PendingQueue())

        self.assertIsNone(app._run_alive_probe(4))
        self.assertEqual(ssh.calls, 0)

    def test_terminal_preserves_operator_file_command(self):
        source = (ROOT / "src" / "RemoteBorneManager.py").read_text(encoding="utf-8")
        self.assertIn("Confirm file operation", source)
        self.assertNotIn('cmd = "rm -f "', source)
        self.assertNotIn('cmd = "mv -f "', source)
        self.assertNotIn('cmd = "cp -f "', source)

    def test_simulator_launcher_has_no_user_specific_python_path(self):
        source = (ROOT / "tools" / "simulator" / "start_rbm_simulator.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("RBM_PYTHON", source)
        self.assertIn("Get-Command python", source)
        self.assertNotIn("Python39", source)

    def test_build_bundles_the_integrated_simulator(self):
        source = (ROOT / "build_rbm.ps1").read_text(encoding="utf-8")
        self.assertIn('--add-data "tools\\simulator;tools\\simulator"', source)
        self.assertIn("--collect-all paramiko", source)

    def test_simulator_has_demo_netlogger_content(self):
        source = (ROOT / "tools" / "simulator" / "rbm_local_evse_simulator.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("/var/aux/netlogger/netlog.demo.pcap.gz", source)

    def test_simulator_accepts_a_real_local_ssh_connection(self):
        class LoaderHost:
            _simulator_module = None

            @staticmethod
            def _simulator_directory():
                return str(ROOT / "tools" / "simulator")

        holder = LoaderHost()
        module = RemoteBorneApp._load_simulator_module(holder)

        logger = logging.getLogger("paramiko.transport")
        previous_level = logger.level
        logger.setLevel(logging.CRITICAL)
        try:
            with tempfile.TemporaryDirectory() as directory:
                evse = module.SimulatedEvse(pathlib.Path(directory) / "evse", "rbm-simulator")
                server = module.LocalSshServer(
                    "127.0.0.1", 0, evse, pathlib.Path(directory) / "host_key.pem"
                )
                server.start()
                try:
                    client = module.paramiko.SSHClient()
                    client.set_missing_host_key_policy(module.paramiko.AutoAddPolicy())
                    port = server.listener.getsockname()[1]
                    client.connect(
                        "127.0.0.1",
                        port=port,
                        username="root",
                        password="rbm-simulator",
                        timeout=5,
                    )
                    _stdin, stdout, _stderr = client.exec_command("echo connected")
                    self.assertIn("command accepted", stdout.read().decode("utf-8"))
                    client.close()
                finally:
                    server.stop()
        finally:
            logger.setLevel(previous_level)


if __name__ == "__main__":
    unittest.main()
