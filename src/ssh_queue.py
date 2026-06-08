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
        self.busy = False
        self.pause_monitoring = False
        self.current_command = None

        self.worker = threading.Thread(target=self._worker, daemon=True)
        self.worker.start()

    def execute(self, cmd, callback=None, **kwargs):
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
        }
        self.q.put(item)

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

    def _worker(self):
        while self.running:
            item = self.q.get()
            if item is None:
                self.q.task_done()
                break

            critical = False
            callback = None
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
                    self.current_command = cmd
                    if critical:
                        self.pause_monitoring = True
                    if not silent:
                        self.log(f"[SSH QUEUE] START -> {label}")
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

                if callback:
                    try:
                        if self.root is not None and self.root.winfo_exists():
                            self.root.after(0, lambda r=result: callback(r))
                    except Exception as e:
                        self.log(f"[SSH QUEUE CALLBACK ERROR] {e}")
                elif critical:
                    self.pause_monitoring = False

            except Exception as e:
                self.log(f"[SSH QUEUE ERROR] {e}")
                if critical:
                    self.pause_monitoring = False
            finally:
                self.busy = False
                self.current_command = None

            self.q.task_done()
