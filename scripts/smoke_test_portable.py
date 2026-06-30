#!/usr/bin/env python3
"""Run a packaged Lake Shore 336 dashboard through a DEMO acceptance test."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def request_text(url: str, timeout: float) -> str:
    with urlopen(url, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"{url} returned HTTP {response.status}")
        return response.read().decode("utf-8")


def request_json(url: str, timeout: float, body: dict[str, object] | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method="POST" if data is not None else "GET",
    )
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
        if response.status != 200:
            raise RuntimeError(f"{url} returned HTTP {response.status}: {payload}")
        return payload


def wait_until_ready(base_url: str, process: subprocess.Popen, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Packaged server exited with code {process.returncode}")
        try:
            return request_json(f"{base_url}/api/ports", 1.0)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last_error = exc
            time.sleep(0.25)
    raise RuntimeError(f"Packaged server was not ready after {timeout:g}s: {last_error}")


def require_equal(payload: dict, key: str, expected: str) -> None:
    actual = str(payload.get(key, ""))
    if actual != expected:
        raise RuntimeError(f"Unexpected {key}: expected {expected!r}, got {actual!r}")


def clean_created_logs(log_dir: Path, files_before: set[Path]) -> None:
    if not log_dir.exists():
        return
    for path in log_dir.iterdir():
        if path.is_file() and path not in files_before:
            path.unlink()


def smoke_test(executable: Path, port: int, timeout: float, cleanup_logs: bool) -> None:
    executable = executable.resolve()
    if not executable.is_file():
        raise FileNotFoundError(f"Packaged executable not found: {executable}")

    log_dir = executable.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    files_before = set(log_dir.iterdir())
    base_url = f"http://127.0.0.1:{port}"
    process = subprocess.Popen(
        [
            str(executable),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--no-open",
        ],
        cwd=executable.parent,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        ports = wait_until_ready(base_url, process, timeout)
        if "DEMO" not in ports.get("ports", []):
            raise RuntimeError("DEMO port is missing from the packaged application")

        main_page = request_text(f"{base_url}/", 3.0)
        maintenance_page = request_text(f"{base_url}/maintenance", 3.0)
        if "Lake Shore" not in main_page or "PID Control" not in maintenance_page:
            raise RuntimeError("Main or maintenance page content is incomplete")

        connected = request_json(f"{base_url}/api/connect", 3.0, {"port": "DEMO"})
        require_equal(connected, "comm", "Demo")

        controlled = request_json(
            f"{base_url}/api/control",
            3.0,
            {
                "target": 95.0,
                "ramp": 1.25,
                "range": 2,
                "cold_input": "B",
                "sample_input": "A",
                "control_input": "A",
            },
        )
        for key, expected in {
            "setpoint": "95.000",
            "ramp_rate": "1.250",
            "heater_range_raw": "2",
            "cold_input": "B",
            "sample_input": "A",
            "control_input": "A",
        }.items():
            require_equal(controlled, key, expected)

        status = request_json(f"{base_url}/api/log/status", 3.0)
        if not status.get("active") or int(status.get("rows", 0)) < 2:
            raise RuntimeError(f"Packaged logger is not recording: {status}")
        if not str(status.get("last_write_local", "")).endswith("+08:00"):
            raise RuntimeError(f"Packaged logger is not using Beijing time: {status}")

        csv_path = Path(str(status.get("csv", "")))
        metadata_path = Path(str(status.get("metadata", "")))
        if not csv_path.is_file() or not metadata_path.is_file():
            raise RuntimeError("Packaged CSV or metadata archive was not created")
        header = csv_path.read_text(encoding="utf-8").splitlines()[0]
        if not header.startswith("timestamp_local,"):
            raise RuntimeError(f"Unexpected CSV header: {header}")
        if "timestamp_iso" in header:
            raise RuntimeError(f"UTC timestamp column should not be present: {header}")
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        if cleanup_logs:
            clean_created_logs(log_dir, files_before)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8877)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--cleanup-logs", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        smoke_test(args.executable, args.port, args.timeout, args.cleanup_logs)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {exc}")
        return 1
    print("PASS: packaged DEMO control and Beijing-time logging")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
