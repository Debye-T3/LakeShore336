# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build, Test, and Run Commands

**EPICS IOC (Linux/WSL only):**
- `make` — builds the IOC binary (`bin/linux-x86_64/ls336`)
- `bash scripts/run_tests.sh` — runs `make` then `pytest`
- `pytest` — runs Python layout/regression tests in `tests/`
- `pytest tests/test_ioc_layout.py -k test_database` — run a single test by keyword
- `bash scripts/check_ioc_ready.sh` — verifies build artifacts and runtime prerequisites
- `bash scripts/setup_epics_wsl.sh` — installs EPICS Base, asyn, StreamDevice under `/opt/epics`, writes `configure/RELEASE.local`
- `bash scripts/run_ioc.sh` — starts the IOC; override with `TTY=/dev/ttyS4 bash scripts/run_ioc.sh`

**Python dashboards (cross-platform):**
- `python -m pip install -r requirements.txt` — installs pyserial
- `python scripts/ls336_web_dashboard.py` — browser dashboard at `http://127.0.0.1:8765` (main operator interface)
- `python scripts/ls336_web_dashboard.py --host 0.0.0.0 --port 8765` — expose on lab network
- `python scripts/ls336_direct_dashboard.py` — older Tk direct serial dashboard
- `python scripts/ls336_direct_dashboard.py --port COM3` — specify Windows COM port
- `python scripts/ls336_dashboard.py` — EPICS PV-based Tk dashboard (requires running IOC + `caget`/`caput` in PATH)

**Windows convenience launchers:**
- Double-click `START_WINDOWS_DASHBOARD.bat` — auto-installs deps, starts web dashboard, opens browser
- `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\diagnose_wsl_windows.ps1` — WSL diagnostics

## Architecture: Three Interface Tiers

This repository provides three independent interfaces for the same Lake Shore 336 temperature controller. Each tier operates without the others — no tier depends on another tier's runtime:

### Tier 1 — EPICS IOC (beamline integration)
`ls336App/` contains the EPICS IOC that exposes the Lake Shore 336 as Channel Access PVs.

- **`ls336App/protocol/ls336.proto`** — StreamDevice protocol definitions mapping Lake Shore serial commands (`KRDG? A`, `SETP 1,%f`, `RAMP 1,%d,%f`, `HTR? 1`) to EPICS records. The `@init` directive on setpoint/ramp writes causes an immediate readback.
- **`ls336App/Db/ls336.db`** — EPICS database defining all public PVs, calc-based validation records (`validate_setpoint`, `validate_ramp_rate`), and communication status derivation. The `COMM:STATUS` mbbo record derives alarm severity from all readback PVs (if any readback has non-zero severity, status = 2 "FAULT"; else 1 "OK").
- **`ls336App/src/ls336Main.cpp`** — Minimal IOC main: if started with a startup script argument, runs it via `iocsh()`; otherwise registers the record device driver and drops to interactive iocsh.
- **`iocBoot/iocLS336/st.cmd`** — Startup script: configures asyn serial port (57600-7-O-1), loads the record database with `$(PREFIX)` and `$(PORT)` macros, then calls `iocInit()`.

**Safety limits are embedded in the database**: setpoint ≤ 350 K, ramp rate ≤ 10 K/min. These are enforced by calc records, not just DRVH/HOPR fields — the validation pattern is `validate_setpoint = (A ≤ 350 && A ≥ 0) ? A : 0` with a matching `ERR` message.

### Tier 2 — Python Serial Dashboards (direct hardware control)
`scripts/ls336_web_dashboard.py` is the primary operator interface. It talks directly to the Lake Shore over a serial port — no EPICS required.

