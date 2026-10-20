# Lake Shore 336 IOC Function Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. If the user chooses subagent-driven execution, use `superpowers:subagent-driven-development` instead.

**Goal:** Make the EPICS IOC expose the tested Python instrument controls while keeping the Web dashboard and its CSV archive as Channel Access clients.

**Architecture:** Keep the existing C++ IOC, asyn serial port, and StreamDevice readback protocols. Add the missing control PVs and serialized command protocols; convert the Web dashboard's real-hardware backend from direct serial to a Python CA client, while retaining its existing demo mode, UI, and CSV/metadata behavior.

**Tech Stack:** EPICS Base, asyn, StreamDevice, EPICS Access Security, Python 3, caproto, the existing HTTP dashboard and PyInstaller packaging.

**Spec:** `docs/superpowers/specs/2026-10-20-lakeshore336-ioc-parity-design.md`

## Global Constraints

- The IOC is the only process that opens the Lake Shore 336 serial connection.
- Keep serial communication at 57600 baud, 7 data bits, odd parity, 1 stop bit.
- IOC startup remains query-only; all control output records use `PINI=NO`.
- Keep existing public readback PV names and treat `_RBV` values as authoritative.
- Preserve the APPLY sequence `CSET → RANGE → RAMP → SETP` with 150 ms pacing.
- Preserve the Python archive's 2 second row interval, CSV field order, Asia/Shanghai timestamps, and 0.2 K stable-state threshold.
- Use Channel Access for the initial public interface; PVA is outside this plan.
- Do not add or run tests or start hardware commissioning unless the user separately asks for verification.
- Keep site-specific CA address lists, gateway routes, and allowed control hosts out of generic defaults; begin with control writes denied until deployment rules are supplied.

## Review Focus

These are the failure cases most likely to cause operational surprises. The owning task must expose the stated behavior; this plan does not authorize adding or running tests.

1. Invalid setpoint, ramp, range, input, or PID values must not reach the instrument (Task 1).
2. A serial error during APPLY must leave a visible failure state; readbacks must show which requested settings actually took effect (Task 1).
3. `CSET` channel labels and `OUTMODE? 1` readback must agree on the real Model 336 (Task 1; hardware commissioning requires separate authorization).
4. CA disconnects and stale PV values must not be written as fresh, valid CSV measurements (Tasks 3 and 5).
5. Repeated log commands, archive errors, and a stopped Python process must be visible through status/heartbeat PVs (Task 5).

---

### Task 1: Add IOC write PVs and serialized control protocols

**Files:**
- Modify: `ls336App/Db/ls336.db`
- Modify: `ls336App/protocol/ls336.proto`
- Modify: `ls336App/src/Makefile`
- Create: `ls336App/src/ls336Control.cpp`
- Create: `ls336App/src/ls336Support.dbd`
- Modify: `docs/superpowers/specs/2026-10-20-lakeshore336-ioc-parity-design.md` only if implementation discovers a necessary interface adjustment

**Interfaces:**
- Consumes: existing `$(P)` and `$(PORT)` macros, current `_RBV` records, and current 57600 7O1 StreamDevice port.
- Produces: `Loop1:INPUT`, `Loop1:CTRL:INPUT`, `Loop1:CTRL:SETP`, `Loop1:CTRL:RAMP:RATE`, `Loop1:CTRL:RANGE`, `Loop1:CTRL:APPLY`, `Loop1:CTRL:BUSY`, `Loop1:CTRL:STATUS`, `Loop1:CTRL:ERROR`, `Loop1:PID:P/I/D`, `Loop1:PID:APPLY`, `Loop1:PID:P/I/D_OLD_RBV`, `Loop1:PID:STATUS`, and `Loop1:PID:ERROR` under the configurable prefix.

