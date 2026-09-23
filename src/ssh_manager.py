# ssh_manager.py — gestion SSH pour RemoteBorneManager
import os
import re
import shlex
import threading
import subprocess
from typing import Callable, Optional

try:
    import winreg
except ImportError:
    winreg = None

try:
    from .plink_backend import PlinkBackend
except ImportError:
    try:
        from plink_backend import PlinkBackend
    except ImportError:
        from src.plink_backend import PlinkBackend

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


class SSHManager:
    def __init__(
        self,
        host: str,
        user: str,
        password: str,
        port: int = 22,
        timeout: int = 5,
        retry_base_delay: float = 2.0,
        retry_max_delay: float = 10.0,
    ):
        self.host = host
        self.user = user
        self.password = password
        self.port = port
        self.timeout = timeout

        self.backend = PlinkBackend(host, user, password, port)

        self.connected = False
        self._ui_callback: Optional[Callable[[str, object], None]] = None
        self._log_callback: Optional[Callable[[str], None]] = None
        self._host_key_confirmation_callback: Optional[Callable[[str, str], bool]] = None
        self._stop = False

        # paramètres de reconnexion
        self.max_retries = 3
        self.retry_base_delay = max(0.5, float(retry_base_delay))
        self.retry_max_delay = max(self.retry_base_delay, float(retry_max_delay))
        self._reconnect_lock = threading.Lock()
        self._reconnect_in_progress = False
        self._reconnect_requested = False
        self._connect_generation = 0
        self._cancel_reconnect_event = threading.Event()
        self._connection_state_lock = threading.Lock()
        self._disconnect_notified = False

    def _is_transport_error(self, message: str) -> bool:
        msg = (message or "").lower()
        transport_markers = (
            "network error",
            "fatal error",
            "connection timed out",
            "timeout after",
            "software caused connection abort",
            "connection refused",
            "connection reset",
            "connection closed",
            "connection aborted",
            "connection lost",
            "connection failed",
            "connection unexpectedly closed",
            "broken pipe",
            "no route to host",
            "network is unreachable",
            "unable to open connection",
            "unable to connect",
            "host does not exist",
            "server unexpectedly closed network connection",
        )
        return any(marker in msg for marker in transport_markers)

    def _mark_connected(self):
        """Record a successful SSH command and allow a future disconnect event."""
        with self._connection_state_lock:
            self.connected = True
            self._disconnect_notified = False

    def report_connection_lost(self, message: str, force_event: bool = False) -> bool:
        """Synchronize the SSH and UI states after a confirmed connection loss.

        A single outage can be seen by several queued commands.  Emit only one
        ``disconnected`` event until a successful connection resets the state.
        ``force_event`` covers callers such as the heartbeat which know that a
        command expected to succeed (``echo alive``) has failed.
        """
        with self._connection_state_lock:
            was_connected = self.connected
            self.connected = False
            should_notify = (was_connected or force_event) and not self._disconnect_notified
            if should_notify:
                self._disconnect_notified = True

        if should_notify:
            self._emit_ui("disconnected", None)
        if should_notify and message:
            self._log(f"[SSH] Connection lost: {message}")
        return should_notify

    def _mark_transport_failure(self, message: str):
        if self._is_transport_error(message):
            self.report_connection_lost(message)

    # ------------------------------------------------------------------ #
    #  Callbacks
    # ------------------------------------------------------------------ #
    def set_ui_callback(self, cb: Callable[[str, object], None]):
        self._ui_callback = cb

    def set_log_callback(self, cb: Callable[[str], None]):
        self._log_callback = cb

    def set_host_key_confirmation_callback(self, cb: Callable[[str, str], bool]):
        """Set the UI callback used before trusting a new SSH host key."""
        self._host_key_confirmation_callback = cb

    def _emit_ui(self, event_type: str, data=None):
        if self._ui_callback:
            try:
                self._ui_callback(event_type, data)
            except Exception as e:
                print(f"[SSH WARN] UI callback failed: {e}")

    def _log(self, msg: str):
        if self._log_callback:
            try:
                self._log_callback(msg)
                return
            except Exception as e:
                print(f"[SSH WARN] Log callback failed: {e}")
        # fallback console si pas de callback
        print(msg)

    def clear_cached_host_keys(
        self, host: Optional[str] = None, port: Optional[int] = None
    ) -> bool:
        """Remove only the PuTTY host keys associated with one SSH target."""
        if os.name != "nt" or winreg is None:
            self._log("[SSH SECURITY] Host-key cache management is supported on Windows only.")
            return False

        target_host = (host or self.host).strip()
        target_port = self.port if port is None else int(port)
        if not target_host:
            self._log("[SSH SECURITY] Empty host: cached host key was not removed.")
            return False

        key_path = r"Software\SimonTatham\PuTTY\SshHostKeys"
        target_suffix = f"@{target_port}:{target_host}".lower()
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                key_path,
                0,
                winreg.KEY_READ | winreg.KEY_WRITE,
            ) as registry_key:
                names = []
                index = 0
                while True:
                    try:
                        name, _, _ = winreg.EnumValue(registry_key, index)
                    except OSError:
                        break
                    if name.lower().endswith(target_suffix):
                        names.append(name)
                    index += 1

                if not names:
                    self._log("[SSH SECURITY] No cached host key found for this target.")
                    return False

                for name in names:
                    winreg.DeleteValue(registry_key, name)

            self._log(f"[SSH] Cleared cached host key for {target_host}:{target_port}.")
            return True
        except OSError as exc:
            self._log(f"[SSH SECURITY] Unable to clear cached host key: {exc}")
            return False

    def _replace_cached_host_key(self) -> bool:
        """Replace the current target's cached key after operator approval."""
        return self.clear_cached_host_keys(self.host, self.port)

    @staticmethod
    def _extract_host_key_fingerprint(output: str) -> Optional[str]:
        """Return Plink's SHA256 fingerprint in the form accepted by -hostkey."""
        match = re.search(
            r"key fingerprint is:\s*\r?\n\s*([^\r\n]+)",
            output or "",
            re.IGNORECASE,
        )
        return match.group(1).strip() if match else None

    # ------------------------------------------------------------------ #
    #  Auto accept host key
    # ------------------------------------------------------------------ #
    def _auto_accept_hostkey(self, expected_generation: Optional[int] = None) -> bool:
        """Confirm a new key explicitly for the current EVSE session."""
        try:
            if (
                expected_generation is not None
                and expected_generation != self._connect_generation
            ):
                self._log("[SSH] Skip host key auto-accept for stale target generation.")
                return
            # The exact approved fingerprint is passed to Plink's batch
            # commands. It is more reliable than depending on its registry
            # cache after an operator switches chargers or networks.
            if self.backend.host_key:
                return True
            cmd = [
                self.backend.plink_path,
                "-ssh",
                "-P", str(self.port),
                "-l", self.user,
                "-pw", self.password,
                self.host,
                "exit",
            ]
            self._log(f"[SSH] Checking host key for {self.host}...")

            kwargs = {}
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                kwargs["startupinfo"] = startupinfo
                kwargs["creationflags"] = CREATE_NO_WINDOW

            probe = subprocess.run(
                cmd,
                input="n\n",
                text=True,
                capture_output=True,
                timeout=self.timeout * 2,
                **kwargs,
            )
            output = "\n".join(part for part in (probe.stdout, probe.stderr) if part)
            lowered = output.lower()
            changed_key = (
                "potential security breach" in lowered
                or "does not match" in lowered
            )
            unknown_key = (
                "host key is not cached" in lowered
                or "store key in cache" in lowered
            )
            if unknown_key or changed_key:
                confirm = self._host_key_confirmation_callback
                if not callable(confirm) or not confirm(self.host, output):
                    self._log("[SSH SECURITY] Host key was not approved by the operator.")
                    return False

                host_key = self._extract_host_key_fingerprint(output)
                if not host_key:
                    self._log("[SSH SECURITY] Host key fingerprint could not be read.")
                    return False

                self.backend.host_key = host_key
                self._log("[SSH] Host key approved for this EVSE session.")
                return True

            if probe.returncode == 0:
                return True

            if not (unknown_key or changed_key):
                # Network or authentication failures are reported by the normal connection.
                return True
        except Exception as e:
            if (
                expected_generation is not None
                and expected_generation != self._connect_generation
            ):
                self._log("[SSH] Host key auto-accept cancelled (target updated).")
                return False
            self._log(f"[SSH SECURITY] Host key check failed: {e}")
            return False

    # ------------------------------------------------------------------ #
    #  Démarrage explicite
    # ------------------------------------------------------------------ #
    def start(self):
        """Démarre la connexion initiale dans un thread."""
        self._log("[SSH] Manager started.")
        t = threading.Thread(target=self._initial_connect, daemon=True)
        t.start()

    # ------------------------------------------------------------------ #
    #  Connexion initiale
    # ------------------------------------------------------------------ #
    def _initial_connect(self):
        if self._stop:
            return
        generation = self._connect_generation

        self._emit_ui("reconnecting", None)
        self._log(f"[SSH] Connecting to {self.host}:{self.port}...")

        # 1) s'assurer que la host key est dans le cache PuTTY
        if not self._auto_accept_hostkey(expected_generation=generation):
            self.connected = False
            self._emit_ui("disconnected", None)
            self._log("[SSH] Initial connection stopped by host key verification.")
            return
        if generation != self._connect_generation or self._stop:
            self._log("[SSH] Initial connect cancelled (target updated).")
            return

        # 2) Connexion en batch avec mot de passe
        ok = self._try_connect_once(expected_generation=generation)
        if generation != self._connect_generation or self._stop:
            self._log("[SSH] Initial connect result ignored (target updated).")
            return
        if ok:
            self._emit_ui("connected", None)
            self._log("[SSH] Initial connect SUCCESS.")
            return

        self._emit_ui("disconnected", None)
        self._log(f"[SSH] Initial connect FAILED: Timeout after {self.timeout} seconds")

        # On laisse la boucle de reconnexion gérer la suite
        self.force_reconnect()

    def _try_connect_once(self, expected_generation: Optional[int] = None) -> bool:
        if (
            expected_generation is not None
            and expected_generation != self._connect_generation
        ):
            return False
        rc, out, err = self.backend.exec("echo connected", timeout=self.timeout)
        if (
            expected_generation is not None
            and expected_generation != self._connect_generation
        ):
            return False
        if rc == 0:
            self._mark_connected()
            return True
        else:
            self.connected = False
            msg = (err or out or "unknown error").strip()
            if "host key" in msg.lower():
                # A key changed while RBM was open. Clear the session approval
                # so the next reconnect asks the operator to validate it.
                self.backend.host_key = None
            self._log(f"[SSH] Connect error: {msg}")
            return False

    # ------------------------------------------------------------------ #
    #  Boucle de reconnexion
    # ------------------------------------------------------------------ #
    def _try_reconnect(self):
        if self._stop:
            return
        generation = self._connect_generation
        with self._reconnect_lock:
            self._reconnect_in_progress = True
            self._reconnect_requested = False

        try:
            self._emit_ui("reconnecting", None)
            self._log("[SSH] Reconnecting...")

            # A charger may become reachable only after the initial connection
            # failed. Verify its host key here as well, before batch-mode Plink
            # retries, so an operator can explicitly trust a new target.
            if not self._auto_accept_hostkey(expected_generation=generation):
                self.connected = False
                self._emit_ui("disconnected", None)
                self._log("[SSH] Reconnect stopped by host key verification.")
                return

            for attempt in range(1, self.max_retries + 1):
                if self._stop:
                    return
                if self._cancel_reconnect_event.is_set():
                    self._cancel_reconnect_event.clear()
                    self._log("[SSH] Reconnect cancelled (target updated).")
                    return
                if generation != self._connect_generation:
                    self._log("[SSH] Reconnect cancelled (target updated).")
                    return

                self._log(f"[SSH] Reconnect attempt {attempt}/{self.max_retries}...")
                ok = self._try_connect_once(expected_generation=generation)
                if ok:
                    self._emit_ui("reconnected", None)
                    self._log("[SSH] Reconnect SUCCESS.")
                    return

                delay = min(self.retry_base_delay * attempt, self.retry_max_delay)
                self._log(
                    f"[SSH] Reconnect attempt {attempt} failed, retry in {delay} s"
                )
                if self._cancel_reconnect_event.wait(timeout=delay):
                    self._cancel_reconnect_event.clear()
                    self._log("[SSH] Reconnect cancelled during backoff (target updated).")
                    return

            self.connected = False
            self._emit_ui("disconnected", None)
            self._log("[SSH] Unable to reconnect after max attempts.")
        finally:
            relaunch = False
            with self._reconnect_lock:
                self._reconnect_in_progress = False
                if self._reconnect_requested and not self._stop and not self.connected:
                    self._reconnect_requested = False
                    relaunch = True
                elif self.connected:
                    # connexion déjà rétablie: purge toute demande en file
                    self._reconnect_requested = False
            if relaunch:
                self._log("[SSH] Launching queued reconnect request.")
                threading.Thread(target=self._try_reconnect, daemon=True).start()

    def force_reconnect(self, force_if_connected: bool = False):
        """API publique : relancer une reconnexion dans un thread."""
        if self.connected and not force_if_connected:
            self._log("[SSH] Already connected, skip force_reconnect.")
            return
        self._stop = False
        self._cancel_reconnect_event.clear()
        with self._reconnect_lock:
            if self._reconnect_in_progress:
                self._reconnect_requested = True
                self._log("[SSH] Reconnect already in progress, queued a new reconnect.")
                return
        threading.Thread(target=self._try_reconnect, daemon=True).start()

    def restart(self):
        """
        Réactive le manager après close() puis relance une reconnexion.
        Utile après changement de config réseau en cours d'exécution.
        """
        self._stop = False
        self.force_reconnect()

    # ------------------------------------------------------------------ #
    #  Mise à jour de la cible (changement IP dans Network Config)
    # ------------------------------------------------------------------ #
    def update_target(
        self,
        host: str,
        user: str,
        password: str,
        port: int = 22,
        auto_reconnect: bool = True,
    ):
        """
        Met à jour IP / user / password / port à chaud, recrée le backend
        et force une reconnexion (optionnelle).
        """
        self.host = host
        self.user = user
        self.password = password
        self.port = port
        self._stop = False
        self._connect_generation += 1
        self._cancel_reconnect_event.set()
        self.backend = PlinkBackend(host, user, password, port)
        self.report_connection_lost(
            f"Target changed to {host}:{port}", force_event=True
        )
        self._log(f"[SSH] Target updated to {host}:{port} ({user})")
        if auto_reconnect:
            self.force_reconnect()

    # ------------------------------------------------------------------ #
    #  Exécution de commande
    # ------------------------------------------------------------------ #
    def execute(
        self,
        cmd: str,
        callback: Optional[Callable[[dict], None]] = None,
        auto_retry: bool = True,
        log_errors: bool = True,
        timeout: Optional[int] = None,
    ):
        """
        Exécute une commande SSH dans un thread séparé.

        callback reçoit : {"success": bool, "out": str, "err": str}
        """

        def worker():
            if not self.connected and auto_retry:
                self._try_reconnect()
            if not self.connected:
                err_msg = "SSH not connected"
                if log_errors:
                    self._log(f"[SSH CMD ERROR] {err_msg}")
                if callback:
                    try:
                        callback({"success": False, "out": "", "err": err_msg})
                    except Exception:
                        pass
                return

            exec_timeout = timeout if timeout is not None else self.timeout
            rc, out, err = self.backend.exec(cmd, timeout=exec_timeout)
            success = (rc == 0)
            res = {"success": success, "out": out, "err": err}

            if not success and log_errors:
                self._log(f"[SSH CMD ERROR] {err or out or 'unknown error'}")
            if not success:
                self._mark_transport_failure(err or out or "")

            if callback:
                try:
                    callback(res)
                except Exception:
                    pass

        threading.Thread(target=worker, daemon=True).start()

    def execute_sync(
        self,
        cmd: str,
        timeout: Optional[int] = None,
        auto_retry: bool = True,
        log_errors: bool = True,
    ) -> dict:
        """
        Exécute une commande SSH de manière bloquante.

        À utiliser uniquement depuis un thread de travail.
        """
        if not self.connected and auto_retry:
            self._try_reconnect()
        if not self.connected:
            err_msg = "SSH not connected"
            if log_errors:
                self._log(f"[SSH CMD ERROR] {err_msg}")
            return {"success": False, "out": "", "err": err_msg}

        exec_timeout = timeout if timeout is not None else self.timeout
        rc, out, err = self.backend.exec(cmd, timeout=exec_timeout)
        success = (rc == 0)
        if not success and log_errors:
            self._log(f"[SSH CMD ERROR] {err or out or 'unknown error'}")
        if not success:
            self._mark_transport_failure(err or out or "")
        return {
            "success": success,
            "out": out,
            "err": err,
            "stdout": out,
            "stderr": err,
            "returncode": rc,
        }

    def execute_stream_sync(
        self,
        cmd: str,
        on_output: Optional[Callable[[str], None]] = None,
        timeout: Optional[int] = None,
        cancel_event: Optional[threading.Event] = None,
        auto_retry: bool = True,
        log_errors: bool = True,
    ) -> dict:
        """Execute a command in the queue worker while forwarding remote output."""
        if not self.connected and auto_retry:
            self._try_reconnect()
        if not self.connected:
            err_msg = "SSH not connected"
            if log_errors:
                self._log(f"[SSH CMD ERROR] {err_msg}")
            return {"success": False, "out": "", "err": err_msg, "returncode": None}

        rc, out, err = self.backend.exec_stream(
            cmd,
            on_output=on_output,
            timeout=timeout,
            cancel_event=cancel_event,
        )
        success = rc == 0
        if not success and log_errors:
            self._log(f"[SSH CMD ERROR] {err or out or 'unknown error'}")
        if not success and err != "Cancelled by operator":
            self._mark_transport_failure(err or out or "")
        return {
            "success": success,
            "out": out,
            "err": err,
            "stdout": out,
            "stderr": err,
            "returncode": rc,
        }

    def ensure_remote_dir(self, remote_dir: str) -> dict:
        if not self.connected:
            self._try_reconnect()
        if not self.connected:
            err = "SSH not connected"
            self._log(f"[SSH CMD ERROR] {err}")
            return {"success": False, "out": "", "err": err}
        rc, out, err = self.backend.exec(
            f"mkdir -p -- {shlex.quote(remote_dir)}", timeout=self.timeout
        )
        success = (rc == 0)
        if not success:
            self._log(f"[SSH CMD ERROR] {err or out or 'unknown error'}")
            self._mark_transport_failure(err or out or "")
        return {"success": success, "out": out, "err": err}

    # ------------------------------------------------------------------ #
    #  SCP
    # ------------------------------------------------------------------ #
    def scp_get(
        self,
        remote_path: str,
        local_path: str,
        timeout: Optional[int] = None,
    ) -> dict:
        if not self.connected:
            self._try_reconnect()
        if not self.connected:
            err = "SSH not connected"
            self._log(f"[SCP GET ERROR] {err}")
            return {"success": False, "out": "", "err": err}
        scp_timeout = timeout if timeout is not None else max(30, self.timeout)
        success, out, err = self.backend.scp_get(
            remote_path, local_path, timeout=scp_timeout
        )
        if not success:
            self._log(f"[SCP GET ERROR] {err or out or 'unknown error'}")
            self._mark_transport_failure(err or out or "")
        return {"success": success, "out": out, "err": err}

    def scp_put(
        self,
        local_path: str,
        remote_path: str,
        timeout: Optional[int] = None,
    ) -> dict:
        if not self.connected:
            self._try_reconnect()
        if not self.connected:
            err = "SSH not connected"
            self._log(f"[SCP PUT ERROR] {err}")
            return {"success": False, "out": "", "err": err}
        scp_timeout = timeout if timeout is not None else max(30, self.timeout)
        success, out, err = self.backend.scp_put(
            local_path, remote_path, timeout=scp_timeout
        )
        if not success:
            self._log(f"[SCP PUT ERROR] {err or out or 'unknown error'}")
            self._mark_transport_failure(err or out or "")
        return {"success": success, "out": out, "err": err}

    # ------------------------------------------------------------------ #
    #  Fermeture
    # ------------------------------------------------------------------ #
    def close(self):
        self._stop = True
        self._cancel_reconnect_event.set()
        self.report_connection_lost("SSH manager closed.", force_event=True)
        self._log("[SSH] Manager closed.")
    
