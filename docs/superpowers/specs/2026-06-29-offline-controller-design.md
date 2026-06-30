# Lake Shore 336 Offline Controller Design

## Goal

Deliver a Windows x64 control package that can run on an offline Windows 10/11 computer without Python, WSL, or an internet connection. The package must support the second hardware test, preserve the existing safety limits, and record all local timestamps in Beijing time.

## Time Semantics

The Python-backed dashboard already writes two archive columns:

- `timestamp_iso`: UTC with a `+00:00` offset.
- `timestamp_local`: Beijing time with a `+08:00` offset.

The static browser DEMO must use the same two-column contract. Its current single `timestamp_iso` value is UTC and is the reported defect. The ordinary dashboard's "Last Write" display must prefer the Beijing timestamp when the backend supplies it and use an explicitly formatted Beijing timestamp in static mode.

Daily filenames continue to use the Beijing calendar date. Metadata continues to identify the timezone as `Asia/Shanghai`.

## Hardware Control Scope

The browser dashboard remains the primary operator interface. It supports:

- Serial discovery and connection at 57600 baud, 7 data bits, odd parity, and one stop bit.
- A/B/C/D temperature readback.
- Cold-head, sample, and control input mapping.
- Loop 1 setpoint, ramp enable/rate, and heater range control.
- Setpoint limit of 0 to 350 K.
- Ramp-rate limit of 0 to 10 K/min.
- PID readback for ordinary users.
- Password-protected PID write for maintenance users.

After a combined control write, the application reads the instrument state back and returns that state to the browser. The second hardware test verifies that the returned setpoint, ramp, heater range, and input mapping agree with the requested values. Real heating proceeds only after beamline personnel confirm the safe target and ramp rate.

## Offline Package

Use PyInstaller `--onedir` output and distribute it as `LakeShore336_portable.zip`.

The extracted package contains:

- `LakeShore336.exe`
- `START.bat`
- bundled Python runtime and dependencies
- bundled dashboard web files
- bundled IANA timezone data
- a writable `logs/` directory created at first run
- a concise offline operator guide

The target computer does not install Python packages. Only the connected Lake Shore serial driver may be required if Windows does not already expose the instrument as a COM port.

The build must not package existing experiment logs. A clean empty `logs/` directory is created in the distribution, and the program writes new logs beside the executable.

## Build and Verification

The build script checks required source files, builds the directory package, copies the launcher and offline guide, creates the empty log directory, and produces the ZIP.

Automated tests cover:

- Static DEMO UTC and Beijing timestamp columns.
- Beijing formatting independent of the browser's local timezone.
- Backend log status exposing both UTC and Beijing last-write values.
- Safety limits and serial configuration.
- Portable build script contents and exclusion of source experiment logs.

Runtime smoke testing starts the built EXE on a temporary port, connects to DEMO, reads data, applies a safe control update, verifies the returned state, confirms archive creation, and checks the main and maintenance pages.

## Failure Handling

- Invalid setpoint, ramp, channel, heater range, and PID values are rejected before a serial command is sent.
- Serial failures return an explicit API error and logging status.
- Archive write failures appear in the ordinary recording status.
- Port conflicts prevent startup with a visible console error.
- The launcher keeps the console open after an unexpected exit so maintenance personnel can read the error.

