import importlib.util
import json
import os
import re
import select
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
MOCK_PATH = ROOT / "scripts" / "ls336_ioc_mock.py"
RUN_TESTS_PATH = ROOT / "scripts" / "run_tests.sh"
RELEASE_LOCAL = ROOT / "configure" / "RELEASE.local"
IOC_BINARY = ROOT / "bin" / "linux-x86_64" / "ls336"
IOC_BOOT_DIR = ROOT / "iocBoot" / "iocLS336"
PTY_TERMIOS_SHIM_SOURCE = ROOT / "tests" / "fixtures" / "pty_termios_shim.c"
LIVE_PREFIX = "LS336TEST:"
CA_ENV = {
    "EPICS_CA_AUTO_ADDR_LIST": "NO",
    "EPICS_CA_ADDR_LIST": "127.0.0.1",
}


def load_mock_module():
    spec = importlib.util.spec_from_file_location("ls336_ioc_mock_test", MOCK_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_epics_base(release_local: Path) -> Path:
    for line in release_local.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\s*EPICS_BASE\s*(?:\?=|=)\s*(.*)$", line)
        if match is None:
            continue
        value = match.group(1).strip()
        if value:
            return Path(value)
    raise ValueError(f"EPICS_BASE assignment missing from {release_local}")


def _resolve_live_prerequisites() -> tuple[Path, Path]:
    if not RELEASE_LOCAL.is_file():
        pytest.fail(f"live IOC RELEASE.local missing: {RELEASE_LOCAL}")
    try:
        epics_base = _read_epics_base(RELEASE_LOCAL)
    except ValueError as exc:
        pytest.fail(str(exc))

    if not IOC_BINARY.is_file():
        pytest.fail(f"live IOC binary missing: {IOC_BINARY}")

    tool_dir = epics_base / "bin" / "linux-x86_64"
    caget = tool_dir / "caget"
    caput = tool_dir / "caput"
    if not caget.is_file():
        pytest.fail(f"EPICS caget missing: {caget}")
    if not caput.is_file():
        pytest.fail(f"EPICS caput missing: {caput}")
    return caget, caput


@dataclass
class RunningIOC:
    prefix: str
    ca_env: dict[str, str]
    caget_path: Path
    caput_path: Path
    command_log: Path
    slave_keepalive_fd: int
    ioc_process: subprocess.Popen[str]
    mock_process: subprocess.Popen[str]
    ioc_stdout_path: Path
    ioc_stderr_path: Path
    mock_stderr_path: Path

    def pv(self, suffix: str) -> str:
        return f"{self.prefix}{suffix}"

    def caget_str(self, suffix: str, timeout: float = 1.0) -> str:
        result = self._run_ca_tool(
            self.caget_path,
            ["-w", str(timeout), "-t", "-S", self.pv(suffix)],
        )
        return result.stdout.strip()

    def caget_float(self, suffix: str, timeout: float = 1.0) -> float:
        result = self._run_ca_tool(
            self.caget_path,
            ["-w", str(timeout), "-t", "-n", self.pv(suffix)],
        )
        return float(result.stdout.strip())

    def caput(self, suffix: str, value: object, timeout: float = 1.0) -> None:
        self._run_ca_tool(
            self.caput_path,
            ["-w", str(timeout), self.pv(suffix), str(value)],
        )

    def commands(self) -> list[dict[str, object]]:
        if not self.command_log.exists():
            return []
        text = self.command_log.read_text(encoding="utf-8")
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def mark(self) -> int:
        return len(self.commands())

    def commands_since(self, mark: int) -> list[dict[str, object]]:
        return self.commands()[mark:]

    def wait_for(self, description: str, predicate, timeout: float = 8.0, interval: float = 0.1):
        deadline = time.monotonic() + timeout
        last_error = None
        while time.monotonic() < deadline:
            try:
                value = predicate()
            except Exception as exc:  # pragma: no cover - diagnostic path
                last_error = exc
            else:
                if value:
                    return value
            time.sleep(interval)

        detail = f"Timed out waiting for {description}"
        if last_error is not None:
            detail += f"; last error: {last_error}"
        raise AssertionError(detail)

    def diagnostics(self) -> str:
        return (
            f"Command log:\n{json.dumps(self.commands(), indent=2)}\n"
            f"IOC stdout:\n{self._read_text(self.ioc_stdout_path)}\n"
            f"IOC stderr:\n{self._read_text(self.ioc_stderr_path)}\n"
            f"Mock stderr:\n{self._read_text(self.mock_stderr_path)}"
        )

    def shutdown(self) -> None:
        _stop_process(self.ioc_process, stdin_text="exit\n")
        _stop_process(self.mock_process)
        if self.slave_keepalive_fd >= 0:
            os.close(self.slave_keepalive_fd)
            self.slave_keepalive_fd = -1

    def _run_ca_tool(self, tool: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [str(tool), *args],
            cwd=ROOT,
            env={**os.environ, **self.ca_env},
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            raise AssertionError(
                f"{tool.name} failed for {args[-1]}: stdout={result.stdout!r} stderr={result.stderr!r}"
            )
        return result

    @staticmethod
    def _read_text(path: Path) -> str:
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")


def _stop_process(process: subprocess.Popen[str], stdin_text: str | None = None) -> None:
    if stdin_text is not None and process.stdin is not None and process.poll() is None:
        try:
            process.stdin.write(stdin_text)
            process.stdin.flush()
        except OSError:
            pass
        except BrokenPipeError:
            pass

    if process.stdin is not None:
        process.stdin.close()

    if process.stdout is not None:
        process.stdout.close()

    try:
        process.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        process.terminate()

    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _start_mock_server(tmp_path: Path) -> tuple[subprocess.Popen[str], str, Path]:
    mock_stderr_path = tmp_path / "mock.stderr"
    command_log = tmp_path / "mock.jsonl"
    with mock_stderr_path.open("w", encoding="utf-8") as mock_stderr:
        process = subprocess.Popen(
            [
                sys.executable,
                str(MOCK_PATH),
                "--command-log",
                str(command_log),
                "--keep-slave-open",
            ],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=mock_stderr,
            stdin=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )

    assert process.stdout is not None
    slave_path = process.stdout.readline().strip()
    if not slave_path:
        _stop_process(process)
        stderr_text = mock_stderr_path.read_text(encoding="utf-8", errors="replace")
        pytest.fail(f"Failed to read PTY path from emulator.\nMock stderr:\n{stderr_text}")

    return process, slave_path, command_log


def _open_serial_keepalive(slave_path: str) -> int:
    return os.open(slave_path, os.O_RDWR | os.O_NOCTTY)


def _compile_pty_termios_shim(tmp_path: Path) -> Path:
    library_path = tmp_path / "pty_termios_shim.so"
    result = subprocess.run(
        [
            "cc",
            "-shared",
            "-fPIC",
            "-ldl",
            "-o",
            str(library_path),
            str(PTY_TERMIOS_SHIM_SOURCE),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        pytest.fail(
            "Failed to build PTY termios shim.\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return library_path


def _ioc_subprocess_env(slave_path: str, shim_path: Path) -> dict[str, str]:
    preload_parts = [str(shim_path)]
    existing_ld_preload = os.environ.get("LD_PRELOAD")
    if existing_ld_preload:
        preload_parts.append(existing_ld_preload)
    return {
        **os.environ,
        **CA_ENV,
        "TTY": slave_path,
        "PREFIX": LIVE_PREFIX,
        "LD_PRELOAD": ":".join(preload_parts),
    }


def _wait_for_ioc_ready(running_ioc: RunningIOC) -> None:
    deadline = time.monotonic() + 15.0
    last_error = None
    last_value = None
    last_status = None
    while time.monotonic() < deadline:
        try:
            value = running_ioc.caget_float("ColdHead:TEMP_RBV", timeout=1.0)
            status = running_ioc.caget_float("COMM:STATUS", timeout=1.0)
        except Exception as exc:
            last_error = exc
        else:
            last_value = value
            last_status = status
            if value == pytest.approx(4.2, abs=0.01) and status == 1.0:
                return
        time.sleep(0.2)

    pytest.fail(
        "IOC did not become ready via ColdHead:TEMP_RBV and COMM:STATUS.\n"
        f"Last readiness error: {last_error}\n"
        f"Last readiness value: {last_value}\n"
        f"Last communication status: {last_status}\n"
        f"{running_ioc.diagnostics()}"
    )


def _has_setpoint_write(entries: list[dict[str, object]], value: float) -> bool:
    for entry in entries:
        command = entry.get("command")
        if not isinstance(command, str) or not command.startswith("SETP 1,"):
            continue
        if float(command.split(",", 1)[1]) == pytest.approx(value, abs=0.001):
            return True
    return False


def _has_ramp_write_pair(
    entries: list[dict[str, object]], expected_enable: int, expected_rate: float
) -> bool:
    commands = [
        entry["command"]
        for entry in entries
        if isinstance(entry.get("command"), str)
    ]
    for index in range(len(commands) - 1):
        if commands[index] != "RAMP? 1":
            continue
        command = commands[index + 1]
        if not command.startswith("RAMP 1,"):
            continue
        _, payload = command.split(" ", 1)
        loop, enable, rate = payload.split(",")
        if loop != "1":
            continue
        if int(enable) != expected_enable:
            continue
        if float(rate) == pytest.approx(expected_rate, abs=0.001):
            return True
    return False


def _assert_alarm_and_error(
    running_ioc: RunningIOC, record: str, error_text: str, timeout: float = 3.0
) -> None:
    observed: dict[str, str] = {}

    def alarm_and_error_match() -> bool:
        observed["STAT"] = running_ioc.caget_str(f"{record}.STAT")
        observed["SEVR"] = running_ioc.caget_str(f"{record}.SEVR")
        observed["ERR"] = running_ioc.caget_str("ERR")
        return (
            observed["STAT"] == "DISABLE"
            and observed["SEVR"] == "INVALID"
            and observed["ERR"] == error_text
        )

    try:
        running_ioc.wait_for(
            f"{record} DISABLE/INVALID alarm",
            alarm_and_error_match,
            timeout=timeout,
            interval=0.1,
        )
    except AssertionError as exc:
        raise AssertionError(
            f"{exc}; last values: {observed}\n{running_ioc.diagnostics()}"
        ) from exc


def _assert_no_matching_write(
    running_ioc: RunningIOC, mark: int, command_prefix: str
) -> None:
    time.sleep(0.2)
    writes = [
        entry["command"]
        for entry in running_ioc.commands_since(mark)
        if isinstance(entry.get("command"), str)
        and entry["command"].startswith(command_prefix)
    ]
    assert writes == [], running_ioc.diagnostics()


@pytest.fixture
def running_ioc():
    if os.name != "posix":
        pytest.skip("live IOC integration tests require POSIX")
    caget_path, caput_path = _resolve_live_prerequisites()

    tmp_path = Path(tempfile.mkdtemp(prefix="ls336-ioc-"))
    mock_process = None
    ioc_process = None
    slave_keepalive_fd = -1
    running = None
    try:
        mock_process, slave_path, command_log = _start_mock_server(tmp_path)
        shim_path = _compile_pty_termios_shim(tmp_path)
        ioc_stdout_path = tmp_path / "ioc.stdout"
        ioc_stderr_path = tmp_path / "ioc.stderr"
        with ioc_stdout_path.open("w", encoding="utf-8") as ioc_stdout, ioc_stderr_path.open(
            "w", encoding="utf-8"
        ) as ioc_stderr:
            ioc_process = subprocess.Popen(
                [str(IOC_BINARY), "st.cmd"],
                cwd=IOC_BOOT_DIR,
                env=_ioc_subprocess_env(slave_path, shim_path),
                stdin=subprocess.PIPE,
                stdout=ioc_stdout,
                stderr=ioc_stderr,
                text=True,
                bufsize=1,
            )
        slave_keepalive_fd = _open_serial_keepalive(slave_path)

        running = RunningIOC(
            prefix=LIVE_PREFIX,
            ca_env=CA_ENV.copy(),
            caget_path=caget_path,
            caput_path=caput_path,
            command_log=command_log,
            slave_keepalive_fd=slave_keepalive_fd,
            ioc_process=ioc_process,
            mock_process=mock_process,
            ioc_stdout_path=ioc_stdout_path,
            ioc_stderr_path=ioc_stderr_path,
            mock_stderr_path=tmp_path / "mock.stderr",
        )

        _wait_for_ioc_ready(running)
    except BaseException:
        if ioc_process is not None:
            _stop_process(ioc_process, stdin_text="exit\n")
        if mock_process is not None:
            _stop_process(mock_process)
        if slave_keepalive_fd >= 0:
            os.close(slave_keepalive_fd)
            slave_keepalive_fd = -1
        shutil.rmtree(tmp_path, ignore_errors=True)
        raise

    try:
        yield running
    finally:
        assert running is not None
        running.shutdown()
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_running_ioc_startup_failure_cleans_up_mock_process(monkeypatch):
    cleanup_calls: list[object] = []
    module = sys.modules[__name__]
    mock_process = object()
    startup_dir = Path("C:/ls336-fixture-startup")

    monkeypatch.setattr(module, "os", SimpleNamespace(name="posix", close=os.close))
    monkeypatch.setattr(tempfile, "mkdtemp", lambda prefix: str(startup_dir))
    monkeypatch.setattr(
        module,
        "_resolve_live_prerequisites",
        lambda: (Path("/tmp/caget"), Path("/tmp/caput")),
    )
    monkeypatch.setattr(
        module,
        "_start_mock_server",
        lambda path: (mock_process, "/tmp/fake-tty", path / "mock.jsonl"),
    )

    def fail_compile(_: Path) -> Path:
        pytest.fail("forced")

    monkeypatch.setattr(module, "_compile_pty_termios_shim", fail_compile)
    monkeypatch.setattr(
        module,
        "_stop_process",
        lambda process, stdin_text=None: cleanup_calls.append(process),
    )
    monkeypatch.setattr(
        module.shutil,
        "rmtree",
        lambda path, ignore_errors=True: cleanup_calls.append(("rmtree", Path(path))),
    )

    fixture_gen = running_ioc.__wrapped__()

    with pytest.raises(pytest.fail.Exception, match="forced"):
        next(fixture_gen)

    assert cleanup_calls == [mock_process, ("rmtree", startup_dir)]


def test_model336state_defaults_match_phase_one_contract():
    module = load_mock_module()
    state = module.Model336State()

    assert state.handle("*IDN?").startswith("LSCI,MODEL336")
    assert state.handle("KRDG? A") == "+4.200"
    assert state.handle("KRDG? B") == "+10.000"
    assert state.handle("KRDG? C") == "+20.000"
    assert state.handle("KRDG? D") == "+30.000"
    assert state.handle("OUTMODE? 1") == "1,1,1"
    assert state.handle("SETP? 1") == "10.000"
    assert state.handle("RAMP? 1") == "1,1.500"
    assert state.handle("RANGE? 1") == "2"
    assert state.handle("HTR? 1") == "12.500"
    assert state.handle("PID? 1") == "10.000,20.000,0.000"


def test_model336state_writes_update_followup_readbacks():
    module = load_mock_module()
    state = module.Model336State()

    assert state.handle("SETP 1,42.125") is None
    assert state.handle("RAMP 1,0,3.250") is None
    assert state.handle("RANGE 1,3") is None

    assert state.handle("SETP? 1") == "42.125"
    assert state.handle("RAMP? 1") == "0,3.250"
    assert state.handle("RANGE? 1") == "3"


def test_model336state_rejects_unsupported_and_malformed_commands():
    module = load_mock_module()
    state = module.Model336State()

    for command in [
        "",
        "KRDG? Z",
        "OUTMODE? 2",
        "SETP 2,10",
        "RAMP 1,2,1.5",
        "RANGE 1,4",
        "PID 1,1,2,3",
    ]:
        with pytest.raises(ValueError):
            state.handle(command)


@pytest.mark.parametrize(
    ("assignment", "expected"),
    [
        ("EPICS_BASE=/custom/epics/base\n", Path("/custom/epics/base")),
        ("EPICS_BASE ?= /srv/epics/base\n", Path("/srv/epics/base")),
        ("  EPICS_BASE   =   /opt/EPICS Base  \n", Path("/opt/EPICS Base")),
    ],
)
def test_release_local_epics_base_parser_supports_make_assignment_forms(
    tmp_path, assignment, expected
):
    release_local = tmp_path / "RELEASE.local"
    release_local.write_text(f"ASYN=/unused\n{assignment}", encoding="utf-8")

    assert _read_epics_base(release_local) == expected


def test_live_prerequisites_fail_when_release_local_is_missing(monkeypatch, tmp_path):
    module = sys.modules[__name__]
    ioc_binary = tmp_path / "ls336"
    ioc_binary.touch()
    monkeypatch.setattr(module, "RELEASE_LOCAL", tmp_path / "missing-RELEASE.local")
    monkeypatch.setattr(module, "IOC_BINARY", ioc_binary)

    with pytest.raises(pytest.fail.Exception, match="RELEASE.local"):
        _resolve_live_prerequisites()


def test_live_prerequisites_fail_when_ioc_binary_is_missing(monkeypatch, tmp_path):
    module = sys.modules[__name__]
    release_local = tmp_path / "RELEASE.local"
    release_local.write_text(f"EPICS_BASE={tmp_path / 'epics'}\n", encoding="utf-8")
    monkeypatch.setattr(module, "RELEASE_LOCAL", release_local)
    monkeypatch.setattr(module, "IOC_BINARY", tmp_path / "missing-ls336")

    with pytest.raises(pytest.fail.Exception, match="IOC binary missing"):
        _resolve_live_prerequisites()


@pytest.mark.parametrize(("present_tool", "missing_name"), [("caput", "caget"), ("caget", "caput")])
def test_live_prerequisites_fail_when_ca_tool_is_missing(
    monkeypatch, tmp_path, present_tool, missing_name
):
    module = sys.modules[__name__]
    epics_base = tmp_path / "EPICS Base"
    tool_dir = epics_base / "bin" / "linux-x86_64"
    tool_dir.mkdir(parents=True)
    (tool_dir / present_tool).touch()
    release_local = tmp_path / "RELEASE.local"
    release_local.write_text(f"EPICS_BASE ?= {epics_base}\n", encoding="utf-8")
    ioc_binary = tmp_path / "ls336"
    ioc_binary.touch()
    monkeypatch.setattr(module, "RELEASE_LOCAL", release_local)
    monkeypatch.setattr(module, "IOC_BINARY", ioc_binary)

    with pytest.raises(pytest.fail.Exception, match=missing_name):
        _resolve_live_prerequisites()


def test_running_ioc_skips_windows_before_live_path_checks(monkeypatch, tmp_path):
    module = sys.modules[__name__]
    monkeypatch.setattr(module, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(module, "RELEASE_LOCAL", tmp_path / "missing-RELEASE.local")
    monkeypatch.setattr(module, "IOC_BINARY", tmp_path / "missing-ls336")

    fixture_gen = running_ioc.__wrapped__()

    with pytest.raises(pytest.skip.Exception, match="require POSIX"):
        next(fixture_gen)


def test_run_tests_script_has_ioc_integration_entry_point():
    script = RUN_TESTS_PATH.read_text(encoding="utf-8")

    assert 'if [[ "${1-}" == "--ioc-integration" ]]; then' in script
    assert 'exec python3 -m pytest -q tests/test_ioc_integration.py -rs' in script


@pytest.mark.skipif(os.name != "posix", reason="PTY server requires POSIX")
def test_mock_server_processes_commands_and_logs_jsonl(tmp_path):
    log_path = tmp_path / "mock.jsonl"
    process = subprocess.Popen(
        [sys.executable, str(MOCK_PATH), "--command-log", str(log_path)],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    try:
        assert process.stdout is not None
        slave_path = process.stdout.readline().strip()
        assert slave_path
        assert Path(slave_path).exists()

        fd = os.open(slave_path, os.O_RDWR | os.O_NOCTTY)
        try:
            os.write(fd, b"*IDN?\r\nSETP 1,42.500\r\nSETP? 1\r\nBOGUS\r\n")

            chunks: list[str] = []
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                ready, _, _ = select.select([fd], [], [], 0.2)
                if not ready:
                    continue
                chunk = os.read(fd, 1024).decode("utf-8")
                if chunk:
                    chunks.append(chunk)
                if "42.500\r\n" in "".join(chunks):
                    break

            response_lines = [
                line for line in "".join(chunks).splitlines() if line.strip()
            ]
            assert response_lines[0].startswith("LSCI,MODEL336")
            assert response_lines[1] == "42.500"
            assert "BOGUS" not in response_lines
        finally:
            os.close(fd)
    finally:
        process.terminate()
        process.wait(timeout=5)

    entries = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert entries[0]["command"] == "*IDN?"
    assert entries[0]["response"].startswith("LSCI,MODEL336")
    assert entries[1] == {"command": "SETP 1,42.500", "response": None}
    assert entries[2] == {"command": "SETP? 1", "response": "42.500"}
    assert entries[3]["command"] == "BOGUS"
    assert "error" in entries[3]
    assert entries[3]["response"] is None


@pytest.mark.skipif(os.name != "posix", reason="PTY server requires POSIX")
def test_mock_server_exits_cleanly_when_slave_disconnects():
    process = subprocess.Popen(
        [sys.executable, str(MOCK_PATH)],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    try:
        assert process.stdout is not None
        slave_path = process.stdout.readline().strip()
        assert slave_path

        fd = os.open(slave_path, os.O_RDWR | os.O_NOCTTY)
        os.write(fd, b"\r\n")
        os.close(fd)

        try:
            return_code = process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=5)
            pytest.fail("Mock PTY server did not exit after slave disconnect")

        _, stderr_text = process.communicate(timeout=1)
        assert return_code == 0
        assert "Traceback" not in stderr_text
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)


def test_live_ioc_startup_reads_identity(running_ioc):
    running_ioc.wait_for(
        "initial temperature polling",
        lambda: (
            running_ioc.caget_float("ColdHead:TEMP_RBV") == pytest.approx(4.2, abs=0.01)
            and running_ioc.caget_float("Sample:TEMP_RBV") == pytest.approx(10.0, abs=0.01)
            and "KRDG? A" in [entry["command"] for entry in running_ioc.commands()]
            and "KRDG? B" in [entry["command"] for entry in running_ioc.commands()]
        ),
        timeout=8.0,
        interval=0.2,
    )

    running_ioc.wait_for(
        "identity polling",
        lambda: "*IDN?" in [entry["command"] for entry in running_ioc.commands()],
        timeout=12.0,
        interval=0.2,
    )

    assert "*IDN?" in [entry["command"] for entry in running_ioc.commands()]
    assert running_ioc.caget_float("ColdHead:TEMP_RBV") == pytest.approx(4.2, abs=0.01)
    assert running_ioc.caget_float("Sample:TEMP_RBV") == pytest.approx(10.0, abs=0.01)

    writes = [
        entry["command"]
        for entry in running_ioc.commands()
        if isinstance(entry.get("command"), str)
        and entry["command"].startswith(("SETP ", "RAMP ", "RANGE "))
    ]
    assert writes == []
    assert "String is too long" not in running_ioc.diagnostics()


def test_live_ioc_setpoint_boundaries_and_invalid_writes(running_ioc):
    for value in (0.0, 350.0):
        mark = running_ioc.mark()
        running_ioc.caput("Loop1:SETP", value)
        running_ioc.wait_for(
            f"SETP write {value:.3f}",
            lambda: _has_setpoint_write(running_ioc.commands_since(mark), value),
            timeout=3.0,
            interval=0.1,
        )
        running_ioc.wait_for(
            f"SETP_RBV {value:.3f}",
            lambda: running_ioc.caget_float("Loop1:SETP_RBV") == pytest.approx(value, abs=0.01),
            timeout=3.0,
            interval=0.1,
        )

    for value in (-0.001, 350.001, float("nan")):
        mark = running_ioc.mark()
        running_ioc.caput("Loop1:SETP", value)
        _assert_alarm_and_error(
            running_ioc,
            "Loop1:SETP",
            "Setpoint must be within 0..350 K",
        )
        _assert_no_matching_write(running_ioc, mark, "SETP 1,")

    assert running_ioc.caget_float("Loop1:SETP_RBV") == pytest.approx(350.0, abs=0.01)


def test_live_ioc_ramp_preserves_query_state_and_rejects_invalid_rate(running_ioc):
    sequences = [
        ("Loop1:RAMP:RATE", 0.0, 1, 0.0),
        ("Loop1:RAMP:ENABLE", 0, 0, 0.0),
        ("Loop1:RAMP:RATE", 10.0, 0, 10.0),
        ("Loop1:RAMP:ENABLE", 1, 1, 10.0),
    ]

    for suffix, value, expected_enable, expected_rate in sequences:
        mark = running_ioc.mark()
        running_ioc.caput(suffix, value)
        running_ioc.wait_for(
            f"{suffix} query/write pair for {value}",
            lambda: _has_ramp_write_pair(
                running_ioc.commands_since(mark),
                expected_enable,
                expected_rate,
            ),
            timeout=3.0,
            interval=0.1,
        )
        running_ioc.wait_for(
            f"ramp RBVs after {suffix}={value}",
            lambda: (
                running_ioc.caget_float("Loop1:RAMP:ENABLE_RBV")
                == pytest.approx(expected_enable, abs=0.01)
                and running_ioc.caget_float("Loop1:RAMP:RATE_RBV")
                == pytest.approx(expected_rate, abs=0.01)
            ),
            timeout=3.0,
            interval=0.1,
        )

    for value in (-0.001, 10.001, float("nan")):
        mark = running_ioc.mark()
        running_ioc.caput("Loop1:RAMP:RATE", value)
        _assert_alarm_and_error(
            running_ioc,
            "Loop1:RAMP:RATE",
            "Ramp rate must be within 0..10 K/min",
        )
        _assert_no_matching_write(running_ioc, mark, "RAMP 1,")

    assert running_ioc.caget_float("Loop1:RAMP:ENABLE_RBV") == pytest.approx(1, abs=0.01)
    assert running_ioc.caget_float("Loop1:RAMP:RATE_RBV") == pytest.approx(10.0, abs=0.01)


def test_live_ioc_ramp_enable_rejects_non_enum_values_and_guards_writer(running_ioc):
    mark = running_ioc.mark()
    running_ioc.caput("Loop1:RAMP:ENABLE", 1)
    running_ioc.wait_for(
        "initial ramp enable write",
        lambda: _has_ramp_write_pair(running_ioc.commands_since(mark), 1, 1.5),
        timeout=3.0,
        interval=0.1,
    )

    for value in (-1, 1.5, 2, 65536, float("nan")):
        mark = running_ioc.mark()
        running_ioc.caput("Loop1:RAMP:ENABLE", value)
        _assert_alarm_and_error(
            running_ioc,
            "Loop1:RAMP:ENABLE",
            "Ramp enable must be 0 or 1",
        )
        _assert_no_matching_write(running_ioc, mark, "RAMP 1,")
        assert running_ioc.caget_float("Loop1:RAMP:ENABLE_RBV") == pytest.approx(
            1, abs=0.01
        )

    mark = running_ioc.mark()
    running_ioc.caput("Loop1:RAMP:ENABLE:WRITE.PROC", 1)
    _assert_alarm_and_error(
        running_ioc,
        "Loop1:RAMP:ENABLE:WRITE",
        "Ramp enable must be 0 or 1",
    )
    _assert_no_matching_write(running_ioc, mark, "RAMP 1,")


def test_live_ioc_range_boundaries_and_invalid_write(running_ioc):
    for value in (0, 3):
        mark = running_ioc.mark()
        running_ioc.caput("Loop1:RANGE", value)
        running_ioc.wait_for(
            f"RANGE write {value}",
            lambda: any(
                entry.get("command") == f"RANGE 1,{value}"
                for entry in running_ioc.commands_since(mark)
            ),
            timeout=3.0,
            interval=0.1,
        )
        running_ioc.wait_for(
            f"RANGE_RBV {value}",
            lambda: running_ioc.caget_float("Loop1:RANGE_RBV") == pytest.approx(value, abs=0.01),
            timeout=3.0,
            interval=0.1,
        )

    for value in (-1, 1.5, 4, 65536, float("nan")):
        mark = running_ioc.mark()
        running_ioc.caput("Loop1:RANGE", value)
        _assert_alarm_and_error(
            running_ioc,
            "Loop1:RANGE",
            "Heater range must be within 0..3",
        )
        _assert_no_matching_write(running_ioc, mark, "RANGE 1,")
        assert running_ioc.caget_float("Loop1:RANGE_RBV") == pytest.approx(3, abs=0.01)

    assert running_ioc.caget_float("Loop1:RANGE_RBV") == pytest.approx(3, abs=0.01)

    mark = running_ioc.mark()
    running_ioc.caput("Loop1:RANGE:WRITE.PROC", 1)
    _assert_alarm_and_error(
        running_ioc,
        "Loop1:RANGE:WRITE",
        "Heater range must be within 0..3",
    )
    _assert_no_matching_write(running_ioc, mark, "RANGE 1,")


def test_live_ioc_disconnect_updates_communication_error(running_ioc):
    _stop_process(running_ioc.mock_process)

    running_ioc.wait_for(
        "communication failure summary after mock disconnect",
        lambda: (
            running_ioc.caget_float("COMM:STATUS") in (0.0, 2.0)
            and running_ioc.caget_str("ERR") == "Communication failure; inspect alarms"
        ),
        timeout=12.0,
        interval=0.2,
    )
