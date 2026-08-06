@echo off
chcp 65001 >nul
"%~dp01_node.exe" %*
if errorlevel 1 (
    echo.
    echo [ERROR] Node execution failed, exit code: %errorlevel%
    pause
)
