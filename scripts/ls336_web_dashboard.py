#!/usr/bin/env python3
"""Browser dashboard backed by an EPICS IOC or the built-in demo client."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import queue
import secrets
import sys
import threading
import time
import webbrowser
from datetime import datetime
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

DEFAULT_TIMEOUT = 2.0
DEFAULT_MAINT_PASSWORD = "ls336-maint"
DEFAULT_PREFIX = os.environ.get("LS336_PREFIX", "LS336:")
if getattr(sys, "frozen", False):
    ROOT = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    LOG_DIR = Path(sys.executable).parent / "logs"
else:
    ROOT = Path(__file__).resolve().parents[1]
    LOG_DIR = ROOT / "logs"
BEIJING_TZ = ZoneInfo("Asia/Shanghai")
INPUT_CHANNELS = ("A", "B", "C", "D")
RANGE_LABELS = {"0": "Off", "1": "Low", "2": "Medium", "3": "High"}

from ls336_epics_client import (
    EpicsAccessDenied,
    EpicsClientError,
    EpicsConnectionError,
    EpicsOperationError,
    EpicsTimeoutError,
    LakeShoreEpicsClient,
    PVReading,
)
CSV_FIELDS = [
    "timestamp_local",
    "cold_head_K",
    "sample_K",
    "input_a_K",
    "input_b_K",
    "input_c_K",
    "input_d_K",
    "setpoint_K",
    "ramp_enable",
    "ramp_rate_K_per_min",
    "heater_range",
    "heater_percent",
    "pid_p",
    "pid_i",
    "pid_d",
    "comm",
    "stable_state",
]


def normalize_input(value: object, default: str = "A") -> str:
    channel = str(value or default).strip().upper()
    if channel not in INPUT_CHANNELS:
        raise ValueError("Input must be A, B, C, or D")
    return channel


def add_requested_control_values(
    values: dict[str, str], value: float, ramp_rate: float, heater_range: int
) -> dict[str, str]:
    values["requested_setpoint"] = f"{value:.3f}"
    values["requested_ramp_enable"] = "On" if ramp_rate > 0 else "Off"
    values["requested_ramp_rate"] = f"{ramp_rate:.3f}"
    values["requested_heater_range_raw"] = str(heater_range)
    values["requested_heater_range"] = RANGE_LABELS[str(heater_range)]
    return values


def stable_state(values: dict[str, str], tolerance: float = 0.2) -> str:
    try:
        sample = float(values["sample"])
        setpoint = float(values["setpoint"])
    except (KeyError, TypeError, ValueError):
        return "--"
    return "Stable" if abs(sample - setpoint) <= tolerance else "Not stable"


def today_key() -> str:
    return datetime.now(BEIJING_TZ).strftime("%Y%m%d")


def beijing_now() -> datetime:
    return datetime.now(BEIJING_TZ)


class DemoLakeShoreClient:
    def __init__(self) -> None:
        self.idn = "DEMO,Lake Shore 336,LSA336-DEMO,1.0"
        self.setpoint_value = 90.0
        self.ramp_rate = 0.5
        self.ramp_enabled = True
        self.heater_range = 3
        self.pid = [40.0, 80.0, 2.0]
        self.cold_input = "A"
        self.sample_input = "B"
        self.control_input = "B"
        self.inputs = {"A": 82.4, "B": 84.1, "C": 296.0, "D": 296.0}
        self.last_update = time.monotonic()

    def open(self) -> None:
        self.last_update = time.monotonic()

    def read_pid(self) -> tuple[str, str, str]:
        return (f"{self.pid[0]:.3f}", f"{self.pid[1]:.3f}", f"{self.pid[2]:.3f}")

    def set_pid(self, p: float, i: float, d: float) -> dict[str, str]:
        old = self.read_pid()
        self.pid = [p, i, d]
        new = self.read_pid()
        return {"old": ",".join(old), "new": ",".join(new)}

    def read_all(self) -> dict[str, str]:
        self._simulate_temperature()
        pid_p, pid_i, pid_d = self.read_pid()
        return {
            "idn": self.idn,
            "cold_head": f"{self.inputs[self.cold_input]:.3f}",
            "sample": f"{self.inputs[self.sample_input]:.3f}",
            "input_a": f"{self.inputs['A']:.3f}",
            "input_b": f"{self.inputs['B']:.3f}",
            "input_c": f"{self.inputs['C']:.3f}",
            "input_d": f"{self.inputs['D']:.3f}",
            "cold_input": self.cold_input,
            "sample_input": self.sample_input,
            "control_input": self.control_input,
            "setpoint": f"{self.setpoint_value:.3f}",
            "ramp_enable": "On" if self.ramp_enabled else "Off",
            "ramp_rate": f"{self.ramp_rate:.3f}",
            "heater_range_raw": str(self.heater_range),
            "heater_range": RANGE_LABELS[str(self.heater_range)],
            "pid_p": pid_p,
            "pid_i": pid_i,
            "pid_d": pid_d,
            "heater": f"{self._heater_output():.1f}",
            "comm": "Demo",
            "updated": time.strftime("%H:%M:%S"),
        }

    def set_setpoint(self, value: float, ramp_rate: float) -> dict[str, str]:
        if not 0 <= value <= 350:
            raise ValueError("Setpoint must be within 0..350 K")
        if not 0 <= ramp_rate <= 10:
            raise ValueError("Ramp rate must be within 0..10 K/min")
        self.ramp_rate = ramp_rate
        self.ramp_enabled = ramp_rate > 0
        self.setpoint_value = value
        return self.read_all()

    def set_inputs(self, cold_input: str, sample_input: str, control_input: str) -> dict[str, str]:
        self.cold_input = normalize_input(cold_input, "A")
        self.sample_input = normalize_input(sample_input, "B")
        self.control_input = normalize_input(control_input, self.sample_input)
        return self.read_all()

    def set_control(
        self,
        value: float,
        ramp_rate: float,
        heater_range: object,
        cold_input: str,
        sample_input: str,
        control_input: str,
    ) -> dict[str, str]:
        if isinstance(heater_range, bool):
            raise ValueError("Heater range must be 0=Off, 1=Low, 2=Medium, or 3=High")
        try:
            range_value = float(heater_range)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Heater range must be 0=Off, 1=Low, 2=Medium, or 3=High") from exc
        if not math.isfinite(range_value) or range_value < 0 or range_value > 3 or not range_value.is_integer():
            raise ValueError("Heater range must be 0=Off, 1=Low, 2=Medium, or 3=High")
        range_code = int(range_value)
        if not 0 <= value <= 350:
            raise ValueError("Setpoint must be within 0..350 K")
        if not 0 <= ramp_rate <= 10:
            raise ValueError("Ramp rate must be within 0..10 K/min")
        self.set_inputs(cold_input, sample_input, control_input)
        self.setpoint_value = value
        self.ramp_rate = ramp_rate
        self.ramp_enabled = ramp_rate > 0
        self.heater_range = range_code
        return add_requested_control_values(self.read_all(), value, ramp_rate, range_code)

    def _simulate_temperature(self) -> None:
        now = time.monotonic()
        dt = min(10.0, max(0.0, now - self.last_update))
        self.last_update = now
        rate_per_second = max(self.ramp_rate, 0.1) / 60.0
        for channel in ("A", "B"):
            lag = 1.0 if channel == self.control_input else 0.65
            value = self.inputs[channel]
            delta = self.setpoint_value - value
            max_move = rate_per_second * dt * lag
            self.inputs[channel] = value + max(-max_move, min(max_move, delta))

    def _heater_output(self) -> float:
        error = max(0.0, self.setpoint_value - self.inputs[self.control_input])
        if self.heater_range == 0:
            return 0.0
        return min(100.0, error * 8.0 + self.heater_range * 8.0)


class LogArchive:
    def __init__(self, log_dir: Path) -> None:
        self.log_dir = log_dir
        self._lock = threading.RLock()
        self.active = False
        self.rows = 0
        self.csv_path: Path | None = None
        self.meta_path: Path | None = None
        self.current_key = ""
        self.ioc_prefix = ""
        self.current_mode = ""
        self.last_write_local = ""
        self.error = ""

    def start_session(self, ioc_prefix: str, mode: str) -> dict[str, object]:
        with self._lock:
            self.active = True
            self.ioc_prefix = ioc_prefix
            self.current_mode = mode
            try:
                self._ensure_file(force=False)
            except OSError as exc:
                self.error = str(exc)
                return self.status()
            payload = self._metadata()
            payload.setdefault("sessions", []).append(
                {
                    "started_local": beijing_now().isoformat(timespec="seconds"),
                    "ioc_prefix": ioc_prefix,
                    "mode": mode,
                }
            )
            self._save_metadata(payload)
            return self.status()

    def pause(self, operator: str) -> dict[str, object]:
        with self._lock:
            self.active = False
            self.error = ""
            self._record_operation("pause_logging", operator)
            return self.status()

    def resume(self, operator: str) -> dict[str, object]:
        with self._lock:
            self.active = True
            self.error = ""
            self._ensure_file(force=False)
            self._record_operation("resume_logging", operator)
            return self.status()

    def new_file(self, operator: str) -> dict[str, object]:
        with self._lock:
            self.active = True
            self.error = ""
            self._ensure_file(force=True)
            self._record_operation("new_log_file", operator)
            return self.status()

    def append(self, values: dict[str, str]) -> None:
        with self._lock:
            if not self.active:
                return
            try:
                self._ensure_file(force=False)
                assert self.csv_path is not None
                now = beijing_now()
                row = {
                    "timestamp_local": now.isoformat(timespec="seconds"),
                    "cold_head_K": values.get("cold_head", ""),
                    "sample_K": values.get("sample", ""),
                    "input_a_K": values.get("input_a", ""),
                    "input_b_K": values.get("input_b", ""),
                    "input_c_K": values.get("input_c", ""),
                    "input_d_K": values.get("input_d", ""),
                    "setpoint_K": values.get("setpoint", ""),
                    "ramp_enable": values.get("ramp_enable", ""),
                    "ramp_rate_K_per_min": values.get("ramp_rate", ""),
                    "heater_range": values.get("heater_range", ""),
                    "heater_percent": values.get("heater", ""),
                    "pid_p": values.get("pid_p", ""),
                    "pid_i": values.get("pid_i", ""),
                    "pid_d": values.get("pid_d", ""),
                    "comm": values.get("comm", ""),
                    "stable_state": stable_state(values),
                }
                with self.csv_path.open("a", newline="", encoding="utf-8") as handle:
                    csv.DictWriter(handle, fieldnames=CSV_FIELDS).writerow(row)
                self.rows += 1
                self.last_write_local = row["timestamp_local"]
                self.error = ""
            except OSError as exc:
                self.error = str(exc)

    def audit_pid(self, operator: str, old: str, new: str) -> None:
        with self._lock:
            self._record_operation("pid_write", operator, {"old": old, "new": new})

    def set_error(self, message: str) -> None:
        with self._lock:
            self.error = message

    def status(self) -> dict[str, object]:
        with self._lock:
            return {
                "active": self.active,
                "rows": self.rows,
                "csv": str(self.csv_path) if self.csv_path else "",
                "metadata": str(self.meta_path) if self.meta_path else "",
                "log_dir": str(self.log_dir),
                "filename": self.csv_path.name if self.csv_path else "",
                "last_write_local": self.last_write_local,
                "error": self.error,
            }

    def _ensure_file(self, force: bool) -> None:
        key = today_key()
        if not force and self.csv_path is not None and self.current_key == key and self.csv_path.exists():
            return
        self.log_dir.mkdir(parents=True, exist_ok=True)
        suffix = "" if not force else f"_manual_{beijing_now().strftime('%H%M%S')}"
        self.current_key = key
        self.csv_path = self.log_dir / f"ls336_temperature_{key}{suffix}.csv"
        self.meta_path = self.log_dir / f"ls336_temperature_{key}{suffix}.meta.json"
        if not self.csv_path.exists():
            with self.csv_path.open("w", newline="", encoding="utf-8") as handle:
                csv.DictWriter(handle, fieldnames=CSV_FIELDS).writeheader()
        self.rows = max(0, sum(1 for _ in self.csv_path.open(encoding="utf-8")) - 1)
        if not self.meta_path.exists():
            self._save_metadata({"sessions": [], "operations": []})

    def _metadata(self) -> dict[str, object]:
        if self.meta_path is None or not self.meta_path.exists():
            return {"sessions": [], "operations": []}
        try:
            return json.loads(self.meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"sessions": [], "operations": []}

    def _save_metadata(self, metadata: dict[str, object] | None = None) -> None:
        if self.meta_path is None:
            return
        payload = metadata or self._metadata()
        payload.setdefault("sessions", [])
        payload.setdefault("operations", [])
        payload.update(
            {
                "instrument": "Lake Shore 336",
                "date": self.current_key,
                "timezone": "Asia/Shanghai",
                "ioc_prefix": self.ioc_prefix,
                "mode": self.current_mode,
                "csv_file": self.csv_path.name if self.csv_path else "",
                "csv_fields": CSV_FIELDS,
                "project_root": str(ROOT),
                "software": "LakeShore336 local dashboard",
            }
        )
        self.meta_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _record_operation(self, action: str, operator: str, details: dict[str, str] | None = None) -> None:
        self._ensure_file(force=False)
        payload = self._metadata()
        payload.setdefault("operations", []).append(
            {
                "timestamp_local": beijing_now().isoformat(timespec="seconds"),
                "operator": operator,
                "action": action,
                "details": details or {},
            }
        )
        self._save_metadata(payload)


class MaintenanceAuth:
    def __init__(self, password: str) -> None:
        self.password = password
        self._tokens: set[str] = set()
        self._lock = threading.RLock()

    def login(self, password: str) -> str:
        if not secrets.compare_digest(password, self.password):
            raise PermissionError("Invalid maintenance password")
        token = secrets.token_urlsafe(24)
        with self._lock:
            self._tokens.add(token)
        return token

    def is_valid(self, token: str) -> bool:
        with self._lock:
            return token in self._tokens


class ArchiveWorker:
    """Periodic CSV writer and EPICS log-command consumer for one IOC client."""

    COMMANDS = {
        "LOG:START": "start",
        "LOG:PAUSE": "pause",
        "LOG:RESUME": "resume",
        "LOG:NEW_FILE": "new_file",
    }
    STATE_CODES = {"stopped": 0, "recording": 1, "paused": 2, "error": 3}
    HEARTBEAT_TIMEOUT = 6.0

    def __init__(self, client: LakeShoreEpicsClient, archive: LogArchive, prefix: str) -> None:
        self.client = client
        self.archive = archive
        self.prefix = prefix
        self._commands: queue.Queue[tuple[str, str]] = queue.Queue(maxsize=8)
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._command_condition = threading.Condition(self._lock)
        self._request_lock = threading.Lock()
        self._pending: set[str] = set()
        self._processed: dict[str, int] = {}
        self._command_errors: dict[str, str] = {}
        self._heartbeat = 0
        self._last_heartbeat_value: int | None = None
        self._last_heartbeat_change = time.monotonic()
        self._callback_token = client.add_monitor_callback(self._on_monitor)
        self._thread = threading.Thread(target=self._run, name="ls336-archive", daemon=True)

    def start(self) -> None:
        try:
            status = self.archive.start_session(self.prefix, "epics")
            if status.get("error"):
                self.archive.set_error(str(status["error"]))
            self._write_sample()
        except Exception as exc:  # noqa: BLE001
            self.archive.set_error(str(exc))
        self._publish_status(heartbeat=True)
        self._thread.start()

    def stop(self) -> None:
        self.client.remove_monitor_callback(self._callback_token)
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=10.0)
        if not self._thread.is_alive():
            with self.archive._lock:
                self.archive.active = False
            self._publish_status(state_override="stopped", heartbeat=False)

    def request(self, command: str, timeout: float = 12.0) -> dict[str, object]:
        command = command.strip().lower()
        suffix = next((key for key, value in self.COMMANDS.items() if value == command), None)
        if suffix is None:
            raise ValueError("Log command must be start, pause, resume, or new_file")
        with self._request_lock:
            with self._command_condition:
                baseline = self._processed.get(suffix, 0)
            self.client.write_log_command(command)
            deadline = time.monotonic() + timeout
            with self._command_condition:
                while self._processed.get(suffix, 0) <= baseline:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise EpicsTimeoutError(f"Timed out waiting for {command} archive command")
                    self._command_condition.wait(timeout=min(remaining, 0.25))
                error = self._command_errors.get(suffix, "")
            if error:
                raise EpicsOperationError(error)
            return self.status()

    def status(self) -> dict[str, object]:
        payload = self.archive.status()
        age = max(0.0, time.monotonic() - self._last_heartbeat_change)
        alive = self._thread.is_alive() and age <= self.HEARTBEAT_TIMEOUT
        payload.update(
            {
                "state": self._state_name(),
                "heartbeat_alive": alive,
                "heartbeat_age_seconds": round(age, 1),
            }
        )
        if self._thread.is_alive() and not alive and not payload.get("error"):
            payload["error"] = "Archive heartbeat is stale"
        return payload

    def _on_monitor(self, suffix: str, reading: PVReading) -> None:
        if suffix == "LOG:HEARTBEAT":
            try:
                value = int(reading.value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return
            with self._lock:
                if value != self._last_heartbeat_value:
                    self._last_heartbeat_value = value
                    self._last_heartbeat_change = time.monotonic()
        command = self.COMMANDS.get(suffix)
        if command is None or not reading.is_valid() or self._integer(reading.value) != 1:
            return
        with self._lock:
            if suffix in self._pending or self._stop.is_set():
                return
            self._pending.add(suffix)
        try:
            self._commands.put_nowait((suffix, command))
        except queue.Full:
            with self._lock:
                self._pending.discard(suffix)
            self.archive.set_error("Archive command queue is full")

    @staticmethod
    def _integer(value: object | None) -> int | None:
        try:
            return int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _number(
        snapshot: dict[str, PVReading], suffix: str, precision: int = 3, max_age: float = 6.0
    ) -> str:
        reading = snapshot.get(suffix)
        if reading is None or not reading.is_valid(max_age=max_age):
            return ""
        try:
            number = float(reading.value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return ""
        return f"{number:.{precision}f}" if math.isfinite(number) else ""

    def _write_sample(self) -> None:
        if not self.archive.active:
            return
        snapshot = self.client.read_snapshot(refresh=True)
        cold = self.client.cold_input
        sample = self.client.sample_input
        values: dict[str, str] = {
            "cold_head": self._number(snapshot, f"Input:{cold}:TEMP_RBV"),
            "sample": self._number(snapshot, f"Input:{sample}:TEMP_RBV"),
            "input_a": self._number(snapshot, "Input:A:TEMP_RBV"),
            "input_b": self._number(snapshot, "Input:B:TEMP_RBV"),
            "input_c": self._number(snapshot, "Input:C:TEMP_RBV"),
            "input_d": self._number(snapshot, "Input:D:TEMP_RBV"),
            "setpoint": self._number(snapshot, "Loop1:SETP_RBV"),
            "ramp_rate": self._number(snapshot, "Loop1:RAMP:RATE_RBV"),
            "heater": self._number(snapshot, "Loop1:HTR_RBV", 1),
            "pid_p": self._number(snapshot, "Loop1:PID:P_RBV", max_age=22.0),
            "pid_i": self._number(snapshot, "Loop1:PID:I_RBV", max_age=22.0),
            "pid_d": self._number(snapshot, "Loop1:PID:D_RBV", max_age=22.0),
        }
        ramp = snapshot.get("Loop1:RAMP:ENABLE_RBV")
        values["ramp_enable"] = (
            ("On" if self._integer(ramp.value) else "Off")
            if ramp is not None and ramp.is_valid() else ""
        )
        range_reading = snapshot.get("Loop1:RANGE_RBV")
        range_code = self._integer(range_reading.value) if range_reading and range_reading.is_valid() else None
        values["heater_range"] = RANGE_LABELS.get(str(range_code), "")
        comm = snapshot.get("COMM:STATUS")
        if comm is None:
            values["comm"] = "Stale"
        elif comm.error:
            if "IOC unavailable" in comm.error:
                values["comm"] = "IOC unavailable"
            elif "Timed out" in comm.error:
                values["comm"] = "IOC timeout"
            else:
                values["comm"] = "CA read error"
        elif not comm.is_valid():
            values["comm"] = "Stale" if comm.is_stale() else "Alarm"
        else:
            values["comm"] = {0: "Disconnected", 1: "Connected", 2: "Error"}.get(
                self._integer(comm.value), "Error"
            )
        self.archive.append(values)

    def _execute_command(self, suffix: str, command: str) -> None:
        error = ""
        try:
            if command == "start":
                result = self.archive.start_session(self.prefix, "epics")
                if result.get("error"):
                    raise OSError(str(result["error"]))
                self._write_sample()
            elif command == "pause":
                self.archive.pause("epics")
            elif command == "resume":
                self.archive.resume("epics")
                self._write_sample()
            elif command == "new_file":
                self.archive.new_file("epics")
                self._write_sample()
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
            self.archive.set_error(error)
        finally:
            try:
                self.client.acknowledge_log_command(command)
            except Exception as exc:  # noqa: BLE001
                error = error or str(exc)
                self.archive.set_error(error)
            with self._command_condition:
                self._pending.discard(suffix)
                self._processed[suffix] = self._processed.get(suffix, 0) + 1
                self._command_errors[suffix] = error
                self._command_condition.notify_all()
        self._publish_status(heartbeat=False)

    def _state_name(self) -> str:
        if self.archive.error:
            return "error"
        if self.archive.active:
            return "recording"
        return "paused" if self.archive.csv_path else "stopped"

    def _publish_status(self, state_override: str | None = None, heartbeat: bool) -> None:
        if heartbeat:
            self._heartbeat = (self._heartbeat + 1) & 0x7FFFFFFF
        state_name = state_override or self._state_name()
        status = self.archive.status()
        try:
            self.client.write_archive_status(
                state=self.STATE_CODES[state_name],
                filename=str(status["filename"]),
                rows=int(status["rows"]),
                last_write=str(status["last_write_local"]),
                error=str(status["error"]),
                heartbeat=self._heartbeat if heartbeat else None,
            )
        except Exception as exc:  # noqa: BLE001
            self.archive.set_error(str(exc))

    def _run(self) -> None:
        next_sample = time.monotonic() + 2.0
        try:
            while not self._stop.is_set():
                timeout = max(0.05, min(0.5, next_sample - time.monotonic()))
                try:
                    suffix, command = self._commands.get(timeout=timeout)
                except queue.Empty:
                    pass
                else:
                    self._execute_command(suffix, command)
                    self._commands.task_done()
                now = time.monotonic()
                if now >= next_sample:
                    try:
                        self._write_sample()
                    except Exception as exc:  # noqa: BLE001
                        self.archive.set_error(str(exc))
                    self._publish_status(heartbeat=True)
                    next_sample = now + 2.0
        except Exception as exc:  # noqa: BLE001
            self.archive.set_error(f"Archive worker stopped: {exc}")
        finally:
            self._publish_status(heartbeat=False)


STATE: dict[str, object | None] = {"client": None, "prefix": None, "mode": None, "archive": None}
STATE_LOCK = threading.RLock()
LOGGER = LogArchive(LOG_DIR)
AUTH = MaintenanceAuth(os.environ.get("LS336_MAINT_PASSWORD", DEFAULT_MAINT_PASSWORD))


MAINTENANCE_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lake Shore 336 Maintenance</title>
<style>body{font-family:Arial,sans-serif;background:#101820;color:#edf7fa;margin:0}main{max-width:900px;margin:0 auto;padding:24px}.panel{border:1px solid #36cde8;background:#1d2b35;padding:16px;margin:14px 0;border-radius:6px}input,button{font:inherit;padding:8px;margin:4px;background:#14212a;color:#edf7fa;border:1px solid #59717c;border-radius:4px}button{background:#246577;font-weight:700}.danger{background:#632033}.status{white-space:pre-wrap;background:#0d171e;padding:10px;border-radius:4px}</style>
</head><body><main><h1>Lake Shore 336 Maintenance</h1>
<div class="panel" id="login"><h2>Login</h2><input id="password" type="password" placeholder="Maintenance password"><button onclick="login()">Login</button></div>
<div class="panel"><h2>Log Control</h2><button onclick="pauseLog()">Pause logging</button><button onclick="resumeLog()">Resume logging</button><button onclick="newLog()">New log file</button><button onclick="downloadCsv()">Download CSV</button><button onclick="status()">Refresh status</button><div class="status" id="log_status">--</div></div>
<div class="panel"><h2>PID Control</h2><button onclick="readPid()">Read PID</button><br><input id="pid_p" type="number" step="0.001" placeholder="P"><input id="pid_i" type="number" step="0.001" placeholder="I"><input id="pid_d" type="number" step="0.001" placeholder="D"><button class="danger" onclick="writePid()">Confirm PID Write</button><div class="status" id="pid_status">--</div></div>
</main><script>
async function api(path,body){const r=await fetch(path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});const d=await r.json();if(!r.ok)throw new Error(d.error||r.statusText);return d}
function show(id,obj){document.getElementById(id).textContent=typeof obj==='string'?obj:JSON.stringify(obj,null,2)}
async function login(){try{await api('/api/maintenance/login',{password:document.getElementById('password').value});show('log_status','Logged in');status()}catch(e){show('log_status',e.message)}}
async function status(){try{show('log_status',await api('/api/log/status'))}catch(e){show('log_status',e.message)}}
async function pauseLog(){try{show('log_status',await api('/api/log/pause',{}))}catch(e){show('log_status',e.message)}}
async function resumeLog(){try{show('log_status',await api('/api/log/resume',{}))}catch(e){show('log_status',e.message)}}
async function newLog(){try{show('log_status',await api('/api/log/new',{}))}catch(e){show('log_status',e.message)}}
function downloadCsv(){location='/api/log/download'}
async function readPid(){try{show('pid_status',await api('/api/pid'))}catch(e){show('pid_status',e.message)}}
async function writePid(){if(!confirm('Write PID to Loop 1?'))return;try{show('pid_status',await api('/api/pid',{p:Number(pid_p.value),i:Number(pid_i.value),d:Number(pid_d.value)}))}catch(e){show('pid_status',e.message)}}
status();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    @staticmethod
    def client_error_status(exc: Exception) -> int:
        if isinstance(exc, (PermissionError, EpicsAccessDenied)):
            return 403
        if isinstance(exc, EpicsTimeoutError):
            return 504
        if isinstance(exc, EpicsConnectionError):
            return 503
        if isinstance(exc, EpicsOperationError):
            return 409
        if isinstance(exc, (ValueError, KeyError, TypeError)):
            return 400
        if isinstance(exc, EpicsClientError):
            return 502
        return 500

    @staticmethod
    def is_demo_mode() -> bool:
        with STATE_LOCK:
            return STATE["mode"] == "demo"

    @staticmethod
    def disconnect_active() -> None:
        with STATE_LOCK:
            old_client = STATE["client"]
            old_archive = STATE["archive"]
            old_mode = STATE["mode"]
            STATE.update(client=None, prefix=None, mode=None, archive=None)
        if isinstance(old_archive, ArchiveWorker):
            old_archive.stop()
        elif old_mode == "demo":
            with LOGGER._lock:
                LOGGER.active = False
        if isinstance(old_client, LakeShoreEpicsClient):
            old_client.close()

    def archive_status(self) -> dict[str, object]:
        with STATE_LOCK:
            archive = STATE["archive"]
            mode = STATE["mode"]
        if isinstance(archive, ArchiveWorker):
            result = archive.status()
            result["mode"] = mode
            return result
        result = LOGGER.status()
        result["mode"] = mode or "disconnected"
        result["state"] = "recording" if LOGGER.active else ("paused" if LOGGER.csv_path else "stopped")
        result["heartbeat_alive"] = mode == "demo"
        result["heartbeat_age_seconds"] = 0.0 if mode == "demo" else None
        return result

    def log_command(self, command: str) -> None:
        with STATE_LOCK:
            archive = STATE["archive"]
            mode = STATE["mode"]
        try:
            if isinstance(archive, ArchiveWorker):
                self.reply_json(archive.request(command))
            elif mode == "demo":
                if command == "pause":
                    result = LOGGER.pause("maintenance")
                elif command == "resume":
                    result = LOGGER.resume("maintenance")
                else:
                    result = LOGGER.new_file("maintenance")
                self.reply_json(result)
            else:
                raise EpicsConnectionError("Connect the dashboard to an IOC before controlling its archive")
        except Exception as exc:  # noqa: BLE001
            self.reply_json({"error": str(exc), "log_status": self.archive_status()}, self.client_error_status(exc))

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            try:
                self.reply_html((ROOT / "web" / "index.html").read_text(encoding="utf-8"))
            except FileNotFoundError:
                self.reply_json({"error": "Dashboard file not found"}, 500)
        elif path == "/maintenance":
            self.reply_html(MAINTENANCE_HTML)
        elif path in ("/api/config", "/api/ports"):
            self.reply_json({"prefix": DEFAULT_PREFIX})
        elif path == "/api/read":
            with STATE_LOCK:
                demo_mode = STATE["mode"] == "demo"
            self.with_client(lambda client: client.read_all(), append_log=demo_mode)
        elif path == "/api/log/status":
            self.reply_json(self.archive_status())
        elif path == "/api/log/download":
            self.reply_file(LOGGER.csv_path)
        elif path == "/api/pid":
            if not self.require_maintenance():
                return
            self.with_client(lambda client: {"pid": ",".join(client.read_pid())})
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            body = self.read_body()
        except (ValueError, OSError) as exc:
            self.reply_json({"error": str(exc)}, 400)
            return
        if path == "/api/connect":
            client: LakeShoreEpicsClient | DemoLakeShoreClient | None = None
            try:
                prefix = str(body.get("prefix") or DEFAULT_PREFIX).strip()
                if prefix.upper() == "DEMO":
                    self.disconnect_active()
                    client = DemoLakeShoreClient()
                    client.open()
                    with STATE_LOCK:
                        STATE.update(client=client, prefix="DEMO", mode="demo", archive=None)
                    LOGGER.start_session("DEMO", "demo")
                    payload = client.read_all()
                    LOGGER.append(payload)
                else:
                    if not prefix:
                        raise ValueError("IOC PV prefix is required")
                    self.disconnect_active()
                    client = LakeShoreEpicsClient(prefix, timeout=DEFAULT_TIMEOUT)
                    client.connect()
                    payload = client.read_all()
                    with STATE_LOCK:
                        STATE.update(client=client, prefix=client.prefix, mode="epics", archive=None)
                    worker = ArchiveWorker(client, LOGGER, client.prefix)
                    with STATE_LOCK:
                        STATE["archive"] = worker
                    worker.start()
                assert client is not None
                payload["log_status"] = self.archive_status()
                self.reply_json(payload)
            except Exception as exc:  # noqa: BLE001
                self.disconnect_active()
                status = self.client_error_status(exc)
                self.reply_json({"error": str(exc)}, status)
        elif path == "/api/setpoint":
            self.with_client(
                lambda client: client.set_setpoint(float(body["target"]), float(body["ramp"])),
                append_log=self.is_demo_mode(),
            )
        elif path == "/api/inputs":
            self.with_client(
                lambda client: client.set_inputs(
                    str(body["cold_input"]),
                    str(body["sample_input"]),
                    str(body.get("control_input") or body["sample_input"]),
                ),
                append_log=self.is_demo_mode(),
            )
        elif path == "/api/control":
            self.with_client(
                lambda client: client.set_control(
                    float(body["target"]),
                    float(body["ramp"]),
                    body["range"],
                    str(body.get("cold_input") or "A"),
                    str(body.get("sample_input") or "B"),
                    str(body.get("control_input") or body.get("sample_input") or "B"),
                ),
                append_log=self.is_demo_mode(),
            )
        elif path == "/api/maintenance/login":
            try:
                token = AUTH.login(str(body.get("password", "")))
            except PermissionError as exc:
                self.reply_json({"error": str(exc)}, 403)
                return
            self.reply_json({"ok": True}, headers={"Set-Cookie": f"ls336_maint={token}; Path=/; SameSite=Strict; HttpOnly"})
        elif path == "/api/log/pause":
            if not self.require_maintenance():
                return
            self.log_command("pause")
        elif path == "/api/log/resume":
            if not self.require_maintenance():
                return
            self.log_command("resume")
        elif path == "/api/log/new":
            if not self.require_maintenance():
                return
            self.log_command("new_file")
        elif path == "/api/pid":
            if not self.require_maintenance():
                return
            try:
                p, i, d = self.validate_pid(body)
            except ValueError as exc:
                self.reply_json({"error": str(exc)}, 400)
                return
            self.with_client(lambda client: self.write_pid(client, p, i, d))
        else:
            self.send_error(404)

    def with_client(self, action, append_log: bool = False) -> None:
        with STATE_LOCK:
            client = STATE["client"]
        if client is None:
            self.reply_json({"error": "Not connected. Enter an IOC prefix and click Connect."}, 400)
            return
        try:
            payload = action(client)
            if append_log and isinstance(payload, dict):
                LOGGER.append(payload)
            if isinstance(payload, dict):
                payload["log_status"] = self.archive_status()
            self.reply_json(payload)
        except EpicsAccessDenied as exc:
            self.reply_json({"error": str(exc), "log_status": self.archive_status()}, 403)
        except EpicsTimeoutError as exc:
            self.reply_json({"error": str(exc), "log_status": self.archive_status()}, 504)
        except EpicsConnectionError as exc:
            self.reply_json({"error": str(exc), "log_status": self.archive_status()}, 503)
        except EpicsOperationError as exc:
            self.reply_json({"error": str(exc), "log_status": self.archive_status()}, 409)
        except ValueError as exc:
            self.reply_json({"error": str(exc), "log_status": self.archive_status()}, 400)
        except Exception as exc:  # noqa: BLE001
            self.reply_json({"error": str(exc), "log_status": self.archive_status()}, 500)

    def write_pid(self, client, p: float, i: float, d: float) -> dict[str, str]:
        result = client.set_pid(p, i, d)
        LOGGER.audit_pid("maintenance", result["old"], result["new"])
        return result

    def validate_pid(self, body: dict[str, object]) -> tuple[float, float, float]:
        try:
            if any(isinstance(body[key], bool) for key in ("p", "i", "d")):
                raise ValueError("PID values must be numeric")
            values = (float(body["p"]), float(body["i"]), float(body["d"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("PID values must be numeric") from exc
        p, i, d = values
        if not all(math.isfinite(value) for value in values) or not (
            0.1 <= p <= 1000 and 0.1 <= i <= 1000 and 0 <= d <= 200
        ):
            raise ValueError("PID values must be P 0.1..1000, I 0.1..1000, D 0..200")
        return values

    def require_maintenance(self) -> bool:
        token = ""
        raw_cookie = self.headers.get("Cookie", "")
        if raw_cookie:
            try:
                parsed = cookies.SimpleCookie(raw_cookie)
                if "ls336_maint" in parsed:
                    token = parsed["ls336_maint"].value
            except cookies.CookieError:
                token = ""
        if not AUTH.is_valid(token):
            self.reply_json({"error": "Maintenance login required"}, 403)
            return False
        return True

    def read_body(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        try:
            return json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError(f"Invalid JSON in request body: {exc}") from exc

    def reply_html(self, html: str) -> None:
        data = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def reply_json(
        self, payload: dict[str, object], status: int = 200, headers: dict[str, str] | None = None
    ) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def reply_file(self, path: Path | None) -> None:
        if path is None or not path.exists():
            self.reply_json({"error": "No archived CSV is available yet."}, 404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args) -> None:
        return


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lake Shore 336 browser dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--prefix", default=DEFAULT_PREFIX, help="IOC PV prefix (also settable with LS336_PREFIX)")
    parser.add_argument("--no-open", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    global DEFAULT_PREFIX
    DEFAULT_PREFIX = args.prefix.strip() or "LS336:"
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}"
    print(f"Lake Shore 336 browser dashboard: {url}")
    if AUTH.password == DEFAULT_MAINT_PASSWORD:
        print("Maintenance password uses the default value. Set LS336_MAINT_PASSWORD before production use.")
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        Handler.disconnect_active()


if __name__ == "__main__":
    main()
