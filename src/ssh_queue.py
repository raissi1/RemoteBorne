import queue
import threading


class SSHQueue:
    def __init__(self, ssh, root, log=None):
        self.ssh = ssh
        self.root = root
        self.log = log or (lambda x: None)

        self.q = queue.Queue()

        self.running = True

        self.busy = False
        self.current_command = None

        self.pause_monitoring = False
        self.reboot_in_progress = False

        self.lock = threading.Lock()

        self.worker = threading.Thread(
            target=self._worker,
            daemon=True
        )
        self.worker.start()

    # ==========================================================
    # PUBLIC
    # ==========================================================
    def stop(self):
        self.running = False

        try:
            self.q.put_nowait(None)
        except Exception:
            pass

    def execute(
        self,
        cmd,
        callback=None,
        timeout=30,
        command_type=None,
        critical=False,
        silent=True,
    ):
        self.q.put({
            "cmd": cmd,
            "callback": callback,
            "timeout": timeout,
            "critical": critical,
            "type": command_type,
            "silent": silent,
        })

    # ==========================================================
    # WORKER
    # ==========================================================
    def _worker(self):

        while self.running:

            try:

                item = self.q.get(timeout=0.5)
                if item is None:
                    break

            except queue.Empty:
                continue

            try:

                with self.lock:

                    self.busy = True

                    cmd = item["cmd"]
                    callback = item["callback"]
                    timeout = item["timeout"]
                    critical = item["critical"]
                    silent = item.get("silent", False)

                    self.current_command = cmd

                    if critical:
                        self.pause_monitoring = True

                    # ==========================================
                    # LOG START
                    # ==========================================
                    if not silent:
                        self.log(f"[SSH QUEUE] START -> {cmd}")

                    # ==========================================
                    # EXECUTION SYNCHRONE
                    # ==========================================
                    result = self.ssh.execute_sync(
                        cmd,
                        timeout=timeout
                    )

                    # ==========================================
                    # LOG END
                    # ==========================================
                    if not silent:
                        self.log(f"[SSH QUEUE] END -> {cmd}")

                    # ==========================================
                    # CALLBACK UI SAFE
                    # ==========================================
                    if callback:

                        try:

                            if (
                                self.root is not None
                                and self.root.winfo_exists()
                            ):

                                self.root.after(
                                    0,
                                    lambda r=result: callback(r)
                                )

                        except Exception as e:

                            self.log(
                                f"[SSH QUEUE CALLBACK ERROR] {e}"
                            )

            except Exception as e:

                self.log(f"[SSH QUEUE ERROR] {e}")

            finally:

                self.busy = False
                self.current_command = None

                try:
                    self.q.task_done()
                except Exception:
                    pass