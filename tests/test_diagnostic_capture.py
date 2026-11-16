"""Diagnostic recording must remain isolated from transport and UI behavior."""
import csv
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from src.diagnostic_capture import CaptureSession, DiagnosticRecorder, observe_operation
from src.plink_backend import PlinkBackend


class FakeBackend:
    host = "192.0.2.1"
    port = 22
    password = "do-not-record-ssh-password"

    @observe_operation("command")
    def exec(self, remote_cmd, timeout=None):
        return 0, "output", ""

    @observe_operation("upload")
    def scp_put(self, local_path, remote_path):
        return False, "", "failed"


class TestCapture(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.recorder = DiagnosticRecorder()
        self.backend = FakeBackend()
        self.backend.diagnostic_recorder = self.recorder
        self.session = self.recorder.start(self.directory.name, {"host": self.backend.host})
        self.addCleanup(self.finish)

    def finish(self):
        self.session.stop()
        self.assertTrue(self.session.finished.wait(3), "writer did not finish")

    def events(self):
        self.finish()
        return [json.loads(line) for line in (self.session.path / "timeline.jsonl").read_text().splitlines()]

    def test_log_configuration_commands_and_no_transport_password(self):
        self.recorder.log("EnergyManager.log", "one\n")
        self.recorder.log("application.log", "two")
        self.assertEqual(self.backend.exec("read something"), (0, "output", ""))
        self.assertEqual(self.backend.scp_put("local", "/remote"), (False, "", "failed"))
        self.session.configuration({"success": True, "out": "power=10\n", "err": ""})
        events = self.events()
        self.assertEqual((self.session.path / "logs/EnergyManager.log").read_text(), "one\n")
        self.assertEqual((self.session.path / "GridCodes.properties").read_text(), "power=10\n")
        self.assertNotIn(self.backend.password, json.dumps(events))
        self.assertEqual([e["success"] for e in events if e["kind"] == "operation_finished"], [True, False])
        self.assertEqual(self.session.state, "finished")
        with (self.session.path / "timeline.csv").open(encoding="utf-8-sig", newline="") as f:
            self.assertEqual(len(list(csv.reader(f))), len(events) + 1)

    def test_inflight_result_never_moves_to_new_session(self):
        started, release = threading.Event(), threading.Event()
        class Slow(FakeBackend):
            @observe_operation("command")
            def exec(self, remote_cmd):
                started.set()
                release.wait(3)
                return 0, "old result", ""
        backend = Slow()
        backend.diagnostic_recorder = self.recorder
        thread = threading.Thread(target=backend.exec, args=("slow",))
        thread.start()
        self.assertTrue(started.wait(2))
        self.finish()
        old = self.session
        self.session = self.recorder.start(self.directory.name, {})
        release.set()
        thread.join(3)
        self.assertFalse(thread.is_alive())
        events = self.events()
        self.assertNotIn("old result", json.dumps(events))
        self.assertTrue(json.loads((old.path / "manifest.json").read_text())["incomplete_operations"])

    def test_transport_results_survive_observer_failure(self):
        with patch.object(self.session, "event", side_effect=OSError("full disk")):
            self.assertEqual(self.backend.exec("test"), (0, "output", ""))

    def test_transport_exceptions_are_preserved(self):
        class Broken(FakeBackend):
            @observe_operation("command")
            def exec(self, remote_cmd):
                raise ValueError("original failure")
        backend = Broken()
        backend.diagnostic_recorder = self.recorder
        with self.assertRaisesRegex(ValueError, "original failure"):
            backend.exec("broken")
        self.assertFalse(self.events()[-1]["success"])

    def test_bounded_queue_reports_loss(self):
        self.session.MAX_BYTES = 1
        self.recorder.log("a.log", "cannot fit")
        self.finish()
        self.assertEqual(self.session.dropped, 1)
        self.assertEqual(self.session.state, "incomplete")

    def test_failed_and_late_snapshot_dont_write_fake_configuration(self):
        self.session.configuration({"success": False, "out": "", "err": "denied"})
        self.finish()
        self.session.configuration({"success": True, "out": "too late"})
        self.assertFalse((self.session.path / "GridCodes.properties").exists())
        self.assertEqual(self.session.state, "incomplete")

    def test_disk_error_is_reported_without_hanging_stop(self):
        original = Path.open
        def failing(path, *args, **kwargs):
            if path.name == "application.log":
                raise OSError("disk full")
            return original(path, *args, **kwargs)
        with patch.object(Path, "open", failing):
            self.recorder.log("application.log", "message")
            self.finish()
        self.assertIn("disk full", self.session.error)
        self.assertEqual(self.backend.exec("after disk error"), (0, "output", ""))

    def test_truncated_output_is_explicit(self):
        self.session.event("operation_finished", operation_id="x", stdout="x" * (CaptureSession.MAX_FIELD + 1))
        events = self.events()
        self.assertEqual(events[-1]["truncated_fields"], ["stdout"])

    def test_stream_failure_is_visible_in_manifest(self):
        self.session.configuration({"success": True, "out": "a=1"})
        self.session.event("stream_status", source="service.log", running=False)
        self.finish()
        self.assertEqual(self.session.state, "incomplete")
        self.assertIn("service.log", self.session.warnings[0])

    def test_actual_backend_is_observed_without_changing_return(self):
        backend = PlinkBackend("test", "user", "secret", plink_path="/missing/plink")
        backend.diagnostic_recorder = self.recorder
        result = backend.exec("echo test")
        self.assertEqual(result[0], 1)
        self.assertIn("not found", result[2])
        self.assertEqual(self.events()[-1]["status"], 1)

    def test_no_recording_after_stop_or_when_inactive(self):
        self.finish()
        before = (self.session.path / "timeline.jsonl").read_bytes()
        self.backend.exec("after stop")
        self.recorder.log("a.log", "late line")
        self.assertEqual(before, (self.session.path / "timeline.jsonl").read_bytes())
        self.backend.diagnostic_recorder = DiagnosticRecorder()
        self.assertEqual(self.backend.exec("inactive"), (0, "output", ""))


if __name__ == "__main__":
    unittest.main()
