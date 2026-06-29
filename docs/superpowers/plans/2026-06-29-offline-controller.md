# Lake Shore 336 Offline Controller Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct static DEMO timestamps, verify hardware-control behavior, and produce a tested offline Windows package.

**Architecture:** Keep the Python HTTP service and static dashboard as the control application. Add a small browser-side Beijing formatter, expose the backend's Beijing last-write timestamp, and make the existing PyInstaller directory build deterministic and free of archived experiment data.

**Tech Stack:** Python 3, `http.server`, pyserial, HTML/CSS/JavaScript, pytest, PyInstaller, Windows batch and PowerShell.

---

### Task 1: Static DEMO Beijing timestamps

**Files:**
- Modify: `tests/test_ioc_layout.py`
- Modify: `web/index.html`

- [ ] **Step 1: Write the failing static timestamp test**

Add assertions that the static dashboard defines `beijingIsoTime`, records both `timestamp_iso` and `timestamp_local`, and uses a CSV header containing both fields:

```python
assert "function beijingIsoTime(" in web
assert "timestamp_iso','timestamp_local" in web
assert "beijingIsoTime()" in web
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```powershell
pytest tests/test_ioc_layout.py -k web_dashboard -q
```

Expected: failure because the static dashboard currently records only `new Date().toISOString()`.

- [ ] **Step 3: Implement the browser formatter and CSV fields**

Implement a formatter based on `Intl.DateTimeFormat(..., {timeZone: "Asia/Shanghai"})` that emits `YYYY-MM-DDTHH:mm:ss+08:00`. Add UTC and Beijing values to each local row, add both headers, and show Beijing time in the static log status.

- [ ] **Step 4: Run the focused test**

Run:

```powershell
pytest tests/test_ioc_layout.py -k web_dashboard -q
```

Expected: all selected tests pass.

### Task 2: Backend last-write timezone contract

**Files:**
- Modify: `tests/test_ioc_layout.py`
- Modify: `scripts/ls336_web_dashboard.py`
- Modify: `web/index.html`

- [ ] **Step 1: Write the failing backend status test**

Import `LogArchive` in a focused test, append DEMO values, and assert:

```python
status["last_write_iso"].endswith("+00:00")
status["last_write_local"].endswith("+08:00")
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```powershell
pytest tests/test_ioc_layout.py -k beijing_last_write -q
```

Expected: failure with missing `last_write_local`.

- [ ] **Step 3: Add the local status field**

Store `last_write_local` when writing each row, return it from `LogArchive.status()`, and make the browser prefer it over `last_write_iso`.

- [ ] **Step 4: Run the focused test**

Run:

```powershell
pytest tests/test_ioc_layout.py -k beijing_last_write -q
```

Expected: pass.

### Task 3: Control-path regression coverage

**Files:**
- Modify: `tests/test_ioc_layout.py`

- [ ] **Step 1: Add direct DEMO control behavior tests**

Load `DemoLakeShoreClient`, apply safe channel mapping and combined control values, then assert the readback reports the requested setpoint, ramp rate, heater range, and control input. Also assert setpoint above 350 K and ramp above 10 K/min raise `ValueError`.

- [ ] **Step 2: Run the focused tests**

Run:

```powershell
pytest tests/test_ioc_layout.py -k "demo_control or safety" -q
```

Expected: tests pass against the existing implementation; any mismatch becomes a required control-path correction before packaging.

### Task 4: Deterministic offline packaging

**Files:**
- Modify: `tests/test_ioc_layout.py`
- Modify: `scripts/build_package.bat`
- Create: `docs/offline_package_zh.md`
- Modify: `README.md`

- [ ] **Step 1: Write failing package contract assertions**

Assert that the build script does not use `--add-data "logs;logs"`, creates an empty distribution log directory, copies the offline guide, copies `START.bat`, and runs a package smoke test before ZIP creation.

- [ ] **Step 2: Run the package test and verify it fails**

Run:

```powershell
pytest tests/test_ioc_layout.py -k portable -q
```

Expected: failure because the current script packages the source `logs/` directory and has no smoke-test gate.

- [ ] **Step 3: Implement the clean package flow**

Build with bundled `web` and `tzdata`, create `dist\LakeShore336\logs`, copy `START.bat` and the Chinese offline guide, run `scripts/smoke_test_portable.py`, then ZIP the verified directory.

- [ ] **Step 4: Document deployment and second hardware test**

Document extraction, startup, COM-port selection, safe DEMO check, safe hardware control sequence, log location, maintenance password, and rollback to heater range Off.

- [ ] **Step 5: Run the package contract test**

Run:

```powershell
pytest tests/test_ioc_layout.py -k portable -q
```

Expected: pass.

### Task 5: Portable runtime smoke test

**Files:**
- Create: `scripts/smoke_test_portable.py`
- Modify: `tests/test_ioc_layout.py`

- [ ] **Step 1: Write a failing test for the smoke-test interface**

Assert the script accepts `--executable`, `--port`, and `--timeout`, starts the server, checks `/`, `/maintenance`, `/api/ports`, connects to DEMO, applies a safe control request, reads log status, and always terminates the process.

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```powershell
pytest tests/test_ioc_layout.py -k portable_smoke -q
```

Expected: failure because the script does not exist.

- [ ] **Step 3: Implement the smoke test**

Use only the Python standard library so it can run on the build computer without extra dependencies. Start the executable with `--no-open`, poll until ready, issue JSON requests, validate readbacks and archive files, then terminate the child process in `finally`.

- [ ] **Step 4: Run the Python test suite**

Run:

```powershell
pytest -q
```

Expected: all tests pass.

### Task 6: Build and runtime acceptance

**Files:**
- Generated: `dist/LakeShore336/`
- Generated: `dist/LakeShore336_portable.zip`

- [ ] **Step 1: Build the package**

Run:

```powershell
cmd /c scripts\build_package.bat
```

Expected: PyInstaller succeeds, runtime smoke test succeeds, and the ZIP is created.

- [ ] **Step 2: Inspect package contents**

Confirm the package contains the executable, launcher, offline guide, bundled web files, bundled timezone data, and an empty `logs/` directory before smoke testing.

- [ ] **Step 3: Verify the final ZIP**

Extract the ZIP to a temporary directory, run the packaged smoke test against its executable, and confirm a Beijing-date CSV with `timestamp_local` ending in `+08:00`.

- [ ] **Step 4: Run final source verification**

Run:

```powershell
pytest -q
python -m py_compile scripts\ls336_web_dashboard.py scripts\smoke_test_portable.py
```

Expected: all tests pass and both Python files compile.

