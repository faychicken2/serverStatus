@echo off
setlocal

REM ------------------------------------------
REM CONFIGURATION
REM ------------------------------------------
set APPNAME=DevboxWatcher
set SCRIPT=devbox_watcher.py

REM Get user Startup folder
for /f "tokens=2,*" %%A in ('reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders" /v "Startup" 2^>nul') do set STARTUP_FOLDER=%%B

echo.
echo === Building %APPNAME% ===
echo.

REM Ensure PyInstaller is installed and up to date
pip install --upgrade pyinstaller >nul

REM Clean up old build folders
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist %APPNAME%.spec del %APPNAME%.spec

REM ------------------------------------------
REM Build executable
REM ------------------------------------------
echo Building executable...
PyInstaller --onefile --windowed --name %APPNAME% %SCRIPT%

if errorlevel 1 (
    echo Build failed!
    pause
    exit /b
)

REM ------------------------------------------
REM Move to Startup folder
REM ------------------------------------------
set EXE_PATH=%~dp0dist\%APPNAME%.exe
if not defined STARTUP_FOLDER (
    echo Could not detect Startup folder from registry.
    echo Please copy manually from:
    echo %EXE_PATH%
) else (
    echo.
    echo Copying %APPNAME%.exe to Startup folder:
    echo %STARTUP_FOLDER%
    copy /Y "%EXE_PATH%" "%STARTUP_FOLDER%\%APPNAME%.exe" >nul
    if errorlevel 1 (
        echo [WARN] Could not copy to Startup folder. You might need admin rights.
    ) else (
        echo Done! It will now auto-start when you log in.
    )
)

echo.
echo Build complete.
echo EXE located at: %EXE_PATH%
echo.
echo Press ENTER to exit...
pause >nul

endlocal
