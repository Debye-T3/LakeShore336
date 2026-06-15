#!/usr/bin/env python3
"""Browser dashboard for direct Lake Shore 336 serial control."""

from __future__ import annotations

import argparse
import glob
import json
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    import serial
    from serial.tools import list_ports
except ImportError:  # pragma: no cover
    serial = None
    list_ports = None


DEFAULT_BAUD = 57600
DEFAULT_TIMEOUT = 2.0
ROOT = Path(__file__).resolve().parents[1]
RANGE_LABELS = {
    "0": "Off",
    "1": "Low",
    "2": "Medium",
    "3": "High",
}
INPUT_CHANNELS = ("A", "B", "C", "D")


def normalize_input(value: object, default: str = "A") -> str:
    channel = str(value or default).strip().upper()
    if channel not in INPUT_CHANNELS:
        raise ValueError("Input must be A, B, C, or D")
    return channel


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
            self.open()
            assert self._serial is not None
            self._serial.write(f"{command}\r\n".encode("ascii"))

    def read_all(self) -> dict[str, str]:
        ramp_enable, ramp_rate = split_ramp(self.query("RAMP? 1"))
        heater_range_raw = normalize_range(self.query("RANGE? 1"))
        pid_p, pid_i, pid_d = split_pid(self.query("PID? 1"))
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
        if ramp_rate > 0:
            self.write(f"RAMP 1,1,{ramp_rate:.3f}")
        self.write(f"SETP 1,{value:.3f}")
        time.sleep(0.5)
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
        cold_input: str | None = None,
        sample_input: str | None = None,
        control_input: str | None = None,
    ) -> dict[str, str]:
        if heater_range not in (0, 1, 2, 3):
            raise ValueError("Heater range must be 0=Off, 1=Low, 2=Medium, or 3=High")
        if not 0 <= value <= 350:
            raise ValueError("Setpoint must be within 0..350 K")
        if not 0 <= ramp_rate <= 10:
            raise ValueError("Ramp rate must be within 0..10 K/min")

        if cold_input is not None:
            self.cold_input = normalize_input(cold_input, self.cold_input)
        if sample_input is not None:
            self.sample_input = normalize_input(sample_input, self.sample_input)
        if control_input is not None:
            self.control_input = normalize_input(control_input, self.sample_input)

        self.write(f"CSET 1,{self.control_input},1,1")
        self.write(f"RANGE 1,{heater_range}")
        self.write(f"RAMP 1,{1 if ramp_rate > 0 else 0},{ramp_rate:.3f}")
        self.write(f"SETP 1,{value:.3f}")
        time.sleep(0.5)
        return self.read_all()

    def step_warmup(self, target: float, step: float, ramp_rate: float) -> dict[str, str]:
        if ramp_rate > 0:
            self.write(f"RAMP 1,1,{ramp_rate:.3f}")
        current = float(self.query("SETP? 1"))
        next_setpoint = min(current + step, target) if target > current else current
        self.write(f"SETP 1,{next_setpoint:.3f}")
        time.sleep(0.5)
        values = self.read_all()
        values["warmup_done"] = str(next_setpoint >= target).lower()
        values["warmup_next"] = f"{next_setpoint:.3f}"
        return values


