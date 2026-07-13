from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_database_exposes_required_public_pvs():
    db = read("ls336App/Db/ls336.db")

    for record in [
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
    ]:
        assert record in db

    assert "WARMUP" not in db


def test_database_enforces_conservative_write_limits():
    db = read("ls336App/Db/ls336.db")

    assert 'field(DRVH, "350")' in db
    assert 'field(HOPR, "350")' in db
    assert 'field(DRVH, "10")' in db
    assert 'field(HOPR, "10")' in db
    assert "validate_setpoint" in db
    assert "validate_ramp_rate" in db
    assert "Setpoint must be within 0..350 K" in db
    assert "Ramp rate must be within 0..10 K/min" in db


def test_database_derives_communication_status_from_readback_alarms():
    db = read("ls336App/Db/ls336.db")

    assert 'field(INPA, "$(P)ColdHead:TEMP_RBV.SEVR CP MS")' in db
    assert 'field(INPB, "$(P)Sample:TEMP_RBV.SEVR CP MS")' in db
    assert 'field(INPC, "$(P)Loop1:SETP_RBV.SEVR CP MS")' in db
    assert 'field(INPD, "$(P)Loop1:RAMP:RATE_RBV.SEVR CP MS")' in db
    assert 'field(INPE, "$(P)Loop1:RAMP:ENABLE_RBV_RAW.SEVR CP MS")' in db
    assert 'field(INPF, "$(P)Loop1:HTR_RBV.SEVR CP MS")' in db
    assert 'field(CALC, "A>0||B>0||C>0||D>0||E>0||F>0?2:1")' in db


def test_protocol_contains_lakeshore_336_commands():
    proto = read("ls336App/protocol/ls336.proto")

    for command in [
        'out "*IDN?"',
        'out "KRDG? A"',
        'out "KRDG? B"',
        'out "SETP? 1"',
        'out "SETP 1,%f"',
        'out "RAMP? 1"',
        'out "RAMP 1,%(\\$1Loop1:RAMP:ENABLE.VAL)d,%f"',
        'out "HTR? 1"',
        "@init { getRampRate; getRampEnable; }",
    ]:
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
        "timestamp_iso",
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


def test_web_dashboard_supports_complete_english_chinese_switching():
    dashboard = read("web/index.html")

    for snippet in [
        '<select id="language" onchange="setLanguage(this.value)"',
        '<option value="en">English</option>',
        '<option value="zh">中文</option>',
        'data-i18n="connect"',
        'data-i18n="temperatureControl"',
        'data-i18n="logArchive"',
        "const translations=",
        "const LANGUAGE_STORAGE_KEY='instrument_ui_language'",
        "new URLSearchParams(window.location.search).get('lang')",
        "localStorage.getItem(LANGUAGE_STORAGE_KEY)",
        "navigator.languages?.[0]||navigator.language",
        "window.history.replaceState(window.history.state,'',url)",
        "document.documentElement.lang=lang==='zh'?'zh-CN':'en'",
        "setLanguage(initialLanguage())",
    ]:
        assert snippet in dashboard

    for english, chinese in [
        ("statusConnected:'CONNECTED'", "statusConnected:'已连接'"),
        ("heaterRange:'Heater Range'", "heaterRange:'加热器档位'"),
        ("stable:'Stable'", "stable:'已稳定'"),
        (
            "warningSetpoint:'Setpoint exceeds 350 K safety limit'",
            "warningSetpoint:'设定温度超过 350 K 安全上限'",
        ),
        (
            "chartEmpty:'Connect or select DEMO to plot temperature trend'",
            "chartEmpty:'请连接仪器或选择 DEMO 以绘制温度趋势'",
        ),
        ("logConnected:'Connected — logging started'", "logConnected:'已连接——日志记录已开始'"),
    ]:
        assert english in dashboard
        assert chinese in dashboard

    for dynamic_contract in [
        "setStatus(connectionState)",
        "el.textContent=hasReading?t(stable?'stable':'notStable'):'--'",
        "items.push({text:t('warningSetpoint'),critical:true})",
        "x.fillText(t('chartEmpty')",
        "st.textContent=t(s.active?'recordingOn':'recordingPaused')",
        "params.range=rangeLabel(null,params.rangeCode)",
        "renderSystemLog()",
    ]:
        assert dynamic_contract in dashboard


def test_documentation_matches_current_public_workflow():
    readme = read("README.md")
    tutorial = read("docs/operator_tutorial_zh.md")

    for snippet in [
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
        "caget LS336:ColdHead:TEMP_RBV",
        "caput LS336:Loop1:SETP 300",
        "caput LS336:Loop1:RAMP:ENABLE 1",
        "caput LS336:Loop1:RAMP:RATE 1",
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
