#!/usr/bin/env python3
"""Pseudo-terminal Lake Shore 336 emulator for IOC integration tests."""

import argparse
import errno
import json
import os
import re
import select
import signal
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path


def _format_signed(value: float) -> str:
    return f"{value:+.3f}"


def _format_float(value: float) -> str:
    return f"{value:.3f}"


def _parse_float(raw: str, command: str) -> float:
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"Malformed command: {command}") from exc


@dataclass
class Model336State:
    idn: str = "LSCI,MODEL336,MOCK,1.0"
    temperatures: dict[str, float] = field(
        default_factory=lambda: {
            "A": 4.2,
            "B": 10.0,
            "C": 20.0,
            "D": 30.0,
        }
    )
    outmode: tuple[int, int, int] = (1, 1, 1)
    setpoint: float = 10.0
    ramp_enable: int = 1
    ramp_rate: float = 1.5
    heater_range: int = 2
    heater_percent: float = 12.5
    pid: tuple[float, float, float] = (10.0, 20.0, 0.0)

    def handle(self, command: str) -> str | None:
        command = command.strip()
        if not command:
            raise ValueError("Unsupported command")

        if command == "*IDN?":
            return self.idn

        if command.startswith("KRDG? "):
            channel = command[6:]
            if channel in self.temperatures:
                return _format_signed(self.temperatures[channel])
            raise ValueError(f"Unsupported command: {command}")

        if command == "OUTMODE? 1":
            return ",".join(str(value) for value in self.outmode)
        if command == "SETP? 1":
            return _format_float(self.setpoint)
        if command == "RAMP? 1":
            return f"{self.ramp_enable},{_format_float(self.ramp_rate)}"
        if command == "RANGE? 1":
            return str(self.heater_range)
        if command == "HTR? 1":
            return _format_float(self.heater_percent)
        if command == "PID? 1":
            return ",".join(_format_float(value) for value in self.pid)

        if command.startswith("SETP "):
            parts = [part.strip() for part in command[5:].split(",")]
            if len(parts) != 2 or parts[0] != "1":
                raise ValueError(f"Malformed command: {command}")
            self.setpoint = _parse_float(parts[1], command)
            return None

        if command.startswith("RAMP "):
            parts = [part.strip() for part in command[5:].split(",")]
            if len(parts) != 3 or parts[0] != "1" or parts[1] not in {"0", "1"}:
                raise ValueError(f"Malformed command: {command}")
            self.ramp_enable = int(parts[1])
            self.ramp_rate = _parse_float(parts[2], command)
            return None

        if command.startswith("RANGE "):
            parts = [part.strip() for part in command[6:].split(",")]
            if len(parts) != 2 or parts[0] != "1":
                raise ValueError(f"Malformed command: {command}")
            try:
                heater_range = int(parts[1])
            except ValueError as exc:
                raise ValueError(f"Malformed command: {command}") from exc
            if heater_range not in {0, 1, 2, 3}:
                raise ValueError(f"Malformed command: {command}")
            self.heater_range = heater_range
            return None

        raise ValueError(f"Unsupported command: {command}")


def _drain_commands(buffer: str) -> tuple[list[str], str]:
    commands: list[str] = []
    while True:
        match = re.search(r"[\r\n]+", buffer)
        if match is None:
            return commands, buffer
        commands.append(buffer[: match.start()])
        buffer = buffer[match.end() :]


def _append_log(handle, command: str, response: str | None, error: str | None = None) -> None:
    entry = {"command": command, "response": response}
    if error is not None:
        entry["error"] = error
    handle.write(json.dumps(entry) + "\n")
    handle.flush()


def _configure_model336_serial(slave_fd: int) -> None:
    import termios
    import tty

    tty.setraw(slave_fd)
    attributes = termios.tcgetattr(slave_fd)
    attributes[0] = 0
    attributes[1] = 0
    attributes[2] |= termios.CLOCAL | termios.CREAD | termios.PARENB | termios.PARODD
    attributes[2] &= ~termios.CSIZE
    attributes[2] |= termios.CS7
    attributes[2] &= ~termios.CSTOPB
    attributes[2] &= ~getattr(termios, "CRTSCTS", 0)
    attributes[3] &= ~(termios.ECHO | termios.ICANON)
    attributes[4] = termios.B57600
    attributes[5] = termios.B57600
    attributes[6][termios.VMIN] = 1
    attributes[6][termios.VTIME] = 0
    termios.tcsetattr(slave_fd, termios.TCSANOW, attributes)


def serve_pty(command_log: Path | None = None, keep_slave_open: bool = False) -> int:
    if os.name != "posix":
        raise RuntimeError("PTY server requires POSIX")

    import pty
    master_fd, slave_fd = pty.openpty()
    state = Model336State()
    running = True
    log_handle = None
    buffer = ""
    saw_slave_activity = False

    def stop(_signum, _frame) -> None:
        nonlocal running
        running = False

    try:
        _configure_model336_serial(slave_fd)
        slave_path = os.ttyname(slave_fd)
        if not keep_slave_open:
            os.close(slave_fd)
            slave_fd = None

        if command_log is not None:
            command_log.parent.mkdir(parents=True, exist_ok=True)
            log_handle = command_log.open("a", encoding="utf-8")

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)

        print(slave_path, flush=True)

        while running:
            try:
                ready, _, _ = select.select([master_fd], [], [], 0.2)
                if not ready:
                    continue

                chunk = os.read(master_fd, 1024)
            except OSError as exc:
                if exc.errno == errno.EIO and saw_slave_activity:
                    break
                if exc.errno == errno.EIO:
                    time.sleep(0.05)
                    continue
                if exc.errno == errno.EBADF and not running:
                    break
                raise
            if not chunk:
                continue

            saw_slave_activity = True
            buffer += chunk.decode("utf-8", errors="replace")
            commands, buffer = _drain_commands(buffer)
            for raw_command in commands:
                command = raw_command.strip()
                if not command:
                    continue
                try:
                    response = state.handle(command)
                except ValueError as exc:
                    if log_handle is not None:
                        _append_log(log_handle, command, None, str(exc))
                    continue

                if log_handle is not None:
                    _append_log(log_handle, command, response)
                if response is not None:
                    os.write(master_fd, f"{response}\r\n".encode("utf-8"))
    finally:
        if log_handle is not None:
            log_handle.close()
        os.close(master_fd)
        if slave_fd is not None:
            os.close(slave_fd)

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--command-log", type=Path, help="Append JSONL command log to PATH.")
    parser.add_argument(
        "--keep-slave-open",
        action="store_true",
        help="Keep the PTY slave file descriptor open for long-lived IOC sessions.",
    )
    args = parser.parse_args(argv)

    if os.name != "posix":
        print("ls336_ioc_mock.py requires POSIX PTY support.", file=sys.stderr)
        return 1

    return serve_pty(args.command_log, keep_slave_open=args.keep_slave_open)


if __name__ == "__main__":
    raise SystemExit(main())
