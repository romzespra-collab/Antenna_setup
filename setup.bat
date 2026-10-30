@echo off
rem setup.bat  v0.2.3 - runs setup.ps1 (Python + PySide6 + start)
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
if errorlevel 1 pause
