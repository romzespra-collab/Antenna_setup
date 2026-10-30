@echo off
chcp 65001 >nul
rem setup.bat  v0.2.2 — ставит Python (с python.org, без winget) и PySide6, запускает программу
cd /d "%~dp0"
title Настройка антенны - установка

call :find
if not defined PYW call :install
if not defined PYW goto :fail_py
set "PY=%PYW:pythonw.exe=python.exe%"
echo Python: %PY%
echo Устанавливаю PySide6, один раз, может занять пару минут ...
"%PY%" -m pip install --disable-pip-version-check --upgrade -r requirements.txt
if errorlevel 1 goto :fail_pip
echo Запускаю программу ...
start "" "%PYW%" "%~dp0antenna_setup.pyw"
exit /b 0

:find
set "PYW="
for %%P in (pythonw.exe) do set "PYW=%%~$PATH:P"
if defined PYW if not "%PYW:WindowsApps=%"=="%PYW%" set "PYW="
if defined PYW goto :eof
for /d %%D in ("%LocalAppData%\Programs\Python\Python3*" "%ProgramFiles%\Python3*") do if exist "%%~D\pythonw.exe" set "PYW=%%~D\pythonw.exe"
goto :eof

:install
set "PYURL=https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe"
if /i "%PROCESSOR_ARCHITECTURE%"=="x86" if not defined PROCESSOR_ARCHITEW6432 set "PYURL=https://www.python.org/ftp/python/3.12.8/python-3.12.8.exe"
set "PYI=%TEMP%\python-3.12.8-setup.exe"
echo Python не найден. Скачиваю Python 3.12 с python.org ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; $ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing -Uri $env:PYURL -OutFile $env:PYI"
if errorlevel 1 goto :eof
if not exist "%PYI%" goto :eof
echo Ставлю Python, 1-2 минуты, окно не закрывай ...
"%PYI%" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0
del "%PYI%" >nul 2>nul
call :find
goto :eof

:fail_py
echo.
echo Не получилось поставить Python автоматически - нет интернета или python.org недоступен.
echo Скачай и установи вручную: https://www.python.org/downloads/
echo При установке отметь галочку "Add python.exe to PATH", потом запусти setup.bat ещё раз.
pause
exit /b 1

:fail_pip
echo.
echo Ошибка установки PySide6. Проверь интернет и запусти setup.bat ещё раз.
pause
exit /b 1
