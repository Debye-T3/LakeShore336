# Lake Shore 336 Simplified EPICS Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a small USB-serial EPICS IOC that exposes Model 336 A-D temperatures and Loop 1 readbacks, safely writes setpoint, ramp, and heater range, and proves unsafe numeric values never reach the instrument.

**Architecture:** The IOC remains the sole owner of the Model 336 connection. EPICS records call StreamDevice protocols over the existing asyn serial port; compatibility names are record aliases, RAMP writes query and preserve the other hardware field in one locked protocol, and numeric outputs use `SDIS` validation before record support executes. A Linux pseudo-terminal emulator provides repeatable command-level acceptance tests without hardware.

**Tech Stack:** EPICS Base 7.0.8.1, asyn R4-44, StreamDevice 2.8.24, EPICS database records, Python 3 standard-library pseudo terminals, pytest, WSL Ubuntu.

---

## File Map

- Modify `ls336App/Db/ls336.db`: public PVs, aliases, scan rates, enum mappings, numeric write guards, communication summary, and private RAMP caches.
- Modify `ls336App/protocol/ls336.proto`: A-D, `OUTMODE?`, setpoint, RAMP, range, heater, and PID protocols.
- Modify `tests/test_ioc_layout.py`: static repository contracts for the simplified Phase 1 IOC.
- Create `scripts/ls336_ioc_mock.py`: stateful Model 336 command emulator over a Linux pseudo-terminal.
- Create `tests/test_ioc_integration.py`: optional WSL integration tests against the built IOC and emulator.
- Modify `scripts/run_tests.sh`: expose the optional integration-test command without making Windows-only tests fail.
- Modify `README.md`: document Phase 1 PVs, startup behavior, mock testing, hardware acceptance, and direct-dashboard mutual exclusion.

### Task 1: Lock the Phase 1 repository contract

**Files:**
- Modify: `tests/test_ioc_layout.py`
- Test: `tests/test_ioc_layout.py`

- [ ] **Step 1: Replace the old IOC PV assertion with the approved public surface**

Use one explicit list and require aliases instead of duplicate A/B records:

```python
def test_database_exposes_simplified_phase_one_pvs():
    db = read("ls336App/Db/ls336.db")

    for name in [
        "Input:A:TEMP_RBV",
        "Input:B:TEMP_RBV",
        "Input:C:TEMP_RBV",
        "Input:D:TEMP_RBV",
        "Loop1:INPUT_RBV",
        "Loop1:SETP",
        "Loop1:SETP_RBV",
        "Loop1:RAMP:ENABLE",
        "Loop1:RAMP:ENABLE_RBV",
        "Loop1:RAMP:RATE",
        "Loop1:RAMP:RATE_RBV",
        "Loop1:RANGE",
        "Loop1:RANGE_RBV",
        "Loop1:HTR_RBV",
        "Loop1:PID:P_RBV",
        "Loop1:PID:I_RBV",
        "Loop1:PID:D_RBV",
        "COMM:STATUS",
        "ERR",
    ]:
        assert f'"$(P){name}"' in db

    assert 'alias("$(P)Input:A:TEMP_RBV", "$(P)ColdHead:TEMP_RBV")' in db
    assert 'alias("$(P)Input:B:TEMP_RBV", "$(P)Sample:TEMP_RBV")' in db
    assert 'record(ai, "$(P)ColdHead:TEMP_RBV")' not in db
    assert 'record(ai, "$(P)Sample:TEMP_RBV")' not in db
```

- [ ] **Step 2: Add protocol, scan, startup, and scope assertions**

```python
def test_protocol_contains_phase_one_commands():
    proto = read("ls336App/protocol/ls336.proto")
    for command in [
        'out "*IDN?"',
        'out "KRDG? A"',
        'out "KRDG? B"',
        'out "KRDG? C"',
        'out "KRDG? D"',
        'out "OUTMODE? 1"',
        'out "SETP? 1"',
        'out "SETP 1,%f"',
        'out "RAMP? 1"',
        'out "RANGE? 1"',
        'out "RANGE 1,%d"',
        'out "HTR? 1"',
        'out "PID? 1"',
    ]:
        assert command in proto


def test_phase_one_scan_periods_and_startup_are_read_only():
    db = read("ls336App/Db/ls336.db")
    proto = read("ls336App/protocol/ls336.proto")

    assert db.count('field(SCAN, "2 second")') >= 10
    assert db.count('field(SCAN, "10 second")') >= 4
    assert 'field(PINI, "NO")' in db
    assert "@init" not in proto


def test_phase_one_excludes_deferred_controls():
    db = read("ls336App/Db/ls336.db")
    makefile = read("ls336App/src/Makefile")
    for term in ["APPLY", "CTRL:ENABLE", "Loop1:INPUT)", "Loop1:PID:P)", "WARMUP"]:
        assert term not in db
    assert ".st" not in makefile
```

