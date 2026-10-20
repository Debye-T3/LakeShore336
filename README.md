# Lake Shore 336 EPICS IOC

This repository contains an EPICS IOC and Python clients for a Lake Shore 336 temperature controller used at a beamline. The IOC owns the serial connection and provides Channel Access readbacks, validated controls, grouped APPLY/PID operations, and archive-command/status PVs. The browser dashboard is a CA client and writes CSV files; it does not open the instrument serial port.

For an operator-facing Chinese tutorial, see [`docs/operator_tutorial_zh.md`](docs/operator_tutorial_zh.md).

## IOC and Python Client Roles

Start the IOC first. It is the only process that opens the controller's serial port. The Web dashboard connects to an IOC PV prefix such as `LS336:` over Channel Access. Do not start the direct-serial fallback while the IOC owns the instrument.

The IOC performs `CSET`, `RANGE`, `RAMP`, `SETP`, and PID serial transactions. Python controls those IOC PVs and runs the two-second CSV archive worker. IOC `LOG:*` PVs let another approved CA client start, pause, resume, or rotate that archive and inspect its status and heartbeat.

The standalone `scripts/ls336_direct_dashboard.py` remains a direct-serial fallback for use only while the IOC is stopped.

## Target Setup

- Host: Linux/WSL IOC host and a Python dashboard host on the same subnet, or connected through a site-configured CA address list/Gateway.
- Instrument link: Lake Shore 336 USB presented as a serial port.
- Default serial device: `/dev/ttyUSB0`.
- Serial settings: 57600 baud, 7 data bits, odd parity, 1 stop bit.
- EPICS modules: EPICS Base, asyn, StreamDevice.
- PV prefix: `LS336:`.

Edit `configure/RELEASE.local` or pass macros at IOC start time if your EPICS module paths, PV prefix, or serial device differ.

## Windows EPICS Web Dashboard

Start the IOC on the computer that can access the Lake Shore serial device. Then on Windows, run the Web dashboard as an EPICS client. Install Python 3 and the listed Python packages:

The friendliest path is to double-click this file from the repository folder:

```bat
START_WINDOWS_DASHBOARD.bat
```

It installs the Channel Access client dependency, starts the local Web dashboard, and opens `http://127.0.0.1:8765`. Set `LS336_PREFIX` before launch if the IOC uses another prefix.

If you prefer commands, install Python 3 for Windows, then run:

```powershell
python -m pip install -r requirements.txt
python scripts\ls336_web_dashboard.py --prefix LS336:
```

In the dashboard, enter the IOC PV prefix and click `Connect`. Enter `DEMO` to use the simulator without an IOC. The `Apply` button sends the staged control input, setpoint, ramp rate, and heater range to the grouped IOC APPLY operation. `_RBV` PVs remain authoritative.

The separate direct-serial fallback is still available when the IOC is stopped:

```powershell
python scripts\ls336_direct_dashboard.py
```

For a specific Windows COM port, use:

```powershell
python scripts\ls336_direct_dashboard.py --port COM3
```

The browser panel retains input mapping, trend and safety displays, heater-range control, PID readback, and maintenance operations. The IOC separately controls its instrument input with `Loop1:INPUT_RBV`; the Python cold-head/sample mapping only selects which temperature is displayed and archived.

After an EPICS connection succeeds, a Python archive worker starts and writes the first row immediately, then samples every two seconds even if the browser is closed. It subscribes to IOC PV timestamps and alarms; stale or alarmed fields are left blank rather than repeated as fresh measurements. IOC `LOG:START`, `LOG:PAUSE`, `LOG:RESUME`, and `LOG:NEW_FILE` commands control the same archive. `LOG:HEARTBEAT` lets the UI show when the worker stops updating. Click `DOWNLOAD CSV` to retrieve the current file. A static demo still uses a temporary browser-only CSV.

Archive files use the Beijing-time daily pattern `ls336_temperature_YYYYMMDD.csv` and `ls336_temperature_YYYYMMDD.meta.json`. If maintenance explicitly creates a new file during the same Beijing-time day, the file gets a manual suffix such as `ls336_temperature_YYYYMMDD_manual_HHMMSS.csv`. CSV `timestamp_local` values and metadata local timestamps are written in `Asia/Shanghai`.

