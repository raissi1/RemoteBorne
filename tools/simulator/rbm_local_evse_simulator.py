#!/usr/bin/env python3
"""Local SSH/SCP EVSE simulator for developer validation of RemoteBorne."""

import argparse
import posixpath
import re
import shlex
import shutil
import socket
import threading
import time
from pathlib import Path, PurePosixPath

try:
    import paramiko
except ImportError as exc:  # pragma: no cover - startup guard
    raise SystemExit(
        "Paramiko is required. Install tools/simulator/requirements.txt first."
    ) from exc


GRID_CODES = "/etc/iotecha/configs/GridCodes"
DERATE_LOG = "/var/aux/ChargerApp/derate.log"
CHARGER_LOG = "/var/aux/ChargerApp/ChargerApp.log"
ENERGY_LOG = "/var/aux/EnergyManager/EnergyManager.log"
DISPATCHER_LOG = "/var/log/iotc-meter-dispatcher.log"


class SimulatedEvse:
    """Owns fake EVSE files and the mutable state exposed through SSH."""

    def __init__(self, data_dir, password):
        self.data_dir = Path(data_dir).resolve()
        self.password = password
        self.lock = threading.RLock()
        self.offline = False
        self.fail_next = False
        self.latency = 0.0
        self.soc = 80
        self.temperatures = [42, 42, 43, 43]
        self.command_count = 0
        self._bootstrap()

    def _bootstrap(self, reset=False):
        if reset and self.data_dir.exists():
            shutil.rmtree(self.data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        files = {
            f"{GRID_CODES}/GridCodes.properties": (
                "# RBM local EVSE simulator\nGridCode=GC_DEMO\nGridTopology=ThreePhase\n"
                "PowerMax_1Ph_VAr=1600\nPowerMax_3Ph_VAr=4800\nQmax_var=3000\n"
            ),
            f"{GRID_CODES}/FR_5.5.2.3_Setpoint-Control.py": "# simulated setpoint script\n",
            f"{GRID_CODES}/FR_cosphi_to_Q.py": "# simulated CosPhi script\n",
            f"{GRID_CODES}/GC_sansPile_FRT": "# simulated GridCode\n",
            f"{GRID_CODES}/GC/FR/GC_FR_Demo.properties": "GridCode=FR_DEMO\n",
            f"{GRID_CODES}/GC/DE/GC_DE_Demo.properties": "GridCode=DE_DEMO\n",
            f"{GRID_CODES}/GC/UK/GC_UK_Demo.properties": "GridCode=UK_DEMO\n",
            "/var/aux/netlogger/netlog.demo.pcap.gz": "RBM simulated NetLogger capture\n",
        }
        for remote_path, content in files.items():
            path = self.resolve(remote_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_text(content, encoding="utf-8")
        self._write_logs()

    def resolve(self, remote_path):
        remote_path = str(remote_path).strip().replace("\\", "/")
        normalized = posixpath.normpath("/" + remote_path.lstrip("/"))
        relative = PurePosixPath(normalized).relative_to("/")
        candidate = (self.data_dir.joinpath(*relative.parts)).resolve()
        if candidate != self.data_dir and self.data_dir not in candidate.parents:
            raise ValueError("Remote path escapes the simulator root")
        return candidate

    def _write_logs(self):
        relay = " ".join(
            "PowerBoard Relay T{}: {}".format(index + 1, value)
            for index, value in enumerate(self.temperatures)
        )
        self._write_text(DERATE_LOG, "DerateDetails: {}\n".format(relay))
        charger = "2026-09-10 10:00:00 [SIM] Charger connected\n"
        if self.soc is not None:
            charger += "2026-09-10 10:00:00 [SIM] evPresentSoC: {}\n".format(self.soc)
        else:
            charger += "2026-09-10 10:00:00 [SIM] vehicle not connected\n"
        self._write_text(CHARGER_LOG, charger)
        self._write_text(ENERGY_LOG, "2026-09-10 10:00:00 [SIM] Energy Manager ready\n")
        self._write_text(DISPATCHER_LOG, "2026-09-10 10:00:00 [SIM] iotc meter dispatcher ready\n")

    def _write_text(self, remote_path, content):
        path = self.resolve(remote_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def append_log(self, remote_path, message):
        path = self.resolve(remote_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with path.open("a", encoding="utf-8") as handle:
            handle.write("{} [SIM] {}\n".format(stamp, message))

    def reset(self):
        with self.lock:
            self.offline = False
            self.fail_next = False
            self.latency = 0.0
            self.soc = 80
            self.temperatures = [42, 42, 43, 43]
            self.command_count = 0
            self._bootstrap(reset=True)

    def status(self):
        with self.lock:
            soc = "none" if self.soc is None else self.soc
            return "offline={} latency={}s soc={} temperatures={} commands={}".format(
                self.offline, self.latency, soc, self.temperatures, self.command_count
            )

    def command_guard(self):
        with self.lock:
            self.command_count += 1
            offline = self.offline
            fail_next = self.fail_next
            self.fail_next = False
            latency = self.latency
        if latency:
            time.sleep(latency)
        if offline:
            return 255, "", "Simulated EVSE is offline"
        if fail_next:
            return 1, "", "Simulated command failure"
        return None


def _quoted_or_absolute_paths(command):
    paths = []
    for quote_path in re.findall(r"['\"]([^'\"]+)['\"]", command):
        if quote_path.startswith("/"):
            paths.append(quote_path)
    for token in re.findall(r"(?<![\w.-])/(?:[^\s;'\"|&]+)", command):
        paths.append(token.rstrip(";,)}]"))
    return paths


def _last_path(command):
    paths = _quoted_or_absolute_paths(command)
    return paths[-1] if paths else None


def _parse_copy_paths(command):
    paths = _quoted_or_absolute_paths(command)
    return paths[-2:] if len(paths) >= 2 else []


class CommandProcessor:
    """Implements the subset of shell commands emitted by RBM."""

    def __init__(self, evse):
        self.evse = evse

    def execute(self, command):
        guard = self.evse.command_guard()
        if guard:
            return guard
        command = command.strip()
        if not command or command == "exit":
            return 0, "", ""
        if "===TEMP===" in command:
            return self._telemetry()
        if re.search(r"\bls\s+-[A-Za-z]*p", command):
            return self._list_directory(command)
        if re.search(r"\btest\s+-d\b", command):
            return self._test_path(command, want_directory=True)
        if re.search(r"\btest\s+-[ef]\b", command):
            return self._test_path(command, want_directory=False)
        if re.search(r"\bwc\s+-c\b", command):
            return self._file_size(command)
        if re.search(r"\bcp\s+", command):
            return self._copy(command)
        if re.search(r"\brm\s+", command):
            return self._remove(command)
        if re.search(r"\bmkdir\s+", command):
            return self._mkdir(command)
        if "rbm_cosphi_" in command:
            return self._cosphi(command)
        if any(path in command for path in (DERATE_LOG, CHARGER_LOG, ENERGY_LOG, DISPATCHER_LOG)):
            return self._read_log(command)
        if re.search(r"\bcat\s+", command):
            return self._cat(command)
        if "reboot" in command.lower():
            self.evse.append_log(ENERGY_LOG, "Simulated device reboot requested")
            return 0, "Simulator: reboot scheduled\n", ""
        if any(token in command for token in ("service ", "systemctl ", "/etc/init.d/")):
            self.evse.append_log(ENERGY_LOG, "Simulated services restarted")
            return 0, "Simulator: services restarted\n", ""
        if "EnergyManager" in command or "setpoint" in command.lower():
            power_match = re.search(r"--power\s+([-+]?\d+(?:\.\d+)?)", command)
            reactive_match = re.search(
                r"--reactive-power\s+([-+]?\d+(?:\.\d+)?)", command
            )
            if power_match:
                active_power = power_match.group(1)
                reactive_power = reactive_match.group(1) if reactive_match else "unchanged"
                self.evse.append_log(
                    ENERGY_LOG,
                    "GridCodes: Request to accept setpoint is ignored "
                    "(no diff comparing to current: { Source: ocpp EvseID: 1, "
                    "V2XMode: CentralSetpoint, { P: {power_W: "
                    f"{active_power}" + "} }, { Q: {power_W: "
                    f"{reactive_power}" + "} }} )",
                )
            else:
                self.evse.append_log(ENERGY_LOG, "Simulated setpoint command accepted")
            return 0, "Simulator: setpoint accepted\n", ""
        return 0, "Simulator: command accepted\n", ""

    def _telemetry(self):
        with self.evse.lock:
            temperatures = list(self.evse.temperatures)
            soc = self.evse.soc
        relay = " ".join(
            "PowerBoard Relay T{}: {}".format(index + 1, value)
            for index, value in enumerate(temperatures)
        )
        output = "===TEMP===\n{}\n===SOC===\n".format(relay)
        if soc is not None:
            output += "{}\n".format(soc)
        return 0, output, ""

    def _list_directory(self, command):
        remote_path = _last_path(command) or GRID_CODES
        try:
            path = self.evse.resolve(remote_path)
        except ValueError as exc:
            return 1, "", str(exc)
        if not path.is_dir():
            return 2, "", "ls: {}: No such file or directory\n".format(remote_path)
        entries = []
        for entry in sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
            entries.append(entry.name + ("/" if entry.is_dir() else ""))
        return 0, "\n".join(entries) + ("\n" if entries else ""), ""

    def _test_path(self, command, want_directory):
        remote_path = _last_path(command)
        if not remote_path:
            return 1, "", "Simulator: missing test path\n"
        try:
            path = self.evse.resolve(remote_path)
        except ValueError as exc:
            return 1, "", str(exc)
        valid = path.is_dir() if want_directory else path.exists()
        return (0, "", "") if valid else (1, "", "")

    def _file_size(self, command):
        remote_path = _last_path(command)
        if not remote_path:
            return 1, "", "Simulator: missing file path\n"
        path = self.evse.resolve(remote_path)
        if not path.is_file():
            return 1, "", "wc: {}: No such file\n".format(remote_path)
        return 0, "{}\n".format(path.stat().st_size), ""

    def _copy(self, command):
        paths = _parse_copy_paths(command)
        if len(paths) != 2:
            return 1, "", "Simulator: copy command was not understood\n"
        source = self.evse.resolve(paths[0])
        destination = self.evse.resolve(paths[1])
        if not source.is_file():
            return 1, "", "cp: {}: No such file\n".format(paths[0])
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        self.evse.append_log(ENERGY_LOG, "Copied {} to {}".format(paths[0], paths[1]))
        return 0, "", ""

    def _remove(self, command):
        remote_path = _last_path(command)
        if not remote_path:
            return 1, "", "Simulator: missing remove path\n"
        path = self.evse.resolve(remote_path)
        if path == self.evse.data_dir:
            return 1, "", "Simulator: refusing to remove root\n"
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
        return 0, "", ""

    def _mkdir(self, command):
        remote_path = _last_path(command)
        if not remote_path:
            return 1, "", "Simulator: missing directory path\n"
        self.evse.resolve(remote_path).mkdir(parents=True, exist_ok=True)
        return 0, "", ""

    def _read_log(self, command):
        for remote_path in (DERATE_LOG, CHARGER_LOG, ENERGY_LOG, DISPATCHER_LOG):
            if remote_path in command:
                path = self.evse.resolve(remote_path)
                if not path.exists():
                    return 1, "", "Simulator log does not exist\n"
                text = path.read_text(encoding="utf-8")
                tail = re.search(r"\btail\s+-n\s+(\d+)", command)
                if tail:
                    text = "\n".join(text.splitlines()[-int(tail.group(1)):]) + "\n"
                return 0, text, ""
        return 1, "", "Simulator: unknown log\n"

    def _cat(self, command):
        remote_path = _last_path(command)
        if not remote_path:
            return 1, "", "Simulator: missing file path\n"
        path = self.evse.resolve(remote_path)
        if not path.is_file():
            return 1, "", "cat: {}: No such file\n".format(remote_path)
        return 0, path.read_text(encoding="utf-8", errors="replace"), ""

    def _cosphi(self, command):
        self.evse.append_log(ENERGY_LOG, "Simulated CosPhi command applied")
        if "RBM_STATUS" in command or "rbm_cosphi_status" in command:
            return 0, "===RBM_STATUS===0\nSimulator: CosPhi command applied\n", ""
        return 0, "Simulator: CosPhi command accepted\n", ""


def _recv_exact(channel, size):
    chunks = []
    remaining = size
    while remaining:
        data = channel.recv(remaining)
        if not data:
            raise EOFError("SCP channel closed unexpectedly")
        chunks.append(data)
        remaining -= len(data)
    return b"".join(chunks)


def _recv_line(channel):
    data = bytearray()
    while True:
        byte = _recv_exact(channel, 1)
        data.extend(byte)
        if byte == b"\n":
            return bytes(data)


class RbmServerInterface(paramiko.ServerInterface):
    def __init__(self, password):
        self.password = password
        self.commands = {}
        self.events = {}

    def check_auth_password(self, username, password):
        if username == "root" and password == self.password:
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def get_allowed_auths(self, username):
        return "password"

    def check_channel_request(self, kind, chanid):
        if kind == "session":
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_exec_request(self, channel, command):
        channel_id = channel.get_id()
        self.commands[channel_id] = command.decode("utf-8", errors="replace")
        event = self.events.setdefault(channel_id, threading.Event())
        event.set()
        return True

    def wait_for_command(self, channel, timeout=5):
        channel_id = channel.get_id()
        event = self.events.setdefault(channel_id, threading.Event())
        event.wait(timeout)
        return self.commands.pop(channel_id, None)


class LocalSshServer:
    def __init__(self, host, port, evse, host_key_path):
        self.host = host
        self.port = port
        self.evse = evse
        self.processor = CommandProcessor(evse)
        self.host_key = self._load_or_create_key(Path(host_key_path))
        self.stop_event = threading.Event()
        self.listener = None
        self.thread = None

    @staticmethod
    def _load_or_create_key(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            return paramiko.RSAKey.from_private_key_file(str(path))
        key = paramiko.RSAKey.generate(2048)
        key.write_private_key_file(str(path))
        return key

    def start(self):
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind((self.host, self.port))
        self.listener.listen(20)
        self.listener.settimeout(1.0)
        self.thread = threading.Thread(target=self._accept_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.listener:
            try:
                self.listener.close()
            except OSError:
                pass
        if self.thread:
            self.thread.join(timeout=2)

    def _accept_loop(self):
        while not self.stop_event.is_set():
            try:
                client, _address = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle_client, args=(client,), daemon=True).start()

    def _handle_client(self, client):
        transport = None
        try:
            transport = paramiko.Transport(client)
            transport.add_server_key(self.host_key)
            interface = RbmServerInterface(self.evse.password)
            transport.start_server(server=interface)
            while transport.is_active() and not self.stop_event.is_set():
                channel = transport.accept(timeout=1.0)
                if channel is None:
                    continue
                command = interface.wait_for_command(channel)
                if command is None:
                    channel.close()
                    continue
                threading.Thread(
                    target=self._handle_channel, args=(channel, command), daemon=True
                ).start()
        except Exception as exc:
            if not self.stop_event.is_set():
                print("[SIM] SSH client error: {}".format(exc), flush=True)
        finally:
            if transport:
                transport.close()
            try:
                client.close()
            except OSError:
                pass

    def _handle_channel(self, channel, command):
        try:
            if command.startswith("scp -f "):
                self._scp_get(channel, command)
                return
            if command.startswith("scp -t "):
                self._scp_put(channel, command)
                return
            status, stdout, stderr = self.processor.execute(command)
            if stdout:
                channel.sendall(stdout.encode("utf-8"))
            if stderr:
                channel.send_stderr(stderr.encode("utf-8"))
            channel.send_exit_status(status)
        except Exception as exc:
            try:
                channel.send_stderr("Simulator error: {}\n".format(exc).encode("utf-8"))
                channel.send_exit_status(1)
            except Exception:
                pass
        finally:
            channel.close()

    def _scp_get(self, channel, command):
        remote_path = self._scp_path(command)
        path = self.evse.resolve(remote_path)
        if not path.is_file():
            channel.sendall(b"\x01No such file\n")
            return
        _recv_exact(channel, 1)
        content = path.read_bytes()
        channel.sendall("C0644 {} {}\n".format(len(content), path.name).encode("utf-8"))
        _recv_exact(channel, 1)
        channel.sendall(content)
        channel.sendall(b"\x00")
        _recv_exact(channel, 1)
        channel.send_exit_status(0)

    def _scp_put(self, channel, command):
        destination = self.evse.resolve(self._scp_path(command))
        channel.sendall(b"\x00")
        header = _recv_line(channel)
        if not header.startswith(b"C"):
            raise ValueError("Unsupported SCP upload header: {!r}".format(header))
        parts = header[1:].decode("utf-8", errors="replace").strip().split(" ", 2)
        if len(parts) != 3:
            raise ValueError("Malformed SCP upload header")
        size = int(parts[1])
        channel.sendall(b"\x00")
        content = _recv_exact(channel, size)
        _recv_exact(channel, 1)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        channel.sendall(b"\x00")
        self.evse.append_log(ENERGY_LOG, "SCP upload to {}".format(self._scp_path(command)))
        channel.send_exit_status(0)

    @staticmethod
    def _scp_path(command):
        tokens = shlex.split(command)
        for marker in ("-f", "-t"):
            if marker in tokens:
                index = tokens.index(marker)
                if index + 1 < len(tokens):
                    return tokens[index + 1]
        raise ValueError("SCP path not found")


def _print_help():
    print("Commands: status | soc <0..100|none> | temps <t1> <t2> <t3> <t4>")
    print("          latency <seconds> | offline on|off | fail-next | reset | help | quit")


def _console(evse, server):
    _print_help()
    while True:
        try:
            raw = input("rbm-sim> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not raw:
            continue
        parts = raw.split()
        action = parts[0].lower()
        try:
            if action in ("quit", "exit"):
                break
            if action == "help":
                _print_help()
            elif action == "status":
                print(evse.status())
            elif action == "soc" and len(parts) == 2:
                with evse.lock:
                    evse.soc = None if parts[1].lower() == "none" else int(parts[1])
                    if evse.soc is not None and not 0 <= evse.soc <= 100:
                        raise ValueError("SoC must be between 0 and 100")
                    evse._write_logs()
                print("SoC updated.")
            elif action == "temps" and len(parts) == 5:
                values = [int(value) for value in parts[1:]]
                with evse.lock:
                    evse.temperatures = values
                    evse._write_logs()
                print("Temperatures updated.")
            elif action == "latency" and len(parts) == 2:
                value = float(parts[1])
                if value < 0:
                    raise ValueError("Latency cannot be negative")
                with evse.lock:
                    evse.latency = value
                print("Latency updated.")
            elif action == "offline" and len(parts) == 2 and parts[1].lower() in ("on", "off"):
                with evse.lock:
                    evse.offline = parts[1].lower() == "on"
                print("Offline mode updated.")
            elif action == "fail-next":
                with evse.lock:
                    evse.fail_next = True
                print("The next target command will fail.")
            elif action == "reset":
                evse.reset()
                print("Simulator reset.")
            else:
                print("Unknown command. Type help.")
        except ValueError as exc:
            print("Invalid value: {}".format(exc))
    server.stop()


def main():
    parser = argparse.ArgumentParser(description="RBM local SSH/SCP EVSE simulator")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=2222, type=int)
    parser.add_argument("--password", default="rbm-simulator")
    parser.add_argument(
        "--data-dir", default=str(Path(__file__).with_name("runtime") / "evse_fs")
    )
    parser.add_argument("--no-console", action="store_true")
    args = parser.parse_args()

    evse = SimulatedEvse(args.data_dir, args.password)
    host_key = Path(args.data_dir).parent / "host_key.pem"
    server = LocalSshServer(args.host, args.port, evse, host_key)
    server.start()
    print("RBM local EVSE simulator is running.")
    print("SSH endpoint: {}:{} | username: root | password: {}".format(args.host, args.port, args.password))
    print("State directory: {}".format(Path(args.data_dir).resolve()))
    if args.no_console:
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            server.stop()
    else:
        _console(evse, server)


if __name__ == "__main__":
    main()