- [ ] **Step 3: Add exact safety-guard assertions**

```python
def test_numeric_outputs_use_pre_device_sdis_guards_without_clamping():
    db = read("ls336App/Db/ls336.db")

    assert 'field(SDIS, "$(P)Loop1:SETP:INVALID PP MS")' in db
    assert 'field(SDIS, "$(P)Loop1:RAMP:RATE:INVALID PP MS")' in db
    assert 'field(SDIS, "$(P)Loop1:RANGE:INVALID PP MS")' in db
    assert 'field(DISS, "INVALID")' in db
    assert 'field(CALC, "A<0||A>350")' in db
    assert 'field(CALC, "A<0||A>10")' in db
    assert 'field(CALC, "A<0||A>3")' in db
    assert 'field(HOPR, "350")' in db
    assert 'field(HOPR, "10")' in db
    assert "field(DRVH" not in db
    assert "field(DRVL" not in db
```

- [ ] **Step 4: Run the focused tests and verify they fail against the old IOC**

Run:

```bash
python -m pytest tests/test_ioc_layout.py -q
```

Expected: failures for missing A-D canonical records, aliases, `OUTMODE?`, range, PID, and `SDIS` guards.

- [ ] **Step 5: Commit the failing contract tests**

```bash
git add tests/test_ioc_layout.py
git commit -m "test: define simplified EPICS phase one contract"
```

### Task 2: Implement read-only identity, temperature, and Loop 1 state

**Files:**
- Modify: `ls336App/protocol/ls336.proto`
- Modify: `ls336App/Db/ls336.db`
- Test: `tests/test_ioc_layout.py`

- [ ] **Step 1: Add complete read protocols**

Replace the read protocol section with:

```text
getIDN {
    out "*IDN?";
    in "%39c";
}

getTemperature {
    out "KRDG? \$1";
    in "%f";
}

getControlInput {
    out "OUTMODE? 1";
    in "%*d,%d,%*d";
}

getSetpoint {
    out "SETP? 1";
    in "%f";
}

getRampEnable {
    out "RAMP? 1";
    in "%d,%*f";
}

getRampRate {
    out "RAMP? 1";
    in "%*d,%f";
}

getRange {
    out "RANGE? 1";
    in "%d";
}

getHeater {
    out "HTR? 1";
    in "%f";
}

getPidP {
    out "PID? 1";
    in "%f,%*f,%*f";
}

getPidI {
    out "PID? 1";
    in "%*f,%f,%*f";
}

getPidD {
    out "PID? 1";
    in "%*f,%*f,%f";
}
```

- [ ] **Step 2: Replace duplicate A/B records with four canonical records and two aliases**

Use this pattern for all four channels, changing only channel and description:

```text
record(ai, "$(P)Input:A:TEMP_RBV") {
    field(DESC, "Input A temperature")
    field(DTYP, "stream")
    field(INP,  "@ls336.proto getTemperature(A) $(PORT)")
    field(EGU,  "K")
    field(PREC, "3")
    field(SCAN, "2 second")
}
alias("$(P)Input:A:TEMP_RBV", "$(P)ColdHead:TEMP_RBV")
```

Create B, C, and D canonical records and put the `Sample:TEMP_RBV` alias immediately after B.

- [ ] **Step 3: Add passive hardware readbacks with explicit enums**

Add `Loop1:INPUT_RBV` as `mbbi` with `0=None`, `1=A`, `2=B`, `3=C`, `4=D`; add setpoint, separate RAMP enable/rate, range, heater, and three PID records. Apply:

```text
field(SCAN, "2 second")
```

to input, setpoint, RAMP, range, and heater records, and:

```text
field(SCAN, "10 second")
```

to IDN and each PID record. Set IDN to periodic polling instead of `I/O Intr`.