Maintenance controls are available at `http://127.0.0.1:8765/maintenance`. Set `LS336_MAINT_PASSWORD` before production use; otherwise the default maintenance password is `ls336-maint`. The page can pause/resume logging, create a new file, download the current CSV, and apply PID values through the IOC's maintenance PVs. PID writes require browser confirmation and record old/new values in metadata. EPICS access security must also grant the dashboard user the required `MAINT`, `LOG_CONTROL`, and `ARCHIVER` permissions.

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

The launcher checks Python, installs Channel Access client packages, starts the local Web dashboard, and opens `http://127.0.0.1:8765`. The IOC must be running first; set `LS336_PREFIX` if needed.

Manual command-line equivalent:

```bash
python3 -m pip install -r requirements.txt
python3 scripts/ls336_web_dashboard.py --prefix LS336:
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

The script packages the Web dashboard and its caproto Channel Access client, runs its existing packaged DEMO smoke check, then writes `dist\LakeShore336_portable.zip`. Copy that ZIP to the Windows computer, extract it, and run `START.bat`. The target computer does not need Python or internet access, but it does need network access to a running IOC. Set `LS336_PREFIX` before launch when the IOC uses a non-default prefix. The direct-serial fallback is a separate application and is not part of the IOC-backed package. Existing experiment files under the source `logs/` directory are never included in the package.

See `docs/offline_package_zh.md` for Chinese deployment instructions.

Vercel workflow:

1. Push this repository to GitHub.
2. In Vercel, import `Debye-T3/LakeShore336`.
3. Keep the default static deployment settings; `vercel.json` rewrites traffic to `web/index.html`.
4. Share the Vercel URL with collaborators.

### Real Instrument On The Lab Network

Run the IOC on the computer with serial access to the Lake Shore 336. Run one Python dashboard/archive service for that IOC on a designated host with Channel Access connectivity:

```bash
LS336_PREFIX=LS336: python3 scripts/ls336_web_dashboard.py --port 8765
```

The Web server binds to `127.0.0.1` by default; open the dashboard on the same computer at `http://127.0.0.1:8765`. Keep one archive service active for an IOC because that process owns the CSV files and publishes the shared log-status PVs.

Other approved control systems can connect directly to the IOC PVs under their scoped CA access rules. Browser requests to a remotely exposed dashboard use the dashboard service's CA identity, so remote Web access requires site-approved HTTP authentication and network restrictions. Keep the default loopback binding until those controls are in place. CA discovery normally works on one subnet; for other subnets, the site EPICS administrator must configure CA address lists or a Gateway and the corresponding network access rules. Use the Vercel site for public/demo access.

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
| `LS336:Loop1:INPUT` | write | Selects Loop 1 control input with an exact numeric code: `1=A`, `2=B`, `3=C`, `4=D`; IOC validates before `CSET`. |
| `LS336:Loop1:CTRL:INPUT/SETP/RAMP:RATE/RANGE` | write | Staged values for a validated grouped control operation. Input uses numeric codes A=1 through D=4; range uses exact integers 0=Off through 3=High. |
| `LS336:Loop1:CTRL:APPLY` | write | Sends CSET, RANGE, RAMP, and SETP in order, then refreshes readbacks. |
| `LS336:Loop1:CTRL:STATUS/BUSY/ERROR` | read | Grouped command progress and failure summary. |
| `LS336:Loop1:SETP` | write | Loop 1 setpoint command PV. |
| `LS336:Loop1:SETP_RBV` | read | Authoritative Loop 1 setpoint readback. |
| `LS336:Loop1:RAMP:ENABLE` | write | Numeric ramp-enable command: exactly `0` or `1`. |
| `LS336:Loop1:RAMP:ENABLE_RBV` | read | Authoritative ramp-enable readback with `Off`/`On` labels. |
| `LS336:Loop1:RAMP:RATE` | write | Loop 1 ramp-rate command PV. |
| `LS336:Loop1:RAMP:RATE_RBV` | read | Authoritative ramp-rate readback. |
| `LS336:Loop1:RANGE` | write | Numeric heater-range command: exactly `0`, `1`, `2`, or `3`. |
| `LS336:Loop1:RANGE_RBV` | read | Authoritative heater-range readback with `Off`/`Low`/`Medium`/`High` labels. |
| `LS336:Loop1:HTR_RBV` | read | Loop 1 heater output percentage. |
| `LS336:Loop1:PID:P_RBV` | read | Read-only Loop 1 PID proportional readback. |
| `LS336:Loop1:PID:I_RBV` | read | Read-only Loop 1 PID integral readback. |
| `LS336:Loop1:PID:D_RBV` | read | Read-only Loop 1 PID derivative readback. |
| `LS336:Loop1:PID:P/I/D` | MAINT write | Staged PID values; written to the controller only by `PID:APPLY`. |
| `LS336:Loop1:PID:APPLY/STATUS/ERROR` | MAINT write/read | Applies P/I/D together and reports completion. |
| `LS336:Loop1:PID:P_OLD_RBV/I_OLD_RBV/D_OLD_RBV` | read | Values queried immediately before the last PID apply. |
| `LS336:LOG:START/PAUSE/RESUME/NEW_FILE` | LOG_CONTROL write | Commands the Python CSV archive worker. Each pulse is acknowledged back to zero. |
| `LS336:LOG:STATE_RBV/FILE_RBV/ROWS_RBV/LAST_WRITE_RBV/ERROR_RBV` | ARCHIVER write/read | Archive status published by the Python service. |
| `LS336:LOG:HEARTBEAT` | ARCHIVER write/read | Counter updated by the archive worker; stops changing if it exits. |
| `LS336:COMM:STATUS` | read | IOC communication summary. States are `Disconnected`, `Connected`, and `Error`. |
| `LS336:ERR` | read | Last IOC-side validation or communication message. |

