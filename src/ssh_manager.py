# ssh_manager.py — gestion SSH pour RemoteBorneManager
import os
import threading
import subprocess
from typing import Callable, Optional

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
        timeout: int = 20,
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

    # ------------------------------------------------------------------ #
    #  Callbacks
    # ------------------------------------------------------------------ #
    def set_ui_callback(self, cb: Callable[[str, object], None]):
        self._ui_callback = cb

    def set_log_callback(self, cb: Callable[[str], None]):
        self._log_callback = cb

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

    # ------------------------------------------------------------------ #
    #  Auto accept host key
    # ------------------------------------------------------------------ #
    def _auto_accept_hostkey(self, expected_generation: Optional[int] = None):
        """
        Accepte automatiquement la host key de la borne en simulant un 'y'
        sur la première connexion plink, AVEC mot de passe, SANS -batch.

        -> évite "The host key is not cached..." + "Cannot confirm host key in batch mode"
        """
        try:
            if (
                expected_generation is not None
                and expected_generation != self._connect_generation
            ):
                self._log("[SSH] Skip host key auto-accept for stale target generation.")
                return
            cmd = [
                self.backend.plink_path,
                "-ssh",
                "-P", str(self.port),
                "-l", self.user,
                "-pw", self.password,
                self.host,
                "exit",
            ]
            self._log(f"[SSH] Auto-accept host key for {self.host}...")

            kwargs = {}
            if os.name == "nt":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                kwargs["startupinfo"] = startupinfo
                kwargs["creationflags"] = CREATE_NO_WINDOW

            subprocess.run(
                cmd,
                input="y\n",  # on répond 'y' au prompt de host key
                text=True,
                capture_output=True,
                timeout=self.timeout * 2,
                **kwargs,
            )
            self._log("[SSH] Host key added/cached.")
        except Exception as e:
            if (
                expected_generation is not None
                and expected_generation != self._connect_generation
            ):
                self._log("[SSH] Host key auto-accept cancelled (target updated).")
                return
            # On ne bloque pas sur ça, on log seulement
            self._log(f"[SSH] Auto-accept host key failed (ignored): {e}")

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
        self._auto_accept_hostkey(expected_generation=generation)
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
            self.connected = True
            return True
        else:
            self.connected = False
            msg = (err or out or "unknown error").strip()
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
        self._connect_generation += 1
        self._cancel_reconnect_event.set()
        self.backend = PlinkBackend(host, user, password, port)
        self.connected = False
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

            if callback:
                try:
                    callback(res)
                except Exception:
                    pass

        threading.Thread(target=worker, daemon=True).start()

    def ensure_remote_dir(self, remote_dir: str) -> dict:
        if not self.connected:
            self._try_reconnect()
        if not self.connected:
            err = "SSH not connected"
            self._log(f"[SSH CMD ERROR] {err}")
            return {"success": False, "out": "", "err": err}
        rc, out, err = self.backend.exec(f'mkdir -p "{remote_dir}"', timeout=self.timeout)
        success = (rc == 0)
        if not success:
            self._log(f"[SSH CMD ERROR] {err or out or 'unknown error'}")
        return {"success": success, "out": out, "err": err}

    # ------------------------------------------------------------------ #
    #  SCP
    # ------------------------------------------------------------------ #
    def scp_get(self, remote_path: str, local_path: str) -> dict:
        if not self.connected:
            self._try_reconnect()
        if not self.connected:
            err = "SSH not connected"
            self._log(f"[SCP GET ERROR] {err}")
            return {"success": False, "out": "", "err": err}
        success, out, err = self.backend.scp_get(
            remote_path, local_path, timeout=self.timeout
        )
        if not success:
            self._log(f"[SCP GET ERROR] {err or out or 'unknown error'}")
        return {"success": success, "out": out, "err": err}

    def scp_put(self, local_path: str, remote_path: str) -> dict:
        if not self.connected:
            self._try_reconnect()
        if not self.connected:
            err = "SSH not connected"
            self._log(f"[SCP PUT ERROR] {err}")
            return {"success": False, "out": "", "err": err}
        success, out, err = self.backend.scp_put(
            local_path, remote_path, timeout=self.timeout
        )
        if not success:
            self._log(f"[SCP PUT ERROR] {err or out or 'unknown error'}")
        return {"success": success, "out": out, "err": err}

    # ------------------------------------------------------------------ #
    #  Fermeture
    # ------------------------------------------------------------------ #
    def close(self):
        self._stop = True
        self.connected = False
        self._emit_ui("disconnected", None)
        self._log("[SSH] Manager closed.")
