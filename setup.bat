@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Настройка антенны - установка

where pythonw >nul 2>nul
if errorlevel 1 (
  echo Python не найден. Пытаюсь установить Python 3.12 через winget...
  winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
  if errorlevel 1 (
    echo.
    echo Не получилось через winget. Установи Python вручную:
    echo   https://www.python.org/downloads/
    echo При установке отметь галочку "Add python.exe to PATH".
    pause
    exit /b 1
  )
  echo.
  echo Python установлен. Закрой это окно и запусти setup.bat ещё раз.
  pause
  exit /b 0
)

echo Устанавливаю PySide6 (один раз, может занять минуту)...
python -m pip install --upgrade PySide6
if errorlevel 1 (
  echo Ошибка установки PySide6. Проверь интернет и запусти ещё раз.
  pause
  exit /b 1
)

echo Запускаю программу...
start "" pythonw "%~dp0antenna_setup.pyw"
exit /b 0