## IOC Control and Access Behavior

Startup sends queries only and never issues `CSET`, `SETP`, `RAMP`, `RANGE`, or `PID`. All hardware write records use `PINI` = `NO`, so IOC boot cannot change controller settings. The grouped control APPLY validates and freezes the requested values, sends the four instrument commands in the tested order, then refreshes readbacks; on failure, it reports protocol/alarm state and actual readbacks without claiming rollback.

A successful command PV write only confirms IOC processing; it is not hardware confirmation. Independent readback PVs such as `LS336:Loop1:SETP_RBV`, `LS336:Loop1:RAMP:ENABLE_RBV`, `LS336:Loop1:RAMP:RATE_RBV`, and `LS336:Loop1:RANGE_RBV` are authoritative.

Ramp enable, heater range, and control-input commands use raw numeric PVs so validation sees the client's original value before any enum coercion. Control input uses codes 1=A through 4=D; range uses exact integers 0=Off through 3=High. Display labels remain on the authoritative `_RBV` records.

Changing `LS336:Loop1:RAMP:RATE` first queries `RAMP? 1` and preserves the current hardware enable bit. Changing `LS336:Loop1:RAMP:ENABLE` first queries `RAMP? 1` and preserves the current hardware rate. PID P/I/D are staged and sent together with one `PID` command. The Python dashboard applies a 22-second freshness limit to PID values because those IOC readbacks scan every 10 seconds; other archive fields use a 6-second limit.

`iocBoot/iocLS336/access.acf` defines separate `CONTROL`, `MAINT`, `LOG_CONTROL`, and `ARCHIVER` groups. It grants reads only until the site installs approved CA user/host rules. For deployment, define site-owned `UAG` and `HAG` entries and add a scoped `RULE(1,WRITE)` to the relevant `ASG`; keep `RULE(1,READ)` for monitoring. The Python archiver account needs both `LOG_CONTROL` and `ARCHIVER` write access. Do not add broad default write rules or invent account names/host addresses in the generic IOC configuration. See the [EPICS ACF language reference](https://docs.epics-controls.org/projects/base/en/latest/ACF-Language.html).

## Safety Limits

The public write PVs use conservative commissioning defaults:

- `LS336:Loop1:SETP` accepts `0..350 K`.
- `LS336:Loop1:RAMP:ENABLE` accepts exactly `0` or `1`.
- `LS336:Loop1:RAMP:RATE` accepts `0..10 K/min`.
- `LS336:Loop1:RANGE` accepts exactly `0`, `1`, `2`, or `3`.
- `LS336:Loop1:INPUT` and `LS336:Loop1:CTRL:INPUT` accept exact integers 1=A through 4=D; grouped setpoint/ramp/range values follow the same limits.
- PID apply accepts P `0.1..1000`, I `0.1..1000`, and D `0..200`.
- Out-of-range, fractional discrete staging values, and non-finite writes are rejected before StreamDevice sends any serial command.
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

Useful IOC verification commands:

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

6. Keep direct-serial tools separate from the IOC. The IOC-backed Web dashboard and portable package use Channel Access and run while the IOC is active; the direct Windows serial dashboard is only for use while the IOC is stopped.

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
