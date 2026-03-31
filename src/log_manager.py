# ===========================================================
#  log_manager.py  (Version C PRO)
#  Gestion fiable des logs distants en "tail -F"
# ===========================================================

import threading
import time

from plink_backend import PlinkBackend


class LogManager:
    """
    Gestion du streaming de logs distants par 'tail -F <file>'.
    """

    def __init__(self, host, username, password, port=22, timeout=10):
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.timeout = timeout

        self.backend = PlinkBackend(host, username, password, port)

        self.stop_event = threading.Event()
        self.thread = None

        self.on_line = None
        self.on_status = None

    def set_line_callback(self, callback):
        self.on_line = callback

    def set_status_callback(self, callback):
        self.on_status = callback

    def start(self, remote_path: str):
        self.stop()
        self.stop_event.clear()
        self.thread = threading.Thread(
            target=self._tail_loop,
            args=(remote_path,),
            daemon=True,
        )
        self.thread.start()
        if self.on_status:
            self.on_status("started", remote_path)

    def stop(self):
        self.stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)
        self.thread = None
        if self.on_status:
            self.on_status("stopped", None)

    def _tail_loop(self, remote_path):
        while not self.stop_event.is_set():
            try:
                self.backend.tail_stream(
                    remote_path,
                    on_line_callback=self._safe_line_callback,
                    stop_event=self.stop_event,
                )
                if self.stop_event.is_set():
                    break
                if self.on_status:
                    self.on_status("error", f"plink disconnected for {remote_path}")
            except Exception as e:
                if self.on_status:
                    self.on_status("error", str(e))

            for _ in range(10):
                if self.stop_event.is_set():
                    break
                time.sleep(0.3)

        if self.on_status:
            self.on_status("stopped", remote_path)

    def _safe_line_callback(self, line: str):
        if self.on_line:
            try:
                self.on_line(line)
            except Exception:
                pass
