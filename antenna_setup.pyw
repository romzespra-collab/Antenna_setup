# -*- coding: utf-8 -*-
"""
Настройка ноутбука под антенну, подключённую напрямую (кабелем / PoE).
Ставит статический IP на выбранный адаптер, проверяет, что антенна отвечает,
и открывает её веб-интерфейс в браузере. Только Windows.

VERSION = "0.1.0"

Журнал изменений:
  0.1.0 — первая версия: пресеты антенн, статический IP через netsh,
          возврат на DHCP, проверка доступности, открытие в браузере,
          тёмная/светлая тема, запуск с правами администратора.
"""
VERSION = "0.1.0"

import ctypes
import ipaddress
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QKeySequence, QPalette, QShortcut
from PySide6.QtWidgets import (
    QApplication, QComboBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

# Пресеты: адрес антенны, маска, логин/пароль по умолчанию (с этикеток).
PRESETS = {
    "Comfast CF-E314N (192.168.10.1)": ("192.168.10.1", "255.255.255.0", "admin / admin"),
    "TP-Link TL-WA5210G (192.168.1.254)": ("192.168.1.254", "255.255.255.0", "admin / admin"),
    "Ubiquiti NanoStation M5 (192.168.1.20)": ("192.168.1.20", "255.255.255.0", "ubnt / ubnt"),
}
MY_HOST_OFFSET = 50  # адрес ноутбука = адрес антенны, последний октет заменён на 50

DARK = dict(bg="#1e2227", panel="#262b32", panel2="#2e343c",
            text="#e6e8eb", muted="#8a919b", accent="#3d8bfd", ok="#3fb950", err="#f85149")
LIGHT = dict(bg="#f3f4f6", panel="#ffffff", panel2="#e9ecf0",
             text="#1d2228", muted="#6b7280", accent="#2563eb", ok="#15803d", err="#b91c1c")


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin():
    try:
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, f'"{os.path.abspath(sys.argv[0])}"', None, 1)
        return True
    except Exception:
        return False


