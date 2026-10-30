@echo off
chcp 65001 >nul
rem build_exe.bat  v0.3.1 — сборка antenna_setup.exe
cd /d "%~dp0"
echo === [1/4] Проверка Python ===
where python >nul 2>nul || (echo Python не найден. Запусти setup.bat & pause & exit /b 1)
echo === [2/4] Библиотеки ===
python -m pip install --disable-pip-version-check -r requirements.txt pyinstaller || (echo Ошибка pip & pause & exit /b 1)
echo === [3/4] PyInstaller ===
python -m PyInstaller --noconfirm --clean antenna_setup.spec || (echo Ошибка сборки & pause & exit /b 1)
echo === [4/4] Самопроверка EXE ===
dist\antenna_setup.exe --selftest || (echo Самопроверка не прошла, см. dist\selftest.txt & pause & exit /b 1)
echo Готово: dist\antenna_setup.exe
pause
