@echo off
setlocal
chcp 65001 >nul

echo Stopping DSH Desktop ...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop-dsh-desktop.ps1"
echo.

rem Wait briefly, then confirm the port was released.
timeout /t 2 /nobreak >nul
powershell -NoProfile -Command "(New-Object Net.Sockets.TcpClient).Connect('127.0.0.1',43120)" 2>nul
if %errorlevel%==0 (
    echo Still running: port 43120 is still listening. Wait a moment, then run stop-dsh-desktop.bat again.
) else (
    echo DSH Desktop stopped. You can now re-run start-dsh-desktop.bat.
)
echo.
pause
