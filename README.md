# Lake Shore 336 EPICS IOC

This repository contains a first-version EPICS IOC for a Lake Shore 336 temperature controller used at a beamline. It exposes readback PVs for the cold head and sample temperatures, plus conservative Loop 1 setpoint, ramp, and stepwise warmup controls for higher-level clients and a small visual dashboard.

## Target Setup

- Host: Linux. On macOS, run Linux in an Ubuntu virtual machine.
- Instrument link: Lake Shore 336 USB presented as a serial port.
- Default serial device: `/dev/ttyUSB0`.
- Serial settings: 57600 baud, 7 data bits, odd parity, 1 stop bit.
- EPICS modules: EPICS Base, asyn, StreamDevice.
- PV prefix: `LS336:`.

Edit `configure/RELEASE.local` or pass macros at IOC start time if your EPICS module paths, PV prefix, or serial device differ.

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
- `IOC: dashboard` opens a visual temperature and warmup control panel.

## Public PVs

| PV | Direction | Purpose |
| --- | --- | --- |
| `LS336:ColdHead:TEMP_RBV` | read | Input A temperature, mapped to cold head temperature. |
| `LS336:Sample:TEMP_RBV` | read | Input B temperature, mapped to sample-side temperature. |
| `LS336:Loop1:SETP` | write | Requested Loop 1 setpoint in K. Limited to 350 K. |
| `LS336:Loop1:SETP_RBV` | read | Loop 1 setpoint read back from the controller. |
| `LS336:Loop1:WARMUP:TARGET` | write | Stepwise warmup target in K. Limited to 350 K. |
| `LS336:Loop1:WARMUP:STEP` | write | Step size for warmup moves, for example 5 K or 10 K. |
| `LS336:Loop1:WARMUP:STEP:5K` | write | Processes a 5 K warmup step preset into `WARMUP:STEP`. |
| `LS336:Loop1:WARMUP:STEP:10K` | write | Processes a 10 K warmup step preset into `WARMUP:STEP`. |
| `LS336:Loop1:WARMUP:NEXT` | write | Processes one warmup step toward the target by writing `Loop1:SETP`. |
| `LS336:Loop1:RAMP:ENABLE` | write | Enable or disable Loop 1 ramping. |
| `LS336:Loop1:RAMP:ENABLE_RBV` | read | Ramp enable state read back from the controller. |
| `LS336:Loop1:RAMP:RATE` | write | Requested Loop 1 ramp rate in K/min. Limited to 5 K/min. |
| `LS336:Loop1:RAMP:RATE_RBV` | read | Loop 1 ramp rate read back from the controller. |
| `LS336:Loop1:HTR_RBV` | read | Loop 1 heater output percentage. |
| `LS336:COMM:STATUS` | read | IOC communication status. |
| `LS336:ERR` | read | Last IOC-side validation or communication message. |

## Safety Limits

The public write PVs use conservative defaults:

- `LS336:Loop1:SETP` is limited to `350 K`.
- `LS336:Loop1:WARMUP:TARGET` is limited to `350 K`.
- `LS336:Loop1:WARMUP:STEP` is limited to `50 K` and defaults to `5 K`.
- `LS336:Loop1:RAMP:RATE` is limited to `5 K/min`.
- The database includes `validate_setpoint` and `validate_ramp_rate` calculation records so limit behavior is explicit in the IOC database.

These limits are intended for first commissioning only. Tighten them for the actual sample, cryostat, and heater configuration before routine use.

## Build On Linux

Install the Linux build dependencies in Ubuntu or another Debian-like Linux:

```bash
sudo apt update
sudo apt install -y build-essential git perl libreadline-dev libncurses-dev re2c wget tar python3 python3-tk
```

Then run the setup script from Linux. It downloads and builds EPICS Base, asyn, and StreamDevice under `/opt/epics`, then writes `configure/RELEASE.local` for this IOC:

```bash
bash scripts/setup_epics_wsl.sh
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

## Run On Linux

This IOC should be run from Linux. On a Mac, use an Ubuntu virtual machine if you need a Linux runtime. The build no longer assumes only `linux-x86_64`; it uses the EPICS host architecture produced by your Linux environment.

Start with the default serial device:

```bash
bash scripts/run_ioc.sh
```

Override the serial device or PV prefix when needed:

```bash
TTY=/dev/ttyUSB0 bash scripts/run_ioc.sh
PREFIX=LS336_DEV: TTY=/dev/ttyUSB0 bash scripts/run_ioc.sh
```

## EPICS Client Checks

Read both temperature channels:

```bash
caget LS336:IDN
caget LS336:ColdHead:TEMP_RBV
caget LS336:Sample:TEMP_RBV
caget LS336:COMM:STATUS
```

## Visual Dashboard

After the IOC is running and EPICS client commands are in `PATH`, open the dashboard:

```bash
python3 scripts/ls336_dashboard.py
```

The dashboard shows cold-head and sample temperatures, communication status, setpoint, ramp state, ramp rate, and heater output. It also provides buttons for 5 K and 10 K warmup steps. Use `--prefix` if you started the IOC with a different PV prefix:

```bash
python3 scripts/ls336_dashboard.py --prefix LS336_DEV:
```

Set a safe Loop 1 target and ramp:

```bash
caput LS336:Loop1:SETP 300
caput LS336:Loop1:RAMP:ENABLE 1
caput LS336:Loop1:RAMP:RATE 1
```

Step the warmup target in a 5 K or 10 K rhythm:

```bash
caput LS336:Loop1:WARMUP:TARGET 300
caput LS336:Loop1:WARMUP:STEP:5K.PROC 1
caput LS336:Loop1:WARMUP:NEXT.PROC 1
caput LS336:Loop1:WARMUP:STEP:10K.PROC 1
caput LS336:Loop1:WARMUP:NEXT.PROC 1
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
