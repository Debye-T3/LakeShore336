from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_database_exposes_required_public_pvs():
    db = read("ls336App/Db/ls336.db")

    expected_records = [
        'record(ai, "$(P)ColdHead:TEMP_RBV")',
        'record(ai, "$(P)Sample:TEMP_RBV")',
        'record(ao, "$(P)Loop1:SETP")',
        'record(ai, "$(P)Loop1:SETP_RBV")',
        'record(ao, "$(P)Loop1:WARMUP:TARGET")',
        'record(ao, "$(P)Loop1:WARMUP:STEP")',
        'record(longout, "$(P)Loop1:WARMUP:STEP:5K")',
        'record(longout, "$(P)Loop1:WARMUP:STEP:10K")',
        'record(calcout, "$(P)Loop1:WARMUP:NEXT")',
        'record(bo, "$(P)Loop1:RAMP:ENABLE")',
        'record(bi, "$(P)Loop1:RAMP:ENABLE_RBV")',
        'record(ao, "$(P)Loop1:RAMP:RATE")',
        'record(ai, "$(P)Loop1:RAMP:RATE_RBV")',
        'record(ai, "$(P)Loop1:HTR_RBV")',
        'record(mbbo, "$(P)COMM:STATUS")',
        'record(stringout, "$(P)ERR")',
    ]

    for record in expected_records:
        assert record in db


def test_database_enforces_conservative_write_limits():
    db = read("ls336App/Db/ls336.db")

    assert 'field(DRVH, "350")' in db
    assert 'field(HOPR, "350")' in db
    assert 'field(DRVH, "10")' in db
    assert 'field(HOPR, "10")' in db
    assert "validate_setpoint" in db
    assert "validate_ramp_rate" in db
    assert 'field(OUT,  "$(P)ERR PP")' in db
    assert "Setpoint must be within 0..350 K" in db
    assert "Ramp rate must be within 0..10 K/min" in db


def test_database_supports_stepwise_warmup_control():
    db = read("ls336App/Db/ls336.db")

    for snippet in [
        'field(DESC, "Warmup target temperature")',
        'field(DESC, "Warmup setpoint step size")',
        'field(VAL,  "5")',
        'field(DESC, "Select 5 K warmup step")',
        'field(DESC, "Select 10 K warmup step")',
        'field(VAL,  "10")',
        'field(OUT,  "$(P)Loop1:WARMUP:STEP PP")',
        'field(INPA, "$(P)Loop1:SETP_RBV NPP NMS")',
        'field(INPB, "$(P)Loop1:WARMUP:STEP NPP NMS")',
        'field(INPC, "$(P)Loop1:WARMUP:TARGET NPP NMS")',
        'field(CALC, "C>A?(A+B<C?A+B:C):A")',
        'field(OUT,  "$(P)Loop1:SETP PP")',
    ]:
        assert snippet in db


def test_database_derives_communication_status_from_readback_alarms():
    db = read("ls336App/Db/ls336.db")

    assert 'field(INPA, "$(P)ColdHead:TEMP_RBV.SEVR CP MS")' in db
    assert 'field(INPB, "$(P)Sample:TEMP_RBV.SEVR CP MS")' in db
    assert 'field(INPC, "$(P)Loop1:SETP_RBV.SEVR CP MS")' in db
    assert 'field(INPD, "$(P)Loop1:RAMP:RATE_RBV.SEVR CP MS")' in db
    assert 'field(INPE, "$(P)Loop1:RAMP:ENABLE_RBV_RAW.SEVR CP MS")' in db
    assert 'field(INPF, "$(P)Loop1:HTR_RBV.SEVR CP MS")' in db
    assert 'field(CALC, "A>0||B>0||C>0||D>0||E>0||F>0?2:1")' in db
    assert 'field(OUT,  "$(P)COMM:STATUS PP")' in db


