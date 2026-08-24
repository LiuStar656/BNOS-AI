@echo off
setlocal
chcp 65001 >nul

rem Check node is available on PATH
where node >nul 2>nul
if errorlevel 1 (
    echo [ERROR] node not found on PATH. Install Node.js first.
    pause
    exit /b 1
)

rem Pre-flight: refuse to launch a second instance while the desktop is already
rem running. Two instances sharing the same --user-data-dir collide, and
rem Chromium aborts with "bad option: --user-data-dir=..." (exit code 9).
powershell -NoProfile -Command "(New-Object Net.Sockets.TcpClient).Connect('127.0.0.1',43120)" 2>nul
if %errorlevel%==0 (
    echo DSH Desktop is already running in the system tray ^(http://127.0.0.1:43120/^).
    echo Closing the window only hides it to the tray - it is NOT stopped.
    echo Right-click the DSH Desktop tray icon and choose Quit, or run stop-dsh-desktop.bat first.
    pause
    exit /b 0
)

rem Use the batch file's own directory as project root (avoids hardcoding the
rem non-ASCII path, sidesteps cmd codepage issues).
cd /d "%~dp0dsh_desktop"

rem Redirect DSH home / desktop user-data / corepack cache out of the sandbox
set "DSH_HOME=C:\Users\Lenovo\.cache\dsh-home"
set "DSH_DESKTOP_USER_DATA_DIR=C:\Users\Lenovo\.cache\dsh-desktop-data"
set "COREPACK_HOME=C:\Users\Lenovo\.cache\node\corepack"

echo Starting DSH Desktop ...
echo    DSH_HOME        = %DSH_HOME%
echo    Desktop data    = %DSH_DESKTOP_USER_DATA_DIR%
echo    URL             = http://127.0.0.1:43120/
echo.

node "dsh-plugin-desktop\lib\bin.js"
set "EXIT_CODE=%errorlevel%"

echo.
echo DSH Desktop stopped (exit code %EXIT_CODE%).
if not "%EXIT_CODE%"=="0" pause
endlocal & exit /b %EXIT_CODE%
