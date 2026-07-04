#!/usr/bin/env python3
"""
Hypr-settings monitor daemon.

Listens to Hyprland events and automatically applies the saved display profile
for the current set of connected monitors.

To enable, add to ~/.config/hypr/hyprland.conf:
    exec-once = python3 /path/to/hypr-settings/monitor_daemon.py

Or as a systemd user service — see README.
"""
import fcntl
import json
import os
import socket
import subprocess
import sys
import tempfile
import time

# Allow running from any working directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from monitor_profiles import (
    profile_key,
    load_profiles,
    write_monitors_lua,
    display_id,
    DAEMON_LOCK,
)

LOG = "[monitor-daemon]"


def _socket_path() -> str:
    sig     = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
    runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return os.path.join(runtime, "hypr", sig, ".socket2.sock")


def _current_monitors() -> list:
    r = subprocess.run(
        ["hyprctl", "monitors", "all", "-j"],
        capture_output=True, text=True, timeout=5,
    )
    if r.returncode != 0:
        return []
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return []


def _apply_profile_for_current_monitors() -> None:
    monitors = _current_monitors()
    if not monitors:
        print(f"{LOG} Could not read monitors", flush=True)
        return

    key = profile_key(monitors)
    profiles = load_profiles()

    if key not in profiles:
        print(f"{LOG} No saved profile for: {key!r}", flush=True)
        return

    profile   = profiles[key]
    saved     = profile["monitors"]
    use_edid  = profile.get("use_edid", True)

    # Remap saved port names to current port names in case the monitor
    # moved to a different physical port (only matters when use_edid=False).
    if not use_edid:
        live_by_id = {display_id(m): m["name"] for m in monitors}
        remapped = []
        for sm in saved:
            m = dict(sm)
            live_name = live_by_id.get(display_id(sm))
            if live_name:
                m["name"] = live_name
            remapped.append(m)
        saved = remapped

    write_monitors_lua(saved, use_edid=use_edid)
    subprocess.run(["hyprctl", "reload"], capture_output=True)

    # Move workspaces to their assigned monitors
    for m in saved:
        for ws in m.get("_workspaces", []):
            subprocess.run(
                ["hyprctl", "dispatch",
                 f"hl.dsp.workspace.move({{ monitor = '{m['name']}', workspace = {ws} }})"],
                capture_output=True,
            )

    print(f"{LOG} Applied profile: {key!r}", flush=True)


def _wait_for_socket(timeout: int = 60) -> str | None:
    for _ in range(timeout):
        sp = _socket_path()
        if sp and os.path.exists(sp):
            return sp
        time.sleep(1)
    return None


def main() -> None:
    sp = _wait_for_socket()
    if not sp:
        print(f"{LOG} Timed out waiting for Hyprland socket", flush=True)
        sys.exit(1)

    print(f"{LOG} Connected — listening on {sp}", flush=True)

    while True:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.connect(sp)
                buf = ""
                while True:
                    chunk = sock.recv(4096).decode("utf-8", errors="replace")
                    if not chunk:
                        break
                    buf += chunk
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        ev = line.strip()
                        if ev.startswith(("monitoradded", "monitorremoved")):
                            print(f"{LOG} Event: {ev}", flush=True)
                            time.sleep(1.5)  # let the monitor fully enumerate
                            _apply_profile_for_current_monitors()
        except OSError as e:
            print(f"{LOG} Socket error ({e}), retrying…", flush=True)
            time.sleep(2)
            sp = _wait_for_socket(timeout=30) or sp


def _acquire_lock() -> bool:
    fh = open(DAEMON_LOCK, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fh.write(str(os.getpid()))
        fh.flush()
        return True
    except OSError:
        return False


if __name__ == "__main__":
    if not _acquire_lock():
        sys.exit(0)  # another instance is already running
    main()
