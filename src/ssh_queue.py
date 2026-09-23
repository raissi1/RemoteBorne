import queue
import threading


class SSHQueue:
    def __init__(self, ssh, root, log=None):
        self.ssh = ssh
        self.root = root
        self.log = log or (lambda x: None)

        self.q = queue.Queue()
        self.running = True
        self.lock = threading.Lock()
        self._pending_keys_lock = threading.Lock()
        self._pending_keys = set()
        self._active_cancel_lock = threading.Lock()
        self._active_cancel_event = None
        self._active_cancel_token = None
        self.busy = False
        self.pause_monitoring = False
        self.current_command = None

        self.worker = threading.Thread(target=self._worker, daemon=True)
        self.worker.start()

    def execute(self, cmd, callback=None, **kwargs):
        dedupe_key = kwargs.get("dedupe_key")
        item = {
            "cmd": cmd,
            "callback": callback,
            "timeout": kwargs.get("timeout"),
            "critical": kwargs.get("critical", False),
            "silent": kwargs.get("silent", False),
            "label": kwargs.get("label"),
            "command_type": kwargs.get("command_type"),
            "auto_retry": kwargs.get("auto_retry", False),
            "log_errors": kwargs.get("log_errors", False),
            "stream_callback": kwargs.get("stream_callback"),
            "cancel_token": kwargs.get("cancel_token"),
            "dedupe_key": dedupe_key,
        }
        if dedupe_key:
            with self._pending_keys_lock:
                if dedupe_key in self._pending_keys:
                    if not item["silent"]:
                        self.log(
                            f"[SSH QUEUE] IGNORE -> {self._display_label(item)} "
                            "already queued or running."
                        )
                    return False
                self._pending_keys.add(dedupe_key)

        try:
            self.q.put(item)
        except Exception:
            self._release_dedupe_key(dedupe_key)
            raise
        return True

    def _release_dedupe_key(self, dedupe_key):
        if not dedupe_key:
            return
        with self._pending_keys_lock:
            self._pending_keys.discard(dedupe_key)

    def _display_label(self, item):
        label = (item.get("label") or "").strip()
        if label:
            return label
        command_type = (item.get("command_type") or "").strip()
        if command_type:
            return command_type.replace("_", " ").title()
        cmd = (item.get("cmd") or "").strip()
        return cmd if len(cmd) <= 80 else f"{cmd[:77]}..."

    def stop(self):
        self.running = False
        self.q.put(None)

    def cancel_active_stream(self, cancel_token=None):
        """Request cancellation of the currently streamed command only."""
        with self._active_cancel_lock:
            if self._active_cancel_event is None:
                return False
            if cancel_token is not None and cancel_token != self._active_cancel_token:
                return False
            self._active_cancel_event.set()
            return True

    def _worker(self):
        while self.running:
            item = self.q.get()
            if item is None:
                self.q.task_done()
                break

            critical = False
            callback = None
            result = None
            dedupe_key = item.get("dedupe_key")
            callback_scheduled = False
            try:
                with self.lock:
                    self.busy = True
                    cmd = item["cmd"]
                    callback = item["callback"]
                    timeout = item["timeout"]
                    critical = item["critical"]
                    silent = item["silent"]
                    label = self._display_label(item)
                    auto_retry = item["auto_retry"]
                    log_errors = item["log_errors"]
                    stream_callback = item["stream_callback"]
                    cancel_token = item["cancel_token"]
                    self.current_command = cmd
                    if critical:
                        self.pause_monitoring = True
                    if not silent:
                        self.log(f"[SSH QUEUE] START -> {label}")
                    if stream_callback:
                        cancel_event = threading.Event()
                        with self._active_cancel_lock:
                            self._active_cancel_event = cancel_event
                            self._active_cancel_token = cancel_token

                        def forward_output(chunk):
                            def deliver():
                                try:
                                    stream_callback(chunk)
                                except Exception as e:
                                    self.log(f"[SSH QUEUE STREAM ERROR] {e}")

                            try:
                                if self.root is not None and self.root.winfo_exists():
                                    self.root.after(0, deliver)
                            except Exception:
                                pass

                        result = self.ssh.execute_stream_sync(
                            cmd,
                            on_output=forward_output,
                            timeout=timeout,
                            cancel_event=cancel_event,
                            auto_retry=auto_retry,
                            log_errors=log_errors,
                        )
                    else:
                        result = self.ssh.execute_sync(
                            cmd,
                            timeout=timeout,
                            auto_retry=auto_retry,
                            log_errors=log_errors,
                        )
                    result["stdout"] = result.get("out", "")
                    result["stderr"] = result.get("err", "")
                    if not silent:
                        self.log(f"[SSH QUEUE] END -> {label}")

            except Exception as e:
                self.log(f"[SSH QUEUE ERROR] {e}")
                result = {
                    "success": False,
                    "out": "",
                    "err": str(e),
                    "stdout": "",
                    "stderr": str(e),
                    "returncode": None,
                }
                if critical:
                    self.pause_monitoring = False
            finally:
                with self._active_cancel_lock:
                    self._active_cancel_event = None
                    self._active_cancel_token = None
                if callback and result is not None:
                    def run_callback(
                        r=result,
                        key=dedupe_key,
                        is_critical=critical,
                        callback_fn=callback,
                    ):
                        try:
                            callback_fn(r)
                        except Exception as e:
                            self.log(f"[SSH QUEUE CALLBACK ERROR] {e}")
                        finally:
                            if is_critical:
                                self.pause_monitoring = False
                            self._release_dedupe_key(key)

                    try:
                        if self.root is not None and self.root.winfo_exists():
                            self.root.after(0, run_callback)
                            callback_scheduled = True
                    except Exception as e:
                        self.log(f"[SSH QUEUE CALLBACK ERROR] {e}")
                if not callback_scheduled:
                    if critical:
                        self.pause_monitoring = False
                    self._release_dedupe_key(dedupe_key)
                self.busy = False
                self.current_command = None

            self.q.task_done()
