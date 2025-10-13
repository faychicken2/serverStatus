import argparse
import json
import os
from pathlib import Path
import threading
import time
import socket
import subprocess
import sys
from datetime import datetime

# ---- tray + icons ----
from PIL import Image, ImageDraw
import pystray
from pystray import MenuItem as Item

APP_NAME = "DevboxWatcher"

# -----------------------------
# Defaults & Config Management
# -----------------------------
DEFAULTS = {
    "host": "falcon-server",  # hostname or IP
    "tcp_port": None,                   # int (e.g., 22) or null for ICMP ping
    "interval_secs": 5,                 # check frequency
    "ping_timeout_ms": 1500,
    "tcp_timeout_secs": 1.5
}

def app_data_dir() -> Path:
    # Persist settings outside the exe so --onefile builds can be tweaked
    base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Roaming")
    d = Path(base) / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d

def default_config_path() -> Path:
    return app_data_dir() / "config.json"

def load_json(path: Path) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[WARN] Failed to read config {path}: {e}", flush=True)
    return {}

def save_json(path: Path, data: dict):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[WARN] Failed to write config {path}: {e}", flush=True)

def merge(a: dict, b: dict) -> dict:
    # shallow merge
    out = dict(a)
    for k, v in b.items():
        out[k] = v
    return out

def parse_args():
    p = argparse.ArgumentParser(
        description="Tray app that shows a dot if a host is online (ICMP or TCP). "
                    "Configurable via CLI flags and %APPDATA%\\DevboxWatcher\\config.json"
    )
    p.add_argument("--host", type=str, help="Hostname or IP to check")
    p.add_argument("--tcp-port", type=int, help="TCP port to check (omit to use ICMP ping)")
    p.add_argument("--interval", type=float, help="Seconds between checks (default 5)")
    p.add_argument("--ping-timeout", type=int, help="Ping timeout in ms (default 1500)")
    p.add_argument("--tcp-timeout", type=float, help="TCP connect timeout in seconds (default 1.5)")
    p.add_argument("--config", type=str, help="Path to a config.json (overrides default location)")
    p.add_argument("--save", action="store_true", help="Save the effective settings back to the config file")
    return p.parse_args()

def effective_settings():
    args = parse_args()

    cfg_path = Path(args.config) if args.config else default_config_path()
    file_cfg = load_json(cfg_path)

    # Build CLI dict only with provided values
    cli_cfg = {}
    if args.host is not None:          cli_cfg["host"] = args.host
    if args.tcp_port is not None:      cli_cfg["tcp_port"] = args.tcp_port
    if args.interval is not None:      cli_cfg["interval_secs"] = args.interval
    if args.ping_timeout is not None:  cli_cfg["ping_timeout_ms"] = args.ping_timeout
    if args.tcp_timeout is not None:   cli_cfg["tcp_timeout_secs"] = args.tcp_timeout

    # precedence: DEFAULTS <- file_cfg <- cli_cfg
    eff = merge(merge(DEFAULTS, file_cfg), cli_cfg)

    # normalize types
    if eff.get("tcp_port") in ("", "null", "None"): eff["tcp_port"] = None

    if args.save:
        save_json(cfg_path, eff)
        print(f"[INFO] Saved settings to {cfg_path}", flush=True)

    return eff, cfg_path

# -----------------------------
# Networking checks
# -----------------------------
def make_dot(color_rgb):
    # 16x16 circular dot with black outline
    img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((2, 2, 14, 14), fill=color_rgb, outline=(0, 0, 0, 255), width=1)
    return img

ICON_OK = make_dot((0, 200, 0))
ICON_FAIL = make_dot((220, 0, 0))

def short_err(e: str, maxlen=80):
    e = (e or "").replace("\r", " ").replace("\n", " ").strip()
    return (e[:maxlen] + "…") if len(e) > maxlen else e

