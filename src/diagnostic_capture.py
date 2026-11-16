"""Optional local diagnostic recording. No Tk or SSH dependencies."""
import csv
import functools
import inspect
import json
import queue
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path


def timestamp():
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


class CaptureSession:
    """Bounded asynchronous writer; stopping drains accepted events before exit."""
    MAX_BYTES = 8 * 1024 * 1024
    MAX_EVENTS = 10000
    MAX_FIELD = 65536

    def __init__(self, directory, metadata):
        self.path = Path(directory) / ("test_" + datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8])
        self.path.mkdir(parents=True)
        (self.path / "logs").mkdir()
        self.metadata = dict(metadata)
        self.started = timestamp()
        self.clock = time.monotonic()
        self.active = True
        self.finished = threading.Event()
        self.lock = threading.Lock()
        self.queue = queue.Queue()
        self.queued_bytes = 0
        self.dropped = 0
        self.sequence = 0
        self.error = None
        self.reason = None
        self.pending = set()
        self.snapshot = "not received before stop"
        self.warnings = []
        self.received_sources = set()
        self.state = "recording"
        # Verify output permissions before starting any remote log streams.
        self._manifest("recording")
        (self.path / "README.txt").write_text(
            "RBM test capture\n\n"
            "timeline.csv: commands, results, streams and application messages in local arrival order.\n"
            "timeline.jsonl: same events in machine-readable form.\n"
            "logs/: received service logs, independent of UI filters and pause.\n"
            "GridCodes.properties: read-only snapshot requested at capture start, when available.\n"
            "manifest.json: capture state, missing configuration, dropped events and write errors.\n\n"
            "Only data received during recording is included. Newly started tails can send recent history.\n"
            "Closing Debug Logs, disconnecting or exiting RBM ends the capture.\n"
            "Commands started before recording are not traced. In-flight commands at Stop are incomplete.\n"
            "Fields exceeding 65536 characters are explicitly marked truncated_fields in the timeline.\n"
            "SSH password arguments and config.ini are not collected. Commands, service logs and GridCodes\n"
            "may contain device-specific data; the folder remains local.\n", encoding="utf-8")
        self.thread = threading.Thread(target=self._write, name="RBM diagnostic writer", daemon=False)
        self.thread.start()
        self.event("capture_started", metadata=self.metadata)

    def _manifest(self, state):
        data = dict(self.metadata, state=state, started=self.started, ended=timestamp() if state != "recording" else None,
                    reason=self.reason, dropped_events=self.dropped, write_error=self.error,
                    incomplete_operations=sorted(self.pending), configuration=self.snapshot, warnings=self.warnings,
                    received_logs=sorted(self.received_sources))
        temporary = self.path / "manifest.tmp"
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path / "manifest.json")

    def event(self, kind, **fields):
        clipped = []
        for key, value in list(fields.items()):
            if isinstance(value, str) and len(value) > self.MAX_FIELD:
                fields[key] = value[:self.MAX_FIELD]
                clipped.append(key)
        if clipped:
            fields["truncated_fields"] = clipped
        with self.lock:
            if not self.active:
                return False
            self.sequence += 1
            event = dict(sequence=self.sequence, time=timestamp(), elapsed=round(time.monotonic() - self.clock, 6), kind=kind, **fields)
            payload = json.dumps(event, ensure_ascii=False)
            size = len(payload.encode("utf-8"))
            if self.queued_bytes + size > self.MAX_BYTES or self.queue.qsize() >= self.MAX_EVENTS:
                self.dropped += 1
                return False
            self.queued_bytes += size
            self.queue.put_nowait((event, payload, size))
            return True

    def log(self, name, line):
        self.event("log", source=name, text=line)

    def configuration(self, result):
        # The queue callback may arrive after Stop or after another capture starts.
        self.event("configuration", success=bool(result.get("success")),
                   text=result.get("out", ""), error=result.get("err", ""))

    def stop(self, reason="operator finished"):
        with self.lock:
            if not self.active:
                return
            self.active = False
            self.reason = reason
            self.queue.put_nowait(None)

    def _write(self):
        handles = {}
        try:
            with (self.path / "timeline.jsonl").open("w", encoding="utf-8") as timeline, \
                 (self.path / "timeline.csv").open("w", encoding="utf-8-sig", newline="") as table:
                writer = csv.writer(table)
                writer.writerow(["sequence", "time", "elapsed_seconds", "kind", "details"])
                while True:
                    item = self.queue.get()
                    if item is None:
                        break
                    event, payload, size = item
                    with self.lock:
                        self.queued_bytes -= size
                    timeline.write(payload + "\n")
                    writer.writerow([event["sequence"], event["time"], event["elapsed"], event["kind"], payload])
                    if event.get("truncated_fields"):
                        self.warnings.append("Truncated event " + str(event["sequence"]) + ": " + ", ".join(event["truncated_fields"]))
                    if event["kind"] == "log":
                        name = Path(event["source"]).name
                        self.received_sources.add(name)
                        if name not in handles:
                            handles[name] = (self.path / "logs" / name).open("a", encoding="utf-8")
                        handles[name].write(event["text"].rstrip("\r\n") + "\n")
                    elif event["kind"] == "operation_started":
                        self.pending.add(event["operation_id"])
                    elif event["kind"] == "operation_finished":
                        self.pending.discard(event["operation_id"])
                    elif event["kind"] == "stream_status" and not event["running"]:
                        self.warnings.append("Stream unavailable: " + event["source"])
                    elif event["kind"] == "stream_ended" and event.get("unexpected"):
                        self.warnings.append("Stream ended: " + event["source"])
                    elif event["kind"] == "capture_error":
                        self.warnings.append(event["error"])
                    elif event["kind"] == "configuration":
                        if event["success"] and not event.get("truncated_fields"):
                            (self.path / "GridCodes.properties").write_text(event["text"], encoding="utf-8")
                            self.snapshot = "saved"
                        else:
                            self.snapshot = "failed or output too large; see timeline"
                    timeline.flush()
                    table.flush()
        except Exception as exc:
            self.error = str(exc)
            with self.lock:
                self.active = False
        finally:
            for handle in handles.values():
                try:
                    handle.close()
                except Exception as exc:
                    self.error = str(exc)
            try:
                for name in self.metadata.get("expected_logs", {}):
                    if name not in self.received_sources:
                        self.warnings.append("No data received: " + name)
                self.state = "incomplete" if self.error or self.dropped or self.pending or self.warnings or self.snapshot != "saved" else "finished"
                self._manifest(self.state)
            except Exception as exc:
                self.error = str(exc)
            self.finished.set()