def test_protocol_contains_lakeshore_336_commands():
    proto = read("ls336App/protocol/ls336.proto")

    expected_commands = [
        'out "*IDN?"',
        'out "KRDG? A"',
        'out "KRDG? B"',
        'out "SETP? 1"',
        'out "SETP 1,%f"',
        'out "RAMP? 1"',
        'out "RAMP 1,%(\\$1Loop1:RAMP:ENABLE.VAL)d,%f"',
        'out "HTR? 1"',
    ]

    for command in expected_commands:
        assert command in proto


def test_startup_script_configures_serial_port_for_wsl_defaults():
    startup = read("iocBoot/iocLS336/st.cmd")

    assert 'epicsEnvSet("PORT", "$(PORT=LS336_PORT)")' in startup
    assert 'epicsEnvSet("TTY", "$(TTY=/dev/ttyUSB0)")' in startup
    assert 'epicsEnvSet("PREFIX", "$(PREFIX=LS336:)")' in startup
    assert 'drvAsynSerialPortConfigure("$(PORT)", "$(TTY)", 0, 0, 0)' in startup
    assert 'asynSetOption("$(PORT)", 0, "baud", "57600")' in startup
    assert 'asynSetOption("$(PORT)", 0, "bits", "7")' in startup
    assert 'asynSetOption("$(PORT)", 0, "parity", "odd")' in startup
    assert 'asynSetOption("$(PORT)", 0, "stop", "1")' in startup


def test_epics_config_loads_release_before_epics_base_config():
    config = read("configure/CONFIG")

    assert "include $(TOP)/configure/RELEASE" in config
    assert "include $(EPICS_BASE)/configure/CONFIG" in config
    assert config.index("include $(TOP)/configure/RELEASE") < config.index(
        "include $(EPICS_BASE)/configure/CONFIG"
    )


def test_epics_configure_directory_has_install_makefile():
    makefile = read("configure/Makefile")
    rules = read("configure/RULES")
    rules_dirs = read("configure/RULES_DIRS")
    rules_ioc = read("configure/RULES.ioc")

    for snippet in [
        "TOP = ..",
        "include $(TOP)/configure/CONFIG",
        "TARGETS = $(CONFIG_TARGETS)",
        "include $(TOP)/configure/RULES",
    ]:
        assert snippet in makefile

    assert "include $(EPICS_BASE)/configure/RULES" in rules
    assert "include $(EPICS_BASE)/configure/RULES_DIRS" in rules_dirs
    assert "include $(EPICS_BASE)/configure/RULES.ioc" in rules_ioc


def test_ioc_source_makefile_builds_main_and_links_tirpc():
    makefile = read("ls336App/src/Makefile")
    main = read("ls336App/src/ls336Main.cpp")

    for snippet in [
        "ls336_DBD += drvAsynSerialPort.dbd",
        "ls336_SRCS += ls336Main.cpp",
        "ls336_SYS_LIBS_Linux += tirpc",
    ]:
        assert snippet in makefile

    for snippet in [
        "epicsThreadSleep",
        "iocsh(0)",
        'extern "C"',
        "ls336_registerRecordDeviceDriver(pdbbase)",
        "return 0",
    ]:
        assert snippet in main

    assert "ls336_registerRecordDeviceDriver.h" not in main


def test_ramp_write_passes_prefix_to_protocol_for_enable_lookup():
    db = read("ls336App/Db/ls336.db")
    proto = read("ls336App/protocol/ls336.proto")

    assert 'field(OUT,  "@ls336.proto setRamp($(P)) $(PORT)")' in db
    assert 'out "RAMP 1,%(\\$1Loop1:RAMP:ENABLE.VAL)d,%f"' in proto


