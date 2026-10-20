"""Channel Access client for the Lake Shore 336 IOC.

This module never opens a serial port. The IOC owns the instrument connection;
this client reads its PVs, submits control requests, and monitors archive PVs.
"""

from __future__ import annotations

import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable

from caproto.threading.client import Context, PV


INPUT_CHANNELS = ("A", "B", "C", "D")
RANGE_LABELS = {0: "Off", 1: "Low", 2: "Medium", 3: "High"}
INPUT_READBACK_LABELS = {0: "None", 1: "A", 2: "B", 3: "C", 4: "D"}
MAX_PV_AGE_SECONDS = 6.0

INSTRUMENT_PVS = {
    "idn": "IDN",
    "input_a": "Input:A:TEMP_RBV",
    "input_b": "Input:B:TEMP_RBV",
    "input_c": "Input:C:TEMP_RBV",
    "input_d": "Input:D:TEMP_RBV",
    "control_input": "Loop1:INPUT_RBV",
    "setpoint": "Loop1:SETP_RBV",
    "ramp_enable": "Loop1:RAMP:ENABLE_RBV",
    "ramp_rate": "Loop1:RAMP:RATE_RBV",
    "heater_range": "Loop1:RANGE_RBV",
    "heater": "Loop1:HTR_RBV",
    "pid_p": "Loop1:PID:P_RBV",
    "pid_i": "Loop1:PID:I_RBV",
    "pid_d": "Loop1:PID:D_RBV",
    "pid_p_old": "Loop1:PID:P_OLD_RBV",
    "pid_i_old": "Loop1:PID:I_OLD_RBV",
    "pid_d_old": "Loop1:PID:D_OLD_RBV",
    "comm_status": "COMM:STATUS",
}

LOG_PVS = {
    "LOG:START",
    "LOG:PAUSE",
    "LOG:RESUME",
    "LOG:NEW_FILE",
    "LOG:STATE_RBV",
    "LOG:FILE_RBV",
    "LOG:ROWS_RBV",
    "LOG:LAST_WRITE_RBV",
    "LOG:ERROR_RBV",
    "LOG:HEARTBEAT",
}

WRITE_PVS = {
    "Loop1:INPUT",
    "Loop1:SETP",
    "Loop1:RAMP:ENABLE",
    "Loop1:RAMP:RATE",
    "Loop1:RANGE",
    "Loop1:CTRL:INPUT",
    "Loop1:CTRL:SETP",
    "Loop1:CTRL:RAMP:RATE",
    "Loop1:CTRL:RANGE",
    "Loop1:CTRL:APPLY",
    "Loop1:PID:P",
    "Loop1:PID:I",
    "Loop1:PID:D",
    "Loop1:PID:APPLY",
    "LOG:START",
    "LOG:PAUSE",
    "LOG:RESUME",
    "LOG:NEW_FILE",
    "LOG:STATE_RBV",
    "LOG:FILE_RBV",
    "LOG:ROWS_RBV",
    "LOG:LAST_WRITE_RBV",
    "LOG:ERROR_RBV",
    "LOG:HEARTBEAT",
}

READ_PVS = set(INSTRUMENT_PVS.values()) | LOG_PVS | {
    "Loop1:CTRL:BUSY",
    "Loop1:CTRL:STATUS",
    "Loop1:CTRL:ERROR",
    "Loop1:PID:STATUS",
    "Loop1:PID:ERROR",
}
ALL_PVS = READ_PVS | WRITE_PVS
STATUS_CODES = {
    "Loop1:CTRL:STATUS": {0: "Idle", 1: "Busy", 2: "Done", 3: "PartialFailure", 4: "Error"},
    "Loop1:PID:STATUS": {0: "Idle", 1: "Busy", 2: "Done", 4: "Error"},
}
LOG_COMMANDS = {
    "start": "LOG:START",
    "pause": "LOG:PAUSE",
    "resume": "LOG:RESUME",
    "new_file": "LOG:NEW_FILE",
}


class EpicsClientError(RuntimeError):
    """Base class for Channel Access errors presented to the dashboard."""


class EpicsConnectionError(EpicsClientError):
    """The IOC or a required PV could not be reached."""


class EpicsTimeoutError(EpicsClientError):
    """A Channel Access operation did not finish before its deadline."""


