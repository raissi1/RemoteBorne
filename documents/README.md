# Remote Borne Manager (RBM)

Remote Borne Manager is a Windows Python application used to control IOTECHA chargers remotely over SSH and SCP through `plink.exe` and `pscp.exe`.

## Main features

- SSH connection management with reconnect handling
- `GridCodes` remote browser with file and folder navigation
- Remote editing with `Find`, `Save`, and `Save As`
- Hardened SCP upload and download flows
- PDF export from remote text files
- Copy to `GridCodes.properties` with optional service restart
- `Energy Manager PRO` with `P/Q` and `CosPhi` modes
- `Restart services`, `Reboot device`, and `Debug logs`
- `Network config` window
- Integrated SSH terminal with history and persistent `cd`
- Temperature and Battery SoC monitoring
- Full right-click context menu in the `GridCodes` browser

## Useful structure

```text
RemoteBorne/
├── config/
├── documents/
├── exports/
├── logs/
├── src/
│   ├── RemoteBorneManager.py
│   ├── ssh_manager.py
│   ├── ssh_queue.py
│   ├── energy_manager.py
│   ├── debug_logs.py
│   ├── network_config.py
│   └── open_help.py
├── tools/
│   ├── plink.exe
│   └── pscp.exe
└── imgs/
```

## Requirements

- Windows 10 or 11
- Python 3.10+
- `plink.exe` and `pscp.exe` available in `tools/`

Install dependencies:

```bash
pip install -r documents/requirements.txt
```

## Configuration

The main SSH configuration is stored in `config/config.ini`:

```ini
[SSH]
host = 192.168.1.100
username = root
password = myPassword
port = 22
```

And the app paths:

```ini
[PATHS]
remote_path = /etc/iotecha/configs/GridCodes
remote_file = GridCodes.properties
local_path = exports/GridCodes.properties
```

You can edit these values from the application:

- `Network` -> `Network config`

Important behavior:

- if the IP address or SSH credentials change, the application saves the config and restarts cleanly instead of trying a hot reconnect

## Launch

```bash
python src/RemoteBorneManager.py
```

## Current behavior highlights

### SSH and stability

- `SSHQueue` serializes critical remote commands
- SCP transfers use a dedicated lock
- queue logs use short readable labels
- transport failures correctly mark the session as disconnected

### GridCodes browser

Right-click on a file:

- `Edit`
- `Download`
- `Print`
- `Copy to GridCodes.properties`
- `Delete`

Right-click on a folder:

- `Delete`

### Monitoring

The `Temperature / Derating` panel shows:

- temperature
- Battery SoC

The `↻` button triggers a manual refresh of both values.

### Integrated terminal

Available from:

- `Terminal` -> `Open Terminal`

Features:

- history with `Up/Down`
- persistent `cd`
- `clear`
- `help`
- `rm`, `mv`, and `cp` forced with `-f`

Interactive commands intentionally blocked:

- `vim`
- `vi`
- `nano`
- `top`
- `htop`
- `less`
- `more`

## Known limits

- `Save` and `Save As` still share a very similar remote naming flow
- exact Battery SoC accuracy still needs to be revalidated on real hardware
- changing IP at runtime now restarts the application instead of attempting a direct hot reconnect

## Related documentation

- `documents/USER_GUIDE.md`
- `documents/PVAL_TEST_PLAN.md`
- `documents/PV_RBM_V8_Init.docx`

## Usage

Internal professional use.