def test_readme_documents_epics_client_workflow():
    readme = read("README.md")

    for snippet in [
        "wsl --install -d Ubuntu-24.04",
        "scripts/setup_epics_wsl.sh",
        "scripts/run_tests.sh",
        "libtirpc-dev",
        "scripts/check_ioc_ready.sh",
        "code .",
        "Tasks: Run Task",
        "caget LS336:ColdHead:TEMP_RBV",
        "caget LS336:Sample:TEMP_RBV",
        "caput LS336:Loop1:SETP",
        "caput LS336:Loop1:RAMP:ENABLE",
        "caput LS336:Loop1:RAMP:RATE",
        "caput LS336:Loop1:WARMUP:TARGET",
        "caput LS336:Loop1:WARMUP:STEP:5K.PROC 1",
        "caput LS336:Loop1:WARMUP:STEP:10K.PROC 1",
        "caput LS336:Loop1:WARMUP:NEXT.PROC 1",
        "350 K",
        "10 K/min",
    ]:
        assert snippet in readme


def test_vscode_tasks_cover_common_ioc_workflows():
    tasks = read(".vscode/tasks.json")

    for snippet in [
        '"label": "IOC: build"',
        '"command": "make"',
        '"label": "IOC: readiness check"',
        '"command": "bash scripts/check_ioc_ready.sh"',
        '"label": "IOC: Python tests"',
        '"command": "bash scripts/run_tests.sh"',
        '"label": "IOC: run"',
        '"command": "${input:serialDevice} bash scripts/run_ioc.sh"',
        '"label": "IOC: dashboard"',
        '"command": "python3 scripts/ls336_dashboard.py"',
        '"label": "Windows: direct dashboard"',
        '"command": "python scripts\\\\ls336_direct_dashboard.py"',
        '"id": "serialDevice"',
    ]:
        assert snippet in tasks


def test_windows_direct_dashboard_uses_serial_without_epics():
    dashboard = read("scripts/ls336_direct_dashboard.py")
    web_dashboard = read("scripts/ls336_web_dashboard.py")
    runner = read("scripts/run_windows_dashboard.bat")
    web_runner = read("scripts/run_web_dashboard_windows.bat")
    easy_runner = read("START_WINDOWS_DASHBOARD.bat")
    mac_runner = read("scripts/run_web_dashboard_mac.sh")
    mac_easy_runner = read("START_MAC_DASHBOARD.command")
    requirements = read("requirements.txt")
    readme = read("README.md")

    for snippet in [
        "class LakeShoreSerialClient",
        "class DirectDashboard",
        "serial.Serial",
        "bytesize=serial.SEVENBITS",
        "parity=serial.PARITY_ODD",
        "stopbits=serial.STOPBITS_ONE",
        'INPUT_CHANNELS = ("A", "B", "C", "D")',
        "KRDG? {channel}",
        '"SETP? 1"',
        '"RAMP? 1"',
        '"HTR? 1"',
        "CSET 1,",
        "Cold Input",
        "Sample Input",
        "Control Input",
        "Apply Inputs",
        "SETP 1,",
        "RAMP 1,",
        "COM3",
        "Start Rhythm Warmup",
        "Rhythm interval min",
        "stop_rhythm_warmup",
        "_set_ramped_setpoint_worker",
        "_advance_warmup_worker",
        "_rhythm_warmup_tick",
        "client.set_ramp(ramp_rate, 1)",
        "client.set_setpoint(next_setpoint)",
        '"_warmup_done"',
        "Warmup target reached",
        "Rhythm warmup is already running",
    ]:
        assert snippet in dashboard

    assert "python -m pip install pyserial" in runner
    assert "pyserial>=3.5" in requirements
    assert "START_WINDOWS_DASHBOARD.bat" in readme
    assert "requirements.txt" in readme
    assert "run_web_dashboard_windows.bat" in easy_runner
    assert "python.org/downloads" in web_runner
    assert "pip install -r requirements.txt" in web_runner
    assert "scripts\\ls336_web_dashboard.py" in web_runner
    assert "http://127.0.0.1:8765" in web_runner
    assert "START_MAC_DASHBOARD.command" in readme
    assert "run_web_dashboard_mac.sh" in mac_easy_runner
    assert "brew install python" in mac_runner
    assert "pip install -r requirements.txt" in mac_runner
    assert "scripts/ls336_web_dashboard.py" in mac_runner
    assert "http://127.0.0.1:8765" in mac_runner
    assert "python scripts\\ls336_direct_dashboard.py" in readme
    assert "does not require Linux, WSL, EPICS" in readme
    assert "Start Rhythm Warmup" in readme
    assert "step size and interval" in readme

    for snippet in [
        "class DemoLakeShoreClient",
        "DEMO",
        "Lake Shore 336 browser dashboard",
        "dashboard_html",
        "RANGE? 1",
        "RANGE 1,",
        "PID? 1",
        "PID 1,",
        "KRDG? {channel}",
        "CSET 1,",
        "/api/control",
        "/api/inputs",
        "set_control",
        "set_inputs",
        "heater_range",
        "pid_p",
        "中文",
        "stable_tol",
        "downloadCsv",
        "warmup_done",
        "threading.RLock",
    ]:
        assert snippet in web_dashboard


