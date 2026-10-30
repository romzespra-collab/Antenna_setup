@echo off
chcp 65001 >nul
setlocal EnableExtensions
title Настройка антенны - установка
rem ============================================================
rem  setup.bat  v0.4.2 (antenna_setup)
rem  По образцу START_ON_NEW_PC.bat из SmartMon (проверенный).
rem  Python 3.15 - ОДИН на компьютер для всех наших программ: уже
rem  стоит - берётся он; нет - ставится официальным установщиком
rem  python.org (для всех пользователей, иначе в папку пользователя).
rem  Дальше: PySide6 в этот Python, самопроверка, запуск программы.
rem  Файл в CRLF (с LF cmd путает метки goto).
rem ============================================================
cd /d "%~dp0"

set "PYMIN=15"
set "PYDIR=315"
set "PYVER=3.15.2"
for /f "tokens=2 delims=[]" %%V in ('ver') do set "WINVER=%%V"
for /f "tokens=2,3 delims=. " %%A in ("%WINVER%") do set "WMAJ=%%A" & set "WMIN=%%B"
if "%WMAJ%"=="5" goto :tooold
if "%WMAJ%"=="6" goto :oldwin
goto :findfirst

:tooold
echo.
echo Эта Windows (%WINVER%) слишком старая: нужна Windows 7 SP1 или новее.
pause
exit /b 2

:oldwin
echo.
echo Эта Windows (%WINVER%) старше Windows 10: программа на ней
echo не запустится - ей нужны Qt6 и Python 3.10+, а они требуют
echo Windows 10 или новее.
pause
exit /b 2

:findfirst
set "PY="
call :findpy
if defined PY goto :havepy
echo.
echo Python: %PY%
set "PYW=%PY:python.exe=pythonw.exe%"
if not exist "%PYW%" set "PYW=%PY%"
echo.
echo Ставлю PySide6 в этот Python (один раз, может занять пару минут)...
"%PY%" -m pip install --disable-pip-version-check --upgrade -r "%~dp0requirements.txt"
if not errorlevel 1 goto :libsok
echo Пробую ещё раз (ensurepip, --user)...
"%PY%" -m ensurepip --upgrade
"%PY%" -m pip install --disable-pip-version-check --user --upgrade -r "%~dp0requirements.txt"
if errorlevel 1 goto :nolibs

:libsok
echo.
echo Самопроверка программы...
"%PY%" "%~dp0antenna_setup.pyw" --selftest
set "RC=%errorlevel%"
echo.
echo Запускаю программу...
start "" "%PYW%" "%~dp0antenna_setup.pyw"
if not "%RC%"=="0" echo ВНИМАНИЕ: самопроверка нашла ошибки - строки с крестиком выше, отчёт: selftest.txt
echo.
echo Готово. Окно можно закрыть.
pause
exit /b %RC%

:nolibs
echo.
echo ОШИБКА: pip не смог поставить PySide6 - проверьте интернет и запустите
echo этот файл ещё раз.
pause
exit /b 1

rem ---- ищет Python 3.%PYMIN% (64 бита): py-лаунчер, PATH, обычные папки ----
:findpy
set "PY="
for /f "usebackq delims=" %%E in (`py -3.%PYMIN% -c "import sys;print(sys.executable)" 2^>nul`) do call :try "%%E"
if defined PY exit /b 0
for /f "usebackq delims=" %%E in (`python -c "import sys;print(sys.executable)" 2^>nul`) do call :try "%%E"
if defined PY exit /b 0
call :try "%ProgramFiles%\Python%PYDIR%\python.exe"
call :try "%LocalAppData%\Programs\Python\Python%PYDIR%\python.exe"
exit /b 0

rem ---- годится ли python.exe: есть, 64 бита, версия ровно 3.%PYMIN% ----
:try
if defined PY exit /b 0
if not exist %1 exit /b 0
%1 -c "import sys,struct;sys.exit(0 if sys.version_info[:2]==(3,%PYMIN%) and struct.calcsize('P')==8 else 1)" >nul 2>nul
if errorlevel 1 exit /b 0
set "PY=%~1"
exit /b 0
