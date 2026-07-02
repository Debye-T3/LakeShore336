# Lake Shore 336 EPICS IOC

This repository contains a first-version EPICS IOC for a Lake Shore 336 temperature controller used at a beamline. It exposes `LS336:IDN`, canonical `LS336:Input:A:TEMP_RBV` through `LS336:Input:D:TEMP_RBV` readbacks, true aliases `LS336:ColdHead:TEMP_RBV` and `LS336:Sample:TEMP_RBV`, the read-only `LS336:Loop1:INPUT_RBV` control-input state, conservative Loop 1 setpoint/ramp/range commands plus matching readbacks, heater output, PID readbacks, communication state, and IOC error text.

For an operator-facing Chinese tutorial, see [`docs/operator_tutorial_zh.md`](docs/operator_tutorial_zh.md).

## Phase 1 IOC Scope

The EPICS IOC is the sole hardware connection owner in Phase 1. Direct Windows dashboards, the local web dashboard, and the portable ZIP package may only talk to hardware while the IOC is stopped. Stop the IOC before opening the direct Windows dashboard, the local web dashboard, or the portable packaged app against the same controller.

Phase 1 does not convert the existing logger into EPICS records. The logging, maintenance login, packaged offline app, and direct `CSET` workflow described in the dashboard sections below remain part of the separate Python applications, not the IOC.

For the IOC itself, the Phase 1 parser uses `OUTMODE? 1` only to publish the read-only `LS336:Loop1:INPUT_RBV` state. The EPICS IOC does not write `CSET` in Phase 1.

## Target Setup

- Host: Windows direct dashboard for operator use; Linux/WSL is optional for the EPICS IOC build.
- Instrument link: Lake Shore 336 USB presented as a serial port.
- Default serial device: `/dev/ttyUSB0`.
- Serial settings: 57600 baud, 7 data bits, odd parity, 1 stop bit.
- EPICS modules: EPICS Base, asyn, StreamDevice.
- PV prefix: `LS336:`.

Edit `configure/RELEASE.local` or pass macros at IOC start time if your EPICS module paths, PV prefix, or serial device differ.

## Windows Direct Dashboard

If the control computer must stay Windows-only, use the direct serial dashboard. This section describes the separate direct application, not the EPICS IOC. It talks to the Lake Shore 336 over a Windows COM port and does not require Linux, WSL, EPICS, `caget`, or `caput`.

The friendliest path is to double-click this file from the repository folder:

```bat
START_WINDOWS_DASHBOARD.bat
```

It checks Python, installs the required serial package from `requirements.txt`, starts the local web dashboard, and opens `http://127.0.0.1:8765`.

If you prefer commands, install Python 3 for Windows, then run:

```powershell
python -m pip install -r requirements.txt
python scripts\ls336_web_dashboard.py
```

The older Tk direct dashboard is still available:

```powershell
python scripts\ls336_direct_dashboard.py
```

In the dashboard, choose the Lake Shore COM port and click `Connect`. The panel reads the instrument directly and shows cold-head temperature, sample temperature, setpoint readback, ramp state, ramp rate, heater output, and communication status.

For controlled temperature changes, set `Ramp K/min` to a conservative value, set the target setpoint, then click `Apply`. The dashboard writes the Lake Shore ramp command before changing setpoints, so the controller handles the smooth K/min climb. In Windows Device Manager, the controller usually appears under `Ports (COM & LPT)` as a `COM` port such as `COM3`.

Command-line example:

```powershell
python scripts\ls336_direct_dashboard.py --port COM3
```

For a browser-based ARPES operator panel with demo mode, temperature trend plotting, heater-range control, PID readback, server-side CSV archiving, safety warnings, and English/Chinese labels, run:

```powershell
python scripts\ls336_web_dashboard.py
```