- [ ] **Step 4: Run the readback contract tests**

Run:

```bash
python -m pytest tests/test_ioc_layout.py -q
```

Expected: readback, alias, command, and scan assertions pass; output safety and RAMP-preservation assertions remain failing.

- [ ] **Step 5: Commit the readback implementation**

```bash
git add ls336App/Db/ls336.db ls336App/protocol/ls336.proto
git commit -m "feat: add Model 336 phase one readbacks"
```

### Task 3: Implement safe setpoint and heater-range writes

**Files:**
- Modify: `ls336App/protocol/ls336.proto`
- Modify: `ls336App/Db/ls336.db`
- Test: `tests/test_ioc_layout.py`

- [ ] **Step 1: Add direct write protocols without startup writes**

```text
setSetpoint {
    out "SETP 1,%f";
}

setRange {
    out "RANGE 1,%d";
}
```

Do not add `@init` handlers.

- [ ] **Step 2: Convert `Loop1:SETP` into the public StreamDevice output**

```text
record(ao, "$(P)Loop1:SETP") {
    field(DESC, "Loop 1 setpoint command")
    field(DTYP, "stream")
    field(OUT,  "@ls336.proto setSetpoint $(PORT)")
    field(EGU,  "K")
    field(PREC, "3")
    field(LOPR, "0")
    field(HOPR, "350")
    field(PINI, "NO")
    field(SDIS, "$(P)Loop1:SETP:INVALID PP MS")
    field(DISV, "1")
    field(DISS, "INVALID")
}

record(calcout, "$(P)Loop1:SETP:INVALID") {
    field(DESC, "Reject unsafe setpoint")
    field(INPA, "$(P)Loop1:SETP.VAL NPP NMS")
    field(CALC, "A<0||A>350")
    field(OOPT, "When Non-zero")
    field(OUT,  "$(P)ERR:SETP.PROC PP")
}
```

Retain the existing setpoint error text, but remove the old `SETP:WRITE` record and old valid-forwarding record.

- [ ] **Step 3: Add the heater-range command record**

```text
record(mbbo, "$(P)Loop1:RANGE") {
    field(DESC, "Loop 1 heater range command")
    field(DTYP, "stream")
    field(OUT,  "@ls336.proto setRange $(PORT)")
    field(ZRST, "Off")
    field(ONST, "Low")
    field(TWST, "Medium")
    field(THST, "High")
    field(PINI, "NO")
    field(SDIS, "$(P)Loop1:RANGE:INVALID PP MS")
    field(DISV, "1")
    field(DISS, "INVALID")
}
```

Add a passive `Loop1:RANGE:INVALID` `calcout` that reads `Loop1:RANGE.VAL` through `NPP`, uses `CALC="A<0||A>3"`, and updates `ERR` without calling device support when invalid. Enum labels alone are not treated as proof that a numeric client cannot submit value 4.

- [ ] **Step 4: Run tests**

Run:

```bash
python -m pytest tests/test_ioc_layout.py -q
```

Expected: setpoint and range contract assertions pass; RAMP-preservation and communication-summary assertions remain failing.

- [ ] **Step 5: Commit**

```bash
git add ls336App/Db/ls336.db ls336App/protocol/ls336.proto
git commit -m "feat: guard setpoint and range writes"
```

### Task 4: Implement atomic query-preserve-write RAMP control

**Files:**
- Modify: `ls336App/protocol/ls336.proto`
- Modify: `ls336App/Db/ls336.db`
- Test: `tests/test_ioc_layout.py`

- [ ] **Step 1: Add static assertions for the two RAMP transactions**

```python
def test_ramp_writes_query_and_preserve_the_other_hardware_field():
    proto = read("ls336App/protocol/ls336.proto")

    assert 'in "%(\\$1Loop1:RAMP:ENABLE:CACHE.VAL)d,%*f"' in proto
    assert 'out "RAMP 1,%(\\$1Loop1:RAMP:ENABLE:CACHE.VAL)d,%f"' in proto
    assert 'in "%*d,%(\\$1Loop1:RAMP:RATE:CACHE.VAL)f"' in proto
    assert 'out "RAMP 1,%d,%(\\$1Loop1:RAMP:RATE:CACHE.VAL)f"' in proto
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
python -m pytest tests/test_ioc_layout.py::test_ramp_writes_query_and_preserve_the_other_hardware_field -q
```