class EpicsAccessDenied(EpicsClientError):
    """The IOC rejected a write under its Access Security rules."""


class EpicsOperationError(EpicsClientError):
    """The IOC rejected or failed a control operation."""


@dataclass(frozen=True)
class PVReading:
    value: object | None
    timestamp: float | None
    alarm_status: int
    alarm_severity: int
    received_monotonic: float
    error: str = ""

    def is_stale(self, max_age: float = MAX_PV_AGE_SECONDS) -> bool:
        return self.timestamp is None or (time.time() - self.timestamp) > max_age

    def is_valid(self, max_age: float = MAX_PV_AGE_SECONDS) -> bool:
        return not self.error and self.alarm_severity == 0 and not self.is_stale(max_age)

    def as_dict(self, max_age: float = MAX_PV_AGE_SECONDS) -> dict[str, object]:
        return {
            "value": self.value,
            "timestamp": self.timestamp,
            "alarm_status": self.alarm_status,
            "alarm_severity": self.alarm_severity,
            "stale": self.is_stale(max_age),
            "error": self.error,
        }


MonitorCallback = Callable[[str, PVReading], None]


def normalize_input(value: object) -> str:
    channel = str(value or "").strip().upper()
    if channel not in INPUT_CHANNELS:
        raise ValueError("Input must be A, B, C, or D")
    return channel


def _scalar(data: object) -> object | None:
    dtype = getattr(data, "dtype", None)
    typecode = getattr(data, "typecode", None)
    is_char_array = (
        dtype is not None and getattr(dtype, "kind", "") in "iu" and getattr(dtype, "itemsize", 0) == 1
    ) or typecode in ("B", "b")
    if is_char_array:
        try:
            return bytes(data).split(b"\x00", 1)[0].decode("utf-8", errors="replace")
        except (TypeError, ValueError):
            pass
    try:
        value = data[0]  # type: ignore[index]
    except (IndexError, KeyError, TypeError):
        value = data
    item = getattr(value, "item", None)
    if callable(item):
        value = item()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").rstrip("\x00")
    return value


def _response_reading(response: object) -> PVReading:
    metadata = getattr(response, "metadata", None)
    timestamp = getattr(metadata, "timestamp", None) if metadata is not None else None
    alarm_status = getattr(metadata, "status", 0) if metadata is not None else 0
    alarm_severity = getattr(metadata, "severity", 0) if metadata is not None else 0
    try:
        alarm_status = int(alarm_status)
    except (TypeError, ValueError):
        alarm_status = 0
    try:
        alarm_severity = int(alarm_severity)
    except (TypeError, ValueError):
        alarm_severity = 0
    return PVReading(
        value=_scalar(getattr(response, "data", None)),
        timestamp=float(timestamp) if timestamp is not None else None,
        alarm_status=alarm_status,
        alarm_severity=alarm_severity,
        received_monotonic=time.monotonic(),
    )


