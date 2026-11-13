"""Fast, headless regression checks for RBM V17 safety rules."""

from __future__ import annotations

import pathlib
import queue
import tempfile
import threading
import unittest
import logging
from unittest.mock import Mock, patch

from src.test_sequence import TestSequenceWindow
from src.RemoteBorneManager import RemoteBorneApp
from src.debug_logs import DebugLogsWindow, parse_diagnostic_line
from src.gridcodes_migrator import analyze_migration, export_plan
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
    def test_sequence_duration_format_is_operator_readable(self):
        self.assertEqual(TestSequenceWindow._format_duration(0), "0 s")
        self.assertEqual(TestSequenceWindow._format_duration(70), "1 min 10 s")
        self.assertEqual(TestSequenceWindow._format_duration(3660), "1 h 01 min")

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


class TestGridCodesMigration(unittest.TestCase):
    def test_analysis_and_export_preserve_source_and_template_structure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            source = root / "old.properties"
            template = root / "new_template.properties"
            rules = root / "rules.json"
            source.write_text("# old comment\nCountry = FR\nLegacyLimit = 7000\nObsolete = yes\n", encoding="utf-8")
            template.write_text("# target comment\nCountry = DE\nPowerLimit = 11000\nNewDefault = enabled\n", encoding="utf-8")
            rules.write_text('{"rename_rules": {"LegacyLimit": "PowerLimit"}}', encoding="utf-8")

            plan = analyze_migration(source, template, rules)
            self.assertEqual(len(plan.items), 1)
            item = plan.items[0]
            self.assertIn("Country = FR", item.content)
            self.assertIn("PowerLimit = 7000", item.content)
            self.assertIn("NewDefault = enabled", item.content)
            self.assertIn("Obsolete", item.report.removed)
            self.assertEqual(source.read_text(encoding="utf-8"), "# old comment\nCountry = FR\nLegacyLimit = 7000\nObsolete = yes\n")

            output, report = export_plan(plan, root / "export")
            self.assertTrue((output / "old.properties").is_file())
            self.assertTrue(report.is_file())

    def test_migration_is_available_from_tools_and_is_packaged(self):
        main_source = (ROOT / "src" / "RemoteBorneManager.py").read_text(encoding="utf-8")
        spec = (ROOT / "RBM.spec").read_text(encoding="utf-8")
        build_script = (ROOT / "build_rbm.ps1").read_text(encoding="utf-8")
        self.assertIn('label="GridCodes Migration"', main_source)
        self.assertIn("migration_win.close()", main_source)
        self.assertIn("gridcodes_migrator", spec)
        self.assertIn("gridcodes_migration_ui", build_script)

    def test_only_debug_logs_is_modeless_while_operator_tools_are_modal(self):
        main_source = (ROOT / "src" / "RemoteBorneManager.py").read_text(encoding="utf-8")
        migration_source = (ROOT / "src" / "gridcodes_migration_ui.py").read_text(encoding="utf-8")
        energy_source = (ROOT / "src" / "energy_manager.py").read_text(encoding="utf-8")
        debug_source = (ROOT / "src" / "debug_logs.py").read_text(encoding="utf-8")

        self.assertIn("self.window.grab_set()", migration_source)
        self.assertIn("self.window.grab_release()", migration_source)
        self.assertIn("self.win.grab_set()", energy_source)
        self.assertIn("def close_netlogger_dialog():", main_source)
        self.assertIn("dialog.grab_set()", main_source)
        terminal_source = main_source[main_source.index("    def open_terminal("):]
        self.assertIn("win.grab_set()", terminal_source)
        self.assertIn("win.grab_release()", terminal_source)
        self.assertNotIn("self.window.grab_set()", debug_source)

    def test_migration_refuses_an_output_inside_the_source_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            source_dir = root / "input"
            source_dir.mkdir()
            source = source_dir / "old.properties"
            template = root / "template.properties"
            source.write_text("Country=FR\n", encoding="utf-8")
            template.write_text("Country=DE\n", encoding="utf-8")
            plan = analyze_migration(source_dir, template)
            with self.assertRaisesRegex(Exception, "inside the source"):
                export_plan(plan, source_dir / "output")

    def test_optional_project_profile_renames_vehicle_and_overrides_power_limits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            source = root / "GC_Twingo_Power-Test"
            template = root / "template.properties"
            source.write_text("Country=FR\nPowerMax_1Ph_VAr=6000\nPowerMax_3Ph_VAr=9000\n", encoding="utf-8")
            template.write_text("Country=DE\nPowerMax_1Ph_VAr=7000\nPowerMax_3Ph_VAr=10000\n", encoding="utf-8")

            plan = analyze_migration(
                source,
                template,
                vehicle_name="R5",
                power_max_1ph_var="7200",
                power_max_3ph_var="11000",
            )
            item = plan.items[0]
            self.assertEqual(item.relative_output.name, "GC_R5_Power-Test")
            self.assertIn("PowerMax_1Ph_VAr=7200", item.content)
            self.assertIn("PowerMax_3Ph_VAr=11000", item.content)
            self.assertEqual(len(item.report.profile_overrides), 2)

    def test_project_profile_is_optional_and_rejects_unsafe_vehicle_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            source = root / "GC_Twingo_Test"
            template = root / "template.properties"
            source.write_text("Country=FR\n", encoding="utf-8")
            template.write_text("Country=DE\n", encoding="utf-8")
            plan = analyze_migration(source, template)
            self.assertEqual(plan.items[0].relative_output.name, "GC_Twingo_Test")
            with self.assertRaisesRegex(Exception, "Vehicle name"):
                analyze_migration(source, template, vehicle_name="R5/unsafe")


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
        self.assertIn('APP_VERSION = "17.0.0"', source)
        self.assertIn("V17.0.0", help_source)

    def test_build_artifacts_match_the_v17_runtime(self):
        script = (ROOT / "build_rbm.ps1").read_text(encoding="utf-8")
        spec = (ROOT / "RBM.spec").read_text(encoding="utf-8")
        self.assertNotIn('Copy-Item "src\\logs"', script)
        self.assertNotIn('Copy-Item "src\\exports"', script)
        self.assertIn("'tools\\\\simulator'", spec)
        self.assertIn("collect_all('paramiko')", spec)
        self.assertIn("RBM_V17_", script)
        self.assertIn("'setpoint_validation'", spec)
        self.assertIn("Build output is incomplete", script)

    def test_energy_manager_uses_shared_setpoint_limits(self):
        source = (ROOT / "src" / "energy_manager.py").read_text(encoding="utf-8")
        main_source = (ROOT / "src" / "RemoteBorneManager.py").read_text(encoding="utf-8")
        self.assertIn("validate_active_power", source)
        self.assertIn("validate_reactive_power", source)
        self.assertIn("validate_cosphi", source)
        self.assertIn("pn_limit_provider=self._get_pn_limit", main_source)
        self.assertIn("validate_reactive_power(reactive, optional=True)", main_source)
        self.assertIn("validate_cosphi(cosphi, default=1.0)", main_source)
        self.assertIn("Reactive (Q) = |{active_int}|", main_source)

    def test_main_cosphi_builds_a_validated_command(self):
        class Value:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

        class Entry(Value):
            def delete(self, _start, _end):
                self.value = ""

            def insert(self, _index, value):
                self.value = str(value)

        class Button:
            def __init__(self):
                self.states = []

            def configure(self, **kwargs):
                self.states.append(kwargs.get("state"))

        class Queue:
            def __init__(self):
                self.commands = []

            def execute(self, command, **kwargs):
                self.commands.append((command, kwargs))
                return True

        app = RemoteBorneApp.__new__(RemoteBorneApp)
        messages = []
        queue = Queue()
        button = Button()
        app._sequence_operation_blocked = lambda _action: False
        app._safe_mark_user_command = lambda: None
        app.connected = True
        app.use_cosphi_var = Value(True)
        app.cosphi_active_entry = Entry("-1000")
        app.cosphi_entry = Entry("0.9")
        app.pn_value_var = Value("11000")
        app._set_pn_limit = lambda _value: True
        app._get_pn_limit = lambda: 11000
        app.log = messages.append
        app.ssh_timeout = 30
        app.ssh_queue = queue
        app.btn_send_cosphi = button

        RemoteBorneApp.send_cosphi_command(app)

        self.assertEqual(len(queue.commands), 1)
        self.assertIn('SetpointCosPhi_Pct=90', queue.commands[0][0])
        self.assertIn('--power -1000 -m CentralSetpoint', queue.commands[0][0])
        self.assertIn('Reactive (Q) = |-1000|', "\n".join(messages))
        self.assertEqual(button.states, ["disabled"])

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

    def test_window_uses_the_supplied_icon_on_windows(self):
        app = RemoteBorneApp.__new__(RemoteBorneApp)
        app.root = Mock()
        with patch("src.RemoteBorneManager.sys.platform", "win32"):
            app._set_app_icon()
        icon = str(ROOT / "BorneCommander.ico")
        self.assertEqual(app.root.iconbitmap.call_count, 2)
        app.root.iconbitmap.assert_any_call(default=icon)
        app.root.iconbitmap.assert_any_call(icon)

    def test_packaged_window_finds_the_pyinstaller_icon(self):
        app = RemoteBorneApp.__new__(RemoteBorneApp)
        app.root = Mock()
        with tempfile.TemporaryDirectory() as directory:
            icon = pathlib.Path(directory) / "BorneCommander.ico"
            icon.write_bytes((ROOT / "BorneCommander.ico").read_bytes())
            with patch("src.RemoteBorneManager.sys.platform", "win32"), patch(
                "src.RemoteBorneManager.sys._MEIPASS", directory, create=True
            ):
                app._set_app_icon()
            app.root.iconbitmap.assert_any_call(default=str(icon))
            app.root.iconbitmap.assert_any_call(str(icon))

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

    def test_terminal_uses_an_integrated_console_prompt(self):
        source = (ROOT / "src" / "RemoteBorneManager.py").read_text(encoding="utf-8")
        terminal_source = source[source.index("    def open_terminal("):]
        self.assertIn('command_start_mark = "terminal_command_start"', terminal_source)
        self.assertIn("output.bind(\"<Return>\", on_enter)", terminal_source)
        self.assertIn('if cmd == "cd" or cmd.startswith("cd "):', terminal_source)
        self.assertNotIn("entry = ttk.Entry(frame", terminal_source)

    def test_debug_logs_reuses_the_approved_host_key(self):
        window = DebugLogsWindow.__new__(DebugLogsWindow)
        window.host = "192.168.1.101"
        window.user = "root"
        window.password = "secret"
        window.port = 22
        window.host_key = "ssh-ed25519 255 SHA256:approved-key"

        command = window._build_plink_tail_cmd("/var/log/example.log")

        self.assertEqual(
            command[command.index("-hostkey") + 1],
            "ssh-ed25519 255 SHA256:approved-key",
        )
        main_source = (ROOT / "src" / "RemoteBorneManager.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("host_key=getattr(getattr(self.ssh, \"backend\", None)", main_source)

    def test_debug_log_streams_release_their_tab_after_an_unexpected_exit(self):
        source = (ROOT / "src" / "debug_logs.py").read_text(encoding="utf-8")
        self.assertIn("self.processes.pop(log_name, None)", source)
        self.assertIn("Press Start to retry.", source)
        self.assertIn("self.on_close()", source)

    def test_debug_logs_include_the_ocpp_service_stream(self):
        source = (ROOT / "src" / "debug_logs.py").read_text(encoding="utf-8")
        self.assertIn('"ocpp-service.log": "/var/aux/ocpp-framework/ocpp-service.log"', source)

    def test_debug_diagnosis_extracts_ocpp_connection_and_fault_details(self):
        connected = parse_diagnostic_line(
            "ocpp-service.log", "NetConnection: Connected"
        )
        boot = parse_diagnostic_line(
            "ocpp-service.log", "Boot: BootNotificationResponse received: ACCEPTED"
        )
        fault = parse_diagnostic_line(
            "ocpp-service.log",
            'Raw network message sent: [2, "id", "StatusNotification", { "connectorId" : 0, "errorCode" : "OtherError", "info" : "Undervoltage", "status" : "Faulted", "vendorErrorCode" : "14" }]',
        )
        transaction = parse_diagnostic_line(
            "ocpp-service.log", 'Raw network message sent: [2, "id", "StartTransaction", { "connectorId" : 1 }]'
        )
        self.assertEqual(connected["ocpp_connection"], "Connected")
        self.assertEqual(boot["ocpp_boot"], "Accepted")
        self.assertEqual(fault["ocpp_connector"], "Connector 0: Faulted")
        self.assertEqual(fault["ocpp_fault"], "OtherError | Undervoltage | code 14")
        self.assertEqual(transaction["ocpp_transaction"], "Start transaction")

    def test_debug_diagnosis_extracts_ocpp_v2x_and_meter_values(self):
        setpoint = parse_diagnostic_line(
            "ocpp-service.log",
            "Smart: Calculated SetPoint at now v2x mode: CentralSetpoint; phases: 3; "
            "activeSetPoint: Current: 0(mA); Power: -2070(W); ; "
            "reactiveSetPoint: Current: 0(mA); Power: 250(W); ;",
        )
        meter = parse_diagnostic_line(
            "ocpp-service.log",
            'MeterValues { "sampledValue" : [ '
            '{ "measurand" : "Voltage", "phase" : "L1-N", "unit" : "V", "value" : "230.10" }, '
            '{ "measurand" : "Voltage", "phase" : "L2-N", "unit" : "V", "value" : "231.20" }, '
            '{ "measurand" : "Current.Offered", "unit" : "A", "value" : "15.465" }, '
            '{ "measurand" : "Power.Offered", "unit" : "W", "value" : "10671" }, '
            '{ "measurand" : "SoC", "unit" : "Percent", "value" : "91" } ] }',
        )
        self.assertEqual(setpoint["ocpp_v2x_mode"], "CentralSetpoint")
        self.assertEqual(setpoint["ocpp_active_setpoint"], "-2070 W")
        self.assertEqual(setpoint["ocpp_reactive_setpoint"], "250 var")
        self.assertEqual(meter["ocpp_meter_voltage"], "L1-N: 230.10 V | L2-N: 231.20 V")
        self.assertEqual(meter["ocpp_meter_current"], "15.465 A")
        self.assertEqual(meter["ocpp_meter_offered_power"], "10671 W")
        self.assertEqual(meter["ocpp_meter_soc"], "91 %")

    def test_debug_diagnosis_extracts_raw_service_metrics(self):
        energy = parse_diagnostic_line(
            "EnergyManager.log",
            "GridCodes request { P: {power_W: -2070} }, { Q: {power_W: 250} }",
        )
        charger = parse_diagnostic_line(
            "ChargerApp.log",
            "PresentSOC = 62; evActivePowerPresent_W = -2000; ChargePowerLimit = 11000",
        )
        meter = parse_diagnostic_line(
            "iotc-meter-dispatcher.log",
            '{"activePower": -2010, "reactivePower": 240, "powerFactor": 0.98, "frequency": 50}',
        )
        self.assertEqual(energy["setpoint_p"], "-2070 W")
        self.assertEqual(charger["soc"], "62 %")
        self.assertEqual(charger["charger_p"], "-2000 W")
        self.assertEqual(meter["meter_q"], "240 var")
        self.assertEqual(meter["frequency"], "50 Hz")

    def test_sequence_has_an_explicit_confirmed_zero_power_stop(self):
        source = (ROOT / "src" / "test_sequence.py").read_text(encoding="utf-8")
        self.assertIn("Confirm Test Sequence", source)
        self.assertIn("def stop_and_send_zero", source)
        self.assertIn("Sequence emergency P=0", source)

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
        self.assertIn('$simulatorTarget = Join-Path $distApp "tools\\simulator"', source)
        self.assertIn('Copy-Item (Join-Path $simulatorSource "rbm_local_evse_simulator.py") $simulatorTarget -Force', source)
        self.assertIn('"tools\\simulator\\rbm_local_evse_simulator.py"', source)
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
