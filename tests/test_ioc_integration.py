import importlib.util
import json
import os
import select
import subprocess
import sys
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MOCK_PATH = ROOT / "scripts" / "ls336_ioc_mock.py"
RUN_TESTS_PATH = ROOT / "scripts" / "run_tests.sh"
IOC_BINARY = ROOT / "bin" / "linux-x86_64" / "ls336"


def load_mock_module():
    spec = importlib.util.spec_from_file_location("ls336_ioc_mock_test", MOCK_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def linux_ioc_binary_exists() -> bool:
    return IOC_BINARY.is_file()


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