**Web dashboard architecture (`ls336_web_dashboard.py`):**
- `LakeShoreSerialClient` — thread-safe serial client with `with self._lock` guards around all reads/writes. Supports dynamic input channel mapping (cold input, sample input, control input can each be A/B/C/D).
- `LogArchive` — auto-records every poll cycle to `logs/ls336_temperature_YYYYMMDD.csv` with companion `.meta.json` files. Uses Beijing time (`Asia/Shanghai`). Starts automatically on connect; ordinary operator page shows status only (can't stop). Maintenance page (`/maintenance`) can pause/resume/new-file/download.
- `MaintenanceAuth` — cookie-based auth; default password `ls336-maint`, overridable via `LS336_MAINT_PASSWORD` env var. Maintenance page exposes PID write (`PID 1,P,I,D`) with browser confirmation and audit logging.
- HTTP API endpoints: `/api/data` (poll), `/api/apply` (CSET+RANGE+RAMP+SETP in one update), `/api/log/status|download|pause|resume|new`, `/api/maintenance/login`, `/api/pid`
- Serves `web/index.html` at `/` and a maintenance page at `/maintenance` (generated inline).

`scripts/ls336_direct_dashboard.py` is the older Tk GUI; `scripts/ls336_dashboard.py` is the EPICS PV-based Tk GUI (requires a running IOC).

### Tier 3 — Static Web Frontend (demo/deploy)
`web/index.html` is a self-contained single-page app with no build step. It can operate in two modes:
1. **Backend mode** — when served by `ls336_web_dashboard.py`, it detects the backend and polls `/api/data` for real instrument data.
2. **Demo mode** — standalone (local file or Vercel deploy), it runs an internal simulation loop with `demo.inputs` drifting values around hardcoded defaults. CSV download in demo mode is browser-temporary only (`ls336_static_demo_temporary_log.csv`).

The HTML contains all CSS (dark theme, cyan/pink palette, responsive), English/Chinese translations inline (`tr` object), a Canvas-based temperature trend chart, safety warning panel (setpoint > 350 K, ramp > 10 K/min, sensor reads 0 K, etc.), and input channel selection dropdowns. **Vercel deployment** uses `vercel.json` to rewrite all traffic to `web/index.html`.

## Key Conventions

- **PV naming**: `LS336:` prefix, colon-separated segments, `_RBV` suffix for readbacks (e.g. `LS336:ColdHead:TEMP_RBV`, `LS336:Loop1:SETP_RBV`)
- **StreamDevice protocol functions**: lower camel case (`getSetpoint`, `setRamp`); the `.proto` file uses `out`/`in` pattern with `%f`/`%d` format specifiers
- **Tests are string-based assertions** against source files: `tests/test_ioc_layout.py` reads raw `.db`, `.proto`, `.cmd`, `.py`, `.html`, `.md` files and asserts substrings exist. Add assertions when changing PV names, protocol commands, safety limits, startup config, or documented workflows.
- **`.gitignore`** excludes: EPICS build output (`bin/`, `dbd/`, `lib/`, `O.*/`), `configure/RELEASE.local`, `downloads/` (dependency archives), `logs/` (experiment data), `.claude/`
- **Commit style**: Conventional Commits (`feat:`, `fix:`, `docs:`) describing IOC behavior affected and validation commands run

## Serial Protocol Notes

The Lake Shore 336 uses 57600-7-O-1 over USB-serial. Key commands:
- `KRDG? A` → Kelvin reading input A
- `SETP? 1` / `SETP 1,<float>` → read/write Loop 1 setpoint
- `RAMP? 1` → returns `enable,rate` (e.g. `1,2.5`)
- `RAMP 1,<0|1>,<float>` → set ramp enable and rate in one command
- `HTR? 1` → heater output percentage
- `CSET?` / `CSET A,B,B,1,A,B` → get/set input channel mapping (cold, sample, control inputs)
- `RANGE? 1` / `RANGE 1,<0-3>` → get/set heater range
- `PID? 1` / `PID 1,P,I,D` → get/set PID parameters

The `RAMP` command writes both enable and rate simultaneously — the dashboard always sends both values together in a single serial write.