def ping_icmp(host: str, timeout_ms: int):
    """Uses Windows ping.exe (no admin). Returns (ok, latency_ms, err)"""
    try:
        out = subprocess.run(
            ["ping", "-n", "1", "-w", str(timeout_ms), host],
            capture_output=True, text=True, encoding="utf-8"
        )
        txt = out.stdout or out.stderr or ""
        if out.returncode == 0 and "TTL=" in txt.upper():
            latency_ms = None
            for piece in txt.replace("=", " ").split():
                if piece.lower().endswith("ms"):
                    try:
                        latency_ms = int(''.join(ch for ch in piece if ch.isdigit()))
                    except Exception:
                        pass
            return True, latency_ms, None
        else:
            return False, None, txt.strip()
    except Exception as e:
        return False, None, str(e)

def tcp_check(host: str, port: int, timeout_s: float):
    """TCP connect test. Returns (ok, latency_ms, err)"""
    start = time.time()
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            latency_ms = int((time.time() - start) * 1000)
            return True, latency_ms, None
    except Exception as e:
        return False, None, str(e)

# -----------------------------
# App / Tray state
# -----------------------------
STOP = threading.Event()
STATE_LOCK = threading.Lock()

class AppState:
    def __init__(self, settings: dict, cfg_path: Path):
        self.host = settings["host"]
        self.tcp_port = settings["tcp_port"]
        self.interval_secs = float(settings["interval_secs"])
        self.ping_timeout_ms = int(settings["ping_timeout_ms"])
        self.tcp_timeout_secs = float(settings["tcp_timeout_secs"])
        self.cfg_path = cfg_path
        self.online = False
        self.last_latency_ms = None
        self.last_msg = "Starting…"
        self.last_printed = None
        self._config_mtime = self._get_mtime()

    def _get_mtime(self):
        try:
            return self.cfg_path.stat().st_mtime
        except Exception:
            return None

    def maybe_reload_if_changed(self):
        m = self._get_mtime()
        if m and m != self._config_mtime:
            try:
                cfg = load_json(self.cfg_path)
                # merge onto defaults (do not apply CLI here)
                eff = merge(DEFAULTS, cfg)
                with STATE_LOCK:
                    self.host = eff["host"]
                    self.tcp_port = eff["tcp_port"]
                    self.interval_secs = float(eff["interval_secs"])
                    self.ping_timeout_ms = int(eff["ping_timeout_ms"])
                    self.tcp_timeout_secs = float(eff["tcp_timeout_secs"])
                self._config_mtime = m
                print(f"[INFO] Reloaded config from {self.cfg_path}", flush=True)
                return True
            except Exception as e:
                print(f"[WARN] Failed to reload config: {e}", flush=True)
        return False

    def mode_label(self):
        return f"TCP {self.tcp_port}" if self.tcp_port is not None else "ICMP ping"

STATE: AppState = None  # set in main()

def status_text():
    with STATE_LOCK:
        mode = STATE.mode_label()
        lat = f"{STATE.last_latency_ms} ms" if STATE.last_latency_ms is not None else "-"
        ok = "Online" if STATE.online else "Offline"
        host = STATE.host
    return f"{host} — {ok}\nMode: {mode}\nLatency: {lat}\nLast: {datetime.now().strftime('%I:%M:%S %p')}"

def maybe_print_status():
    with STATE_LOCK:
        s = f"{datetime.now().strftime('%H:%M:%S')}  {STATE.host}: " \
            f"{'ONLINE' if STATE.online else 'OFFLINE'}  " \
            f"mode={STATE.mode_label()}  latency={STATE.last_latency_ms if STATE.last_latency_ms is not None else '-'}"
        changed = (s != STATE.last_printed)
        if changed:
            STATE.last_printed = s
    if changed:
        print(s, flush=True)

