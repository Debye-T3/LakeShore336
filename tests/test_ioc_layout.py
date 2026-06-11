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
    assert 'field(DRVH, "5")' in db
    assert 'field(HOPR, "5")' in db
    assert "validate_setpoint" in db
    assert "validate_ramp_rate" in db
    assert 'field(OUT,  "$(P)ERR PP")' in db
    assert "Setpoint must be within 0..350 K" in db
    assert "Ramp rate must be within 0..5 K/min" in db


def test_database_derives_communication_status_from_readback_alarms():
    db = read("ls336App/Db/ls336.db")

    assert 'field(INPA, "$(P)ColdHead:TEMP_RBV.SEVR CP MS")' in db
    assert 'field(INPB, "$(P)Sample:TEMP_RBV.SEVR CP MS")' in db
    assert 'field(INPC, "$(P)Loop1:SETP_RBV.SEVR CP MS")' in db
    assert 'field(CALC, "A>0||B>0||C>0?2:1")' in db
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
        'out "RAMP 1,%d,%f"',
        'out "HTR? 1"',
    ]

    for command in expected_commands:
        assert command in proto


def test_startup_script_configures_serial_port_for_wsl_defaults():
    startup = read("iocBoot/iocLS336/st.cmd")

    assert 'epicsEnvSet("PORT", "LS336_PORT")' in startup
    assert 'epicsEnvSet("TTY", "/dev/ttyUSB0")' in startup
    assert 'epicsEnvSet("PREFIX", "LS336:")' in startup
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
        "libtirpc-dev",
        "scripts/check_ioc_ready.sh",
        "caget LS336:ColdHead:TEMP_RBV",
        "caget LS336:Sample:TEMP_RBV",
        "caput LS336:Loop1:SETP",
        "caput LS336:Loop1:RAMP:ENABLE",
        "caput LS336:Loop1:RAMP:RATE",
        "350 K",
        "5 K/min",
    ]:
        assert snippet in readme


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


def test_ioc_check_script_documents_required_runtime_checks():
    script = read("scripts/check_ioc_ready.sh")

    for snippet in [
        "command -v make",
        "configure/RELEASE.local",
        "bin/linux-x86_64/ls336",
        "iocBoot/iocLS336/st.cmd",
        "caget LS336:ColdHead:TEMP_RBV",
        "caput LS336:Loop1:SETP 300",
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
