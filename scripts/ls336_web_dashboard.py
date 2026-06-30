#!/usr/bin/env python3
"""Browser dashboard for direct Lake Shore 336 serial control."""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
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

try:
    import serial
    from serial.tools import list_ports
except ImportError:  # pragma: no cover
    serial = None
    list_ports = None


DEFAULT_BAUD = 57600
DEFAULT_TIMEOUT = 2.0
DEFAULT_MAINT_PASSWORD = "ls336-maint"
COMMAND_PACE_SECONDS = 0.15
if getattr(sys, "frozen", False):
    ROOT = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    LOG_DIR = Path(sys.executable).parent / "logs"
else:
    ROOT = Path(__file__).resolve().parents[1]
    LOG_DIR = ROOT / "logs"
BEIJING_TZ = ZoneInfo("Asia/Shanghai")
INPUT_CHANNELS = ("A", "B", "C", "D")
RANGE_LABELS = {"0": "Off", "1": "Low", "2": "Medium", "3": "High"}
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


def split_ramp(reply: str) -> tuple[str, str]:
    pieces = [piece.strip() for piece in reply.split(",", 1)]
    if len(pieces) != 2:
        return reply, "--"
    return ("On" if pieces[0] == "1" else "Off", pieces[1])


def split_pid(reply: str) -> tuple[str, str, str]:
    pieces = [piece.strip() for piece in reply.split(",")]
    if len(pieces) != 3:
        return ("--", "--", "--")
    return (pieces[0], pieces[1], pieces[2])


def normalize_range(reply: str) -> str:
    return reply.strip().split(",", 1)[0]


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