def do_check(icon: pystray.Icon):
    with STATE_LOCK:
        host = STATE.host
        tcp_port = STATE.tcp_port
        ping_timeout_ms = STATE.ping_timeout_ms
        tcp_timeout_secs = STATE.tcp_timeout_secs

    if tcp_port is None:
        ok, lat, err = ping_icmp(host, ping_timeout_ms)
    else:
        ok, lat, err = tcp_check(host, tcp_port, tcp_timeout_secs)

    with STATE_LOCK:
        STATE.online = ok
        STATE.last_latency_ms = lat
        STATE.last_msg = "Online" if ok else f"Offline ({short_err(err)})" if err else "Offline"

    icon.title = status_text()
    icon.icon = ICON_OK if ok else ICON_FAIL
    maybe_print_status()

def worker(icon: pystray.Icon):
    """Forever loop: check + sleep, and hot-reload config when file changes."""
    while not STOP.is_set():
        do_check(icon)

        # sleep in tiny slices so quits and reloads are responsive
        slept = 0.0
        while slept < max(0.2, STATE.interval_secs) and not STOP.is_set():
            time.sleep(0.2)
            slept += 0.2

        # Hot reload if config changed
        STATE.maybe_reload_if_changed()

# -----------------------------
# Tray menu actions
# -----------------------------
def action_force_check(icon, item):
    do_check(icon)

def action_toggle_mode(icon, item):
    """Toggle ICMP <-> TCP(22) quickly."""
    with STATE_LOCK:
        STATE.tcp_port = 22 if STATE.tcp_port is None else None
    icon.update_menu()
    do_check(icon)

def action_open_config(icon, item):
    # Create config file if missing (seed with current effective settings)
    if not STATE.cfg_path.exists():
        cfg_seed = {
            "host": STATE.host,
            "tcp_port": STATE.tcp_port,
            "interval_secs": STATE.interval_secs,
            "ping_timeout_ms": STATE.ping_timeout_ms,
            "tcp_timeout_secs": STATE.tcp_timeout_secs
        }
        save_json(STATE.cfg_path, cfg_seed)
    try:
        os.startfile(str(STATE.cfg_path))  # open in default editor
    except Exception as e:
        print(f"[WARN] Could not open config: {e}", flush=True)

def action_reload_config(icon, item):
    if STATE.maybe_reload_if_changed():
        do_check(icon)

def action_quit(icon, item):
    STOP.set()
    try:
        icon.stop()
    except Exception:
        pass

def menu_label_mode(_item=None):
    return f"Mode: {STATE.mode_label()}"

def menu_label_host(_item=None):
    with STATE_LOCK:
        return f"Host: {STATE.host}"

# -----------------------------
# Tray plumbing
# -----------------------------
def setup(icon: pystray.Icon):
    icon.visible = True
    do_check(icon)
    t = threading.Thread(target=worker, args=(icon,), daemon=True)
    t.start()

def build_menu():
    return (
        Item(lambda i: menu_label_host(i), None, enabled=False),
        Item(lambda i: menu_label_mode(i), action_toggle_mode),
        Item("Force Check", action_force_check),
        Item("Open Config", action_open_config),
        Item("Reload Config", action_reload_config),
        Item("Quit", action_quit),
    )

def main():
    global STATE
    settings, cfg_path = effective_settings()
    STATE = AppState(settings, cfg_path)

    icon = pystray.Icon(
        name=APP_NAME,
        title="Starting…",
        icon=ICON_FAIL,
        menu=pystray.Menu(*build_menu())
    )

    # Run tray detached so Ctrl+C works in console (omit for --windowed EXE)
    icon.run_detached(setup=setup)

    print(f"{APP_NAME} running. Press Ctrl+C to quit.")
    print(f"Config file: {cfg_path}")
    print("If the tray dot is hidden, enable it under Settings > Personalization > Taskbar > Other system tray icons.\n", flush=True)

    try:
        while not STOP.is_set():
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        STOP.set()
        try:
            icon.stop()
        except Exception:
            pass
        print(f"{APP_NAME} stopped.", flush=True)

if __name__ == "__main__":
    if sys.platform != "win32":
        print("Heads-up: this is intended for Windows (uses ping.exe).")
    main()