def test_public_demo_site_documents_safe_sharing_workflow():
    demo = read("web/index.html")
    vercel = read("vercel.json")
    readme = read("README.md")

    for snippet in [
        "Lake Shore 336 ARPES Temp Control",
        "Cold Head Temp",
        "Sample Stage Temp",
        "Temperature Control",
        "Heater Range",
        "Input A",
        "Input B",
        "Control Input",
        "Off",
        "Low",
        "Medium",
        "High",
        "PID",
        "START RHYTHM",
        "中文",
        "/api/control",
        "ls336_arpes_log.csv",
    ]:
        assert snippet in demo

    assert '"/web/index.html"' in vercel

    for snippet in [
        "Public Demo Website",
        "Vercel",
        "web/index.html",
        "Real Instrument On The Lab Network",
        "python3 scripts/ls336_web_dashboard.py --host 0.0.0.0 --port 8765",
        "http://<lab-computer-ip>:8765",
        "Do not expose the real instrument control panel directly to the public internet",
    ]:
        assert snippet in readme


def test_operator_tutorial_explains_real_and_demo_use():
    tutorial = read("docs/operator_tutorial_zh.md")

    for snippet in [
        "Vercel 不能直接连接实验室仪器",
        "START_WINDOWS_DASHBOARD.bat",
        "START_MAC_DASHBOARD.command",
        "http://127.0.0.1:8765",
        "python scripts\\ls336_web_dashboard.py",
        "COM3",
        "/dev/cu.usbserial",
        "DEMO",
        "Heater Range",
        "Off",
        "Low",
        "Medium",
        "High",
        "PID",
        "0.2 或 0.5 K/min",
        "ls336_arpes_log.csv",
    ]:
        assert snippet in tutorial


def test_ioc_boot_uses_current_epics_host_architecture():
    boot_makefile = read("iocBoot/iocLS336/Makefile")
    runner = read("scripts/run_ioc.sh")

    assert "ARCH = linux-x86_64" not in boot_makefile
    assert "EpicsHostArch" in runner
    assert "EPICS_HOST_ARCH" in runner
    assert 'find "${PROJECT_ROOT}/bin"' in runner
    assert 'exec "$candidate" st.cmd' in runner


def test_dashboard_exposes_visual_temperature_and_warmup_controls():
    dashboard = read("scripts/ls336_dashboard.py")

    for snippet in [
        "class LakeShoreDashboard",
        '"ColdHead:TEMP_RBV"',
        '"Sample:TEMP_RBV"',
        '"COMM:STATUS"',
        '"Loop1:SETP"',
        '"Loop1:RAMP:RATE"',
        '"Loop1:WARMUP:TARGET"',
        '"Loop1:WARMUP:STEP:5K"',
        '"Loop1:WARMUP:STEP:10K"',
        '"Loop1:WARMUP:NEXT"',
        '["caget", "-t", self.pv(suffix)]',
        '["caput", self.pv(suffix), str(value)]',
    ]:
        assert snippet in dashboard