def _enum_value(reading: PVReading | None, default: int = 0) -> int:
    if reading is None:
        return default
    try:
        return int(reading.value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _format_number(value: object | None, precision: int = 3) -> str:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "--"
    if not math.isfinite(number):
        return "--"
    return f"{number:.{precision}f}"


class LakeShoreEpicsClient:
    """Threading-CA client for one IOC prefix."""

    def __init__(self, prefix: str, timeout: float = 2.0):
        normalized = str(prefix or "").strip()
        if not normalized:
            raise ValueError("IOC PV prefix is required")
        self.prefix = normalized if normalized.endswith(":") else f"{normalized}:"
        self.timeout = timeout
        self.cold_input = "A"
        self.sample_input = "B"
        self.control_input = "B"
        self._lock = threading.RLock()
        self._operation_lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._context: Context | None = None
        self._pvs: dict[str, PV] = {}
        self._subscriptions: list[object] = []
        self._cache: dict[str, PVReading] = {}
        self._status_events: dict[str, list[tuple[int, int]]] = {}
        self._monitor_callbacks: dict[int, MonitorCallback] = {}
        self._next_callback_token = 1
        self._monitor_generation: dict[str, int] = {}
        self._connected = False
        # caproto subscriptions hold weak references to callbacks.
        self._subscription_callback = self._on_monitor

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._connected and all(
                self._pvs[suffix].connected for suffix in self._pvs
            )

    def connect(self) -> None:
        with self._lock:
            if self._connected:
                return
            context = Context(timeout=self.timeout)
            suffixes = sorted(ALL_PVS)
            names = [self.prefix + suffix for suffix in suffixes]
            self._context = context
            self._pvs = dict(zip(suffixes, context.get_pvs(*names)))

        try:
            for suffix, pv in self._pvs.items():
                try:
                    pv.wait_for_connection(timeout=self.timeout)
                except Exception as exc:  # noqa: BLE001
                    raise self._translate_error(f"connect to {self.prefix}{suffix}", exc) from exc

            for suffix in sorted(READ_PVS):
                subscription = self._pvs[suffix].subscribe(data_type="time")
                subscription.add_callback(self._subscription_callback)
                self._subscriptions.append(subscription)

            with self._lock:
                self._connected = True
            self.read_snapshot(refresh=True)
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        for subscription in self._subscriptions:
            try:
                subscription.clear()
            except Exception:  # noqa: BLE001
                pass
        self._subscriptions.clear()
        context = self._context
        self._context = None
        self._pvs.clear()
        with self._condition:
            self._connected = False
            self._cache.clear()
            self._status_events.clear()
            self._condition.notify_all()
        if context is not None:
            try:
                context.disconnect(wait=True)
            except Exception:  # noqa: BLE001
                pass

    def add_monitor_callback(self, callback: MonitorCallback) -> int:
        with self._lock:
            token = self._next_callback_token
            self._next_callback_token += 1
            self._monitor_callbacks[token] = callback
            return token

    def remove_monitor_callback(self, token: int) -> None:
        with self._lock:
            self._monitor_callbacks.pop(token, None)

    def _on_monitor(self, subscription: object, response: object) -> None:
        pv = getattr(subscription, "pv")
        full_name = str(getattr(pv, "name"))
        suffix = full_name[len(self.prefix) :] if full_name.startswith(self.prefix) else full_name
        reading = _response_reading(response)
        with self._condition:
            self._cache[suffix] = reading
            generation = self._monitor_generation.get(suffix, 0) + 1
            self._monitor_generation[suffix] = generation
            if suffix in STATUS_CODES:
                events = self._status_events.setdefault(suffix, [])
                events.append((generation, _enum_value(reading)))
                del events[:-12]
            callbacks = list(self._monitor_callbacks.values())
            self._condition.notify_all()
        for callback in callbacks:
            try:
                callback(suffix, reading)
            except Exception:  # noqa: BLE001
                continue

    def _pv(self, suffix: str) -> PV:
        if not self._connected:
            raise EpicsConnectionError("Not connected to the IOC")
        try:
            return self._pvs[suffix]
        except KeyError as exc:
            raise EpicsConnectionError(f"PV is not configured: {self.prefix}{suffix}") from exc

    @staticmethod
    def _translate_error(operation: str, exc: Exception) -> EpicsClientError:
        message = str(exc)
        lowered = message.lower()
        if "access" in lowered or "nowtaccess" in lowered or "noaccess" in lowered:
            return EpicsAccessDenied(f"IOC access denied while trying to {operation}: {message}")
        if "timeout" in lowered or "timed out" in lowered:
            return EpicsTimeoutError(f"Timed out trying to {operation}: {message}")
        if "not connected" in lowered or "disconnected" in lowered or "search" in lowered:
            return EpicsConnectionError(f"IOC unavailable while trying to {operation}: {message}")
        return EpicsClientError(f"Channel Access failed while trying to {operation}: {message}")

    def _write(
        self, suffix: str, value: int | float | str | bytes, timeout: float | None = None
    ) -> None:
        pv = self._pv(suffix)
        try:
            pv.write(value, wait=True, timeout=timeout or self.timeout)
        except Exception as exc:  # noqa: BLE001
            raise self._translate_error(f"write {self.prefix}{suffix}", exc) from exc

    def _read_one(self, suffix: str) -> PVReading:
        try:
            response = self._pv(suffix).read(data_type="time", timeout=self.timeout)
            reading = _response_reading(response)
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                previous = self._cache.get(suffix)
            message = str(self._translate_error(f"read {self.prefix}{suffix}", exc))
            if previous is not None:
                return PVReading(
                    value=previous.value,
                    timestamp=previous.timestamp,
                    alarm_status=previous.alarm_status,
                    alarm_severity=previous.alarm_severity,
                    received_monotonic=time.monotonic(),
                    error=message,
                )
            return PVReading(None, None, 0, 3, time.monotonic(), message)
        with self._condition:
            self._cache[suffix] = reading
            self._condition.notify_all()
        return reading

    def read_snapshot(self, refresh: bool = True) -> dict[str, PVReading]:
        if not self._connected:
            raise EpicsConnectionError("Not connected to the IOC")
        suffixes = sorted(READ_PVS)
        if refresh:
            with ThreadPoolExecutor(max_workers=min(12, len(suffixes))) as executor:
                futures = {executor.submit(self._read_one, suffix): suffix for suffix in suffixes}
                for future in as_completed(futures):
                    future.result()
        with self._lock:
            return {suffix: self._cache.get(suffix, PVReading(None, None, 0, 3, time.monotonic(), "No CA sample")) for suffix in suffixes}

    def read_all(self) -> dict[str, object]:
        snapshot = self.read_snapshot(refresh=True)

        def raw(key: str) -> object | None:
            suffix = INSTRUMENT_PVS[key]
            reading = snapshot.get(suffix)
            return reading.value if reading is not None else None

        channel_code = _enum_value(snapshot.get(INSTRUMENT_PVS["control_input"]))
        control_input = INPUT_READBACK_LABELS.get(channel_code, "--")
        comm_code = _enum_value(snapshot.get(INSTRUMENT_PVS["comm_status"]))
        comm_reading = snapshot.get(INSTRUMENT_PVS["comm_status"])
        comm = {0: "Disconnected", 1: "Connected", 2: "Error"}.get(comm_code, "Error")
        if comm_reading is not None:
            if comm_reading.error:
                if "IOC unavailable" in comm_reading.error:
                    comm = "IOC unavailable"
                elif "Timed out" in comm_reading.error:
                    comm = "IOC timeout"
                else:
                    comm = "CA read error"
            elif not comm_reading.is_valid():
                comm = "Stale" if comm_reading.is_stale() else "Alarm"

        cold = normalize_input(self.cold_input)
        sample = normalize_input(self.sample_input)
        range_code = _enum_value(snapshot.get(INSTRUMENT_PVS["heater_range"]))
        ramp_enable_code = _enum_value(snapshot.get(INSTRUMENT_PVS["ramp_enable"]))
        values: dict[str, object] = {
            "idn": raw("idn") or "--",
            "cold_head": _format_number(raw(f"input_{cold.lower()}")),
            "sample": _format_number(raw(f"input_{sample.lower()}")),
            "input_a": _format_number(raw("input_a")),
            "input_b": _format_number(raw("input_b")),
            "input_c": _format_number(raw("input_c")),
            "input_d": _format_number(raw("input_d")),
            "cold_input": cold,
            "sample_input": sample,
            "control_input": control_input,
            "setpoint": _format_number(raw("setpoint")),
            "ramp_enable": "On" if ramp_enable_code else "Off",
            "ramp_rate": _format_number(raw("ramp_rate")),
            "heater_range_raw": str(range_code),
            "heater_range": RANGE_LABELS.get(range_code, "Unknown"),
            "pid_p": _format_number(raw("pid_p")),
            "pid_i": _format_number(raw("pid_i")),
            "pid_d": _format_number(raw("pid_d")),
            "heater": _format_number(raw("heater"), 1),
            "comm": comm,
            "updated": time.strftime("%H:%M:%S"),
            "pv_quality": {
                suffix: reading.as_dict()
                for suffix, reading in snapshot.items()
                if suffix in INSTRUMENT_PVS.values()
            },
        }
        if snapshot[INSTRUMENT_PVS["pid_p_old"]].value is not None:
            values["pid_p_old"] = _format_number(raw("pid_p_old"))
            values["pid_i_old"] = _format_number(raw("pid_i_old"))
            values["pid_d_old"] = _format_number(raw("pid_d_old"))
        return values

    def read_pid(self) -> tuple[str, str, str]:
        snapshot = self.read_snapshot(refresh=True)
        return tuple(
            _format_number(snapshot[INSTRUMENT_PVS[key]].value)
            for key in ("pid_p", "pid_i", "pid_d")
        )  # type: ignore[return-value]

    def set_inputs(self, cold_input: str, sample_input: str, control_input: str) -> dict[str, object]:
        cold = normalize_input(cold_input)
        sample = normalize_input(sample_input)
        control = normalize_input(control_input)
        with self._operation_lock:
            with self._lock:
                self.cold_input = cold
                self.sample_input = sample
                self.control_input = control
            self._write("Loop1:INPUT", INPUT_CHANNELS.index(control) + 1)
            return self.read_all()

    def set_setpoint(self, value: float, ramp_rate: float) -> dict[str, object]:
        if not math.isfinite(value) or not 0 <= value <= 350:
            raise ValueError("Setpoint must be within 0..350 K")
        if not math.isfinite(ramp_rate) or not 0 <= ramp_rate <= 10:
            raise ValueError("Ramp rate must be within 0..10 K/min")
        with self._operation_lock:
            self._write("Loop1:RAMP:ENABLE", 1 if ramp_rate > 0 else 0)
            self._write("Loop1:RAMP:RATE", ramp_rate)
            self._write("Loop1:SETP", value)
            return self._wait_for_readbacks({
                "Loop1:SETP_RBV": value,
                "Loop1:RAMP:RATE_RBV": ramp_rate,
                "Loop1:RAMP:ENABLE_RBV": 1 if ramp_rate > 0 else 0,
            })

    def set_control(
        self,
        value: float,
        ramp_rate: float,
        heater_range: object,
        cold_input: str,
        sample_input: str,
        control_input: str,
    ) -> dict[str, object]:
        cold = normalize_input(cold_input)
        sample = normalize_input(sample_input)
        control = normalize_input(control_input)
        if not math.isfinite(value) or not 0 <= value <= 350:
            raise ValueError("Setpoint must be within 0..350 K")
        if not math.isfinite(ramp_rate) or not 0 <= ramp_rate <= 10:
            raise ValueError("Ramp rate must be within 0..10 K/min")
        if isinstance(heater_range, bool):
            raise ValueError("Heater range must be 0=Off, 1=Low, 2=Medium, or 3=High")
        try:
            range_value = float(heater_range)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Heater range must be 0=Off, 1=Low, 2=Medium, or 3=High") from exc
        if not math.isfinite(range_value) or range_value < 0 or range_value > 3 or not range_value.is_integer():
            raise ValueError("Heater range must be 0=Off, 1=Low, 2=Medium, or 3=High")
        range_code = int(range_value)

        with self._operation_lock:
            with self._lock:
                self.cold_input = cold
                self.sample_input = sample
                self.control_input = control

            self._write("Loop1:CTRL:INPUT", INPUT_CHANNELS.index(control) + 1)
            self._write("Loop1:CTRL:SETP", value)
            self._write("Loop1:CTRL:RAMP:RATE", ramp_rate)
            self._write("Loop1:CTRL:RANGE", range_code)
            status_suffix = "Loop1:CTRL:STATUS"
            baseline = self._status_generation(status_suffix)
            self._write("Loop1:CTRL:APPLY", 1, timeout=max(10.0, self.timeout * 5.0))
            status = self._wait_for_status(status_suffix, baseline, allowed={2, 3, 4})
            values = self.read_all()
        if status in (3, 4):
            message = self._cached_string("Loop1:CTRL:ERROR") or "Control APPLY failed"
            raise EpicsOperationError(f"{message}; check the instrument readbacks")
        values["apply_status"] = STATUS_CODES[status_suffix][status]
        values["requested_setpoint"] = f"{value:.3f}"
        values["requested_ramp_enable"] = "On" if ramp_rate > 0 else "Off"
        values["requested_ramp_rate"] = f"{ramp_rate:.3f}"
        values["requested_heater_range_raw"] = str(range_code)
        values["requested_heater_range"] = RANGE_LABELS[range_code]
        return values

    def set_pid(self, p: float, i: float, d: float) -> dict[str, str]:
        values = (p, i, d)
        if any(not math.isfinite(value) for value in values):
            raise ValueError("PID values must be numeric")
        if not (0.1 <= p <= 1000 and 0.1 <= i <= 1000 and 0 <= d <= 200):
            raise ValueError("PID values must be P 0.1..1000, I 0.1..1000, D 0..200")
        with self._operation_lock:
            self._write("Loop1:PID:P", p)
            self._write("Loop1:PID:I", i)
            self._write("Loop1:PID:D", d)
            suffix = "Loop1:PID:STATUS"
            baseline = self._status_generation(suffix)
            self._write("Loop1:PID:APPLY", 1, timeout=max(10.0, self.timeout * 5.0))
            status = self._wait_for_status(suffix, baseline, allowed={2, 4})
            snapshot = self.read_snapshot(refresh=True)
            if status != 2:
                message = self._cached_string("Loop1:PID:ERROR") or "PID APPLY failed"
                raise EpicsOperationError(message)
            old = ",".join(
                _format_number(snapshot[INSTRUMENT_PVS[key]].value)
                for key in ("pid_p_old", "pid_i_old", "pid_d_old")
            )
            new = ",".join(
                _format_number(snapshot[INSTRUMENT_PVS[key]].value)
                for key in ("pid_p", "pid_i", "pid_d")
            )
            return {"old": old, "new": new}

    def write_log_command(self, command: str) -> None:
        try:
            suffix = LOG_COMMANDS[command.strip().lower()]
        except KeyError as exc:
            raise ValueError("Log command must be start, pause, resume, or new_file") from exc
        with self._operation_lock:
            current = self._read_one(suffix)
            if _enum_value(current) != 0:
                raise EpicsOperationError(f"{suffix} is still active; wait for it to return to 0")
            self._write(suffix, 1)

    def acknowledge_log_command(self, command: str) -> None:
        try:
            suffix = LOG_COMMANDS[command.strip().lower()]
        except KeyError as exc:
            raise ValueError("Log command must be start, pause, resume, or new_file") from exc
        with self._operation_lock:
            self._write(suffix, 0)

    def write_archive_status(
        self,
        state: int,
        filename: str,
        rows: int,
        last_write: str,
        error: str,
        heartbeat: int | None = None,
    ) -> None:
        """Publish archive state owned by this Python archive worker."""
        if state not in (0, 1, 2, 3):
            raise ValueError("Archive state must be 0..3")
        with self._operation_lock:
            self._write("LOG:STATE_RBV", state)
            self._write("LOG:FILE_RBV", filename.encode("utf-8") + b"\x00")
            self._write("LOG:ROWS_RBV", max(0, rows))
            self._write("LOG:LAST_WRITE_RBV", last_write[:39])
            self._write("LOG:ERROR_RBV", error[:39])
            if heartbeat is not None:
                self._write("LOG:HEARTBEAT", heartbeat)

    def _status_generation(self, suffix: str) -> int:
        with self._lock:
            return self._monitor_generation.get(suffix, 0)

    def _wait_for_status(self, suffix: str, baseline: int, allowed: set[int]) -> int:
        deadline = time.monotonic() + max(10.0, self.timeout * 5.0)
        last_generation = baseline
        with self._condition:
            while time.monotonic() < deadline:
                for generation, value in self._status_events.get(suffix, []):
                    if generation <= baseline or generation <= last_generation:
                        continue
                    last_generation = generation
                    if value in allowed:
                        return value
                self._condition.wait(timeout=0.25)
        raise EpicsTimeoutError(f"Timed out waiting for {self.prefix}{suffix} to finish")

    def _cached_string(self, suffix: str) -> str:
        with self._lock:
            reading = self._cache.get(suffix)
        return str(reading.value) if reading and reading.value is not None else ""

    def _wait_for_readbacks(self, expected: dict[str, float], timeout: float = 8.0) -> dict[str, object]:
        deadline = time.monotonic() + timeout
        latest: dict[str, object] = {}
        while time.monotonic() < deadline:
            latest = self.read_all()
            checks = {
                "Loop1:SETP_RBV": (latest.get("setpoint"), expected.get("Loop1:SETP_RBV")),
                "Loop1:RAMP:RATE_RBV": (latest.get("ramp_rate"), expected.get("Loop1:RAMP:RATE_RBV")),
                "Loop1:RAMP:ENABLE_RBV": (
                    latest.get("ramp_enable") in ("On", True),
                    bool(expected.get("Loop1:RAMP:ENABLE_RBV")),
                ),
            }
            if all(
                (actual == wanted) if isinstance(wanted, bool) else
                (actual != "--" and abs(float(actual) - float(wanted)) <= 0.001)
                for actual, wanted in checks.values()
            ):
                return latest
            time.sleep(0.2)
        raise EpicsTimeoutError("IOC accepted the request, but readbacks did not reach the requested values")