Expected: FAIL because the old protocol copies a command PV instead of querying hardware.

- [ ] **Step 3: Add the two locked StreamDevice protocols**

```text
setRampRate {
    out "RAMP? 1";
    in "%(\$1Loop1:RAMP:ENABLE:CACHE.VAL)d,%*f";
    out "RAMP 1,%(\$1Loop1:RAMP:ENABLE:CACHE.VAL)d,%f";
}

setRampEnable {
    out "RAMP? 1";
    in "%*d,%(\$1Loop1:RAMP:RATE:CACHE.VAL)f";
    out "RAMP 1,%d,%(\$1Loop1:RAMP:RATE:CACHE.VAL)f";
}
```

The first `out` acquires the StreamDevice/asyn lock and holds it through the final `out`.

- [ ] **Step 4: Add private caches and public command records**

```text
record(longin, "$(P)Loop1:RAMP:ENABLE:CACHE") {
    field(DESC, "Private ramp enable cache")
    field(PINI, "NO")
}

record(ai, "$(P)Loop1:RAMP:RATE:CACHE") {
    field(DESC, "Private ramp rate cache")
    field(PINI, "NO")
}
```

Configure the public `bo` with `setRampEnable($(P))`, and configure the public `ao` with `setRampRate($(P))`, `LOPR=0`, `HOPR=10`, `PINI=NO`, and the same `SDIS` validation structure used by setpoint with `CALC="A<0||A>10"`. Do not expose caches in README or the public PV table.

- [ ] **Step 5: Run tests**

Run:

```bash
python -m pytest tests/test_ioc_layout.py -q
```

Expected: all protocol, RAMP, alias, scope, and safety-layout tests pass.

- [ ] **Step 6: Commit**

```bash
git add tests/test_ioc_layout.py ls336App/Db/ls336.db ls336App/protocol/ls336.proto
git commit -m "feat: preserve hardware state in ramp writes"
```

### Task 5: Derive communication status and keep errors small

**Files:**
- Modify: `ls336App/Db/ls336.db`
- Test: `tests/test_ioc_layout.py`

- [ ] **Step 1: Add the required-readback alarm inputs**

Use one `calcout` with IDN severity in `A` and the ten required readback severities in `B-K`:

```text
field(CALC, "A>0?0:(B>0||C>0||D>0||E>0||F>0||G>0||H>0||I>0||J>0||K>0?2:1)")
```

Map result values through a soft `mbbo`:

```text
0 = Disconnected
1 = Connected
2 = Error
```

Exclude PID severity from this calculation.

- [ ] **Step 2: Preserve a short generic `ERR` path**

Keep `ERR:SETP`, `ERR:RAMP`, and `ERR:RANGE` private string records. Their processing writes a bounded message to public `ERR`. Add one communication helper that writes `Communication failure; inspect record STAT/SEVR` when `COMM:STATUS` becomes Error or Disconnected. Do not add counters, acknowledgement, or a separate error state machine.

- [ ] **Step 3: Add and run communication assertions**

```python
def test_communication_status_uses_idn_and_required_readbacks_only():
    db = read("ls336App/Db/ls336.db")
    calc = 'A>0?0:(B>0||C>0||D>0||E>0||F>0||G>0||H>0||I>0||J>0||K>0?2:1)'

    assert calc in db
    assert "PID:P_RBV.SEVR" not in db
    assert "PID:I_RBV.SEVR" not in db
    assert "PID:D_RBV.SEVR" not in db
    assert "Disconnected" in db
    assert "Connected" in db
    assert "Error" in db
```

Run:

```bash
python -m pytest tests/test_ioc_layout.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_ioc_layout.py ls336App/Db/ls336.db
git commit -m "feat: summarize IOC communication state"
```

### Task 6: Add the pseudo-terminal Model 336 emulator

**Files:**
- Create: `scripts/ls336_ioc_mock.py`
- Create: `tests/test_ioc_integration.py`
- Modify: `scripts/run_tests.sh`

- [ ] **Step 1: Write unit tests for command parsing and mutable state**

Define tests that instantiate `Model336State` directly:

