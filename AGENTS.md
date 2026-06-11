# Repository Guidelines

## Project Structure & Module Organization

This repository is an EPICS IOC for a Lake Shore 336 temperature controller. Core IOC files live under `ls336App/`: `Db/ls336.db` defines public PV records and safety limits, `protocol/ls336.proto` defines StreamDevice serial commands, and `src/` builds the `ls336` IOC binary. Startup configuration is in `iocBoot/iocLS336/st.cmd`. EPICS build configuration is under `configure/`, with site overrides expected in untracked `configure/RELEASE.local`. Utility scripts are in `scripts/`, and Python layout/regression tests are in `tests/`.

## Build, Test, and Development Commands

- `bash scripts/setup_epics_wsl.sh`: installs EPICS Base, asyn, and StreamDevice under `/opt/epics`, then writes `configure/RELEASE.local`. It auto-detects dependency archives in `downloads/` before falling back to GitHub.
- `make`: builds the IOC using EPICS make rules.
- `bash scripts/check_ioc_ready.sh`: verifies local build prerequisites, `RELEASE.local`, the IOC binary, and expected runtime check commands.
- `pytest`: runs the Python tests that validate IOC layout, PV definitions, safety limits, setup scripts, and README command coverage.
- `cd iocBoot/iocLS336 && ../../bin/linux-x86_64/ls336 st.cmd`: starts the IOC with the default `/dev/ttyUSB0` serial device.

## Coding Style & Naming Conventions

Keep EPICS database records readable and aligned with the existing style: four-space indentation inside `record(...)` blocks and quoted field values. Public PVs use the `LS336:` prefix at runtime and descriptive uppercase segments such as `ColdHead:TEMP_RBV`, `Loop1:SETP`, and `Loop1:RAMP:RATE_RBV`. StreamDevice protocol functions use lower camel case names like `getSetpoint` and `setRamp`. Python tests use `test_...` functions and straightforward string assertions against repository files.

## Testing Guidelines

Add or update tests in `tests/test_ioc_layout.py` when changing PV names, protocol commands, safety limits, startup defaults, setup scripts, or README workflows. Keep tests focused on observable repository contracts: required records, limit values, serial settings, documented commands, and generated configuration paths. Run `pytest` before submitting changes; run `make` and `bash scripts/check_ioc_ready.sh` inside WSL when EPICS build or boot files change.

## Commit & Pull Request Guidelines

Use concise Conventional Commit-style messages such as `docs: update IOC setup notes` or `fix: correct ramp protocol command`. Pull requests should describe the IOC behavior affected, list validation commands run, note any safety-limit changes, and include relevant EPICS client checks such as `caget LS336:ColdHead:TEMP_RBV` or `caput LS336:Loop1:SETP 300`.

## Security & Configuration Tips

Do not commit machine-specific `configure/RELEASE.local` paths, WSL build output directories, IOC boot histories, or downloaded dependency archives. Treat setpoint and ramp-rate limit changes as safety-sensitive; document the commissioning rationale and test the validation records before use on hardware.

## WSL/EPICS Notes

WSL is used as a Linux terminal environment, not as a full desktop VM. The Windows checkout path is `/mnt/d/Projects/LakeShore336` inside Ubuntu. GitHub access from WSL may be unreliable, so `scripts/setup_epics_wsl.sh` should support local archives in `downloads/`. The script builds only the asyn and StreamDevice core components required by this IOC; do not re-enable bundled example/test apps unless their extra dependencies are intentionally added.
