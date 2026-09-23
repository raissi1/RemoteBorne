# plink_backend.py — version avec chemins tools\plink.exe et tools\pscp.exe

import os
import queue
import subprocess
import sys
import threading
import time

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


class PlinkBackend:
    def __init__(self, host, username, password, port=22,
                 plink_path=None, pscp_path=None, host_key=None):
        if getattr(sys, "frozen", False):
            # mode exe PyInstaller: outils à côté du .exe
            project_root = os.path.dirname(sys.executable)
        else:
            # dossier où se trouve ce fichier (src)
            this_dir = os.path.dirname(os.path.abspath(__file__))
            # racine du projet = dossier parent de src
            project_root = os.path.dirname(this_dir)

        # dossier tools à la racine
        tools_dir = os.path.join(project_root, "tools")

        # chemins par défaut vers plink.exe et pscp.exe
        default_plink = os.path.join(tools_dir, "plink.exe")
        default_pscp = os.path.join(tools_dir, "pscp.exe")

        self.plink_path = plink_path or default_plink
        self.pscp_path = pscp_path or default_pscp

        self.host = host
        self.username = username
        self.password = password
        self.port = port
        # Set after explicit operator approval for the current EVSE session.
        self.host_key = host_key

    def _host_key_args(self):
        return ["-hostkey", self.host_key] if self.host_key else []

        # petit check utile pour le debug
        if not os.path.isfile(self.plink_path):
            raise FileNotFoundError(
                f"plink.exe introuvable : {self.plink_path}\n"
                "Vérifie que plink.exe est bien dans le dossier tools/"
            )
        if not os.path.isfile(self.pscp_path):
            raise FileNotFoundError(
                f"pscp.exe introuvable : {self.pscp_path}\n"
                "Vérifie que pscp.exe est bien dans le dossier tools/"
            )

    # ----------------------------------------------------------
    # Helpers pour lancer plink/pscp SANS fenêtre
    # ----------------------------------------------------------
    def _popen_kwargs(self):
        if os.name != "nt":
            return {}
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        return {
            "startupinfo": startupinfo,
            "creationflags": CREATE_NO_WINDOW,
        }

    # ----------------------------------------------------------
    # SSH COMMAND
    # ----------------------------------------------------------
    def exec(self, remote_cmd, timeout=None):
        if not remote_cmd or not str(remote_cmd).strip():
            return 1, "", "Empty remote command"
        cmd = [
            self.plink_path,
            "-ssh",
            "-batch",
            *self._host_key_args(),
            "-P", str(self.port),
            "-l", self.username,
            "-pw", self.password,
            self.host,
            remote_cmd,
        ]
        if timeout is None:
            timeout = 10

        kwargs = self._popen_kwargs()

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                **kwargs,
            )
            return proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired:
            return 1, "", f"Timeout after {timeout} seconds"
        except Exception as e:
            return 1, "", str(e)

    def exec_stream(self, remote_cmd, on_output=None, timeout=None, cancel_event=None):
        """Run a remote command while forwarding stdout/stderr line by line."""
        if not remote_cmd or not str(remote_cmd).strip():
            return 1, "", "Empty remote command"

        cmd = [
            self.plink_path,
            "-ssh",
            "-batch",
            *self._host_key_args(),
            "-P", str(self.port),
            "-l", self.username,
            "-pw", self.password,
            self.host,
            remote_cmd,
        ]
        kwargs = self._popen_kwargs()
        output_lines = []
        chunks = queue.Queue()

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                **kwargs,
            )
        except Exception as e:
            return 1, "", str(e)

        def read_output():
            try:
                for line in iter(proc.stdout.readline, ""):
                    chunks.put(line)
            finally:
                if proc.stdout:
                    proc.stdout.close()

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        deadline = None if timeout is None else time.monotonic() + timeout

        try:
            while reader.is_alive() or not chunks.empty():
                if cancel_event is not None and cancel_event.is_set():
                    proc.kill()
                    reader.join(timeout=1)
                    return 1, "".join(output_lines), "Cancelled by operator"
                if deadline is not None and time.monotonic() >= deadline:
                    proc.kill()
                    reader.join(timeout=1)
                    return 1, "".join(output_lines), f"Timeout after {timeout} seconds"
                try:
                    line = chunks.get(timeout=0.2)
                except queue.Empty:
                    continue
                output_lines.append(line)
                if on_output:
                    try:
                        on_output(line)
                    except Exception:
                        pass

            returncode = proc.wait(timeout=1)
            return returncode, "".join(output_lines), ""
        except Exception as e:
            try:
                proc.kill()
            except Exception:
                pass
            return 1, "".join(output_lines), str(e)

    def scp_get(self, remote_path, local_path, timeout=None):
        if not remote_path:
            return False, "", "Empty remote path"
        if not local_path:
            return False, "", "Empty local path"

        local_dir = os.path.dirname(local_path) or "."
        os.makedirs(local_dir, exist_ok=True)

        cmd = [
            self.pscp_path,
            "-batch",
            "-scp",
            *self._host_key_args(),
            "-P", str(self.port),
            "-pw", self.password,
            f"{self.username}@{self.host}:{remote_path}",
            local_path,
        ]
        if timeout is None:
            timeout = 10
        kwargs = self._popen_kwargs()
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                **kwargs,
            )
            success = proc.returncode == 0
            return success, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired:
            return False, "", f"Timeout after {timeout} seconds"
        except Exception as e:
            return False, "", str(e)

    def scp_put(self, local_path, remote_path, timeout=None):
        if not local_path:
            return False, "", "Empty local path"
        if not os.path.isfile(local_path):
            return False, "", f"Local file not found: {local_path}"
        if not remote_path:
            return False, "", "Empty remote path"

        cmd = [
            self.pscp_path,
            "-batch",
            "-scp",
            *self._host_key_args(),
            "-P", str(self.port),
            "-pw", self.password,
            local_path,
            f"{self.username}@{self.host}:{remote_path}",
        ]
        if timeout is None:
            timeout = 10
        kwargs = self._popen_kwargs()
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                **kwargs,
            )
            success = proc.returncode == 0
            return success, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired:
            return False, "", f"Timeout after {timeout} seconds"
        except Exception as e:
            return False, "", str(e)
