# antenna_setup.spec  v0.8.0 — PyInstaller: onefile, без консоли, просит права администратора
# v0.8.0: общие модули safe_json (config.json) и app_log (журнал) — в EXE; утилиты разработчика — нет.
# v0.7.0: значок программы (app_icon): база app_icon_pack.dat, app_icon / app_icon_qt, QtSvg.
a = Analysis(['antenna_setup.pyw'], pathex=[], datas=[('app_icon_pack.dat', '.')],
             hiddenimports=['app_icon', 'app_icon_qt', 'PySide6.QtSvg', 'safe_json', 'app_log'],
             excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.Qt3DCore',
                       'PySide6.QtMultimedia', 'PySide6.QtQuick', 'PySide6.QtQml', 'PySide6.QtCharts'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, name='antenna_setup', console=False, upx=False,
          uac_admin=True)