class DiagnosticRecorder:
    def __init__(self):
        self.session = None

    def start(self, directory, metadata):
        if self.session and not self.session.finished.is_set():
            raise RuntimeError("The previous capture is still recording or saving.")
        self.session = CaptureSession(directory, metadata)
        return self.session

    def event(self, kind, **fields):
        try:
            if self.session:
                self.session.event(kind, **fields)
        except Exception:
            pass  # Diagnostics must never change application behavior.

    def log(self, name, line):
        self.event("log", source=name, text=line)


def observe_operation(kind):
    """Capture logical requests, never PuTTY argv (which contains credentials)."""
    def decorate(method):
        signature = inspect.signature(method)
        @functools.wraps(method)
        def wrapped(self, *args, **kwargs):
            session = None
            operation_id = None
            try:
                recorder = getattr(self, "diagnostic_recorder", None)
                session = recorder.session if recorder else None
                if session and session.active:
                    operation_id = uuid.uuid4().hex
                    bound = signature.bind(self, *args, **kwargs).arguments
                    request = {key: str(bound[key]) for key in ("remote_cmd", "remote_path", "local_path") if key in bound}
                    session.event("operation_started", operation_id=operation_id, operation=kind,
                                  host=self.host, port=self.port, **request)
                else:
                    session = None
            except Exception:
                session = None
            try:
                result = method(self, *args, **kwargs)
            except BaseException as exc:
                if session:
                    try:
                        session.event("operation_finished", operation_id=operation_id, error=str(exc), success=False)
                    except Exception:
                        pass
                raise
            if session:
                try:
                    status, stdout, stderr = result
                    success = bool(status) if kind in ("download", "upload") else status == 0
                    session.event("operation_finished", operation_id=operation_id, status=status,
                                  success=success, stdout=stdout, stderr=stderr)
                except Exception:
                    pass
            return result
        return wrapped
    return decorate