class LakeShoreSerialClient:
    def __init__(self, port: str, baud: int = DEFAULT_BAUD, timeout: float = DEFAULT_TIMEOUT):
        if serial is None:
            raise RuntimeError("pyserial is not installed. Run: python -m pip install pyserial")
        self.port = port
        self.baud = baud
        self.timeout = timeout
        self._lock = threading.RLock()
        self._serial: serial.Serial | None = None
        self.cold_input = "A"
        self.sample_input = "B"
        self.control_input = "B"

    def open(self) -> None:
        with self._lock:
            if self._serial and self._serial.is_open:
                return
            self._serial = serial.Serial(
                self.port,
                baudrate=self.baud,
                bytesize=serial.SEVENBITS,
                parity=serial.PARITY_ODD,
                stopbits=serial.STOPBITS_ONE,
                timeout=self.timeout,
                write_timeout=self.timeout,
            )

    def query(self, command: str) -> str:
        with self._lock:
            self.open()
            assert self._serial is not None
            self._serial.reset_input_buffer()
            self._serial.write(f"{command}\r\n".encode("ascii"))
            reply = self._serial.readline().decode("ascii", errors="replace").strip()
            if not reply:
                raise RuntimeError(f"No reply for {command}")
            return reply

    def write(self, command: str) -> None:
        with self._lock:
            self._raw_write(command)

    def _raw_write(self, command: str) -> None:
        self.open()
        assert self._serial is not None
        self._serial.write(f"{command}\r\n".encode("ascii"))

    def _paced_write(self, command: str) -> None:
        self._raw_write(command)
        time.sleep(COMMAND_PACE_SECONDS)

    def read_pid(self) -> tuple[str, str, str]:
        return split_pid(self.query("PID? 1"))

    def set_pid(self, p: float, i: float, d: float) -> dict[str, str]:
        with self._lock:
            old = self.read_pid()
            self._raw_write(f"PID 1,{p:.3f},{i:.3f},{d:.3f}")
            time.sleep(0.2)
            new = self.read_pid()
            return {"old": ",".join(old), "new": ",".join(new)}

    def read_all(self) -> dict[str, str]:
        ramp_enable, ramp_rate = split_ramp(self.query("RAMP? 1"))
        heater_range_raw = normalize_range(self.query("RANGE? 1"))
        pid_p, pid_i, pid_d = self.read_pid()
        input_values = {channel: self.query(f"KRDG? {channel}") for channel in INPUT_CHANNELS}
        return {
            "idn": self.query("*IDN?"),
            "cold_head": input_values[self.cold_input],
            "sample": input_values[self.sample_input],
            "input_a": input_values["A"],
            "input_b": input_values["B"],
            "input_c": input_values["C"],
            "input_d": input_values["D"],
            "cold_input": self.cold_input,
            "sample_input": self.sample_input,
            "control_input": self.control_input,
            "setpoint": self.query("SETP? 1"),
            "ramp_enable": ramp_enable,
            "ramp_rate": ramp_rate,
            "heater_range_raw": heater_range_raw,
            "heater_range": RANGE_LABELS.get(heater_range_raw, heater_range_raw),
            "pid_p": pid_p,
            "pid_i": pid_i,
            "pid_d": pid_d,
            "heater": self.query("HTR? 1"),
            "comm": "Connected",
            "updated": time.strftime("%H:%M:%S"),
        }

    def set_setpoint(self, value: float, ramp_rate: float) -> dict[str, str]:
        if not 0 <= value <= 350:
            raise ValueError("Setpoint must be within 0..350 K")
        if not 0 <= ramp_rate <= 10:
            raise ValueError("Ramp rate must be within 0..10 K/min")
        with self._lock:
            self._raw_write(f"RAMP 1,{1 if ramp_rate > 0 else 0},{ramp_rate:.3f}")
            self._raw_write(f"SETP 1,{value:.3f}")
            time.sleep(0.5)
            return self.read_all()

    def set_inputs(self, cold_input: str, sample_input: str, control_input: str) -> dict[str, str]:
        self.cold_input = normalize_input(cold_input, "A")
        self.sample_input = normalize_input(sample_input, "B")
        self.control_input = normalize_input(control_input, self.sample_input)
        self.write(f"CSET 1,{self.control_input},1,1")
        return self.read_all()

    def set_control(
        self,
        value: float,
        ramp_rate: float,
        heater_range: int,
        cold_input: str,
        sample_input: str,
        control_input: str,
    ) -> dict[str, str]:
        if heater_range not in (0, 1, 2, 3):
            raise ValueError("Heater range must be 0=Off, 1=Low, 2=Medium, or 3=High")
        if not 0 <= value <= 350:
            raise ValueError("Setpoint must be within 0..350 K")
        if not 0 <= ramp_rate <= 10:
            raise ValueError("Ramp rate must be within 0..10 K/min")
        self.cold_input = normalize_input(cold_input, self.cold_input)
        self.sample_input = normalize_input(sample_input, self.sample_input)
        self.control_input = normalize_input(control_input, self.sample_input)
        with self._lock:
            self._paced_write(f"CSET 1,{self.control_input},1,1")
            self._paced_write(f"RANGE 1,{heater_range}")
            self._paced_write(f"RAMP 1,{1 if ramp_rate > 0 else 0},{ramp_rate:.3f}")
            self._paced_write(f"SETP 1,{value:.3f}")
            return add_requested_control_values(self.read_all(), value, ramp_rate, heater_range)


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
        heater_range: int,
        cold_input: str,
        sample_input: str,
        control_input: str,
    ) -> dict[str, str]:
        if heater_range not in (0, 1, 2, 3):
            raise ValueError("Heater range must be 0=Off, 1=Low, 2=Medium, or 3=High")
        if not 0 <= value <= 350:
            raise ValueError("Setpoint must be within 0..350 K")
        if not 0 <= ramp_rate <= 10:
            raise ValueError("Ramp rate must be within 0..10 K/min")
        self.set_inputs(cold_input, sample_input, control_input)
        self.setpoint_value = value
        self.ramp_rate = ramp_rate
        self.ramp_enabled = ramp_rate > 0
        self.heater_range = heater_range
        return add_requested_control_values(self.read_all(), value, ramp_rate, heater_range)

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
        self.active = True
        self.rows = 0
        self.csv_path: Path | None = None
        self.meta_path: Path | None = None
        self.current_key = ""
        self.current_port = ""
        self.current_mode = ""
        self.last_write_local = ""
        self.error = ""

    def start_session(self, selected_port: str, mode: str) -> dict[str, object]:
        with self._lock:
            self.active = True
            self.current_port = selected_port
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
                    "selected_port": selected_port,
                    "mode": mode,
                }
            )
            self._save_metadata(payload)
            return self.status()

    def pause(self, operator: str) -> dict[str, object]:
        with self._lock:
            self.active = False
            self._record_operation("pause_logging", operator)
            return self.status()

    def resume(self, operator: str) -> dict[str, object]:
        with self._lock:
            self.active = True
            self._ensure_file(force=False)
            self._record_operation("resume_logging", operator)
            return self.status()

    def new_file(self, operator: str) -> dict[str, object]:
        with self._lock:
            self.active = True
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

    def status(self) -> dict[str, object]:
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
                "selected_port": self.current_port,
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


