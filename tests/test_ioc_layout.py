import importlib.util
import re
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def record_block(db: str, name: str) -> str:
    match = re.search(
        rf'record\([^)]*, "{re.escape(name)}"\)\s*\{{.*?\n\}}',
        db,
        re.DOTALL,
    )
    assert match is not None, name
    return match.group(0)


def load_web_dashboard():
    path = ROOT / "scripts" / "ls336_web_dashboard.py"
    spec = importlib.util.spec_from_file_location("ls336_web_dashboard_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_database_exposes_simplified_phase_one_pvs():
    db = read("ls336App/Db/ls336.db")

    for record in [
        'record(stringin, "$(P)IDN")',
        'record(ai, "$(P)Input:A:TEMP_RBV")',
        'record(ai, "$(P)Input:B:TEMP_RBV")',
        'record(ai, "$(P)Input:C:TEMP_RBV")',
        'record(ai, "$(P)Input:D:TEMP_RBV")',
        'record(mbbi, "$(P)Loop1:INPUT_RBV")',
        'field(INP,  "@ls336.proto getTemperature(A) $(PORT)")',
        'field(INP,  "@ls336.proto getTemperature(B) $(PORT)")',
        'field(INP,  "@ls336.proto getTemperature(C) $(PORT)")',
        'field(INP,  "@ls336.proto getTemperature(D) $(PORT)")',
        'record(ao, "$(P)Loop1:SETP")',
        'record(ai, "$(P)Loop1:SETP_RBV")',
        'record(bo, "$(P)Loop1:RAMP:ENABLE")',
        'record(bi, "$(P)Loop1:RAMP:ENABLE_RBV")',
        'record(ao, "$(P)Loop1:RAMP:RATE")',
        'record(ai, "$(P)Loop1:RAMP:RATE_RBV")',
        'record(mbbo, "$(P)Loop1:RANGE")',
        'record(mbbi, "$(P)Loop1:RANGE_RBV")',
        'record(ai, "$(P)Loop1:HTR_RBV")',
        'record(ai, "$(P)Loop1:PID:P_RBV")',
        'record(ai, "$(P)Loop1:PID:I_RBV")',
        'record(ai, "$(P)Loop1:PID:D_RBV")',
        'record(mbbo, "$(P)COMM:STATUS")',
        'record(stringout, "$(P)ERR")',
        'alias("$(P)Input:A:TEMP_RBV", "$(P)ColdHead:TEMP_RBV")',
        'alias("$(P)Input:B:TEMP_RBV", "$(P)Sample:TEMP_RBV")',
    ]:
        assert record in db

    assert 'record(ai, "$(P)ColdHead:TEMP_RBV")' not in db
    assert 'record(ai, "$(P)Sample:TEMP_RBV")' not in db


def test_phase_one_readback_enums_use_approved_labels():
    db = read("ls336App/Db/ls336.db")

    input_block = record_block(db, "$(P)Loop1:INPUT_RBV")
    for snippet in [
        'field(ZRST, "None")',
        'field(ONST, "A")',
        'field(TWST, "B")',
        'field(THST, "C")',
        'field(FRST, "D")',
    ]:
        assert snippet in input_block

    range_block = record_block(db, "$(P)Loop1:RANGE_RBV")
    for snippet in [
        'field(ZRST, "Off")',
        'field(ONST, "Low")',
        'field(TWST, "Medium")',
        'field(THST, "High")',
    ]:
        assert snippet in range_block


def test_protocol_covers_phase_one_queries_writes_and_omits_init():
    proto = read("ls336App/protocol/ls336.proto")

    for command in [
        'getIDN {',
        'out "*IDN?";',
        'getTemperature {',
        'out "KRDG? \\$1";',
        'getControlInput {',
        'out "OUTMODE? 1";',
        'getSetpoint {',
        'out "SETP? 1";',
        'setSetpoint {',
        'out "SETP 1,%f";',
        'getRampEnable {',
        'getRampRate {',
        'out "RAMP? 1";',
        'getRange {',
        'out "RANGE? 1";',
        'setRange {',
        'out "RANGE 1,%d";',
        'getHeater {',
        'out "HTR? 1";',
        'getPidP {',
        'getPidI {',
        'getPidD {',
        'out "PID? 1";',
    ]:
        assert command in proto

    assert "@init" not in proto


def test_ramp_write_protocol_queries_and_preserves_the_other_field():
    proto = read("ls336App/protocol/ls336.proto")

    for snippet in [
        'setRampRate {',
        'setRampEnable {',
        'in "%(\\$1Loop1:RAMP:ENABLE:CACHE.VAL)d,%*f";',
        'out "RAMP 1,%(\\$1Loop1:RAMP:ENABLE:CACHE.VAL)d,%f";',
        'in "%*d,%(\\$1Loop1:RAMP:RATE:CACHE.VAL)f";',
        'out "RAMP 1,%d,%(\\$1Loop1:RAMP:RATE:CACHE.VAL)f";',
    ]:
        assert snippet in proto


def test_ramp_write_database_uses_private_caches_and_public_validation():
    db = read("ls336App/Db/ls336.db")

    for snippet in [
        'record(longin, "$(P)Loop1:RAMP:ENABLE:CACHE")',
        'record(ai, "$(P)Loop1:RAMP:RATE:CACHE")',
        'record(bo, "$(P)Loop1:RAMP:ENABLE")',
        'field(OUT,  "@ls336.proto setRampEnable($(P)) $(PORT)")',
        'record(ao, "$(P)Loop1:RAMP:RATE")',
        'field(OUT,  "@ls336.proto setRampRate($(P)) $(PORT)")',
        'field(EGU,  "K/min")',
        'field(PREC, "3")',
        'field(LOPR, "0")',
        'field(HOPR, "10")',
        'field(SDIS, "$(P)Loop1:RAMP:RATE:INVALID PP MS")',
        'field(DISV, "1")',
        'field(DISS, "INVALID")',
        'record(calcout, "$(P)Loop1:RAMP:RATE:INVALID")',
        'field(INPA, "$(P)Loop1:RAMP:RATE.VAL NPP NMS")',
        'field(CALC, "A<0||A>10")',
        'field(OOPT, "When Non-zero")',
        'field(OUT,  "$(P)ERR:RAMP.PROC PP")',
        'record(stringout, "$(P)ERR:RAMP")',
        'field(VAL,  "Ramp rate must be within 0..10 K/min")',
    ]:
        assert snippet in db


def test_startup_and_scan_contracts_match_phase_one_polling():
    db = read("ls336App/Db/ls336.db")
    startup = read("iocBoot/iocLS336/st.cmd")
    makefile = read("ls336App/src/Makefile")

    for pv_name in [
        "$(P)IDN",
        "$(P)Loop1:PID:P_RBV",
        "$(P)Loop1:PID:I_RBV",
        "$(P)Loop1:PID:D_RBV",
    ]:
        assert 'field(SCAN, "10 second")' in record_block(db, pv_name)

    for pv_name in [
        "$(P)Input:A:TEMP_RBV",
        "$(P)Input:B:TEMP_RBV",
        "$(P)Input:C:TEMP_RBV",
        "$(P)Input:D:TEMP_RBV",
        "$(P)Loop1:INPUT_RBV",
        "$(P)Loop1:SETP_RBV",
        "$(P)Loop1:RAMP:ENABLE_RBV",
        "$(P)Loop1:RAMP:RATE_RBV",
        "$(P)Loop1:RANGE_RBV",
        "$(P)Loop1:HTR_RBV",
    ]:
        assert 'field(SCAN, "2 second")' in record_block(db, pv_name)

    for pv_name in [
        "$(P)Loop1:SETP",
        "$(P)Loop1:RAMP:ENABLE",
        "$(P)Loop1:RAMP:RATE",
        "$(P)Loop1:RANGE",
    ]:
        assert 'field(PINI, "NO")' in record_block(db, pv_name)
    assert re.search(r"(?m)^\s*seq\b.*\.st(?:\s|$)", startup) is None
    assert ".st" not in makefile


def test_phase_one_deferred_scope_stays_out_of_the_database_and_boot():
    db = read("ls336App/Db/ls336.db")

    for exact_name in [
        '"$(P)Loop1:INPUT")',
        '"$(P)Loop1:PID:P")',
        '"$(P)Loop1:PID:I")',
        '"$(P)Loop1:PID:D")',
    ]:
        assert exact_name not in db

    for pv_name in ["APPLY", "CTRL:ENABLE", "WARMUP"]:
        assert f"$(P){pv_name}" not in db


def test_phase_one_safety_layout_uses_invalid_helpers_without_drv_limits():
    db = read("ls336App/Db/ls336.db")

    for snippet in [
        'field(SDIS, "$(P)Loop1:SETP:INVALID PP MS")',
        'field(SDIS, "$(P)Loop1:RAMP:RATE:INVALID PP MS")',
        'field(SDIS, "$(P)Loop1:RANGE:INVALID PP MS")',
        'field(DISS, "INVALID")',
        'field(CALC, "A<0||A>350")',
        'field(CALC, "A<0||A>10")',
        'field(CALC, "A<0||A>3")',
        'field(HOPR, "350")',
        'field(HOPR, "10")',
    ]:
        assert snippet in db

    assert db.count('field(DISS, "INVALID")') >= 3
    for pv_name in [
        "$(P)Loop1:SETP",
        "$(P)Loop1:RAMP:RATE",
    ]:
        block = record_block(db, pv_name)
        assert 'field(DRVH,' not in block
        assert 'field(DRVL,' not in block


def test_communication_status_uses_exact_severity_inputs_and_states():
    db = read("ls336App/Db/ls336.db")
    status_block = record_block(db, "$(P)COMM:STATUS")
    calc_block = record_block(db, "$(P)COMM:STATUS:CALC")

    for snippet in [
        'record(mbbo, "$(P)COMM:STATUS")',
        'field(ZRST, "Disconnected")',
        'field(ONST, "Connected")',
        'field(TWST, "Error")',
        'field(VAL,  "0")',
        'field(FLNK, "$(P)COMM:STATUS:ERROR")',
    ]:
        assert snippet in status_block
    assert 'field(DTYP,' not in status_block

    for snippet in [
        'field(INPA, "$(P)IDN.SEVR CP MS")',
        'field(INPB, "$(P)Input:A:TEMP_RBV.SEVR CP MS")',
        'field(INPC, "$(P)Input:B:TEMP_RBV.SEVR CP MS")',
        'field(INPD, "$(P)Input:C:TEMP_RBV.SEVR CP MS")',
        'field(INPE, "$(P)Input:D:TEMP_RBV.SEVR CP MS")',
        'field(INPF, "$(P)Loop1:INPUT_RBV.SEVR CP MS")',
        'field(INPG, "$(P)Loop1:SETP_RBV.SEVR CP MS")',
        'field(INPH, "$(P)Loop1:RAMP:ENABLE_RBV.SEVR CP MS")',
        'field(INPI, "$(P)Loop1:RAMP:RATE_RBV.SEVR CP MS")',
        'field(INPJ, "$(P)Loop1:RANGE_RBV.SEVR CP MS")',
        'field(INPK, "$(P)Loop1:HTR_RBV.SEVR CP MS")',
        'field(CALC, "A>0?0:(B>0||C>0||D>0||E>0||F>0||G>0||H>0||I>0||J>0||K>0?2:1)")',
        'field(OOPT, "Every Time")',
        'field(OUT,  "$(P)COMM:STATUS PP")',
        'field(SCAN, "2 second")',
    ]:
        assert snippet in calc_block

    for snippet in [
        "PID:P_RBV.SEVR",
        "PID:I_RBV.SEVR",
        "PID:D_RBV.SEVR",
        "RAMP:ENABLE_RBV_RAW.SEVR",
        "RAMP:ENABLE:CACHE",
        "RAMP:RATE:CACHE",
    ]:
        assert snippet not in calc_block


def test_communication_error_helper_writes_short_summary_to_public_err():
    db = read("ls336App/Db/ls336.db")

    helper_block = record_block(db, "$(P)COMM:STATUS:ERROR")
    err_block = record_block(db, "$(P)ERR:COMM")

    for snippet in [
        'record(calcout, "$(P)COMM:STATUS:ERROR")',
        'field(INPA, "$(P)COMM:STATUS NPP NMS")',
        'field(CALC, "A!=1")',
        'field(OOPT, "When Non-zero")',
        'field(OUT,  "$(P)ERR:COMM.PROC PP")',
    ]:
        assert snippet in helper_block

    for snippet in [
        'record(stringout, "$(P)ERR:COMM")',
        'field(VAL,  "Communication failure; inspect record STAT/SEVR")',
        'field(OUT,  "$(P)ERR PP")',
    ]:
        assert snippet in err_block


def test_startup_script_configures_serial_port_for_wsl_defaults():
    startup = read("iocBoot/iocLS336/st.cmd")

    assert 'epicsEnvSet("PORT", "$(PORT=LS336_PORT)")' in startup
    assert 'epicsEnvSet("TTY", "$(TTY=/dev/ttyUSB0)")' in startup
    assert 'epicsEnvSet("PREFIX", "$(PREFIX=LS336:)")' in startup
    assert 'drvAsynSerialPortConfigure("$(PORT)", "$(TTY)", 0, 0, 0)' in startup
    expected_serial_block = """asynSetOption("$(PORT)", 0, "baud", "57600")
asynSetOption("$(PORT)", 0, "bits", "7")
asynSetOption("$(PORT)", 0, "parity", "odd")
asynSetOption("$(PORT)", 0, "stop", "1")
asynSetOption("$(PORT)", 0, "clocal", "Y")
asynSetOption("$(PORT)", 0, "crtscts", "N")"""
    assert expected_serial_block in startup


def test_pty_termios_shim_fixture_advertises_lakeshore_serial_settings():
    shim = read("tests/fixtures/pty_termios_shim.c")

    for snippet in [
        "int ioctl(int fd, unsigned long request, ...)",
        "int tcsetattr(int fd, int optional_actions, const struct termios *t)",
        'strncmp(target, "/dev/pts/", 9) == 0',
        "request == TCGETS",
        "t->c_ispeed = B57600;",
        "t->c_ospeed = B57600;",
        "t->c_cflag |= PARENB | PARODD | CLOCAL | CREAD;",
        "t->c_cflag &= ~CSIZE;",
        "t->c_cflag |= CS7;",
        "t->c_cflag &= ~CSTOPB;",
    ]:
        assert snippet in shim

    assert "CRTSCTS" in shim


def test_ioc_source_makefile_builds_main_and_links_tirpc():
    makefile = read("ls336App/src/Makefile")
    main = read("ls336App/src/ls336Main.cpp")

    assert "ls336_DBD += drvAsynSerialPort.dbd" in makefile
    assert "ls336_SRCS += ls336Main.cpp" in makefile
    assert "ls336_SYS_LIBS_Linux += tirpc" in makefile
    assert "ls336_registerRecordDeviceDriver(pdbbase)" in main
    assert "ls336_registerRecordDeviceDriver.h" not in main


def test_direct_dashboards_do_not_expose_rhythm_or_warmup_controls():
    for content in [
        read("scripts/ls336_web_dashboard.py"),
        read("scripts/ls336_direct_dashboard.py"),
        read("scripts/ls336_dashboard.py"),
        read("web/index.html"),
        read("README.md"),
        read("docs/operator_tutorial_zh.md"),
        read("scripts/check_ioc_ready.sh"),
    ]:
        for term in [
            "Rhythm",
            "rhythm",
            "Warmup",
            "warmup",
            "WARMUP",
            "Start Rhythm",
            "Advance One Step",
            "/api/step",
        ]:
            assert term not in content


def test_web_dashboard_auto_archives_temperature_logs_with_maintenance_controls():
    dashboard = read("scripts/ls336_web_dashboard.py")
    demo = read("web/index.html")
    gitignore = read(".gitignore")

    for snippet in [
        'LOG_DIR = ROOT / "logs"',
        'DEFAULT_MAINT_PASSWORD = "ls336-maint"',
        'BEIJING_TZ = ZoneInfo("Asia/Shanghai")',
        "class LogArchive",
        "class MaintenanceAuth",
        "today_key",
        "ls336_temperature_",
        ".meta.json",
        "CSV_FIELDS",
        "timestamp_local",
        "started_local",
        "cold_head_K",
        "sample_K",
        "setpoint_K",
        "ramp_enable",
        "ramp_rate_K_per_min",
        "heater_range",
        "heater_percent",
        "pid_p",
        "pid_i",
        "pid_d",
        "stable_state",
        "LOGGER.start_session",
        '"timezone": "Asia/Shanghai"',
        "/api/log/status",
        "/api/log/download",
        "/api/log/pause",
        "/api/log/resume",
        "/api/log/new",
        "/api/maintenance/login",
        "/api/pid",
        "LS336_MAINT_PASSWORD",
        "PID 1,",
        "pid_write",
        "Content-Disposition",
    ]:
        assert snippet in dashboard

    for snippet in [
        "timestamp_iso",
        "last_write_iso",
        "started_iso",
        "utc_now",
    ]:
        assert snippet not in dashboard

    for snippet in [
        "CSV File",
        "Rows Written",
        "Last Write",
        "Download CSV",
        "Maintenance",
        "Demo mode",
        "ls336_static_demo_temporary_log.csv",
    ]:
        assert snippet in demo

    for snippet in [
        "START LOG",
        "STOP LOG",
        "LOG FOLDER",
        "/api/log/pause",
        "/api/log/resume",
        "/api/pid",
        "Confirm PID Write",
    ]:
        assert snippet not in demo

    assert "logs/" in gitignore


def test_static_demo_csv_contains_only_beijing_timestamp():
    demo = read("web/index.html")

    assert "function beijingIsoTime(" in demo
    assert "beijingIsoTime()" in demo
    assert "'timestamp_local','cold_head_K'" in demo
    assert "timestamp_iso" not in demo
    assert "new Date().toISOString()" not in demo


def test_backend_log_status_exposes_beijing_last_write():
    dashboard = load_web_dashboard()
    with TemporaryDirectory(dir=ROOT) as temp_dir:
        archive = dashboard.LogArchive(Path(temp_dir))
        client = dashboard.DemoLakeShoreClient()

        archive.start_session("DEMO", "demo")
        archive.append(client.read_all())
        status = archive.status()

        assert "last_write_iso" not in status
        assert str(status["last_write_local"]).endswith("+08:00")


def test_demo_control_returns_requested_readbacks_and_rejects_unsafe_values():
    dashboard = load_web_dashboard()
    client = dashboard.DemoLakeShoreClient()

    values = client.set_control(95.0, 1.25, 2, "B", "A", "A")

    assert values["setpoint"] == "95.000"
    assert values["ramp_enable"] == "On"
    assert values["ramp_rate"] == "1.250"
    assert values["heater_range_raw"] == "2"
    assert values["heater_range"] == "Medium"
    assert values["cold_input"] == "B"
    assert values["sample_input"] == "A"
    assert values["control_input"] == "A"

    with pytest.raises(ValueError, match="0..350 K"):
        client.set_control(351.0, 1.0, 1, "A", "B", "B")
    with pytest.raises(ValueError, match="0..10 K/min"):
        client.set_control(95.0, 10.1, 1, "A", "B", "B")
    with pytest.raises(ValueError, match="Heater range"):
        client.set_control(95.0, 1.0, 4, "A", "B", "B")


def test_web_dashboard_keeps_command_inputs_separate_from_readbacks():
    demo = read("web/index.html")
    update_body = demo.split("function update(d){", 1)[1].split("// 鈹€鈹€ Stability", 1)[0]

    for snippet in [
        "setIfNotEditing('target',d.setpoint)",
        "setIfNotEditing('ramp',d.ramp_rate)",
        "setIfNotEditing('range',d.heater_range_raw)",
        "document.getElementById('enable_ramp').checked=(d.ramp_enable",
    ]:
        assert snippet not in update_body

    assert "function syncCommandInputsFromReadback(d)" in demo
    assert "syncCommandInputsFromReadback(d);" in demo
    assert "logControlReadback(body,result)" in demo
    assert "pendingControlRequest" in demo


def test_serial_control_writes_only_control_commands_with_pacing(monkeypatch):
    dashboard = load_web_dashboard()
    writes: list[str] = []
    sleeps: list[float] = []

    class FakeSerialClient(dashboard.LakeShoreSerialClient):
        def __init__(self) -> None:
            self._lock = dashboard.threading.RLock()
            self.cold_input = "A"
            self.sample_input = "B"
            self.control_input = "B"

        def _raw_write(self, command: str) -> None:
            writes.append(command)

        def read_all(self) -> dict[str, str]:
            return {
                "setpoint": "95.000",
                "ramp_enable": "On",
                "ramp_rate": "1.250",
                "heater_range_raw": "2",
                "heater_range": "Medium",
            }

    monkeypatch.setattr(dashboard.time, "sleep", lambda seconds: sleeps.append(seconds))

    values = FakeSerialClient().set_control(95.0, 1.25, 2, "B", "A", "A")

    assert writes == ["CSET 1,A,1,1", "RANGE 1,2", "RAMP 1,1,1.250", "SETP 1,95.000"]
    assert "PID 1," not in " ".join(writes)
    assert sleeps == [dashboard.COMMAND_PACE_SECONDS] * 4
    assert values["requested_setpoint"] == "95.000"
    assert values["requested_ramp_rate"] == "1.250"
    assert values["requested_heater_range_raw"] == "2"


def test_portable_build_script_creates_clean_verified_offline_package():
    build = read("scripts/build_package.bat")

    assert '--add-data "logs;logs"' not in build
    assert 'mkdir "dist\\LakeShore336\\logs"' in build
    assert 'copy /Y "scripts\\run_portable.bat" "dist\\LakeShore336\\START.bat" >nul || exit /b 1' in build
    assert 'copy /Y "docs\\offline_package_zh.md" "dist\\LakeShore336\\OFFLINE_GUIDE_ZH.md" >nul || exit /b 1' in build
    assert "docs\\offline_package_zh.md" in build
    assert "scripts\\smoke_test_portable.py" in build
    assert "scripts\\create_portable_zip.py" in build
    assert "LakeShore336_portable.zip" in build


def test_portable_smoke_test_checks_pages_control_and_archiving():
    smoke = read("scripts/smoke_test_portable.py")

    for snippet in [
        "--executable",
        "--port",
        "--timeout",
        "/maintenance",
        "/api/ports",
        "/api/connect",
        "/api/control",
        "/api/log/status",
        "last_write_local",
        "terminate",
    ]:
        assert snippet in smoke


def test_documentation_matches_current_public_workflow():
    readme = read("README.md")
    tutorial = read("docs/operator_tutorial_zh.md")

    for snippet in [
        "The EPICS IOC is the sole hardware connection owner in Phase 1.",
        "Direct Windows dashboards, the local web dashboard, and the portable ZIP package may only talk to hardware while the IOC is stopped.",
        "Phase 1 does not convert the existing logger into EPICS records.",
        "`OUTMODE? 1` only to publish the read-only `LS336:Loop1:INPUT_RBV` state.",
        "The EPICS IOC does not write `CSET` in Phase 1.",
        "Startup sends queries only and never issues `SETP`, `RAMP`, or `RANGE`.",
        "All public output records use `PINI` = `NO`",
        "A successful command PV write only confirms IOC processing; it is not hardware confirmation.",
        "Independent readback PVs such as `LS336:Loop1:SETP_RBV`, `LS336:Loop1:RAMP:ENABLE_RBV`, `LS336:Loop1:RAMP:RATE_RBV`, and `LS336:Loop1:RANGE_RBV` are authoritative.",
        "`LS336:Loop1:SETP` accepts `0..350 K`.",
        "`LS336:Loop1:RAMP:RATE` accepts `0..10 K/min`.",
        "`LS336:Loop1:RANGE` accepts `0..3`.",
        "Out-of-range writes are blocked by `SDIS` before StreamDevice sends any serial command.",
        "The integration tests check for zero serial output on rejected `SETP`, `RAMP`, and `RANGE` writes.",
        "Changing `LS336:Loop1:RAMP:RATE` first queries `RAMP? 1` and preserves the current hardware enable bit.",
        "Changing `LS336:Loop1:RAMP:ENABLE` first queries `RAMP? 1` and preserves the current hardware rate.",
        "Each update is emitted as one locked StreamDevice transaction.",
        "`pytest -q`",
        "`make`",
        "`bash scripts/run_tests.sh --ioc-integration`",
        "`wsl -d Ubuntu-24.04 -- bash -lc 'cd /mnt/d/Projects/LakeShore336 && bash scripts/run_tests.sh --ioc-integration'`",
        "The PTY shim is test-only; production `iocBoot/iocLS336/st.cmd` keeps the real controller at `57600 7O1`.",
        "server-side CSV archiving",
        "starts recording automatically",
        "ordinary operator page only shows recording status",
        "DOWNLOAD CSV",
        "ls336_temperature_YYYYMMDD.csv",
        "Beijing-time daily pattern",
        "Asia/Shanghai",
        "LS336_MAINT_PASSWORD",
        "ls336-maint",
        "/maintenance",
        "PID writes require confirmation",
        "meta.json",
        "LS336:IDN",
        "LS336:Input:A:TEMP_RBV",
        "LS336:Input:B:TEMP_RBV",
        "LS336:Input:C:TEMP_RBV",
        "LS336:Input:D:TEMP_RBV",
        "LS336:ColdHead:TEMP_RBV",
        "LS336:Sample:TEMP_RBV",
        "LS336:Loop1:INPUT_RBV",
        "LS336:Loop1:PID:P_RBV",
        "LS336:Loop1:PID:I_RBV",
        "LS336:Loop1:PID:D_RBV",
        "`Disconnected`, `Connected`, and `Error`",
        "caget LS336:Input:A:TEMP_RBV",
        "caget LS336:Input:B:TEMP_RBV",
        "caget LS336:Input:C:TEMP_RBV",
        "caget LS336:Input:D:TEMP_RBV",
        "caget LS336:ColdHead:TEMP_RBV",
        "caget LS336:Loop1:INPUT_RBV",
        "caput LS336:Loop1:SETP 300",
        "caput LS336:Loop1:RAMP:ENABLE 1",
        "caput LS336:Loop1:RAMP:RATE 1",
        "caput LS336:Loop1:RANGE 1",
        "caget LS336:Loop1:SETP_RBV",
        "caget LS336:Loop1:RAMP:ENABLE_RBV",
        "caget LS336:Loop1:RAMP:RATE_RBV",
        "caget LS336:Loop1:RANGE_RBV",
        "caget LS336:Loop1:HTR_RBV",
        "Use `Low` or `Off` until heater commissioning says otherwise.",
        "Stop the IOC before opening the direct Windows dashboard, the local web dashboard, or the portable packaged app against the same controller.",
        "If the serial link drops, confirm `LS336:COMM:STATUS`, reconnect the USB/serial path, and wait for the authoritative RBVs to recover before sending another command.",
    ]:
        assert snippet in readme

    for snippet in [
        "温度日志归档",
        "连接成功后会自动开始记录",
        "北京时间",
        "Asia/Shanghai",
        "logs/",
        "meta.json",
        "维护页面",
        "LS336_MAINT_PASSWORD",
        "PID 写入属于高风险维护操作",
        "CSV 没有写入",
    ]:
        assert snippet in tutorial


def test_wsl_setup_script_installs_epics_stack_and_writes_release_local():
    script = read("scripts/setup_epics_wsl.sh")

    for snippet in [
        "EPICS_ROOT=${EPICS_ROOT:-/opt/epics}",
        "EPICS_BASE_TAG=${EPICS_BASE_TAG:-R7.0.8.1}",
        "ASYN_TAG=${ASYN_TAG:-R4-44}",
        "STREAM_TAG=${STREAM_TAG:-2.8.24}",
        "configure/RELEASE.local",
        "libtirpc-dev",
        "libpcre3-dev",
        "PCRE_MULTIARCH",
        "USR_INCLUDES_Linux += -I/usr/include/tirpc",
        "SYS_LIBS_Linux += tirpc",
        "PCRE_INCLUDE=/usr/include",
        "PCRE_LIB=/usr/lib/${PCRE_MULTIARCH}",
    ]:
        assert snippet in script
