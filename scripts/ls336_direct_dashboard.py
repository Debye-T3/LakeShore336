#!/usr/bin/env python3
"""Direct serial dashboard for Lake Shore 336 on Windows/macOS/Linux."""

from __future__ import annotations

import argparse
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

try:
    import serial
    from serial.tools import list_ports
except ImportError:  # pragma: no cover - exercised by users without pyserial.
    serial = None
    list_ports = None


DEFAULT_BAUD = 57600
DEFAULT_TIMEOUT = 2.0


class LakeShoreSerialClient:
    def __init__(
        self,
        port: str,
        baud: int = DEFAULT_BAUD,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        if serial is None:
            raise RuntimeError("pyserial is not installed. Run: python -m pip install pyserial")

        self.port = port
        self.baud = baud
        self.timeout = timeout
        self._lock = threading.Lock()
        self._serial: serial.Serial | None = None

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

    def close(self) -> None:
        with self._lock:
            if self._serial:
                self._serial.close()
                self._serial = None

    def query(self, command: str) -> str:
        with self._lock:
            self._ensure_open_locked()
            assert self._serial is not None
            self._serial.reset_input_buffer()
            self._serial.write(f"{command}\r\n".encode("ascii"))
            reply = self._serial.readline().decode("ascii", errors="replace").strip()
            if not reply:
                raise RuntimeError(f"No reply for {command}")
            return reply

    def write(self, command: str) -> None:
        with self._lock:
            self._ensure_open_locked()
            assert self._serial is not None
            self._serial.write(f"{command}\r\n".encode("ascii"))

    def read_all(self) -> dict[str, str]:
        ramp = self.query("RAMP? 1")
        ramp_enable, ramp_rate = self._split_ramp(ramp)
        return {
            "idn": self.query("*IDN?"),
            "cold_head": self.query("KRDG? A"),
            "sample": self.query("KRDG? B"),
            "setpoint": self.query("SETP? 1"),
            "ramp_enable": ramp_enable,
            "ramp_rate": ramp_rate,
            "heater": self.query("HTR? 1"),
            "comm": "Connected",
        }

    def set_setpoint(self, value: float) -> None:
        self.write(f"SETP 1,{value:.3f}")

    def set_ramp(self, rate: float, enable: int = 1) -> None:
        self.write(f"RAMP 1,{enable},{rate:.3f}")

    @staticmethod
    def _split_ramp(reply: str) -> tuple[str, str]:
        pieces = [piece.strip() for piece in reply.split(",", 1)]
        if len(pieces) != 2:
            return reply, "--"
        return ("On" if pieces[0] == "1" else "Off", pieces[1])

    def _ensure_open_locked(self) -> None:
        if not self._serial or not self._serial.is_open:
            self._serial = serial.Serial(
                self.port,
                baudrate=self.baud,
                bytesize=serial.SEVENBITS,
                parity=serial.PARITY_ODD,
                stopbits=serial.STOPBITS_ONE,
                timeout=self.timeout,
                write_timeout=self.timeout,
            )


class DirectDashboard(tk.Tk):
    def __init__(self, port: str | None, interval_ms: int) -> None:
        super().__init__()
        self.interval_ms = interval_ms
        self.client: LakeShoreSerialClient | None = None
        self.responses: queue.Queue[tuple[str, object]] = queue.Queue()
        self.values = {
            key: tk.StringVar(value="--")
            for key in [
                "idn",
                "cold_head",
                "sample",
                "setpoint",
                "ramp_enable",
                "ramp_rate",
                "heater",
                "comm",
            ]
        }
        self.status = tk.StringVar(value="Select a COM port and connect")
        self.warmup_step = tk.DoubleVar(value=5.0)

        self.title("Lake Shore 336 Direct Dashboard")
        self.minsize(800, 560)
        self._build_ui(port)
        self._poll_worker_results()

    def _build_ui(self, initial_port: str | None) -> None:
        style = ttk.Style(self)
        style.configure("Header.TLabel", font=("Arial", 18, "bold"))
        style.configure("Temp.TLabel", font=("Arial", 34, "bold"))
        style.configure("CardTitle.TLabel", font=("Arial", 11))
        style.configure("CardValue.TLabel", font=("Arial", 14, "bold"))
        style.configure("Action.TButton", font=("Arial", 11, "bold"))

        root = ttk.Frame(self, padding=18)
        root.pack(fill="both", expand=True)

        top = ttk.Frame(root)
        top.pack(fill="x")
        ttk.Label(top, text="Lake Shore 336 Direct", style="Header.TLabel").pack(side="left")

        ports = available_ports()
        self.port_box = ttk.Combobox(top, values=ports, width=24)
        self.port_box.set(initial_port or (ports[0] if ports else "COM3"))
        self.port_box.pack(side="right", padx=(8, 0))
        ttk.Button(top, text="Connect", command=self.connect).pack(side="right")
        ttk.Label(top, text="Port").pack(side="right", padx=(0, 6))

        temps = ttk.Frame(root)
        temps.pack(fill="x", pady=(16, 10))
        self._temperature_card(temps, "Cold Head", self.values["cold_head"]).pack(
            side="left", fill="x", expand=True, padx=(0, 8)
        )
        self._temperature_card(temps, "Sample", self.values["sample"]).pack(
            side="left", fill="x", expand=True, padx=(8, 0)
        )

        readbacks = ttk.Frame(root)
        readbacks.pack(fill="x", pady=8)
        for title, key in [
            ("Setpoint", "setpoint"),
            ("Ramp", "ramp_enable"),
            ("Ramp Rate", "ramp_rate"),
            ("Heater", "heater"),
            ("Comm", "comm"),
        ]:
            self._small_card(readbacks, title, self.values[key]).pack(
                side="left", fill="x", expand=True, padx=4
            )

        controls = ttk.LabelFrame(root, text="Controls", padding=12)
        controls.pack(fill="x", pady=12)

        self.setpoint_entry = self._entry_row(
            controls, 0, "Setpoint K", "300", self.apply_setpoint
        )
        self.ramp_entry = self._entry_row(controls, 1, "Ramp K/min", "1", self.apply_ramp)
        self.target_entry = self._entry_row(
            controls, 2, "Warmup Target K", "300", self.apply_warmup_target
        )

        step_row = ttk.Frame(controls)
        step_row.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        ttk.Button(
            step_row,
            text="Use 5 K Step",
            command=lambda: self.warmup_step.set(5.0),
            style="Action.TButton",
        ).pack(side="left", padx=(0, 8))
        ttk.Button(
            step_row,
            text="Use 10 K Step",
            command=lambda: self.warmup_step.set(10.0),
            style="Action.TButton",
        ).pack(side="left", padx=8)
        ttk.Button(
            step_row,
            text="Advance One Step",
            command=self.advance_warmup,
            style="Action.TButton",
        ).pack(side="left", padx=8)
        ttk.Label(step_row, text="Current step").pack(side="left", padx=(18, 4))
        ttk.Label(step_row, textvariable=self.warmup_step).pack(side="left")
        ttk.Button(step_row, text="Refresh", command=self.refresh_now).pack(side="right")

        info = ttk.LabelFrame(root, text="Instrument", padding=12)
        info.pack(fill="both", expand=True, pady=8)
        ttk.Label(info, text="ID").grid(row=0, column=0, sticky="nw")
        ttk.Label(info, textvariable=self.values["idn"], wraplength=650).grid(
            row=0, column=1, sticky="ew", padx=(12, 0)
        )
        info.columnconfigure(1, weight=1)

        ttk.Label(root, textvariable=self.status).pack(fill="x", pady=(8, 0))

    def _temperature_card(self, parent: ttk.Frame, title: str, variable: tk.StringVar) -> ttk.Frame:
        card = ttk.Frame(parent, padding=16, relief="solid")
        ttk.Label(card, text=title, style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(card, textvariable=variable, style="Temp.TLabel").pack(anchor="w")
        ttk.Label(card, text="K").pack(anchor="w")
        return card

    def _small_card(self, parent: ttk.Frame, title: str, variable: tk.StringVar) -> ttk.Frame:
        card = ttk.Frame(parent, padding=10, relief="solid")
        ttk.Label(card, text=title, style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(card, textvariable=variable, style="CardValue.TLabel").pack(anchor="w")
        return card

    def _entry_row(self, parent: ttk.LabelFrame, row: int, label: str, default: str, callback) -> ttk.Entry:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        entry = ttk.Entry(parent, width=14)
        entry.insert(0, default)
        entry.grid(row=row, column=1, sticky="w", padx=8, pady=4)
        ttk.Button(parent, text="Apply", command=callback).grid(row=row, column=2, sticky="w", pady=4)
        return entry

    def connect(self) -> None:
        port = self.port_box.get().strip()
        if not port:
            messagebox.showerror("Port", "Choose a COM port first.")
            return
        self.client = LakeShoreSerialClient(port)
        self._run_action("Connect", self._connect_and_read)

    def _connect_and_read(self) -> dict[str, str]:
        self._require_client().open()
        return self._require_client().read_all()

    def refresh_now(self) -> None:
        self._run_action("Refresh", self._require_client().read_all)

    def apply_setpoint(self) -> None:
        value = self._entry_number("Setpoint", self.setpoint_entry, 0, 350)
        if value is not None:
            self._run_action("Setpoint", self._require_client().set_setpoint, value)

    def apply_ramp(self) -> None:
        value = self._entry_number("Ramp rate", self.ramp_entry, 0, 5)
        if value is not None:
            self._run_action("Ramp", self._require_client().set_ramp, value, 1)

    def apply_warmup_target(self) -> None:
        value = self._entry_number("Warmup target", self.target_entry, 0, 350)
        if value is not None:
            self.status.set(f"Warmup target set to {value:g} K")

    def advance_warmup(self) -> None:
        target = self._entry_number("Warmup target", self.target_entry, 0, 350)
        if target is None:
            return
        self._run_action("Advance warmup", self._advance_warmup_worker, target)

    def _advance_warmup_worker(self, target: float) -> dict[str, str]:
        client = self._require_client()
        current = float(client.query("SETP? 1"))
        step = self.warmup_step.get()
        next_setpoint = min(current + step, target) if target > current else current
        client.set_setpoint(next_setpoint)
        time.sleep(0.2)
        return client.read_all()

    def _entry_number(self, label: str, entry: ttk.Entry, low: float, high: float) -> float | None:
        try:
            value = float(entry.get())
        except ValueError:
            messagebox.showerror(label, f"{label} must be a number.")
            return None
        if not low <= value <= high:
            messagebox.showerror(label, f"{label} must be between {low:g} and {high:g}.")
            return None
        return value

    def _require_client(self) -> LakeShoreSerialClient:
        if self.client is None:
            raise RuntimeError("Not connected. Choose a COM port and click Connect.")
        return self.client

    def _run_action(self, label: str, func, *args) -> None:
        self.status.set(f"{label}...")

        def worker() -> None:
            try:
                result = func(*args)
            except Exception as exc:  # noqa: BLE001
                self.responses.put(("error", f"{label}: {exc}"))
            else:
                self.responses.put(("result", (label, result)))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_worker_results(self) -> None:
        while True:
            try:
                kind, payload = self.responses.get_nowait()
            except queue.Empty:
                break

            if kind == "error":
                self.status.set(str(payload))
                continue

            label, result = payload
            if isinstance(result, dict):
                for key, value in result.items():
                    self.values[key].set(value or "--")
                self.status.set(f"Updated {time.strftime('%H:%M:%S')}")
                self.after(self.interval_ms, self.refresh_now)
            else:
                self.status.set(f"{label} complete")
                self.after(250, self.refresh_now)

        self.after(100, self._poll_worker_results)


def available_ports() -> list[str]:
    if list_ports is None:
        return []
    return [port.device for port in list_ports.comports()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lake Shore 336 direct serial dashboard")
    parser.add_argument("--port", help="Serial port, for example COM3 on Windows")
    parser.add_argument("--interval", type=float, default=2.0, help="Refresh interval in seconds")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    app = DirectDashboard(args.port, max(500, int(args.interval * 1000)))
    app.mainloop()


if __name__ == "__main__":
    main()
