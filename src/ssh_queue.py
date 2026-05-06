import queue
import threading


class SSHQueue:
    def __init__(self, ssh, root, log=None):
        self.ssh = ssh
        self.root = root
        self.log = log or (lambda x: None)

        self.q = queue.Queue()
        self.running = True

        self.worker = threading.Thread(target=self._worker, daemon=True)
        self.worker.start()

    def execute(self, cmd, callback=None):
        self.q.put((cmd, callback))

    def _worker(self):
        while self.running:
            cmd, callback = self.q.get()

            try:
                def internal_cb(res):
                    if callback:
                        self.root.after(0, lambda: callback(res))

                self.ssh.execute(
                    cmd,
                    callback=internal_cb,
                    auto_retry=False,
                    log_errors=False
                )

            except Exception as e:
                self.log(f"[SSH QUEUE ERROR] {e}")

            self.q.task_done()