- [x] Add `Loop1:INPUT` as an A-D control-input command using the same `CSET 1,<input>,1,1` semantics as the Python client; keep `Loop1:INPUT_RBV` as the `OUTMODE? 1` readback.
- [x] Add separate `Loop1:CTRL:INPUT` staging and setpoint/ramp/range staging PVs so the grouped command does not send hardware writes before `CTRL:APPLY`.
- [x] Add a synchronous `aSub` helper that captures and validates the four staged values before starting an APPLY; reject concurrent APPLY while the prior command is busy. Keep StreamDevice as the only serial transport.
- [x] Add one `applyControl` StreamDevice protocol that sends `CSET`, `RANGE`, `RAMP`, and `SETP` in that order with 150 ms waits, then queries the four relevant readbacks into their authoritative PVs. Keep the whole command sequence and queries in one protocol so the asyn device lock spans the sequence. StreamDevice documents that its first `out` locks the device until protocol termination and supports millisecond `wait` commands: [protocol reference](https://paulscherrerinstitute.github.io/StreamDevice/protocol.html), [record processing](https://paulscherrerinstitute.github.io/StreamDevice/processing.html).
- [x] Drive `CTRL:BUSY`, `CTRL:STATUS`, and `CTRL:ERROR` from the aSub prepare/finish handlers and protocol alarm/readback comparison. On failure report protocol-level error and continue polling readbacks; do not claim an atomic rollback.
- [x] Add PID P/I/D staging, an aSub validation/snapshot, old-value readbacks, and one `PID:APPLY` operation that reads old PID values, sends one `PID 1,p,i,d` command, waits 200 ms, then reads the new values. Validate P 0.1–1000, I 0.1–1000, and D 0–200 before sending, per the Model 336 command summary in the [manufacturer manual](https://www.lakeshore.com/docs/default-source/product-downloads/336manual.pdf).
- [x] Preserve the current direct `SETP`, `RAMP`, and `RANGE` PVs and their existing limits; ensure no new write PV has `PINI=YES`.

### Task 2: Configure fail-closed EPICS write access

**Files:**
- Create: `iocBoot/iocLS336/access.acf`
- Modify: `iocBoot/iocLS336/st.cmd`
- Modify: `ls336App/Db/ls336.db`
- Modify: `README.md`

**Interfaces:**
- Consumes: Task 1's PV suffixes.
- Produces: ACF groups `CONTROL`, `MAINT`, `LOG_CONTROL`, and `ARCHIVER`; routine hardware commands, PID commands, operator log commands, and archive-status writes are assigned to the corresponding group.

- [x] Add `ASG` fields to write and status PVs: routine control, PID maintenance, operator log commands, and archiver status/heartbeat use separate groups.
- [x] Add the ACF file and load it in `st.cmd` before `iocInit`; keep write access denied if site access rules are absent or incomplete.
- [x] Document which group controls each PV family and how the site supplies allowed CA users/hosts; do not invent site IP addresses or allow all network hosts by default.
- [x] Keep the startup sequence query-only and leave the serial settings unchanged.

### Task 3: Add a reusable Python Channel Access client

**Files:**
- Create: `scripts/ls336_epics_client.py`
- Modify: `requirements.txt`
- Modify: `scripts/build_package.bat`

**Interfaces:**
- Produces: `LakeShoreEpicsClient(prefix: str, timeout: float = 2.0)` with `connect()`, `close()`, `read_all()`, `read_snapshot()`, `set_inputs()`, `set_setpoint()`, `set_control()`, `read_pid()`, `set_pid()`, and `write_log_command()` methods.
- `read_snapshot()` returns each subscribed value with its CA timestamp and alarm status/severity so the logger can reject stale or invalid samples.
- `set_control()` writes the four staging PVs, triggers `CTRL:APPLY`, waits for `CTRL:STATUS`, then returns actual `_RBV` values; `set_pid()` does the same for the single PID APPLY operation and returns old/new values.

- [x] Implement the client with caproto's threading CA client and monitor subscriptions; use `data_type="time"` for timestamp/alarm metadata. The official [threading client reference](https://caproto.github.io/caproto/v0.7.0/threading-client.html) documents cached CA connections, monitor callbacks, and time metadata.
- [x] Make connection state, timeouts, access-denied errors, and stale subscriptions explicit exceptions/results; protect the shared monitor cache with a lock.
- [x] Add caproto to `requirements.txt` and PyInstaller collection directives so the Windows packaged Web app can import the client without a system `libca` dependency.
- [x] Keep hardware I/O out of this module; it must not import pyserial or enumerate COM ports.

### Task 4: Convert the Web dashboard to EPICS mode

**Files:**
- Modify: `scripts/ls336_web_dashboard.py`
- Modify: `web/index.html`
- Modify: `scripts/run_web_dashboard_windows.bat`
- Modify: `scripts/run_web_dashboard_mac.sh`
- Modify: `scripts/smoke_test_portable.py` (keep the existing package acceptance check aligned with the prefix-based connect route)

**Interfaces:**
- Consumes: `LakeShoreEpicsClient` from Task 3 and the PV contract from Task 1.
- Produces: Existing HTTP routes for connect/read/control/input/PID operations, now backed by CA; `--prefix` and `LS336_PREFIX` select the IOC prefix; `DEMO` keeps the simulator path.

- [x] Replace the real-hardware `LakeShoreSerialClient` and serial-port selector in the Web app with an EPICS prefix selector/default; preserve the separate `scripts/ls336_direct_dashboard.py` as the direct-serial fallback for use only while IOC is stopped.
- [x] Keep `DemoLakeShoreClient` and the existing browser UI/trend/status behavior.
- [x] Route `control` through the grouped APPLY operation; route the separate input selection through `Loop1:INPUT`; route setpoint/ramp through the existing command PVs with Python's ramp-enable rule.
- [x] Route maintenance PID through staging plus `PID:APPLY`; retain login, confirmation, before/after readback, and `LogArchive.audit_pid()`.
- [x] Keep Cold Head/Sample display mapping in the Python app configuration; it must not be confused with the instrument's control-input PV.
- [x] Remove the Web app's real-device serial-port enumeration and update connection errors to distinguish IOC unavailable, access denied, and instrument communication errors.

### Task 5: Drive the existing CSV archive from IOC PVs

**Files:**
- Modify: `scripts/ls336_web_dashboard.py`
- Modify: `ls336App/Db/ls336.db`

**Interfaces:**
- Consumes: Task 3's CA monitor samples and IOC `LOG:*` command/readback PVs.
- Produces: Existing `LogArchive` CSV and metadata files plus `LOG:STATE_RBV`, `LOG:FILE_RBV`, `LOG:ROWS_RBV`, `LOG:LAST_WRITE_RBV`, `LOG:ERROR_RBV`, and `LOG:HEARTBEAT` updates.

- [x] Add soft IOC records for `LOG:START`, `LOG:PAUSE`, `LOG:RESUME`, `LOG:NEW_FILE`, and the readback/status PVs; assign write security groups from Task 2.
- [x] Subscribe to the four temperatures, setpoint, ramp, range, heater, PID, control-input, and communication PVs. Run a Python archive worker at 2 second intervals, independent of browser refresh requests; begin a session and write the first row immediately on connect/start.
- [x] Process log commands from CA monitors so another approved EPICS client can control the same archive; serialize command handling, require the command PV to return to 0 before accepting another pulse, and update `LOG:STATE_RBV` only after the operation succeeds or fails.
- [x] Reuse the existing CSV field order, Asia/Shanghai timestamp, 0.2 K stability rule, daily/manual file naming, metadata sessions/operations, pause/resume/new-file behavior, PID audit, and download route.
- [x] Track per-PV timestamp and alarm validity; write blank/invalid fields rather than replaying stale data as a fresh measurement. Stop heartbeat updates when the archive worker exits and show lost-heartbeat status in the UI.
- [x] Stop subscriptions and the worker cleanly when the Web server shuts down; keep file-writing exceptions visible in `LOG:ERROR_RBV` and the existing status endpoint.

### Task 6: Update deployment and operator documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/operator_tutorial_zh.md`
- Modify: `docs/offline_package_zh.md`
- Modify: `scripts/run_portable.bat`

**Interfaces:**
- Consumes: Final PV names, `LS336_PREFIX`, ACF group assignments, and the Web dashboard's CA connection behavior.
- Produces: One consistent startup path for IOC first, then the Python EPICS dashboard/archive client.

- [x] Document IOC ownership of the serial port and the required order: start IOC, then connect the Web app by PV prefix.
- [x] Document same-subnet CA discovery, the site-configured address-list/Gateway requirement for other subnets, and the web service identity boundary for remote browser access.
- [x] Document how to grant routine, maintenance, and archive permissions without exposing write PVs broadly.
- [x] Update the portable package guide: the packaged Web UI now needs CA access to a running IOC; the standalone direct-serial fallback remains separate.
- [x] Update the operator tutorial with the new control-input, grouped APPLY, PID APPLY, and log PV behavior while preserving the old public readback names.

## Verification Boundary

This plan does not add or run automated tests, builds, smoke checks, or hardware commissioning. Those checks need a separate explicit request. The code change must not be described as hardware-validated until the approved commissioning sequence has been performed with the actual controller.