Then open `http://127.0.0.1:8765`. Choose `DEMO` to test without hardware, or choose the real Lake Shore serial port. The browser panel focuses on the controls normally needed during ARPES operation: cold-head temperature, sample-stage temperature, input A/B/C/D readback, cold/sample/control input selection, setpoint, ramp rate, heater range (`Off`, `Low`, `Medium`, `High`), PID readback values, and archived temperature logging. `Apply` writes the Lake Shore `CSET`, `RANGE`, `RAMP`, and `SETP` commands in one controlled update. Ordinary users can read PID values, but PID writes are only available in the maintenance page.

After `CONNECT` succeeds, the local Python service starts recording automatically. The ordinary operator page only shows recording status, current CSV filename, row count, and last write time, so experiment users do not need to remember to start logging and cannot accidentally stop it. Click `DOWNLOAD CSV` to retrieve the current archive file. The CSV is written by the local Python service, so it survives browser refreshes and is ready for experiment archiving. The static web demo can still download a temporary browser-only CSV, but only the local Python dashboard creates archived files.

Archive files use the Beijing-time daily pattern `ls336_temperature_YYYYMMDD.csv` and `ls336_temperature_YYYYMMDD.meta.json`. If maintenance explicitly creates a new file during the same Beijing-time day, the file gets a manual suffix such as `ls336_temperature_YYYYMMDD_manual_HHMMSS.csv`. CSV `timestamp_local` values and metadata local timestamps are written in `Asia/Shanghai`.

Maintenance controls are available at `http://127.0.0.1:8765/maintenance`. Set `LS336_MAINT_PASSWORD` before production use; otherwise the default maintenance password is `ls336-maint`. The maintenance page can pause/resume logging, create a new log file, download the current CSV, and perform controlled Loop 1 PID writes. PID writes require confirmation in the browser and are recorded in the metadata audit log with old and new values.

## Mac Browser Dashboard

On Mac, the friendliest path is to double-click this file from the repository folder:

```text
START_MAC_DASHBOARD.command
```

If macOS blocks the file because it is not executable yet, open Terminal in the repository folder and run:

```bash
chmod +x START_MAC_DASHBOARD.command scripts/run_web_dashboard_mac.sh
./START_MAC_DASHBOARD.command
```

The launcher checks Python, installs the required serial package from `requirements.txt`, starts the local web dashboard, and opens `http://127.0.0.1:8765`.

Manual command-line equivalent:

```bash
python3 -m pip install -r requirements.txt
python3 scripts/ls336_web_dashboard.py
```

## Share With Other People

There are two supported sharing modes:

### Public Demo Website

The static demo in `web/index.html` can be deployed to Vercel or any static web host. It does not connect to hardware; it simulates a Lake Shore 336 so collaborators can open the interface, test English/Chinese labels, heater range, PID readback values, safety warnings, and temporary browser CSV downloads.

## Build an offline Windows package

On a connected 64-bit Windows 10/11 build computer, run:

```bat
scripts\build_package.bat
```

The script installs/checks build dependencies, creates the PyInstaller application, runs an automated packaged DEMO control and Beijing-time logging smoke test, and writes `dist\LakeShore336_portable.zip`. Copy that ZIP to the offline Windows computer, extract it, and run `START.bat`. The target computer does not need Python, WSL, or internet access. Existing experiment files under the source `logs/` directory are never included in the package.

See `docs/offline_package_zh.md` for the Chinese deployment and second hardware-test procedure.

Vercel workflow:

1. Push this repository to GitHub.
2. In Vercel, import `Debye-T3/LakeShore336`.
3. Keep the default static deployment settings; `vercel.json` rewrites traffic to `web/index.html`.
4. Share the Vercel URL with collaborators.

### Real Instrument On The Lab Network

Run the browser dashboard on the computer physically connected to the Lake Shore 336:

```bash
python3 scripts/ls336_web_dashboard.py --host 0.0.0.0 --port 8765
```

Find that computer's local IP address:

```bash
ipconfig getifaddr en0
```

People on the same lab network can then open:

```text
http://<lab-computer-ip>:8765
```

Do not expose the real instrument control panel directly to the public internet. Use the Vercel site for public/demo access and the local-network dashboard for real hardware.

## VS Code and Codex

Open the repository in VS Code:

