# Remote Borne Manager - User Guide

## 1. Startup

Launch the application:

```bash
python src/RemoteBorneManager.py
```

Or use the packaged executable if it has already been built.

## 2. SSH connection

- `Connect`: opens the SSH session and initializes the remote UI
- `Disconnect`: closes the session and prevents an immediate automatic reconnect
- connection state is visible in the logs and through the status indicator

If the network drops, the application may attempt an automatic reconnect. If the IP address or SSH settings are changed from `Network config`, the application restarts cleanly.

## 3. GridCodes browser

The main browser displays the remote directory configured in `PATHS.remote_path`.

Navigation:

- double-click a folder to enter it
- double-click `[.] (Parent)` to go back up
- the `Path` field shows the current remote directory
- `Refresh` reloads the remote listing

## 4. GridCodes context menu

Right-click on a file:

- `Edit`
- `Download`
- `Print`
- `Copy to GridCodes.properties`
- `Delete`

Right-click on a folder:

- `Delete`

Notes:

- deletion always asks for confirmation
- `Copy to GridCodes.properties` may offer to restart services afterward

## 5. Remote file editing

From `Edit`:

- `Find` opens local search inside the editor
- `Save` overwrites the current remote file
- `Save As` uploads the content to a new remote target name or full path
- line endings are normalized to `LF`
- edit authentication can be requested before the editor opens

Useful shortcuts:

- `Ctrl+F`: search
- `Escape`: clear highlight
- `Ctrl+W`: close the editor

## 6. Download, upload, print

### Download

- copies the remote file to a local destination
- runs in the background to avoid UI freezing

### Upload

- sends a local file to the current remote folder
- performs a final remote size check

### Print

- downloads the remote file
- generates a readable local PDF
- proposes a default name derived from the source file

## 7. Energy Manager PRO

Open:

- `Energy` -> `Energy Manager PRO`

Features:

- `P/Q` mode
- `CosPhi` mode
- command history
- `Monitor Energy Manager` panel

### P/Q mode

- enter `Active Power P`
- enter `Reactive Power Q`
- click `Send P/Q`

### CosPhi mode

- enter `Active Power P`
- enter `CosPhi`
- use `Calculate Q` if needed
- click `Send CosPhi`

## 8. Maintenance

Available from the menu or buttons:

- `Restart services`
- `Reboot device`
- `Debug logs`

### Restart services

- restarts the target services on the charger
- uses a longer SSH timeout

### Reboot device

- asks for confirmation
- sends the remote reboot command

### Debug logs

- opens the remote log window
- follows logs without unnecessary blocking popups

## 9. Temperature / Battery SoC monitoring

The `Temperature / Derating` panel shows:

- board temperature
- Battery SoC

The `Refresh` button triggers an immediate manual refresh.

## 10. Network config

The `Network config` window lets you change:

- host / IP
- username
- password
- port
- `remote_path`
- `remote_file`
- `local_path`
- edit password

Current behavior:

- if only paths or the edit password change, they are reloaded directly
- if IP, port, or credentials change, the application restarts after saving

## 11. Integrated SSH terminal

Open:

- `Terminal` -> `Open Terminal`

Features:

- history with `Up/Down`
- persistent `cd`
- `clear`
- `help`
- execution of simple shell commands
- execution of Python and shell scripts

Typical commands:

```bash
ls
pwd
cd /var/aux/EnergyManager
cat file.txt
python3 script.py
sh restart.sh
```

Unsupported interactive commands:

- `vim`
- `vi`
- `nano`
- `top`
- `htop`
- `less`
- `more`

For safety and UI consistency:

- `rm`, `mv`, and `cp` are forced with `-f`

## 12. Quick troubleshooting

### Host key / Plink

If `plink` reports a host key error in batch mode:

- make sure you are targeting the correct charger
- clear the cached PuTTY key for that IP if required
- reconnect only after validating the new host key fingerprint

### Temperature or Battery SoC not updating

- confirm the SSH session is still active
- use the `Refresh` button
- check the application logs

### IP address change

- save the new values in `Network config`
- let the application restart
- reconnect to the new target

### Energy Manager PRO

- if a button still appears hidden, make sure you are running a version that includes the latest window sizing fixes

## 13. Known points

- Battery `SoC` depends on the latest valid value available in charger logs and current vehicle activity
- some long-duration and rapid multi-action scenarios still need to be rerun on real hardware after infrastructure changes
- if the SSH host key changes, reconnecting still requires standard trust verification on the target IP