```python
def test_mock_answers_queries_and_applies_writes():
    state = Model336State()

    assert state.handle("*IDN?").startswith("LSCI,MODEL336")
    assert state.handle("KRDG? A") == "+4.200"
    assert state.handle("OUTMODE? 1") == "1,1,1"
    assert state.handle("RAMP? 1") == "1,1.500"

    assert state.handle("SETP 1,25.000") is None
    assert state.handle("RAMP 1,0,2.500") is None
    assert state.handle("RANGE 1,3") is None

    assert state.handle("SETP? 1") == "25.000"
    assert state.handle("RAMP? 1") == "0,2.500"
    assert state.handle("RANGE? 1") == "3"
```

- [ ] **Step 2: Implement deterministic instrument state**

`Model336State.handle(command)` must:

- Return CRLF-terminated query data through the server layer.
- Store every received command in order.
- Return fixed A-D temperatures, PID, heater output, identity, and output mode.
- Mutate setpoint, RAMP enable/rate, and range only for valid command syntax.
- Raise `ValueError` for unsupported commands so tests detect accidental protocol expansion.

- [ ] **Step 3: Implement the Linux pseudo-terminal server**

Use `pty.openpty()`, set the slave side to raw mode, print the slave path as the first stdout line, and process CR/LF-delimited commands until SIGTERM. Add `--command-log PATH`; append one JSON object per command:

```json
{"command":"RAMP? 1","response":"1,1.500"}
```

Flush the log after every line so the integration test can inspect it while the IOC is running.

- [ ] **Step 4: Add platform and build detection to the integration test**

At module level:

```python
pytestmark = pytest.mark.skipif(
    os.name != "posix" or not Path("bin/linux-x86_64/ls336").exists(),
    reason="requires a built Linux IOC under WSL",
)
```

Resolve `caget` and `caput` from `EPICS_BASE` in `configure/RELEASE.local`. Fail with a clear assertion if the configured binaries are absent.

- [ ] **Step 5: Expose an explicit integration-test switch**

Update `scripts/run_tests.sh` so:

```bash
bash scripts/run_tests.sh
```

runs the normal suite, while:

```bash
bash scripts/run_tests.sh --ioc-integration
```

runs `python3 -m pytest -q tests/test_ioc_integration.py -rs`.

- [ ] **Step 6: Run emulator unit tests**

Run:

```bash
python -m pytest tests/test_ioc_integration.py -q
```

Expected on Windows: skipped with `requires a built Linux IOC under WSL`. Expected inside a built WSL checkout: emulator-only tests pass before IOC process tests are added.

- [ ] **Step 7: Commit**

```bash
git add scripts/ls336_ioc_mock.py tests/test_ioc_integration.py scripts/run_tests.sh
git commit -m "test: add Model 336 pseudo-terminal emulator"
```

### Task 7: Prove startup safety, numeric rejection, and RAMP preservation

**Files:**
- Modify: `tests/test_ioc_integration.py`
- Test: `tests/test_ioc_integration.py`

- [ ] **Step 1: Add an IOC fixture**

The fixture must:

1. Start the emulator and read its pseudo-terminal path.
2. Start `bin/linux-x86_64/ls336 st.cmd` from `iocBoot/iocLS336` with `TTY` set to that path and `PREFIX=LS336TEST:`.
3. Wait until `caget LS336TEST:IDN` succeeds.
4. Yield the CA command helpers and command-log path.
5. Send `exit` to IOC stdin, then terminate remaining child processes in `finally`.

- [ ] **Step 2: Verify aliases and startup read-only behavior**

```python
def test_startup_reads_state_without_writing_controls(running_ioc):
    assert running_ioc.caget("LS336TEST:ColdHead:TEMP_RBV") == pytest.approx(4.2)
    assert running_ioc.caget("LS336TEST:Sample:TEMP_RBV") == pytest.approx(10.0)

    commands = running_ioc.commands()
    assert "KRDG? A" in commands
    assert "KRDG? B" in commands
    assert not any(
        command.startswith(("SETP 1,", "RAMP 1,", "RANGE 1,"))
        for command in commands
    )
```

- [ ] **Step 3: Verify both valid boundaries are transmitted**

Write 0 and 350 K, then 0 and 10 K/min. Assert the command log contains each boundary command after its `caput`.

- [ ] **Step 4: Prove invalid values never reach the serial device**

For setpoint `-0.001` and `350.001`, ramp rate `-0.001` and `10.001`, and heater range `4`:

