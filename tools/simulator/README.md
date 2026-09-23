# RBM Local EVSE Simulator

This developer-only tool simulates an EVSE over real SSH and SCP. RBM connects
to it through the same Plink and PSCP executables used for a physical charger.
It does not modify the RBM application or send any command to real equipment.

## Start

From the project root, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\simulator\start_rbm_simulator.ps1
```

Keep the simulator window open. Its command prompt controls the simulated EVSE.

## RBM Network Configuration

Configure RBM with the following values, then save and connect:

| Field | Value |
| --- | --- |
| IP address | `127.0.0.1` |
| Port | `2222` |
| Username | `root` |
| Password | `rbm-simulator` |
| Remote path | `/etc/iotecha/configs/GridCodes` |
| Remote file | `GridCodes.properties` |
| Local path | Your normal RBM export folder |

On the first connection, RBM can ask to confirm the local simulator host key.
Confirm it only when the simulator console is running on the same PC.

## What Can Be Tested

- SSH connection, reconnect, host-key confirmation and manual disconnect.
- File listing, `Go`, `Up`, `Root`, download, upload, edit, delete and GridCode copy.
- P/Q and CosPhi setpoints, with simulated confirmation responses.
- Temperature and SoC refresh from simulated charger logs.
- Debug log windows, restart services and reboot command flows.
- Slow or failed target responses without using a physical EVSE.

## Simulator Commands

| Command | Effect |
| --- | --- |
| `status` | Display current simulator state. |
| `soc 80` | Set the simulated SoC from 0 to 100. |
| `soc none` | Simulate a charger log without an available SoC. |
| `temps 42 42 43 43` | Set relay temperatures T1 to T4. |
| `latency 2` | Add two seconds to every target command. |
| `offline on` | Make target commands fail as if the EVSE became unavailable. |
| `offline off` | Restore normal target responses. |
| `fail-next` | Make the next target command fail. |
| `reset` | Restore demo files and default telemetry. |
| `help` | Display this command list. |
| `quit` | Stop the simulator. |

All generated files, telemetry and the local SSH host key are stored under
`tools/simulator/runtime/`. This directory is excluded from Git. Delete it to
start with a fresh simulated EVSE, including a new SSH host key.

## Safety Boundary

The simulator validates RBM client behaviour only. It does not validate the
actual charger firmware, electrical safety, GridCode compliance, OCPP behaviour
or Energy Manager execution on a real EVSE.
