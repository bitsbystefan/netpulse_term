#!/usr/bin/env python3
# NetPulse Terminal — dependency-free host monitoring for macOS and Linux.
# GitHub: https://github.com/bitsbystefan
# License: MIT; see LICENSE in the project root.
"""Dependency-free terminal monitor that reads NetPulse settings.json."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

MAX_HOSTS = 15
PING_TIME_RE = re.compile(r"time[=<]([0-9.]+)\s*ms", re.IGNORECASE)


@dataclass
class Host:
    enabled: bool = False
    label: str = ""
    address: str = ""
    status: str = "Not checked"
    ping_text: str = "Not checked"
    successes: int = 0
    failures: int = 0
    lowest_ms: Optional[float] = None
    highest_ms: Optional[float] = None
    total_ms: float = 0.0
    latency_samples: int = 0

    @property
    def average_ms(self) -> Optional[float]:
        if not self.latency_samples:
            return None
        return self.total_ms / self.latency_samples

    def record(self, status: str, ping_text: str, latency_ms: Optional[float]) -> None:
        self.status = status
        self.ping_text = ping_text
        if status == "Online":
            self.successes += 1
            if latency_ms is not None:
                self.lowest_ms = min(self.lowest_ms if self.lowest_ms is not None else latency_ms, latency_ms)
                self.highest_ms = max(self.highest_ms if self.highest_ms is not None else latency_ms, latency_ms)
                self.total_ms += latency_ms
                self.latency_samples += 1
        else:
            self.failures += 1


def read_settings(path: Path) -> Tuple[int, List[Host]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit("settings.json not found. Put it beside netpulse_term.py or use --settings.")
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit("Could not read settings.json: {}".format(exc))

    if not isinstance(data, dict):
        raise SystemExit("settings.json must contain a JSON object.")

    try:
        interval = int(data.get("interval_seconds", 5))
    except (TypeError, ValueError):
        interval = 5
    interval = max(1, min(3600, interval))

    saved_hosts = data.get("hosts", [])
    if not isinstance(saved_hosts, list):
        saved_hosts = []

    hosts: List[Host] = []
    for entry in saved_hosts[:MAX_HOSTS]:
        if not isinstance(entry, dict):
            entry = {}
        hosts.append(Host(
            enabled=bool(entry.get("enabled", False)),
            label=str(entry.get("label", "") or ""),
            address=str(entry.get("address", "") or "").strip(),
        ))
    while len(hosts) < MAX_HOSTS:
        hosts.append(Host())
    return interval, hosts


def ping_command(address: str) -> List[str]:
    system = platform.system()
    if system == "Darwin":
        return ["/sbin/ping", "-n", "-c", "1", "-W", "2000", address]
    if system == "Linux":
        return ["ping", "-n", "-c", "1", "-W", "2", address]
    raise RuntimeError("NetPulse Terminal supports macOS and Linux ping syntax.")


def ping_once(address: str) -> Tuple[str, str, Optional[float]]:
    started = time.monotonic()
    try:
        result = subprocess.run(
            ping_command(address), capture_output=True, text=True, timeout=4, check=False
        )
    except FileNotFoundError:
        return "Error", "ping not found", None
    except subprocess.TimeoutExpired:
        return "Error", "Ping timed out", None
    except (OSError, RuntimeError) as exc:
        return "Error", "Ping error: {}".format(exc), None

    output = (result.stdout or "") + "\n" + (result.stderr or "")
    lowered = output.lower()
    if result.returncode != 0:
        if "operation not permitted" in lowered or "permission denied" in lowered:
            return "Error", "Permission denied", None
        if any(phrase in lowered for phrase in (
            "unknown host", "bad address", "name or service not known",
            "temporary failure in name resolution", "cannot resolve",
        )):
            return "Error", "Invalid host", None
        return "Offline", "No response", None

    match = PING_TIME_RE.search(output)
    if match:
        latency = float(match.group(1))
    else:
        latency = (time.monotonic() - started) * 1000.0
    return "Online", "{:.2f}".format(latency), latency


# Headings, minimum widths, and alignment. Widths adapt to terminal size.
COLUMNS: Sequence[Tuple[str, int, str]] = (
    ("On", 2, "center"), ("Label", 5, "left"), ("IP/host", 7, "left"),
    ("Status", 6, "left"), ("Ping ms", 7, "right"), ("Success", 7, "right"),
    ("Failure", 7, "right"), ("Low ms", 6, "right"), ("High ms", 7, "right"),
    ("Avg ms", 6, "right"),
)


def terminal_widths() -> List[int]:
    widths = [max(minimum, len(title)) for title, minimum, _ in COLUMNS]
    columns = shutil.get_terminal_size((100, 30)).columns
    extra = max(0, columns - sum(widths) - 2 * (len(widths) - 1))
    label_extra = min(24 - widths[1], (extra + 1) // 2)
    widths[1] += max(0, label_extra)
    extra -= max(0, label_extra)
    widths[2] += min(28 - widths[2], extra)
    return widths


def fit(value: str, width: int) -> str:
    if len(value) <= width:
        return value
    if width <= 1:
        return value[:width]
    return value[:width - 1] + "…"


def format_ms(value: Optional[float]) -> str:
    return "—" if value is None else "{:.2f}".format(value)


def paint(text: str, status: str, enabled: bool, use_color: bool) -> str:
    if not use_color:
        return text
    color = {"Online": "32", "Offline": "31", "Error": "33",
             "Not checked": "90", "Disabled": "90"}.get(status, "33")
    if not enabled and status != "Disabled":
        color = "90"
    return "\033[{}m{}\033[0m".format(color, text)


def render(interval: int, hosts: Sequence[Host], use_color: bool, live_screen: bool, once: bool) -> None:
    widths = terminal_widths()
    separator = "  "
    if live_screen:
        sys.stdout.write("\033[2J\033[H")

    print("NetPulse — IoT Network Health Monitor")
    print("Interval: {} second(s)    Updated: {}".format(
        interval, datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))
    print()

    headings = [title for title, _, _ in COLUMNS]
    header_cells = [fit(title, widths[i]) for i, title in enumerate(headings)]
    print(separator.join(cell.ljust(widths[i]) for i, cell in enumerate(header_cells)))
    print(separator.join("─" * width for width in widths))

    for host in hosts:
        if not host.enabled:
            status, ping_text = "Disabled", "—"
        elif not host.address:
            status, ping_text = "Error", "No address"
        else:
            status, ping_text = host.status, host.ping_text

        values = [
            "x" if host.enabled else "-", host.label or "—", host.address or "—",
            status, ping_text, str(host.successes), str(host.failures),
            format_ms(host.lowest_ms), format_ms(host.highest_ms), format_ms(host.average_ms),
        ]
        cells = [fit(value, widths[i]) for i, value in enumerate(values)]
        rendered = []
        for index, cell in enumerate(cells):
            alignment = COLUMNS[index][2]
            formatted = cell.rjust(widths[index]) if alignment == "right" else cell.ljust(widths[index])
            if index == 3:
                formatted = paint(formatted, status, host.enabled, use_color)
            rendered.append(formatted)
        print(separator.join(rendered))

    print()
    if once:
        print("One cycle complete. Run counters and statistics are not saved.")
    else:
        print("Ctrl-C to stop. Counters and statistics reset on each start; settings are not changed.")
    if live_screen:
        sys.stdout.flush()


def monitor(settings_path: Path, once: bool = False) -> int:
    interval, hosts = read_settings(settings_path)
    if not any(host.enabled and host.address for host in hosts):
        raise SystemExit("No enabled hosts with an address in {}.".format(settings_path))

    # Some launchers set TERM=dumb even when they attach the process to a real
    # terminal. Use the TTY check so those sessions still get live redraws.
    live_screen = sys.stdout.isatty()
    use_color = live_screen and "NO_COLOR" not in os.environ
    alternate_screen = live_screen and not once
    if alternate_screen:
        # Keep the live redraws out of the terminal's normal scrollback buffer.
        sys.stdout.write("\033[?1049h")
        sys.stdout.flush()
    if live_screen:
        sys.stdout.write("\033[?25l")
        sys.stdout.flush()

    interrupted = False
    try:
        while True:
            for host in hosts:
                if host.enabled and host.address:
                    status, ping_text, latency = ping_once(host.address)
                    host.record(status, ping_text, latency)
                elif host.enabled:
                    host.status, host.ping_text = "Not checked", "Not checked"
                else:
                    host.status, host.ping_text = "Disabled", "—"

            render(interval, hosts, use_color, live_screen, once)
            if once:
                return 0
            time.sleep(interval)
    except KeyboardInterrupt:
        interrupted = True
    finally:
        if live_screen:
            sys.stdout.write("\033[?25h")
            sys.stdout.flush()
        if alternate_screen:
            sys.stdout.write("\033[?1049l")
            sys.stdout.flush()
    if interrupted:
        print("Monitoring stopped.")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Monitor NetPulse hosts in the terminal.")
    parser.add_argument(
        "--settings", type=Path, default=Path(__file__).resolve().with_name("settings.json"),
        help="settings.json path (default: beside this script)",
    )
    parser.add_argument("--once", action="store_true", help="run one ping cycle and exit")
    args = parser.parse_args(argv)
    return monitor(args.settings, once=args.once)


if __name__ == "__main__":
    raise SystemExit(main())