1. Record the command-log length.
2. Run `caput`.
3. Wait 200 ms.
4. Assert no new `SETP 1,`, `RAMP 1,`, or `RANGE 1,` command exists.
5. Assert `.STAT` is `DISABLE` and `.SEVR` is `INVALID`.
6. Assert `LS336TEST:ERR` contains the corresponding limit message.

- [ ] **Step 5: Prove RAMP writes preserve the other hardware field**

Start from emulator state `enable=1, rate=1.500`:

```text
caput LS336TEST:Loop1:RAMP:RATE 2.5
```

must produce consecutive commands:

```text
RAMP? 1
RAMP 1,1,2.500000
```

Then:

```text
caput LS336TEST:Loop1:RAMP:ENABLE 0
```

must produce:

```text
RAMP? 1
RAMP 1,0,2.500000
```

Accept equivalent non-lossy floating-point formatting, but require the parsed numeric value to equal 2.5.

- [ ] **Step 6: Build and run the integration suite in WSL**

Run:

```bash
make
bash scripts/run_tests.sh --ioc-integration
```

Expected: all IOC integration tests pass, with no skips.

- [ ] **Step 7: Commit**

```bash
git add tests/test_ioc_integration.py
git commit -m "test: verify IOC command safety and ramp semantics"
```

### Task 8: Document commissioning and run final verification

**Files:**
- Modify: `README.md`
- Test: `tests/test_ioc_layout.py`

- [ ] **Step 1: Add the Phase 1 public PV table and operating boundary**

Document:

- IOC is the only process allowed to open the Model 336 connection.
- Stop the IOC before using the direct web dashboard or portable ZIP.
- Canonical A-D PVs and A/B compatibility aliases.
- Loop 1 readbacks and the three writable controls.
- PID and control input are read-only.
- Setpoint 0-350 K and ramp rate 0-10 K/min.
- Startup sends queries only.

- [ ] **Step 2: Add mock and hardware test commands**

Include:

```bash
pytest -q
make
bash scripts/run_tests.sh --ioc-integration
cd iocBoot/iocLS336
../../bin/linux-x86_64/ls336 st.cmd
```

Include safe client examples:

```bash
caget LS336:Input:A:TEMP_RBV
caget LS336:Loop1:SETP_RBV
caput LS336:Loop1:SETP 100
caput LS336:Loop1:RAMP:RATE 1
caput LS336:Loop1:RAMP:ENABLE 1
```

State that heater-range changes require beamline-approved hardware conditions.

- [ ] **Step 3: Update documentation assertions**

Extend `test_documentation_matches_current_public_workflow` with the canonical A-D PV, `OUTMODE? 1`, integration-test command, startup-query-only statement, and IOC/direct-dashboard mutual-exclusion statement.

- [ ] **Step 4: Run repository tests**

Run:

```bash
pytest -q
```

Expected: all tests pass; the WSL-only IOC integration module is skipped on Windows.

- [ ] **Step 5: Run WSL build and readiness checks**

Run:

```bash
make clean
make
bash scripts/check_ioc_ready.sh
bash scripts/run_tests.sh --ioc-integration
```

Expected: IOC binary generated, readiness checks pass, and all integration tests pass.

- [ ] **Step 6: Inspect the final diff**

Run:

```bash
git diff --check
git status --short
git diff --stat
```

Expected: no whitespace errors and only intended Phase 1 files changed.

- [ ] **Step 7: Commit documentation**

```bash
git add README.md tests/test_ioc_layout.py
git commit -m "docs: add simplified IOC commissioning guide"
```

## Hardware Acceptance Gate

The pseudo-terminal suite is required before hardware testing. On the real Model 336:

1. Confirm 57600 baud, 7 data bits, odd parity, one stop bit, no flow control.
2. Start the IOC and inspect asyn trace or an external capture to confirm no `SETP`, `RAMP`, or `RANGE` write occurs during startup.
3. Compare IDN, A-D temperatures, control input, setpoint, RAMP, range, heater output, and PID against the front panel.
4. Use only beamline-approved setpoint, RAMP, and range values.
5. Verify each command through its independent `_RBV`.
6. Disconnect USB and confirm record alarms plus `COMM:STATUS`.
7. Reconnect USB and confirm periodic scans recover without restarting the IOC.
