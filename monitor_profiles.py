"""
Shared profile storage and monitors.lua writer.
Used by both displays_tab.py (UI) and monitor_daemon.py (background daemon).
"""
import json
import os

PROFILES_FILE = os.path.expanduser("~/.config/hypr/monitor-profiles.json")
MONITORS_LUA  = os.path.expanduser("~/.config/hypr/monitors.lua")

import tempfile
DAEMON_LOCK = os.path.join(
    tempfile.gettempdir(),
    f"hypr-monitor-daemon-{os.getenv('USER', 'user')}.lock",
)


def daemon_pid() -> int | None:
    """Return the running daemon's PID, or None if it isn't running."""
    try:
        with open(DAEMON_LOCK) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)  # raises OSError if process doesn't exist
        return pid
    except (FileNotFoundError, ValueError, OSError):
        return None


def display_id(m: dict) -> str:
    """Stable identifier for a physical display (prefers EDID description)."""
    desc = m.get("description", "").strip()
    return desc if desc else m["name"]


def profile_key(monitors: list) -> str:
    """Canonical, sorted key for a set of monitors."""
    return " + ".join(sorted(display_id(m) for m in monitors))


def load_profiles() -> dict:
    try:
        with open(PROFILES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_profile(key: str, monitors: list, use_edid: bool) -> None:
    profiles = load_profiles()
    profiles[key] = {
        "monitors": [_serialize(m) for m in monitors],
        "use_edid": use_edid,
    }
    os.makedirs(os.path.dirname(PROFILES_FILE), exist_ok=True)
    with open(PROFILES_FILE, "w", encoding="utf-8") as f:
        json.dump(profiles, f, indent=2)


def delete_profile(key: str) -> None:
    profiles = load_profiles()
    profiles.pop(key, None)
    os.makedirs(os.path.dirname(PROFILES_FILE), exist_ok=True)
    with open(PROFILES_FILE, "w", encoding="utf-8") as f:
        json.dump(profiles, f, indent=2)


def _serialize(m: dict) -> dict:
    """Extract only the config fields needed to recreate the monitor setup."""
    return {
        "name":        m["name"],
        "description": m.get("description", ""),
        "width":       m["width"],
        "height":      m["height"],
        "refreshRate": m["refreshRate"],
        "x":           m.get("x", 0),
        "y":           m.get("y", 0),
        "scale":       m.get("scale", 1.0),
        "transform":   m.get("transform", 0),
        "mirror":      m.get("mirror"),
        "disabled":    m.get("disabled", False),
        "_workspaces": m.get("_workspaces", []),
    }


def write_monitors_lua(monitors: list, use_edid: bool = False) -> None:
    def output_key(m):
        desc = m.get("description", "").strip()
        if use_edid and desc:
            return "desc:" + desc.replace('"', '\\"')
        return m["name"]

    lines = []
    for m in monitors:
        scale = m.get("scale", 1.0)
        parts = [
            f'output = "{output_key(m)}"',
            f'mode = "{m["width"]}x{m["height"]}@{m.get("refreshRate", 60.0):.0f}"',
            f'position = "{m["x"]}x{m["y"]}"',
            f'scale = {scale:.2g}',
        ]
        if m.get("transform", 0):
            parts.append(f'transform = {m["transform"]}')
        if m.get("mirror"):
            parts.append(f'mirror = "{m["mirror"]}"')
        if m.get("disabled"):
            parts.append("disabled = true")
        lines.append("hl.monitor({ " + ", ".join(parts) + " })")

    ws_lines = []
    for m in monitors:
        ws_ids = m.get("_workspaces", [])
        if not ws_ids or m.get("mirror"):
            continue
        for i, ws in enumerate(ws_ids):
            rule_parts = [
                f'workspace = "name:{ws}"',
                f'monitor = "{m["name"]}"',
            ]
            if i == 0:
                rule_parts.append("default = true")
            ws_lines.append("hl.workspace_rule({ " + ", ".join(rule_parts) + " })")

    if ws_lines:
        lines.append("")
        lines.extend(ws_lines)

    os.makedirs(os.path.dirname(MONITORS_LUA), exist_ok=True)
    with open(MONITORS_LUA, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
