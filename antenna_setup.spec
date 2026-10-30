# antenna_setup.spec  v0.3.5 — PyInstaller: onefile, без консоли, просит права администратора
a = Analysis(['antenna_setup.pyw'], pathex=[], datas=[], hiddenimports=[],
             excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.Qt3DCore',
                       'PySide6.QtMultimedia', 'PySide6.QtQuick', 'PySide6.QtQml', 'PySide6.QtCharts'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, name='antenna_setup', console=False, upx=False,
          uac_admin=True)