```bash
git clone https://github.com/Debye-T3/LakeShore336.git
cd LakeShore336
code .
```

If you are using Codex in VS Code, open the Codex side panel or command palette entry from the extension, then ask it to work in this repository. The included `.vscode/tasks.json` exposes the common IOC workflows through `Terminal` > `Run Task` or the command palette command `Tasks: Run Task`:

- `IOC: Python tests` runs the repository layout and regression tests, using pytest when installed and a lightweight fallback otherwise.
- `IOC: build` builds the EPICS IOC with `make`.
- `IOC: readiness check` verifies the expected build artifacts and client check commands.
- `IOC: run` starts the IOC and prompts for optional runtime macros such as `TTY=/dev/ttyS4` or `PREFIX=LS336_DEV:`.
- `IOC: dashboard` opens a visual temperature and control panel.
- `Windows: direct dashboard` opens the Windows serial dashboard without EPICS.

## Public PVs

| PV | Direction | Purpose |
| --- | --- | --- |
| `LS336:IDN` | read | Instrument identity from `*IDN?`. |
| `LS336:Input:A:TEMP_RBV` | read | Canonical Input A temperature readback. |
| `LS336:Input:B:TEMP_RBV` | read | Canonical Input B temperature readback. |
| `LS336:Input:C:TEMP_RBV` | read | Canonical Input C temperature readback. |
| `LS336:Input:D:TEMP_RBV` | read | Canonical Input D temperature readback. |
| `LS336:ColdHead:TEMP_RBV` | read alias | True EPICS alias of `LS336:Input:A:TEMP_RBV`. |
| `LS336:Sample:TEMP_RBV` | read alias | True EPICS alias of `LS336:Input:B:TEMP_RBV`. |
| `LS336:Loop1:INPUT_RBV` | read | Read-only Loop 1 control-input state parsed from `OUTMODE? 1`. |
| `LS336:Loop1:SETP` | write | Loop 1 setpoint command PV. |
| `LS336:Loop1:SETP_RBV` | read | Authoritative Loop 1 setpoint readback. |
| `LS336:Loop1:RAMP:ENABLE` | write | Loop 1 ramp-enable command PV. |
| `LS336:Loop1:RAMP:ENABLE_RBV` | read | Authoritative ramp-enable readback. |
| `LS336:Loop1:RAMP:RATE` | write | Loop 1 ramp-rate command PV. |
| `LS336:Loop1:RAMP:RATE_RBV` | read | Authoritative ramp-rate readback. |
| `LS336:Loop1:RANGE` | write | Loop 1 heater-range command PV. |
| `LS336:Loop1:RANGE_RBV` | read | Authoritative heater-range readback. |
| `LS336:Loop1:HTR_RBV` | read | Loop 1 heater output percentage. |
| `LS336:Loop1:PID:P_RBV` | read | Read-only Loop 1 PID proportional readback. |
| `LS336:Loop1:PID:I_RBV` | read | Read-only Loop 1 PID integral readback. |
| `LS336:Loop1:PID:D_RBV` | read | Read-only Loop 1 PID derivative readback. |
| `LS336:COMM:STATUS` | read | IOC communication summary. States are `Disconnected`, `Connected`, and `Error`. |
| `LS336:ERR` | read | Last IOC-side validation or communication message. |

## Phase 1 IOC Behavior

Startup sends queries only and never issues `SETP`, `RAMP`, or `RANGE`. All public output records use `PINI` = `NO`, so IOC boot cannot silently change hardware setpoints, ramp state, ramp rate, or heater range.

A successful command PV write only confirms IOC processing; it is not hardware confirmation. Independent readback PVs such as `LS336:Loop1:SETP_RBV`, `LS336:Loop1:RAMP:ENABLE_RBV`, `LS336:Loop1:RAMP:RATE_RBV`, and `LS336:Loop1:RANGE_RBV` are authoritative.

