# RBM V10 - Revalidation Test Plan

## Goal

This document is a short guide for replaying the most sensitive scenarios after the major `RBM V10` fixes and packaging updates.

## 1. Items already addressed in V10

- UI freezes around `refresh`, `download`, `print`, `upload`, and editor flows
- serialization of critical remote commands through `SSHQueue`
- explicit SCP timeouts
- restoration of the integrated SSH terminal
- restoration of the full `GridCodes` context menu
- fix for the `Energy Manager PRO` window sizing
- clean application restart after IP / SSH changes in `Network config`
- cleaner handling of debug log popups and auxiliary windows
- updated project documents and harmonized delivery names

## 2. Revalidation priorities

1. SSH stability and reconnect behavior
2. editing, upload, and print flows
3. `Energy Manager PRO`
4. integrated SSH terminal
5. temperature and Battery SoC monitoring
6. consistency between code features and delivered documentation

## 3. High-priority test cases

### T13 - Automatic reconnect

- Preconditions: active SSH session
- Steps:
  1. simulate a network interruption
  2. restore the network
- Expected:
  - reconnect attempts are visible
  - the app returns to `Connected` if the target becomes reachable again

### T14 - Runtime IP change

- Steps:
  1. open `Network config`
  2. modify the IP address or SSH settings
  3. save
- Expected:
  - configuration is saved
  - the application restarts cleanly
  - reconnect is possible to the new target after relaunch

### T30 - Editing and save

- Steps:
  1. open a remote file
  2. modify the content
  3. trigger `Save`
- Expected:
  - content uploads without UI blocking
  - line endings are normalized

### T31 / T31B - Download / Upload

- Expected:
  - no UI freeze during transfer
  - transfer completes successfully
  - upload path performs a final remote size check

### T32 - PDF print

- Expected:
  - local PDF is generated
  - text remains readable
  - proposed file name matches the source file

### T40 / T42 - Energy Manager

- Expected:
  - `P/Q` send works
  - `CosPhi` send works
  - logs remain short and readable

### T60 - Debug logs

- Expected:
  - the window opens successfully
  - logs are followed without blocking popups

### T61 / T62 - Temperature / Battery SoC

- Expected:
  - manual refresh works through `Refresh`
  - temperature is displayed
  - Battery SoC is displayed

### T79 - SSH terminal GUI

- Steps:
  1. open `Terminal -> Open Terminal`
  2. test `ls`, `pwd`, and `cd`
  3. test `Up/Down` history
- Expected:
  - commands execute correctly
  - `cd` remains persistent
  - no UI freeze

### T89 - Blocked interactive commands

- Steps:
  1. open the terminal
  2. type `vim`
  3. type `nano`
- Expected:
  - clean error message
  - no interactive program starts
  - the application remains responsive

## 4. Remaining points to watch

- Battery `SoC` accuracy versus the real vehicle value
- long-duration behavior over several hours
- rapid multi-action scenarios when an editor is already open
- final validation of all customer-facing documents against the packaged `V10` build

## 5. Exit criteria

- no UI blocking on critical workflows
- terminal and help stay consistent with the visible features
- user guide, validation plan, and packaged document names are aligned
- three consecutive runs without major regression on the priority cases