def available_ports() -> list[str]:
    ports = ["DEMO"]
    if sys.platform == "darwin":
        ports.extend(port for port in sorted(glob.glob("/dev/cu.*")) if "Bluetooth" not in port)
        return ports
    if sys.platform.startswith("win") and list_ports is not None:
        ports.extend(port.device for port in list_ports.comports())
        return ports
    ports.extend(sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyS*") + glob.glob("/dev/ttyACM*")))
    return ports


STATE: dict[str, object | None] = {"client": None, "selected_port": None, "mode": None}
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
    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            try:
                self.reply_html((ROOT / "web" / "index.html").read_text(encoding="utf-8"))
            except FileNotFoundError:
                self.reply_json({"error": "Dashboard file not found"}, 500)
        elif path == "/maintenance":
            self.reply_html(MAINTENANCE_HTML)
        elif path == "/api/ports":
            self.reply_json({"ports": available_ports()})
        elif path == "/api/read":
            self.with_client(lambda client: client.read_all(), append_log=True)
        elif path == "/api/log/status":
            self.reply_json(LOGGER.status())
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
            try:
                selected_port = str(body["port"])
                client = DemoLakeShoreClient() if selected_port == "DEMO" else LakeShoreSerialClient(selected_port)
                client.open()
                STATE["client"] = client
                STATE["selected_port"] = selected_port
                STATE["mode"] = "demo" if selected_port == "DEMO" else "hardware"
                LOGGER.start_session(selected_port, str(STATE["mode"]))
                payload = client.read_all()
                LOGGER.append(payload)
                payload["log_status"] = LOGGER.status()
                self.reply_json(payload)
            except (KeyError, ValueError, RuntimeError, OSError) as exc:
                self.reply_json({"error": str(exc)}, 400)
        elif path == "/api/setpoint":
            self.with_client(
                lambda client: client.set_setpoint(float(body["target"]), float(body["ramp"])),
                append_log=True,
            )
        elif path == "/api/inputs":
            self.with_client(
                lambda client: client.set_inputs(
                    str(body["cold_input"]),
                    str(body["sample_input"]),
                    str(body.get("control_input") or body["sample_input"]),
                ),
                append_log=True,
            )
        elif path == "/api/control":
            self.with_client(
                lambda client: client.set_control(
                    float(body["target"]),
                    float(body["ramp"]),
                    int(body["range"]),
                    str(body.get("cold_input") or "A"),
                    str(body.get("sample_input") or "B"),
                    str(body.get("control_input") or body.get("sample_input") or "B"),
                ),
                append_log=True,
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
            self.reply_json(LOGGER.pause("maintenance"))
        elif path == "/api/log/resume":
            if not self.require_maintenance():
                return
            self.reply_json(LOGGER.resume("maintenance"))
        elif path == "/api/log/new":
            if not self.require_maintenance():
                return
            self.reply_json(LOGGER.new_file("maintenance"))
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
        client = STATE["client"]
        if client is None:
            self.reply_json({"error": "Not connected. Choose a port and click Connect."}, 400)
            return
        try:
            payload = action(client)
            if append_log and isinstance(payload, dict):
                LOGGER.append(payload)
                payload["log_status"] = LOGGER.status()
            self.reply_json(payload)
        except Exception as exc:  # noqa: BLE001
            self.reply_json({"error": str(exc), "log_status": LOGGER.status()}, 500)

    def write_pid(self, client, p: float, i: float, d: float) -> dict[str, str]:
        result = client.set_pid(p, i, d)
        LOGGER.audit_pid("maintenance", result["old"], result["new"])
        return result

    def validate_pid(self, body: dict[str, object]) -> tuple[float, float, float]:
        try:
            values = (float(body["p"]), float(body["i"]), float(body["d"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("PID values must be numeric") from exc
        if any(value < 0 or value > 10000 for value in values):
            raise ValueError("PID values must be within 0..10000")
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
    parser.add_argument("--no-open", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}"
    print(f"Lake Shore 336 browser dashboard: {url}")
    if AUTH.password == DEFAULT_MAINT_PASSWORD:
        print("Maintenance password uses the default value. Set LS336_MAINT_PASSWORD before production use.")
    if not args.no_open:
        webbrowser.open(url)
    server.serve_forever()


if __name__ == "__main__":
    main()
