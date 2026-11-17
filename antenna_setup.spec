# antenna_setup.spec  v0.7.0 — PyInstaller: onefile, без консоли, просит права администратора
# v0.7.0: значок программы (app_icon): база app_icon_pack.dat, app_icon / app_icon_qt, QtSvg.
a = Analysis(['antenna_setup.pyw'], pathex=[], datas=[('app_icon_pack.dat', '.')],
             hiddenimports=['app_icon', 'app_icon_qt', 'PySide6.QtSvg'],
             excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.Qt3DCore',
                       'PySide6.QtMultimedia', 'PySide6.QtQuick', 'PySide6.QtQml', 'PySide6.QtCharts'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, name='antenna_setup', console=False, upx=False,
          uac_admin=True)
