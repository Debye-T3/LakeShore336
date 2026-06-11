# Lake Shore 336 EPICS IOC

This repository contains a first-version EPICS IOC for a Lake Shore 336 temperature controller used at a beamline. It exposes readback PVs for the cold head and sample temperatures, plus conservative Loop 1 setpoint and ramp controls for higher-level Python clients.

## Target Setup

- Host: WSL/Linux on a Windows control computer.
- Instrument link: Lake Shore 336 USB presented as a serial port.
- Default serial device: `/dev/ttyUSB0`.
- Serial settings: 57600 baud, 7 data bits, odd parity, 1 stop bit.
- EPICS modules: EPICS Base, asyn, StreamDevice.
- PV prefix: `LS336:`.

Edit `configure/RELEASE.local` or pass macros at IOC start time if your EPICS module paths or serial device differ.

## Public PVs

| PV | Direction | Purpose |
| --- | --- | --- |
| `LS336:ColdHead:TEMP_RBV` | read | Input A temperature, mapped to cold head temperature. |
| `LS336:Sample:TEMP_RBV` | read | Input B temperature, mapped to sample-side temperature. |
| `LS336:Loop1:SETP` | write | Requested Loop 1 setpoint in K. Limited to 350 K. |
| `LS336:Loop1:SETP_RBV` | read | Loop 1 setpoint read back from the controller. |
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
- `LS336:Loop1:RAMP:RATE` is limited to `5 K/min`.
- The database includes `validate_setpoint` and `validate_ramp_rate` calculation records so limit behavior is explicit in the IOC database.

These limits are intended for first commissioning only. Tighten them for the actual sample, cryostat, and heater configuration before routine use.

## Build

This IOC is built from a WSL/Ubuntu terminal. WSL does not need a Linux desktop; use the Ubuntu app from the Windows Start menu, Windows Terminal, or run `wsl` from PowerShell. Windows drives are mounted under `/mnt`, so this checkout is available at:

```bash
cd /mnt/d/Projects/LakeShore336
```

Install WSL from an administrator PowerShell if it is not already available:

```powershell
wsl --install -d Ubuntu-24.04
```

After Windows restarts and Ubuntu is initialized, install the Linux build dependencies:

```bash
sudo apt update
sudo apt install -y build-essential git perl libreadline-dev libncurses-dev re2c wget tar libtirpc-dev libpcre3-dev
```

Then run the setup script from WSL. It downloads and builds EPICS Base, asyn, and StreamDevice under `/opt/epics`, then writes `configure/RELEASE.local` for this IOC:

```bash
cd /mnt/d/Projects/LakeShore336
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
make
bash scripts/check_ioc_ready.sh
```

The setup script intentionally builds only the asyn and StreamDevice core libraries needed by this IOC. It skips bundled test/example applications that require extra synApps modules or duplicate link settings. On Ubuntu, asyn is configured with `libtirpc-dev`, and StreamDevice is configured to use the system PCRE library from `libpcre3-dev`.

## Run

Start with the default serial device:

```bash
cd iocBoot/iocLS336
../../bin/linux-x86_64/ls336 st.cmd
```

The startup should recognize `drvAsynSerialPortConfigure`. If it does not, rebuild after confirming `ls336App/src/Makefile` includes `drvAsynSerialPort.dbd`.

Override the serial device when needed:

```bash
cd iocBoot/iocLS336
TTY=/dev/ttyS4 ../../bin/linux-x86_64/ls336 st.cmd
```

## EPICS Client Checks

Read both temperature channels:

```bash
caget LS336:ColdHead:TEMP_RBV
caget LS336:Sample:TEMP_RBV
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

On Windows, confirm which COM port appears after plugging in the Lake Shore 336. In WSL, that port may appear as `/dev/ttyS<N>` or may need USB/IP forwarding depending on Windows and WSL versions. Once visible in WSL, update `TTY` in `iocBoot/iocLS336/st.cmd` or pass it as an environment macro before launching the IOC.

Check visible serial devices from WSL:

```bash
ls /dev/ttyUSB*
ls /dev/ttyS*
```

Use the actual device when starting the IOC:

```bash
TTY=/dev/ttyS4 ../../bin/linux-x86_64/ls336 st.cmd
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
