#!/usr/bin/env python3
"""Small EPICS dashboard for the Lake Shore 336 IOC."""

from __future__ import annotations

import argparse
import os
import queue
import shutil
import subprocess
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk


DEFAULT_PREFIX = os.environ.get("LS336_PREFIX", "LS336:")


class EpicsClient:
    def __init__(self, prefix: str, timeout: float = 3.0) -> None:
        self.prefix = prefix
        self.timeout = timeout

    def pv(self, suffix: str) -> str:
        return f"{self.prefix}{suffix}"

    def caget(self, suffix: str) -> str:
        return self._run(["caget", "-t", self.pv(suffix)])

    def caput(self, suffix: str, value: str | float | int) -> str:
        return self._run(["caput", self.pv(suffix), str(value)])

    def proc(self, suffix: str) -> str:
        return self.caput(f"{suffix}.PROC", 1)

    def _run(self, args: list[str]) -> str:
        if shutil.which(args[0]) is None:
            raise RuntimeError(f"{args[0]} is not in PATH. Source EPICS env first.")

        result = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
            timeout=self.timeout,
        )
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(message or f"{' '.join(args)} failed")
        return result.stdout.strip()


class LakeShoreDashboard(tk.Tk):
    READ_PVS = {
        "idn": "IDN",
        "cold_head": "ColdHead:TEMP_RBV",
        "sample": "Sample:TEMP_RBV",
        "setpoint": "Loop1:SETP_RBV",
        "ramp_enable": "Loop1:RAMP:ENABLE_RBV",
        "ramp_rate": "Loop1:RAMP:RATE_RBV",
        "heater": "Loop1:HTR_RBV",
        "comm": "COMM:STATUS",
    }

    def __init__(self, client: EpicsClient, interval_ms: int) -> None:
        super().__init__()
        self.client = client
        self.interval_ms = interval_ms
        self.responses: queue.Queue[tuple[str, object]] = queue.Queue()
        self.values = {key: tk.StringVar(value="--") for key in self.READ_PVS}
        self.status = tk.StringVar(value="Starting")
        self.prefix_text = tk.StringVar(value=f"PV prefix: {self.client.prefix}")

        self.title("Lake Shore 336 Dashboard")
        self.minsize(760, 520)
        self.configure(bg="#f4f6f8")

        self._build_ui()
        self._poll_worker_results()
        self._schedule_refresh(100)

    def _build_ui(self) -> None:
        style = ttk.Style(self)
        style.configure("Header.TLabel", font=("Arial", 18, "bold"))
        style.configure("Temp.TLabel", font=("Arial", 34, "bold"))
        style.configure("Card.TFrame", background="#ffffff", relief="solid")
        style.configure("CardTitle.TLabel", background="#ffffff", font=("Arial", 11))
        style.configure("CardValue.TLabel", background="#ffffff", font=("Arial", 14, "bold"))
        style.configure("Action.TButton", font=("Arial", 11, "bold"))

        root = ttk.Frame(self, padding=18)
        root.pack(fill="both", expand=True)

        top = ttk.Frame(root)
        top.pack(fill="x")
        ttk.Label(top, text="Lake Shore 336", style="Header.TLabel").pack(side="left")
        ttk.Label(top, textvariable=self.prefix_text).pack(side="right")

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
            controls, 0, "Setpoint K", "300", self._apply_setpoint
        )
        self.ramp_rate_entry = self._entry_row(
            controls, 1, "Ramp K/min", "1", self._apply_ramp
        )
        action_row = ttk.Frame(controls)
        action_row.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        ttk.Button(
            action_row,
            text="Refresh",
            command=self.refresh_now,
        ).pack(side="right")

        info = ttk.LabelFrame(root, text="Instrument", padding=12)
        info.pack(fill="both", expand=True, pady=8)
        ttk.Label(info, text="ID").grid(row=0, column=0, sticky="nw")
        ttk.Label(info, textvariable=self.values["idn"], wraplength=620).grid(
            row=0, column=1, sticky="ew", padx=(12, 0)
        )
        info.columnconfigure(1, weight=1)

        footer = ttk.Label(root, textvariable=self.status)
        footer.pack(fill="x", pady=(8, 0))

    def _temperature_card(self, parent: ttk.Frame, title: str, variable: tk.StringVar) -> ttk.Frame:
        card = ttk.Frame(parent, style="Card.TFrame", padding=16)
        ttk.Label(card, text=title, style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(card, textvariable=variable, style="Temp.TLabel").pack(anchor="w")
        ttk.Label(card, text="K", style="CardTitle.TLabel").pack(anchor="w")
        return card

    def _small_card(self, parent: ttk.Frame, title: str, variable: tk.StringVar) -> ttk.Frame:
        card = ttk.Frame(parent, style="Card.TFrame", padding=10)
        ttk.Label(card, text=title, style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(card, textvariable=variable, style="CardValue.TLabel").pack(anchor="w")
        return card

    def _entry_row(
        self,
        parent: ttk.LabelFrame,
        row: int,
        label: str,
        default: str,
        callback,
    ) -> ttk.Entry:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        entry = ttk.Entry(parent, width=14)
        entry.insert(0, default)
        entry.grid(row=row, column=1, sticky="w", padx=8, pady=4)
        ttk.Button(parent, text="Apply", command=callback).grid(row=row, column=2, sticky="w", pady=4)
        return entry

    def _apply_setpoint(self) -> None:
        self._apply_number("Setpoint", self.setpoint_entry, "Loop1:SETP", 0, 350)

    def _apply_ramp(self) -> None:
        value = self._number_from_entry("Ramp rate", self.ramp_rate_entry, 0, 10)
        if value is None:
            return

        def write_ramp() -> str:
            self.client.caput("Loop1:RAMP:ENABLE", 1)
            return self.client.caput("Loop1:RAMP:RATE", value)

        self._run_action("Apply ramp", write_ramp)

    def _apply_number(
        self,
        label: str,
        entry: ttk.Entry,
        suffix: str,
        low: float,
        high: float,
    ) -> None:
        value = self._number_from_entry(label, entry, low, high)
        if value is not None:
            self._run_action(label, self.client.caput, suffix, value)

    def _number_from_entry(
        self, label: str, entry: ttk.Entry, low: float, high: float
    ) -> float | None:
        try:
            value = float(entry.get())
        except ValueError:
            messagebox.showerror(label, f"{label} must be a number.")
            return None

        if not low <= value <= high:
            messagebox.showerror(label, f"{label} must be between {low:g} and {high:g}.")
            return None
        return value

    def refresh_now(self) -> None:
        self._run_action("Refresh", self._read_all)

    def _schedule_refresh(self, delay_ms: int | None = None) -> None:
        self.after(delay_ms or self.interval_ms, self._periodic_refresh)

    def _periodic_refresh(self) -> None:
        self.refresh_now()
        self._schedule_refresh()

    def _read_all(self) -> dict[str, str]:
        return {key: self.client.caget(suffix) for key, suffix in self.READ_PVS.items()}

    def _run_action(self, label: str, func, *args) -> None:
        self.status.set(f"{label}...")

        def worker() -> None:
            try:
                result = func(*args)
            except Exception as exc:  # noqa: BLE001 - surface command failures in the UI.
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
            else:
                self.status.set(f"{label} complete")
                self.after(250, self.refresh_now)

        self.after(100, self._poll_worker_results)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lake Shore 336 EPICS dashboard")
    parser.add_argument("--prefix", default=DEFAULT_PREFIX, help="PV prefix, default: LS336:")
    parser.add_argument(
        "--interval",
        type=float,
        default=2.0,
        help="Refresh interval in seconds, default: 2",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    app = LakeShoreDashboard(
        EpicsClient(args.prefix),
        interval_ms=max(500, int(args.interval * 1000)),
    )
    app.mainloop()


if __name__ == "__main__":
    main()
