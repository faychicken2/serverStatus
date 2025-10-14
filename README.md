# DevboxWatcher

A tiny Windows **system tray** app that shows whether your Linux devbox (or any host) is **online**.  
It checks reachability via **ICMP ping** or **TCP port**, updates a green/red tray dot, and shows latency in the tooltip.

- No admin required (uses `ping.exe` for ICMP on Windows; window hidden).
- Configurable via **config file** and/or **CLI flags**.
- Hot-reloads config from disk without restarting.
- Optional one-file **EXE** build with PyInstaller.
- Startup integration (Startup folder or Task Scheduler).

---

## Features

- ✅ **Tray icon**: green (online) / red (offline)
- ✅ **Modes**:
  - ICMP ping (default)
  - TCP port check (e.g., 22 for SSH)
- ✅ **Tooltip**: host, status, mode, latency, last check time
- ✅ **Tray menu**:
  - Host (display)
  - Mode toggle (ICMP ↔ TCP 22)
  - Force Check
  - Open Config
  - Reload Config
  - Quit
- ✅ **Config**: `%APPDATA%\DevboxWatcher\config.json` (auto-created)
- ✅ **CLI overrides** (and optional `--save` to persist)
- ✅ **No console flash** when pinging

---

## Requirements

- Windows 10/11  
- Python 3.8+ (if running from source)  
- Packages: `pystray`, `Pillow`
  ```powershell
  py -m pip install pystray pillow
  ```

> Building to EXE? Install PyInstaller:
```powershell
py -m pip install --upgrade pyinstaller
```

---

## Quick Start (run from source)

1) Install deps:
```powershell
py -m pip install pystray pillow
```

2) Run:
```powershell
py devbox_watcher.py
```

3) Show/Pin the tray icon if hidden:  
**Settings → Personalization → Taskbar → Other system tray icons → enable Python/DevboxWatcher**.

4) Use the tray menu → **Open Config** to edit settings, then **Reload Config**.

---

## Configuration

### Where
`%APPDATA%\DevboxWatcher\config.json`
(e.g., `C:\Users\<you>\AppData\Roaming\DevboxWatcher\config.json`)

### Example
```json
{
  "host": "devbox.mycorp.local",
  "tcp_port": 22,              // null for ICMP ping
  "interval_secs": 5,
  "ping_timeout_ms": 1500,
  "tcp_timeout_secs": 1.5
}
```

### Hot reload
Edit the file → Tray menu → **Reload Config** (no restart needed).

---

## Command-line (overrides config)

```powershell
# Quick test without touching config:
py devbox_watcher.py --host 10.0.0.12 --tcp-port 22 --interval 3

# Save those settings back to config.json:
py devbox_watcher.py --host 10.0.0.12 --tcp-port 22 --interval 3 --save
```

**Flags**
- `--host <name|ip>`
- `--tcp-port <int>` (omit to use ICMP)
- `--interval <seconds>`
- `--ping-timeout <ms>`
- `--tcp-timeout <seconds>`
- `--config <path\to\config.json>`
- `--save` (writes effective settings to config file)

---

## Build a one-file EXE on Windows

```powershell
py -m pip install --upgrade pyinstaller
py -m PyInstaller --onefile --windowed --name DevboxWatcher devbox_watcher.py
```
- Output: `.\dist\DevboxWatcher.exe`
- Still reads `%APPDATA%\DevboxWatcher\config.json`, so you can reconfigure after compiling.
- If PyInstaller errors on very new Python versions, try upgrading PyInstaller or building with Python 3.12.

**Custom file icon** (EXE icon):
```powershell
py -m PyInstaller --onefile --windowed --icon app.ico --name DevboxWatcher devbox_watcher.py
```

---

## Build a Windows EXE **from Linux** (Docker cross-compile)

Create a `build.sh` in your project folder:

```bash
#!/usr/bin/env bash
set -euo pipefail

# From your project folder (has devbox_watcher.py)
# Create a quick requirements.txt (or edit to match yours)
printf "pystray\nPillow\n" > requirements.txt

# Run a Windows-targeting PyInstaller inside Docker
docker run --rm -v "$PWD":/src -w /src \
  cdrx/pyinstaller-windows:python3 \
  bash -lc "pip install -r requirements.txt && \
            pyinstaller --onefile --windowed --name DevboxWatcher devbox_watcher.py"

echo "Built EXE at ./dist/DevboxWatcher.exe"
```

Make it executable and run:
```bash
chmod +x build.sh
./build.sh
```

> Note: You’re cross-building for Windows; the output EXE runs on Windows. If the image lags on very new Python versions, target Python **3.12**. 

> Note: I made a way to build it in linux for situations where you have admin in linux but but windows. 

---

## Start at Login (Windows)

### Option A — Startup folder (simple)
1. `Win + R` → `shell:startup` → Enter  
2. Copy `DevboxWatcher.exe` into that folder **(or)** create a shortcut to it.

### Option B — Task Scheduler (robust; add delay)
1. Open **Task Scheduler** → **Create Task…**
2. **General**: Name `DevboxWatcher`; **Run only when user is logged on**
3. **Triggers**: New → **At log on** → **Delay 15 seconds**
4. **Actions**: New → Start a program → `...\dist\DevboxWatcher.exe`  
   **Start in**: its folder path
5. Save → Right-click task → **Run** to test

### Option C — Auto-copy on build (batch)
Use this `build.bat` to build and place the EXE into the Startup folder automatically:

```bat
@echo off
setlocal
set APPNAME=DevboxWatcher
set SCRIPT=devbox_watcher.py
for /f "tokens=2,*" %%A in ('reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders" /v "Startup" 2^>nul') do set STARTUP_FOLDER=%%B

pip install --upgrade pyinstaller >nul
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist %APPNAME%.spec del %APPNAME%.spec

PyInstaller --onefile --windowed --name %APPNAME% %SCRIPT%
if errorlevel 1 (
    echo Build failed!
    pause
    exit /b
)

set EXE_PATH=%~dp0dist\%APPNAME%.exe
if not defined STARTUP_FOLDER (
    echo Could not detect Startup folder. Copy manually from:
    echo %EXE_PATH%
) else (
    echo Copying to Startup: %STARTUP_FOLDER%
    copy /Y "%EXE_PATH%" "%STARTUP_FOLDER%\%APPNAME%.exe" >nul
)

echo.
echo Build complete. Press ENTER to exit...
pause >nul
endlocal
```

---

## Known tips

- If the tray icon is hidden, toggle it in **Taskbar → Other system tray icons**.
- Adding a 10–20s delay at logon (Task Scheduler) can help ensure Explorer is ready before the tray icon initializes.
- To remove from startup: `Win + R` → `shell:startup` → delete the EXE or its shortcut.

---

## License

MIT