def test_wsl_setup_script_installs_epics_stack_and_writes_release_local():
    script = read("scripts/setup_epics_wsl.sh")

    for snippet in [
        "EPICS_ROOT=${EPICS_ROOT:-/opt/epics}",
        "EPICS_BASE_TAG=${EPICS_BASE_TAG:-R7.0.8.1}",
        "ASYN_TAG=${ASYN_TAG:-R4-44}",
        "STREAM_TAG=${STREAM_TAG:-2.8.24}",
        "EPICS_BASE_URL=${EPICS_BASE_URL:-https://github.com/epics-base/epics-base.git}",
        "ASYN_URL=${ASYN_URL:-https://github.com/epics-modules/asyn.git}",
        "STREAM_URL=${STREAM_URL:-https://github.com/paulscherrerinstitute/StreamDevice.git}",
        "EPICS_BASE_ARCHIVE=${EPICS_BASE_ARCHIVE:-}",
        "ASYN_ARCHIVE=${ASYN_ARCHIVE:-}",
        "STREAM_ARCHIVE=${STREAM_ARCHIVE:-}",
        "downloads/epics-base-R7.0.8.1.tar.gz",
        "downloads/asyn-R4-44.tar.gz",
        "downloads/StreamDevice-2.8.24.tar.gz",
        "Using local archive",
        "GIT_ATTEMPTS=${GIT_ATTEMPTS:-3}",
        "github.com/epics-base/epics-base.git",
        "github.com/epics-modules/asyn.git",
        "github.com/paulscherrerinstitute/StreamDevice.git",
        "configure/RELEASE.local",
        "EPICS_BASE=${EPICS_ROOT}/base",
        "ASYN=${EPICS_ROOT}/support/asyn",
        "STREAM=${EPICS_ROOT}/support/StreamDevice",
        "libtirpc-dev",
        "libpcre3-dev",
        "/usr/include/tirpc/rpc/rpc.h",
        "USR_INCLUDES_Linux += -I/usr/include/tirpc",
        "SYS_LIBS_Linux += tirpc",
        "CALC=",
        "SYNAPPS=",
        "PCRE=",
        "PCRE_INCLUDE=/usr/include",
        "PCRE_LIB=/usr/lib/x86_64-linux-gnu",
        'make -j -C "${EPICS_ROOT}/support/asyn/asyn"',
        'make -j -C "${EPICS_ROOT}/support/StreamDevice/src"',
        "tar -xzf",
        "make -j",
    ]:
        assert snippet in script


def test_python_test_runner_has_pytest_fallback():
    script = read("scripts/run_tests.sh")

    for snippet in [
        "python3 -c \"import pytest\"",
        "exec python3 -m pytest -q",
        "using the built-in lightweight test runner",
        "glob(\"test_*.py\")",
    ]:
        assert snippet in script


def test_ioc_check_script_documents_required_runtime_checks():
    script = read("scripts/check_ioc_ready.sh")

    for snippet in [
        "command -v make",
        "configure/RELEASE.local",
        "scripts/run_tests.sh",
        "scripts/run_ioc.sh",
        "find bin",
        "iocBoot/iocLS336/st.cmd",
        "caget LS336:ColdHead:TEMP_RBV",
        "caget LS336:Sample:TEMP_RBV",
        "caget LS336:IDN",
        "caget LS336:COMM:STATUS",
        "caput LS336:Loop1:SETP 300",
        "caput LS336:Loop1:WARMUP:STEP 5",
        "caput LS336:Loop1:WARMUP:NEXT.PROC 1",
    ]:
        assert snippet in script


def test_windows_wsl_initializer_self_elevates_and_installs_ubuntu():
    script = read("scripts/enable_wsl_windows.ps1")

    for snippet in [
        "Start-Process powershell",
        "-Verb RunAs",
        "Microsoft-Windows-Subsystem-Linux",
        "VirtualMachinePlatform",
        "wsl --set-default-version 2",
        "wsl --install -d Ubuntu-24.04",
    ]:
        assert snippet in script