Changing `LS336:Loop1:RAMP:RATE` first queries `RAMP? 1` and preserves the current hardware enable bit. Changing `LS336:Loop1:RAMP:ENABLE` first queries `RAMP? 1` and preserves the current hardware rate. Each update is emitted as one locked StreamDevice transaction.

## Safety Limits

The public write PVs use conservative commissioning defaults:

- `LS336:Loop1:SETP` accepts `0..350 K`.
- `LS336:Loop1:RAMP:RATE` accepts `0..10 K/min`.
- `LS336:Loop1:RANGE` accepts `0..3`.
- Out-of-range writes are blocked by `SDIS` before StreamDevice sends any serial command.
- The integration tests check for zero serial output on rejected `SETP`, `RAMP`, and `RANGE` writes.

These limits are intended for first commissioning only. Tighten them for the actual sample, cryostat, and heater configuration before routine use.

## Build On Linux

This IOC is built from Linux. On a Mac, use an Ubuntu virtual machine if you need a Linux runtime. On Windows, WSL works too; WSL does not need a Linux desktop, and Windows drives are mounted under `/mnt`.

Install the Linux build dependencies in Ubuntu or another Debian-like Linux:

```bash
sudo apt update
sudo apt install -y build-essential git perl libreadline-dev libncurses-dev re2c wget tar libtirpc-dev libpcre3-dev python3 python3-tk
```

Then run the setup script from Linux. It downloads and builds EPICS Base, asyn, and StreamDevice under `/opt/epics`, then writes `configure/RELEASE.local` for this IOC:

```bash
bash scripts/setup_epics_wsl.sh
```

If WSL cannot reach GitHub, download these archives in Windows and place them under `D:\Projects\LakeShore336\downloads`; the setup script will automatically use them instead of cloning:

```text
downloads/epics-base-R7.0.8.1.tar.gz
downloads/asyn-R4-44.tar.gz
downloads/StreamDevice-2.8.24.tar.gz
```

The script uses these defaults, which can be overridden with environment variables before running it:

```make
EPICS_BASE=/opt/epics/base
ASYN=/opt/epics/support/asyn
STREAM=/opt/epics/support/StreamDevice
```

Build the IOC and run the readiness check:

```bash
bash scripts/run_tests.sh
make
bash scripts/check_ioc_ready.sh
```

Useful Phase 1 verification commands:

- `pytest -q`
- `make`
- `bash scripts/run_tests.sh --ioc-integration`
- `wsl -d Ubuntu-24.04 -- bash -lc 'cd /mnt/d/Projects/LakeShore336 && bash scripts/run_tests.sh --ioc-integration'`

The PTY shim is test-only; production `iocBoot/iocLS336/st.cmd` keeps the real controller at `57600 7O1`.

## Run On Linux

This IOC should be run from Linux. On a Mac, use an Ubuntu virtual machine if you need a Linux runtime. The build no longer assumes only `linux-x86_64`; it uses the EPICS host architecture produced by your Linux environment.

The setup script intentionally builds only the asyn and StreamDevice core libraries needed by this IOC. It skips bundled test/example applications that require extra synApps modules or duplicate link settings. On Ubuntu, asyn is configured with `libtirpc-dev`, and StreamDevice is configured to use the system PCRE library from `libpcre3-dev`.

Start with the default serial device:

```bash
bash scripts/run_ioc.sh
```

Override the serial device or PV prefix when needed:

The startup should recognize `drvAsynSerialPortConfigure`. If it does not, rebuild after confirming `ls336App/src/Makefile` includes `drvAsynSerialPort.dbd`.

```bash
TTY=/dev/ttyUSB0 bash scripts/run_ioc.sh
PREFIX=LS336_DEV: TTY=/dev/ttyUSB0 bash scripts/run_ioc.sh
```

## EPICS Client Checks

Read identity, canonical temperatures, aliases, and communication state:

```bash
caget LS336:IDN
caget LS336:Input:A:TEMP_RBV
caget LS336:Input:B:TEMP_RBV
caget LS336:Input:C:TEMP_RBV
caget LS336:Input:D:TEMP_RBV
caget LS336:ColdHead:TEMP_RBV
caget LS336:Sample:TEMP_RBV
caget LS336:Loop1:INPUT_RBV
caget LS336:COMM:STATUS
```