class DemoLakeShoreClient:
    def __init__(self) -> None:
        self.idn = "DEMO,Lake Shore 336,LSA336-DEMO,1.0"
        self.cold_head = 82.4
        self.sample = 84.1
        self.setpoint_value = 90.0
        self.ramp_rate = 0.5
        self.ramp_enabled = True
        self.heater_range = 3
        self.pid = [40.0, 80.0, 2.0]
        self.cold_input = "A"
        self.sample_input = "B"
        self.control_input = "B"
        self.inputs = {
            "A": 82.4,
            "B": 84.1,
            "C": 296.0,
            "D": 296.0,
        }
        self.last_update = time.monotonic()

    def open(self) -> None:
        self.last_update = time.monotonic()

    def read_all(self) -> dict[str, str]:
        self._simulate_temperature()
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
            "pid_p": f"{self.pid[0]:.3f}",
            "pid_i": f"{self.pid[1]:.3f}",
            "pid_d": f"{self.pid[2]:.3f}",
            "heater": f"{self._heater_output():.1f}",
            "comm": "Demo",
            "updated": time.strftime("%H:%M:%S"),
        }

    def set_setpoint(self, value: float, ramp_rate: float) -> dict[str, str]:
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
        cold_input: str | None = None,
        sample_input: str | None = None,
        control_input: str | None = None,
    ) -> dict[str, str]:
        if heater_range not in (0, 1, 2, 3):
            raise ValueError("Heater range must be 0=Off, 1=Low, 2=Medium, or 3=High")
        if not 0 <= value <= 350:
            raise ValueError("Setpoint must be within 0..350 K")
        if not 0 <= ramp_rate <= 10:
            raise ValueError("Ramp rate must be within 0..10 K/min")
        if cold_input is not None:
            self.cold_input = normalize_input(cold_input, self.cold_input)
        if sample_input is not None:
            self.sample_input = normalize_input(sample_input, self.sample_input)
        if control_input is not None:
            self.control_input = normalize_input(control_input, self.sample_input)
        self.setpoint_value = value
        self.ramp_rate = ramp_rate
        self.ramp_enabled = ramp_rate > 0
        self.heater_range = heater_range
        return self.read_all()

    def step_warmup(self, target: float, step: float, ramp_rate: float) -> dict[str, str]:
        self.ramp_rate = ramp_rate
        self.ramp_enabled = ramp_rate > 0
        self.setpoint_value = min(self.setpoint_value + step, target)
        values = self.read_all()
        values["warmup_done"] = str(self.setpoint_value >= target).lower()
        values["warmup_next"] = f"{self.setpoint_value:.3f}"
        return values

    def _simulate_temperature(self) -> None:
        now = time.monotonic()
        dt = min(10.0, max(0.0, now - self.last_update))
        self.last_update = now
        rate_per_second = max(self.ramp_rate, 0.1) / 60.0
        for channel in INPUT_CHANNELS:
            if channel in ("C", "D"):
                continue
            lag = 1.0 if channel == self.control_input else 0.65
            value = self.inputs[channel]
            delta = self.setpoint_value - value
            max_move = rate_per_second * dt * lag
            move = max(-max_move, min(max_move, delta))
            self.inputs[channel] = value + move

    def _heater_output(self) -> float:
        error = max(0.0, self.setpoint_value - self.inputs[self.control_input])
        if self.heater_range == 0:
            return 0.0
        return min(100.0, error * 8.0 + self.heater_range * 8.0)


def split_ramp(reply: str) -> tuple[str, str]:
    pieces = [piece.strip() for piece in reply.split(",", 1)]
    if len(pieces) != 2:
        return reply, "--"
    return ("On" if pieces[0] == "1" else "Off", pieces[1])


def normalize_range(reply: str) -> str:
    return reply.strip().split(",", 1)[0]


def split_pid(reply: str) -> tuple[str, str, str]:
    pieces = [piece.strip() for piece in reply.split(",")]
    if len(pieces) != 3:
        return ("--", "--", "--")
    return (pieces[0], pieces[1], pieces[2])


def dashboard_html() -> str:
    return (ROOT / "web" / "index.html").read_text(encoding="utf-8")


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


STATE: dict[str, object | None] = {"client": None}


HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lake Shore 336 Dashboard</title>
<style>
body{margin:0;background:#f4f6fb;color:#172033;font-family:Arial,Helvetica,sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px}
header{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:20px}
h1{font-size:28px;margin:0}.bar{display:flex;gap:8px;align-items:center}
select,input,button{font:inherit;border:1px solid #cbd5e1;border-radius:6px;padding:8px 10px;background:white;color:#172033}
button{cursor:pointer;background:#2563eb;color:white;border-color:#2563eb;font-weight:700}
button.secondary{background:#e2e8f0;color:#172033;border-color:#cbd5e1}
.grid{display:grid;grid-template-columns:1.2fr 1fr;gap:16px}
.cards{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:12px;margin:16px 0}
.card{background:white;border:1px solid #dbe3ef;border-radius:8px;padding:16px}
.label{color:#64748b;font-size:13px}.temp{font-size:46px;font-weight:800;margin-top:6px}.value{font-size:20px;font-weight:800;margin-top:6px}
.panel{background:white;border:1px solid #dbe3ef;border-radius:8px;padding:16px;margin-top:16px}
.controls{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;align-items:end}.controls.three{grid-template-columns:repeat(3,minmax(0,1fr))}
.status{margin-top:14px;color:#475569}.ok{color:#15803d}.bad{color:#b91c1c}
.warn{background:#fff7ed;border-color:#fed7aa;color:#9a3412}.good{background:#f0fdf4;border-color:#bbf7d0;color:#166534}
.muted{color:#64748b;font-size:13px}.pill{display:inline-block;border-radius:999px;padding:4px 10px;font-weight:700;background:#e2e8f0}.pill.good{background:#dcfce7;color:#166534}.pill.warn{background:#ffedd5;color:#9a3412}
@media(max-width:900px){.grid,.cards,.controls,.controls.three{grid-template-columns:1fr}header{align-items:flex-start;flex-direction:column}}
</style>
</head>
<body>
<main>
<header>
  <h1 data-i18n="title">Lake Shore 336 Direct Dashboard</h1>
  <div class="bar">
    <select id="language" onchange="setLanguage(this.value)"><option value="en">English</option><option value="zh">中文</option></select>
    <select id="port"></select>
    <button onclick="connect()" data-i18n="connect">Connect</button>
    <button class="secondary" onclick="refresh()" data-i18n="refresh">Refresh</button>
  </div>
</header>
<section class="grid">
  <div class="card"><div class="label" data-i18n="sample">Sample</div><div class="temp"><span id="sample">--</span> K</div></div>
  <div class="card"><div class="label" data-i18n="coldHead">Cold Head</div><div class="temp"><span id="cold_head">--</span> K</div></div>
</section>
<section class="cards">
  <div class="card"><div class="label" data-i18n="setpoint">Setpoint</div><div class="value"><span id="setpoint">--</span> K</div></div>
  <div class="card"><div class="label" data-i18n="ramp">Ramp</div><div class="value" id="ramp_enable">--</div></div>
  <div class="card"><div class="label" data-i18n="rampRate">Ramp Rate</div><div class="value"><span id="ramp_rate">--</span> K/min</div></div>
  <div class="card"><div class="label" data-i18n="heater">Heater</div><div class="value"><span id="heater">--</span> %</div></div>
  <div class="card"><div class="label" data-i18n="comm">Comm</div><div class="value" id="comm">--</div></div>
  <div class="card"><div class="label" data-i18n="stable">Stable</div><div class="value" id="stable_state">--</div></div>
</section>
<section class="panel">
  <h2 data-i18n="control">Temperature Control</h2>
  <div class="controls">
    <label><span data-i18n="setpointK">Setpoint K</span><br><input id="target" value="90" type="number" step="0.1"></label>
    <label><span data-i18n="rampKmin">Ramp K/min</span><br><input id="ramp" value="0.5" type="number" step="0.1"></label>
    <button onclick="setpoint()" data-i18n="applySetpoint">Apply Setpoint</button>
    <button class="secondary" onclick="refresh()" data-i18n="readBack">Read Back</button>
  </div>
</section>
<section class="panel">
  <h2 data-i18n="rhythm">Rhythm Warmup</h2>
  <div class="controls">
    <label><span data-i18n="warmTarget">Warmup Target K</span><br><input id="warm_target" value="100" type="number" step="0.1"></label>
    <label><span data-i18n="stepK">Step K</span><br><input id="step" value="5" type="number" step="0.1"></label>
    <label><span data-i18n="rhythmInterval">Rhythm Interval min</span><br><input id="interval" value="5" type="number" step="0.1"></label>
    <div><button onclick="oneStep()" data-i18n="advance">Advance One Step</button> <button class="secondary" onclick="toggleRhythm()" id="rhythm_button" data-i18n="startRhythm">Start Rhythm</button></div>
  </div>
</section>
<section class="panel">
  <h2 data-i18n="stability">Stability / Hold</h2>
  <div class="controls">
    <label><span data-i18n="stableTol">Stable tolerance K</span><br><input id="stable_tol" value="0.2" type="number" step="0.05"></label>
    <label><span data-i18n="stableMin">Stable duration min</span><br><input id="stable_min" value="2" type="number" step="0.5"></label>
    <label><span data-i18n="holdMin">Hold / soak min</span><br><input id="hold_min" value="10" type="number" step="1"></label>
    <div><button onclick="startHold()" data-i18n="startHold">Start Hold</button> <button class="secondary" onclick="stopHold()" data-i18n="stopHold">Stop Hold</button></div>
  </div>
  <div class="status" id="hold_status" data-i18n="holdReady">Hold is idle.</div>
</section>
<section class="panel">
  <h2 data-i18n="logging">CSV Logging</h2>
  <div class="controls three">
    <button onclick="startLog()" data-i18n="startLog">Start Log</button>
    <button class="secondary" onclick="stopLog()" data-i18n="stopLog">Stop Log</button>
    <button class="secondary" onclick="downloadCsv()" data-i18n="downloadCsv">Download CSV</button>
  </div>
  <div class="status" id="log_status">0 rows</div>
</section>
<section class="panel warn" id="warning_panel"><strong data-i18n="warnings">Safety warnings</strong><div id="warnings">--</div></section>
<section class="panel"><div class="label" data-i18n="instrumentId">Instrument ID</div><div id="idn">--</div><div class="status" id="status" data-i18n="ready">Ready. Select a port and connect.</div></section>
</main>
<script>
let timer=null, autoTimer=null, logEnabled=false, logRows=[];
let lastData={}, stableSince=null, holdActive=false, holdComplete=false, language='en';
const tr={
en:{title:'Lake Shore 336 Direct Dashboard',connect:'Connect',refresh:'Refresh',sample:'Sample',coldHead:'Cold Head',setpoint:'Setpoint',ramp:'Ramp',rampRate:'Ramp Rate',heater:'Heater',comm:'Comm',stable:'Stable',control:'Temperature Control',setpointK:'Setpoint K',rampKmin:'Ramp K/min',applySetpoint:'Apply Setpoint',readBack:'Read Back',rhythm:'Rhythm Warmup',warmTarget:'Warmup Target K',stepK:'Step K',rhythmInterval:'Rhythm Interval min',advance:'Advance One Step',startRhythm:'Start Rhythm',stopRhythm:'Stop Rhythm',stability:'Stability / Hold',stableTol:'Stable tolerance K',stableMin:'Stable duration min',holdMin:'Hold / soak min',startHold:'Start Hold',stopHold:'Stop Hold',holdReady:'Hold is idle.',logging:'CSV Logging',startLog:'Start Log',stopLog:'Stop Log',downloadCsv:'Download CSV',warnings:'Safety warnings',instrumentId:'Instrument ID',ready:'Ready. Select a port and connect.',updated:'Updated',notConnected:'Not connected',stableNow:'Stable',notStable:'Not stable',logStarted:'Log running',logStopped:'Log stopped',holdWaiting:'Hold waiting for stable temperature',holdRunning:'Hold running',holdDone:'Hold complete',noWarnings:'No warnings',demoHint:'Demo mode connected'},
zh:{title:'Lake Shore 336 直连面板',connect:'连接',refresh:'刷新',sample:'样品温度',coldHead:'冷头温度',setpoint:'设定温度',ramp:'升温开关',rampRate:'升温速率',heater:'加热输出',comm:'通信',stable:'稳定',control:'温度控制',setpointK:'设定温度 K',rampKmin:'升温速率 K/min',applySetpoint:'应用设定',readBack:'读回',rhythm:'节奏升温',warmTarget:'升温目标 K',stepK:'每步 K',rhythmInterval:'节奏间隔 min',advance:'前进一步',startRhythm:'开始节奏',stopRhythm:'停止节奏',stability:'稳定判据 / 保温',stableTol:'稳定容差 K',stableMin:'稳定持续 min',holdMin:'保温 min',startHold:'开始保温',stopHold:'停止保温',holdReady:'保温未启动。',logging:'CSV 日志',startLog:'开始记录',stopLog:'停止记录',downloadCsv:'下载 CSV',warnings:'安全提醒',instrumentId:'仪器 ID',ready:'准备好。选择端口并连接。',updated:'已更新',notConnected:'未连接',stableNow:'已稳定',notStable:'未稳定',logStarted:'正在记录',logStopped:'记录已停止',holdWaiting:'等待温度稳定后开始保温',holdRunning:'正在保温',holdDone:'保温完成',noWarnings:'没有提醒',demoHint:'Demo 模式已连接'}
};
function number(id){return Number(document.getElementById(id).value)}
async function api(path, body){const res=await fetch(path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});const data=await res.json();if(!res.ok)throw new Error(data.error||res.statusText);return data}
function showStatus(msg,bad=false){const el=document.getElementById('status');el.textContent=msg;el.className=bad?'status bad':'status ok'}
function t(k){return tr[language][k]||tr.en[k]||k}
function setLanguage(lang){language=lang;document.querySelectorAll('[data-i18n]').forEach(el=>{el.textContent=t(el.dataset.i18n)});document.getElementById('rhythm_button').textContent=timer?t('stopRhythm'):t('startRhythm');updateStable();updateWarnings();updateHold()}
function update(data){lastData={...lastData,...data};for(const [k,v] of Object.entries(data)){const el=document.getElementById(k);if(el)el.textContent=v||'--'} updateStable();updateWarnings();updateHold();if(logEnabled)appendLog();if(data.updated)showStatus(t('updated')+' '+data.updated)}
async function loadPorts(){const data=await api('/api/ports');const s=document.getElementById('port');s.innerHTML='';for(const p of data.ports){const o=document.createElement('option');o.value=p;o.textContent=p;s.appendChild(o)}}
async function connect(){try{const data=await api('/api/connect',{port:document.getElementById('port').value});update(data);showStatus(document.getElementById('port').value==='DEMO'?t('demoHint'):t('updated')+' '+data.updated);startAutoRefresh()}catch(e){showStatus(e.message,true)}}
async function refresh(){try{update(await api('/api/read'))}catch(e){showStatus(e.message,true)}}
async function setpoint(){try{update(await api('/api/setpoint',{target:number('target'),ramp:number('ramp')}))}catch(e){showStatus(e.message,true)}}
async function oneStep(){try{const data=await api('/api/step',{target:number('warm_target'),step:number('step'),ramp:number('ramp')});update(data);if(data.warmup_done==='true'){stopRhythm();showStatus('Warmup target reached at '+data.warmup_next+' K')}}catch(e){showStatus(e.message,true)}}
function toggleRhythm(){timer?stopRhythm():startRhythm()}
function startRhythm(){oneStep();timer=setInterval(oneStep, Math.max(1000, number('interval')*60*1000));document.getElementById('rhythm_button').textContent=t('stopRhythm')}
function stopRhythm(){if(timer)clearInterval(timer);timer=null;document.getElementById('rhythm_button').textContent=t('startRhythm')}
function startAutoRefresh(){if(autoTimer)clearInterval(autoTimer);autoTimer=setInterval(refresh,2000)}
function isStable(){const sample=Number(lastData.sample), setp=Number(lastData.setpoint), tol=number('stable_tol');return Number.isFinite(sample)&&Number.isFinite(setp)&&Math.abs(sample-setp)<=tol}
function updateStable(){const el=document.getElementById('stable_state');if(!lastData.sample){el.textContent='--';return}if(isStable()){if(!stableSince)stableSince=Date.now();const mins=(Date.now()-stableSince)/60000;el.textContent=mins>=number('stable_min')?t('stableNow'):mins.toFixed(1)+' min'}else{stableSince=null;el.textContent=t('notStable')}}
function stableLongEnough(){return stableSince && (Date.now()-stableSince)/60000>=number('stable_min')}
function startHold(){holdActive=true;holdComplete=false;setpoint();updateHold()}
function stopHold(){holdActive=false;holdComplete=false;delete document.getElementById('hold_status').dataset.start;document.getElementById('hold_status').textContent=t('holdReady')}
function updateHold(){const el=document.getElementById('hold_status');if(!holdActive)return;if(!stableLongEnough()){el.textContent=t('holdWaiting');return}if(!el.dataset.start)el.dataset.start=String(Date.now());const elapsed=(Date.now()-Number(el.dataset.start))/60000;const remain=number('hold_min')-elapsed;if(remain<=0){holdComplete=true;holdActive=false;delete el.dataset.start;el.textContent=t('holdDone')}else{el.textContent=t('holdRunning')+': '+remain.toFixed(1)+' min left'}}
function warnings(){const out=[];const setp=Number(document.getElementById('target').value), ramp=number('ramp'), heater=Number(lastData.heater), sample=Number(lastData.sample);if(setp>350)out.push('Setpoint > 350 K');if(ramp>10)out.push('Ramp > 10 K/min');if(heater>85)out.push('Heater output high: '+heater.toFixed(1)+'%');if(sample>350)out.push('Sample > 350 K');return out}
function updateWarnings(){const items=warnings();const panel=document.getElementById('warning_panel');document.getElementById('warnings').textContent=items.length?items.join('; '):t('noWarnings');panel.className=items.length?'panel warn':'panel good'}
function startLog(){logEnabled=true;document.getElementById('log_status').textContent=t('logStarted')+', '+logRows.length+' rows'}
function stopLog(){logEnabled=false;document.getElementById('log_status').textContent=t('logStopped')+', '+logRows.length+' rows'}
function appendLog(){const row=[new Date().toISOString(),lastData.cold_head,lastData.sample,lastData.setpoint,lastData.ramp_enable,lastData.ramp_rate,lastData.heater,lastData.comm,document.getElementById('stable_state').textContent];logRows.push(row);document.getElementById('log_status').textContent=(logEnabled?t('logStarted'):t('logStopped'))+', '+logRows.length+' rows'}
function downloadCsv(){const head=['timestamp','cold_head_K','sample_K','setpoint_K','ramp_enable','ramp_rate_K_per_min','heater_percent','comm','stable_state'];const csv=[head,...logRows].map(r=>r.map(v=>`"${String(v??'').replace(/"/g,'""')}"`).join(',')).join('\n');const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv],{type:'text/csv'}));a.download='ls336_temperature_log.csv';a.click();URL.revokeObjectURL(a.href)}
loadPorts();setLanguage('en');
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/":
            self.reply_html(dashboard_html())
        elif self.path == "/api/ports":
            self.reply_json({"ports": available_ports()})
        elif self.path == "/api/read":
            self.with_client(lambda client: client.read_all())
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        body = self.read_body()
        if self.path == "/api/connect":
            selected_port = str(body["port"])
            client = DemoLakeShoreClient() if selected_port == "DEMO" else LakeShoreSerialClient(selected_port)
            client.open()
            STATE["client"] = client
            self.reply_json(client.read_all())
        elif self.path == "/api/setpoint":
            self.with_client(lambda client: client.set_setpoint(float(body["target"]), float(body["ramp"])))
        elif self.path == "/api/inputs":
            self.with_client(
                lambda client: client.set_inputs(
                    str(body["cold_input"]),
                    str(body["sample_input"]),
                    str(body.get("control_input") or body["sample_input"]),
                )
            )
        elif self.path == "/api/control":
            self.with_client(
                lambda client: client.set_control(
                    float(body["target"]),
                    float(body["ramp"]),
                    int(body["range"]),
                    str(body.get("cold_input") or "A"),
                    str(body.get("sample_input") or "B"),
                    str(body.get("control_input") or body.get("sample_input") or "B"),
                )
            )
        elif self.path == "/api/step":
            self.with_client(
                lambda client: client.step_warmup(
                    float(body["target"]), float(body["step"]), float(body["ramp"])
                )
            )
        else:
            self.send_error(404)

    def with_client(self, action) -> None:
        client = STATE["client"]
        if client is None:
            self.reply_json({"error": "Not connected. Choose a port and click Connect."}, 400)
            return
        try:
            self.reply_json(action(client))
        except Exception as exc:  # noqa: BLE001
            self.reply_json({"error": str(exc)}, 500)

    def read_body(self) -> dict[str, object]:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length).decode("utf-8") or "{}")

    def reply_html(self, html: str) -> None:
        data = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def reply_json(self, payload: dict[str, object], status: int = 200) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
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
    if not args.no_open:
        webbrowser.open(url)
    server.serve_forever()


if __name__ == "__main__":
    main()
