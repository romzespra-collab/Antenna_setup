@echo off
chcp 65001 >nul
rem build_exe.bat  v0.8.0 — сборка antenna_setup.exe
cd /d "%~dp0"
echo === [1/5] Проверка Python ===
where python >nul 2>nul || (echo Python не найден. Запусти setup.bat & pause & exit /b 1)
echo === [2/5] Проверка утечек (токены, пароли) ===
python check_leaks.py || (echo Найдены секреты — сборка остановлена & pause & exit /b 1)
echo === [3/5] Библиотеки ===
python -m pip install --disable-pip-version-check -r requirements.txt pyinstaller || (echo Ошибка pip & pause & exit /b 1)
echo === [4/5] PyInstaller ===
python -m PyInstaller --noconfirm --clean antenna_setup.spec || (echo Ошибка сборки & pause & exit /b 1)
echo === [5/5] Самопроверка EXE ===
dist\antenna_setup.exe --selftest || (echo Самопроверка не прошла, см. dist\selftest.txt & pause & exit /b 1)
echo Готово: dist\antenna_setup.exe
pause