## Hardware Commissioning Checklist

1. Confirm query-only startup and the basic readback path.

```bash
caget LS336:IDN
caget LS336:Input:A:TEMP_RBV
caget LS336:Input:B:TEMP_RBV
caget LS336:Input:C:TEMP_RBV
caget LS336:Input:D:TEMP_RBV
caget LS336:ColdHead:TEMP_RBV
caget LS336:Sample:TEMP_RBV
caget LS336:Loop1:INPUT_RBV
caget LS336:COMM:STATUS
```

2. Send a safe setpoint and verify the authoritative readback.

```bash
caput LS336:Loop1:SETP 300
caget LS336:Loop1:SETP_RBV
```

3. Enable ramping, set a conservative rate, and verify each command via the matching RBV.

```bash
caput LS336:Loop1:RAMP:ENABLE 1
caput LS336:Loop1:RAMP:RATE 1
caget LS336:Loop1:RAMP:ENABLE_RBV
caget LS336:Loop1:RAMP:RATE_RBV
```

4. Set a cautious heater range, then check the range and heater-output readbacks. Use `Low` or `Off` until heater commissioning says otherwise.

```bash
caput LS336:Loop1:RANGE 1
caget LS336:Loop1:RANGE_RBV
caget LS336:Loop1:HTR_RBV
```

5. If the serial link drops, confirm `LS336:COMM:STATUS`, reconnect the USB/serial path, and wait for the authoritative RBVs to recover before sending another command.

6. Keep the direct apps separate from the IOC. The direct Windows dashboard, browser dashboard, and portable ZIP can still be useful for their own workflows, including logging, but only while the IOC is stopped.

## Visual Dashboard

After the IOC is running and EPICS client commands are in `PATH`, open the dashboard:

```bash
python3 scripts/ls336_dashboard.py
```

The dashboard shows cold-head and sample temperatures, communication status, setpoint, ramp state, ramp rate, and heater output. Use `--prefix` if you started the IOC with a different PV prefix:

```bash
python3 scripts/ls336_dashboard.py --prefix LS336_DEV:
```

Set a safe Loop 1 target and ramp:

```bash
caput LS336:Loop1:SETP 300
caput LS336:Loop1:RAMP:ENABLE 1
caput LS336:Loop1:RAMP:RATE 1
```

Confirm readbacks:

```bash
caget LS336:Loop1:SETP_RBV
caget LS336:Loop1:RAMP:ENABLE_RBV
caget LS336:Loop1:RAMP:RATE_RBV
caget LS336:Loop1:HTR_RBV
```

## Windows to WSL Serial Notes

On Windows, confirm which COM port appears after plugging in the Lake Shore 336. In WSL, that port may appear as `/dev/ttyS<N>` or may need USB/IP forwarding depending on Windows and WSL versions. Once visible in WSL, pass it as a `TTY` environment macro before launching the IOC, or set the same value when running the `IOC: run` VS Code task.

Check visible serial devices from WSL:

```bash
ls /dev/ttyUSB*
ls /dev/ttyS*
```

Use the actual device when starting the IOC:

```bash
TTY=/dev/ttyS4 bash scripts/run_ioc.sh
```

## WSL Troubleshooting

If `wsl --install -d Ubuntu-24.04` fails with:

```text
Wsl/InstallDistro/Service/RegisterDistro/CreateVm/HCS/0x80070001
```

run the Windows diagnostics script:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\diagnose_wsl_windows.ps1
```

Check `wsl-diagnostics.log`. If it shows `VirtualizationFirmwareEnabled=False`, enable CPU virtualization in BIOS/UEFI first. For Intel CPUs this is usually named `Intel Virtualization Technology`, `VT-x`, or `Intel VT`; for AMD CPUs it is usually `SVM Mode`. After saving BIOS changes and booting Windows again, rerun:

```powershell
wsl --install -d Ubuntu-24.04
```