def run_cmd(args):
    """Запускает команду без окна консоли. Возвращает (ok, текст)."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        r = subprocess.run(args, capture_output=True, text=True, encoding="cp866",
                           errors="replace", timeout=30, creationflags=flags)
        out = (r.stdout or "") + (r.stderr or "")
        return r.returncode == 0, out.strip()
    except Exception as e:
        return False, str(e)


def list_adapters():
    """Список имён физических адаптеров через PowerShell."""
    ok, out = run_cmd(["powershell", "-NoProfile", "-Command",
                       "Get-NetAdapter -Physical | Select-Object -ExpandProperty Name"])
    if not ok:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def host_ip_for(antenna_ip):
    net = ipaddress.ip_network(antenna_ip + "/24", strict=False)
    hosts = list(net.hosts())
    last = int(antenna_ip.split(".")[-1])
    candidate = hosts[0] if last != MY_HOST_OFFSET else hosts[1]
    base = ".".join(antenna_ip.split(".")[:3])
    return f"{base}.{MY_HOST_OFFSET}" if last != MY_HOST_OFFSET else f"{base}.{MY_HOST_OFFSET + 1}"


def check_http(ip, timeout=3.0):
    """Возвращает код HTTP или None, если нет ответа."""
    try:
        with urllib.request.urlopen(f"http://{ip}/", timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return None


def apply_theme(app, p):
    pal = QPalette(QColor(p["bg"]))
    pal.setColor(QPalette.Window, QColor(p["bg"]))
    pal.setColor(QPalette.WindowText, QColor(p["text"]))
    pal.setColor(QPalette.Base, QColor(p["panel"]))
    pal.setColor(QPalette.AlternateBase, QColor(p["panel2"]))
    pal.setColor(QPalette.Text, QColor(p["text"]))
    pal.setColor(QPalette.Button, QColor(p["panel2"]))
    pal.setColor(QPalette.ButtonText, QColor(p["text"]))
    pal.setColor(QPalette.Highlight, QColor(p["accent"]))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.PlaceholderText, QColor(p["muted"]))
    pal.setColor(QPalette.ToolTipBase, QColor(p["panel"]))
    pal.setColor(QPalette.ToolTipText, QColor(p["text"]))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor(p["muted"]))
    app.setPalette(pal)
    app.setStyleSheet(f"""
        QWidget {{ color: {p['text']}; font-size: 10pt; }}
        QLineEdit, QComboBox, QPlainTextEdit {{
            background: {p['panel']}; color: {p['text']};
            border: 1px solid {p['panel2']}; border-radius: 6px; padding: 4px;
        }}
        QComboBox QAbstractItemView {{ background: {p['panel']}; color: {p['text']}; }}
        QPushButton {{
            background: {p['panel2']}; color: {p['text']};
            border: 1px solid {p['panel2']}; border-radius: 6px;
            padding: 6px 12px; min-width: 80px;
        }}
        QPushButton:hover {{ border-color: {p['accent']}; }}
        QPushButton:disabled {{ color: {p['muted']}; }}
        QPushButton#primary {{ background: {p['accent']}; color: #ffffff; border: none; }}
        QMenu {{ background: {p['panel']}; color: {p['text']}; border: 1px solid {p['panel2']}; }}
        QMenu::item:selected {{ background: {p['accent']}; color: #ffffff; }}
        QMessageBox, QFileDialog, QInputDialog {{ background: {p['panel']}; }}
        QMessageBox QLabel {{ color: {p['text']}; background: transparent; }}
        QLabel#chip {{ border-radius: 10px; padding: 3px 10px;
                       background: {p['panel2']}; color: {p['text']}; }}
    """)


class Main(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Настройка антенны {VERSION}")
        self.resize(640, 520)
        self.dark = True

        cw = QWidget()
        self.setCentralWidget(cw)
        root = QVBoxLayout(cw)

        head = QHBoxLayout()
        title = QLabel("Настройка антенны")
        title.setStyleSheet("font-size: 15pt; font-weight: bold;")
        self.chip = QLabel("● готов")
        self.chip.setObjectName("chip")
        self.btn_theme = QPushButton("☀")
        self.btn_theme.setFixedWidth(44)
        self.btn_theme.clicked.connect(self.toggle_theme)
        head.addWidget(title)
        head.addStretch()
        head.addWidget(self.chip)
        head.addWidget(self.btn_theme)
        root.addLayout(head)

        self.preset = QComboBox()
        self.preset.addItems(PRESETS.keys())
        self.preset.currentIndexChanged.connect(self.on_preset)
        root.addWidget(QLabel("Антенна:"))
        root.addWidget(self.preset)

        self.info = QLabel()
        self.info.setWordWrap(True)
        root.addWidget(self.info)

        row = QHBoxLayout()
        self.adapter = QComboBox()
        self.btn_refresh = QPushButton("Обновить")
        self.btn_refresh.clicked.connect(self.load_adapters)
        row.addWidget(QLabel("Сетевой адаптер:"))
        row.addWidget(self.adapter, 1)
        row.addWidget(self.btn_refresh)
        root.addLayout(row)

        row2 = QHBoxLayout()
        self.my_ip = QLineEdit()
        self.my_ip.setToolTip("Адрес ноутбука на время настройки")
        row2.addWidget(QLabel("IP ноутбука:"))
        row2.addWidget(self.my_ip, 1)
        root.addLayout(row2)

        btns = QHBoxLayout()
        self.btn_set = QPushButton("Поставить IP  F5")
        self.btn_set.setObjectName("primary")
        self.btn_set.clicked.connect(self.set_static)
        self.btn_check = QPushButton("Проверить  F6")
        self.btn_check.clicked.connect(self.check)
        self.btn_open = QPushButton("Открыть в браузере  Ctrl+O")
        self.btn_open.clicked.connect(self.open_browser)
        self.btn_dhcp = QPushButton("Вернуть DHCP")
        self.btn_dhcp.clicked.connect(self.restore_dhcp)
        for b in (self.btn_set, self.btn_check, self.btn_open, self.btn_dhcp):
            btns.addWidget(b)
        root.addLayout(btns)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.log_view.customContextMenuRequested.connect(self.log_menu)
        root.addWidget(self.log_view, 1)

        QShortcut(QKeySequence("F5"), self, self.set_static)
        QShortcut(QKeySequence("F6"), self, self.check)
        QShortcut(QKeySequence("Ctrl+O"), self, self.open_browser)
        QShortcut(QKeySequence("Ctrl+T"), self, self.toggle_theme)

        self.on_preset(0)
        self.load_adapters()
        self.set_chip("● готов", self.color("muted"))

        if sys.platform == "win32" and not is_admin():
            self.log("Нужны права администратора. Запусти программу от имени администратора.")
            self.btn_set.setEnabled(False)
            self.btn_dhcp.setEnabled(False)

    # --- тема и состояние ---
    def color(self, key):
        return (DARK if self.dark else LIGHT)[key]

    def toggle_theme(self):
        self.dark = not self.dark
        self.btn_theme.setText("☀" if self.dark else "☾")
        apply_theme(QApplication.instance(), DARK if self.dark else LIGHT)
        self.set_chip(self.chip.text(), self.color("muted"))

    def set_chip(self, text, color):
        self.chip.setText(text)
        self.chip.setStyleSheet(f"color: {color};")

    def log(self, text):
        self.log_view.appendPlainText(text)

    # --- данные ---
    def current_antenna_ip(self):
        return list(PRESETS.values())[self.preset.currentIndex()][0]

    def on_preset(self, _):
        ip, mask, creds = list(PRESETS.values())[self.preset.currentIndex()]
        self.info.setText(f"Адрес антенны: {ip}    Логин / пароль по умолчанию: {creds}")
        self.my_ip.setText(host_ip_for(ip))

    def load_adapters(self):
        self.adapter.clear()
        names = list_adapters() if sys.platform == "win32" else []
        if names:
            self.adapter.addItems(names)
            self.log(f"Найдено адаптеров: {len(names)}")
        else:
            self.log("Адаптеры не найдены (нужен Windows и PowerShell).")

    # --- действия ---
    def set_static(self):
        name = self.adapter.currentText()
        ip = self.my_ip.text().strip()
        if not name:
            QMessageBox.warning(self, "Адаптер", "Выбери сетевой адаптер.")
            return
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            QMessageBox.warning(self, "IP", "Неверный IP-адрес ноутбука.")
            return
        mask = list(PRESETS.values())[self.preset.currentIndex()][1]
        ok, out = run_cmd(["netsh", "interface", "ip", "set", "address",
                           f"name={name}", "static", ip, mask])
        if ok:
            self.set_chip("● IP задан", self.color("ok"))
            self.log(f"Статический IP {ip} на «{name}» установлен.")
        else:
            self.set_chip("● ошибка", self.color("err"))
            self.log(f"Ошибка netsh: {out}")

    def restore_dhcp(self):
        name = self.adapter.currentText()
        if not name:
            return
        ok, out = run_cmd(["netsh", "interface", "ip", "set", "address", f"name={name}", "dhcp"])
        if ok:
            self.set_chip("● DHCP", self.color("muted"))
            self.log(f"Адаптер «{name}» переведён на DHCP.")
        else:
            self.log(f"Ошибка netsh: {out}")

    def check(self):
        ip = self.current_antenna_ip()
        self.log(f"Проверяю {ip} …")
        self.set_chip("● проверка", self.color("accent"))
        QApplication.processEvents()
        code = check_http(ip)
        if code is None:
            self.set_chip("● нет ответа", self.color("err"))
            self.log(f"{ip}: нет ответа. Проверь кабель, PoE и IP ноутбука.")
        else:
            self.set_chip("● антенна отвечает", self.color("ok"))
            self.log(f"{ip}: отвечает, HTTP {code}.")

    def open_browser(self):
        QDesktopServices.openUrl(QUrl(f"http://{self.current_antenna_ip()}"))
        self.log(f"Открываю http://{self.current_antenna_ip()} …")


def main():
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AntennaSetup.App")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    apply_theme(app, DARK)
    win = Main()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
