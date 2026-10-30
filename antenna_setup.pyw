# -*- coding: utf-8 -*-
"""
antenna_setup.pyw  v0.3.7

Настройка ноутбука под антенну, подключённую напрямую (кабелем / PoE).
Ставит статический IP на выбранный адаптер (с запоминанием прежних настроек),
проверяет, что антенна отвечает (пинг, порты 80/443, веб), открывает её
веб-интерфейс и возвращает сеть как было. Обновляется с GitHub. Только Windows.

Журнал изменений:
  v0.3.7: кнопка «⏹ Стоп» в «Действиях»; «↩ Вернуть как было» работает и во время поиска —
          останавливает его и возвращает сеть адаптера.
  v0.3.6: свой временный адрес поиска (x.x.x.247, статический) больше не принимается за «свою сеть»
          антенны — сразу прослушка кабеля и перебор подсетей (с вопросом).
  v0.3.5: перед поиском адаптеры перечитываются (адрес мог прийти после запуска — раньше поиск
          говорил «нет адреса»); автоадрес Windows 169.254.x.x показывается и объясняется.
  v0.3.4: плитка «Адаптер ▾» вверху — клик / правый клик: выбрать адаптер (поиск и смена IP —
          только на нём); перебор подсетей пропускает подсети других адаптеров — Wi-Fi с интернетом
          не ломается.
  v0.3.3: поиск сначала только в своей сети, сеть не меняется: шлюз и DHCP-сервер (раздал IP)
          проверяются и показываются всегда; адрес получен по DHCP — другие подсети не трогаются вовсе;
          перебор других подсетей — только после вопроса.
  v0.3.2: поиск антенны переделан: шлюз и DHCP-сервер адаптера — первыми; прослушка кабеля 12 с
          (все пакеты на адаптере + запросы Ubiquiti/MikroTik) — подсети услышанных адресов
          проверяются первыми; после смены IP ждём, пока Windows подготовит адрес (DAD), а не 3 с;
          больше заводских подсетей; услышанные, но молчащие адреса тоже показываются.
  v0.3.1: поиск падал в Python 3.15 («'lazy_import' object is not callable») — свои потоки вместо
          concurrent.futures; при ошибке поиска сеть адаптера возвращается; антенна без открытого
          веба тоже находится (ARP); ⋯ → «Обновить программу с GitHub» всегда активна и работает
          без токена (репозиторий публичный): проверка, скачивание, установка, перезапуск.
  v0.3.0: обновление с GitHub — общий модуль gh_update 1.3.1 из SmartMon (app/gh_update*.py:
          токен с инструкцией «?», автопроверка, «Что нового», докачка, сверка суммы, перезапуск);
          setup.bat — по образцу START_ON_NEW_PC.bat из SmartMon (один Python 3.15 на компьютер).
  v0.2.3: установка через setup.ps1 (у .bat с русским текстом Windows 10 теряла метки и молча
          закрывала окно); при падении программы — окно с ошибкой и antenna_setup.log.
  v0.2.2: setup.bat ставит Python с python.org сам (без winget, которого нет на части Windows 10).
  v0.2.1: в меню ⋯ пункт «Обновить программу с GitHub»; «Обновить» → «Обновить адаптеры»;
          пресеты убраны: вместо них «🔎 Найти антенну» (F7) — поиск на кабеле в своей
          подсети и в заводских (временный IP, потом сеть возвращается), список найденных.
  v0.2.0: исправлен вылет при запуске (не было log_menu); проверка в фоне,
          окно не зависает; редирект антенны на https больше не даёт
          «нет ответа»; пинг считается только по TTL=; маска пресета
          учитывается при расчёте IP; проверка подсети и конфликтов адреса;
          «Вернуть как было» — прежние IP/шлюз/DNS или DHCP; свои пресеты;
          автопроверка после смены IP; запрос прав администратора;
          свой заголовок окна, шапка, плитки, боковая панель, тема ☀/☾,
          меню ⋯ и правый клик везде; настройки сохраняются сами;
          обновление с GitHub; --selftest.
  v0.1.0: первая версия: пресеты антенн, статический IP через netsh,
          возврат на DHCP, проверка доступности, открытие в браузере.
"""
VERSION = "0.3.7"
APP_NAME = "Настройка антенны"
APP_ID = "AntennaSetup.App"
GITHUB_REPO = "romzespra-collab/Antenna_setup"
GITHUB_BRANCH = "main"

import base64
import ctypes
import http.client
import importlib
import importlib.util
import ipaddress
import json
import os
import queue
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
APP_ROOT = Path(sys.executable).parent if FROZEN else Path(os.path.abspath(__file__)).parent
CONFIG_PATH = APP_ROOT / "config.json"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))   # app/ — общие модули (gh_update)
NO_WINDOW = 0x08000000
IS_WIN = sys.platform == "win32"

# ───────────────────────── авто-установка библиотек ─────────────────────────
REQUIRED = (("PySide6", "PySide6>=6.5"),)


def _python_exe():
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and (exe.parent / "python.exe").exists():
        return str(exe.parent / "python.exe")
    return str(exe)


def pip_install(pips, console=True):
    py = _python_exe()
    flags = 0x10 if (IS_WIN and console) else (NO_WINDOW if IS_WIN else 0)
    base = [py, "-m", "pip", "install", "--disable-pip-version-check"]
    try:
        if subprocess.run([py, "-m", "pip", "--version"], creationflags=flags,
                          capture_output=not console).returncode != 0:
            subprocess.run([py, "-m", "ensurepip", "--upgrade"], creationflags=flags)
        ok = subprocess.run(base + list(pips), creationflags=flags).returncode == 0
        if not ok:
            ok = subprocess.run(base + ["--user"] + list(pips), creationflags=flags).returncode == 0
    except Exception:
        ok = False
    importlib.invalidate_caches()
    return ok


def ensure_packages():
    if FROZEN or "--selftest" in sys.argv:
        return
    missing = [(m, p) for m, p in REQUIRED if importlib.util.find_spec(m) is None]
    if not missing:
        return
    pip_install([p for _, p in missing])
    still = [p for m, p in missing if importlib.util.find_spec(m) is None]
    if still:
        msg = ("Не удалось поставить библиотеки:\n  " + "\n  ".join(still) +
               "\n\nПоставь вручную:\n  pip install " + " ".join(still))
        if IS_WIN:
            ctypes.windll.user32.MessageBoxW(None, msg, APP_NAME, 0x10)
        else:
            print(msg)
        sys.exit(1)



def _crash_hook(exc_type, exc, tb):
    """Падение не молча: текст в antenna_setup.log и окно с ошибкой."""
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    try:
        with open(APP_ROOT / "antenna_setup.log", "a", encoding="utf-8") as f:
            f.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] v{VERSION}\n{text}")
    except Exception:
        pass
    if IS_WIN and "--selftest" not in sys.argv:
        try:
            ctypes.windll.user32.MessageBoxW(None, f"Ошибка программы (записано в antenna_setup.log):\n\n{text[-1500:]}",
                                             APP_NAME, 0x10)
        except Exception:
            pass
    else:
        sys.__excepthook__(exc_type, exc, tb)


sys.excepthook = _crash_hook
ensure_packages()

from PySide6.QtCore import (QEvent, QLibraryInfo, QObject, QTranslator, QPoint, QPointF, QProcess, QRectF,  # noqa: E402
                            Qt, QTimer, QUrl, Signal)
from PySide6.QtGui import (QColor, QDesktopServices, QFont, QIcon,  # noqa: E402
                           QKeySequence, QPainter, QPalette, QPen,
                           QPixmap, QShortcut, QTextCursor)
from PySide6.QtWidgets import (QAbstractButton, QApplication, QButtonGroup,  # noqa: E402
                               QComboBox, QFileDialog, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMenu, QMessageBox,
                               QPlainTextEdit, QProgressBar, QPushButton,
                               QStackedWidget, QTextEdit, QVBoxLayout,
                               QWidget)

# ───────────────────────── поиск и тема ─────────────────────────
# заводские подсети антенн и роутеров — по ним ищем, если в своей подсети пусто
SEARCH_SUBNETS = ("192.168.1, 192.168.0, 192.168.10, 192.168.88, 192.168.2, 192.168.100, 192.168.20, "
                  "192.168.8, 192.168.11, 192.168.3, 192.168.5, 10.0.0, 10.10.10, 169.254.1")
OLD_SUBNETS = ("192.168.1, 192.168.0, 192.168.10, 192.168.88, 192.168.2, 192.168.100, 192.168.20, 192.168.8",)  # прежние списки по умолчанию → заменяются новым
SEARCH_HOST = 247  # временный адрес ноутбука при поиске
SEARCH_PORTS = (80, 443)
MY_HOST_OFFSET = 50  # адрес ноутбука = номер сети + 50

THEMES = {
    "dark": {"bg": "#1b1d23", "side": "#16181d", "panel": "#23262e", "panel2": "#2a2e38",
             "line": "#343946", "text": "#e6e8ee", "muted": "#8a91a3", "log_bg": "#111318",
             "log_fg": "#d5d8e0", "accent": "#4f8cff", "ok": "#3ecf8e", "err": "#ff5d6c",
             "warn": "#f5b545", "toggle_off": "#454b59", "side_text": "#ffffff"},
    "light": {"bg": "#f3f4f7", "side": "#2b3445", "panel": "#ffffff", "panel2": "#f1f3f7",
              "line": "#dde1e8", "text": "#1c2230", "muted": "#6b7385", "log_bg": "#fbfbfd",
              "log_fg": "#1c2230", "accent": "#2f6fe4", "ok": "#1f9d63", "err": "#d93848",
              "warn": "#b9800f", "toggle_off": "#c3c8d2", "side_text": "#ffffff"},
}
# цвета страниц боковой панели: (тёмная тема, светлая — темнее)
PAGE_COLORS = {"antenna": ("#4f8cff", "#2f6fe4"), "settings": ("#b07cff", "#7c4ad9"),
               "update": ("#f5a142", "#c26e0f")}
P = dict(THEMES["dark"])  # текущая палитра

DEFAULT_CONFIG = {
    "theme": "dark", "search_subnets": SEARCH_SUBNETS,
    "antenna_ip": "", "mask": "", "my_ip": "", "adapter": "",
    "check_timeout": 3, "check_retries": 6, "auto_check": True, "ask_admin": True,
    "upd_token": "", "upd_auto": True, "upd_branch": GITHUB_BRANCH, "upd_every_h": 12,
    "saved_net": {}, "geometry": "", "page": 0,
}

# ───────────────────────── конфиг (атомарно, с .bak) ─────────────────────────


def _replace_retry(src, dst, tries=10):
    for i in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:  # WinError 5/32 — файл занят антивирусом/редактором
            if i == tries - 1:
                raise
            time.sleep(0.2)


def atomic_write_text(path, text):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    _replace_retry(tmp, path)


def load_config(path=CONFIG_PATH):
    """(cfg, можно_писать). Битый JSON → .bak; и он битый → не писать вовсе."""
    cfg = dict(DEFAULT_CONFIG)
    path = Path(path)
    if not path.exists():
        return cfg, True
    for p in (path, path.with_name(path.name + ".bak")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg.update(data)
                return cfg, True
        except Exception:
            continue
    return cfg, False


def save_config(cfg, path=CONFIG_PATH):
    path = Path(path)
    text = json.dumps(cfg, ensure_ascii=False, indent=2)
    if path.exists():
        try:
            json.loads(path.read_text(encoding="utf-8"))
            shutil.copyfile(path, path.with_name(path.name + ".bak"))
        except Exception:
            pass
    atomic_write_text(path, text)

# ───────────────────────── сеть ─────────────────────────


def decode_out(b):
    if isinstance(b, str):
        return b
    for enc in ("utf-8", "cp866", "cp1251"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", "replace")


def run_cmd(args, timeout=30):
    """Команда без окна консоли. Возвращает (ok, текст)."""
    try:
        r = subprocess.run(args, capture_output=True, timeout=timeout,
                           creationflags=NO_WINDOW if IS_WIN else 0)
        out = decode_out(r.stdout or b"") + decode_out(r.stderr or b"")
        return r.returncode == 0, out.strip()
    except subprocess.TimeoutExpired:
        return False, "команда не ответила за %d с" % timeout
    except Exception as e:
        return False, str(e)


def run_ps(script, timeout=40):
    pre = "[Console]::OutputEncoding=[Text.Encoding]::UTF8;$ProgressPreference='SilentlyContinue';"
    enc = base64.b64encode((pre + script).encode("utf-16-le")).decode()
    return run_cmd(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                    "-EncodedCommand", enc], timeout)


def ps_str(s):
    return "'" + str(s).replace("'", "''") + "'"


def list_adapters():
    """Физические адаптеры: [{Name, Desc, Status, Media, IP, Prefix, Dhcp}]. Проводные — первыми."""
    script = (
        "$r=foreach($a in Get-NetAdapter -Physical){"
        "$all=@(Get-NetIPAddress -InterfaceIndex $a.ifIndex -AddressFamily IPv4 -EA SilentlyContinue);"
        "$ip=$all|?{$_.PrefixOrigin -ne 'WellKnown'}|select -First 1;"
        "if(-not $ip){$ip=$all|select -First 1};"
        "$if=Get-NetIPInterface -InterfaceIndex $a.ifIndex -AddressFamily IPv4 -EA SilentlyContinue;"
        "$c=Get-CimInstance Win32_NetworkAdapterConfiguration -Filter \"InterfaceIndex=$($a.ifIndex)\" -EA SilentlyContinue;"
        "[pscustomobject]@{Name=$a.Name;Desc=$a.InterfaceDescription;Status=[string]$a.Status;"
        "Media=[string]$a.PhysicalMediaType;IP=[string]$ip.IPAddress;Prefix=[int]$ip.PrefixLength;"
        "Dhcp=[string]$if.Dhcp;DhcpSrv=[string]$c.DHCPServer;"
        "Gw=[string]($c.DefaultIPGateway|?{$_ -notmatch ':'}|select -First 1)}};"
        "ConvertTo-Json -Compress -InputObject @($r)")
    ok, out = run_ps(script)
    if not ok:
        raise RuntimeError(out or "PowerShell не ответил")
    data = json.loads(out or "[]")
    if isinstance(data, dict):
        data = [data]
    wifi = ("802.11", "wireless", "wi-fi", "wlan")
    for a in data:
        text = (a.get("Media", "") + " " + a.get("Desc", "")).lower()
        a["Wifi"] = any(w in text for w in wifi)
    data.sort(key=lambda a: (a["Wifi"], a.get("Status") != "Up", a.get("Name", "")))
    return data


def snapshot_adapter(name):
    """Текущие IPv4-настройки адаптера, чтобы потом вернуть как было."""
    n = ps_str(name)
    script = (
        f"$n={n};$i=Get-NetIPInterface -InterfaceAlias $n -AddressFamily IPv4 -EA Stop;"
        "$ip=Get-NetIPAddress -InterfaceAlias $n -AddressFamily IPv4 -EA SilentlyContinue|"
        "?{$_.PrefixOrigin -ne 'WellKnown'}|select -First 1;"
        "$gw=(Get-NetRoute -InterfaceAlias $n -DestinationPrefix '0.0.0.0/0' -EA SilentlyContinue|"
        "select -First 1).NextHop;"
        "$d=(Get-DnsClientServerAddress -InterfaceAlias $n -AddressFamily IPv4 -EA SilentlyContinue).ServerAddresses;"
        "ConvertTo-Json -Compress -InputObject ([pscustomobject]@{Dhcp=[string]$i.Dhcp;"
        "IP=[string]$ip.IPAddress;Prefix=[int]$ip.PrefixLength;Gw=[string]$gw;Dns=@($d)})")
    ok, out = run_ps(script)
    if not ok:
        raise RuntimeError(out or "не удалось прочитать настройки адаптера")
    d = json.loads(out)
    snap = {"dhcp": d.get("Dhcp", "").lower() == "enabled", "ip": d.get("IP") or "",
            "mask": "", "gw": d.get("Gw") or "", "dns": [x for x in (d.get("Dns") or []) if x]}
    if snap["ip"] and d.get("Prefix"):
        snap["mask"] = str(ipaddress.ip_network(f"0.0.0.0/{d['Prefix']}").netmask)
    return snap


def restore_commands(name, snap):
    """Команды netsh, возвращающие адаптер к снимку."""
    nm = f"name={name}"
    base = ["netsh", "interface", "ipv4"]
    if snap.get("dhcp") or not snap.get("ip"):
        return [base + ["set", "address", nm, "source=dhcp"],
                base + ["set", "dnsservers", nm, "source=dhcp"]]
    cmds = [base + ["set", "address", nm, "static", snap["ip"], snap["mask"] or "255.255.255.0"]
            + ([snap["gw"]] if snap.get("gw") else [])]
    dns = snap.get("dns") or []
    if dns:
        cmds.append(base + ["set", "dnsservers", nm, "static", dns[0], "primary", "validate=no"])
        for i, d in enumerate(dns[1:], 2):
            cmds.append(base + ["add", "dnsservers", nm, d, f"index={i}", "validate=no"])
    else:
        cmds.append(base + ["set", "dnsservers", nm, "static", "none"])
    return cmds


def host_ip_for(antenna_ip, mask="255.255.255.0"):
    """Адрес ноутбука в той же подсети: сеть+50, при совпадении — +51, иначе первый свободный."""
    net = ipaddress.ip_network(f"{antenna_ip}/{mask}", strict=False)
    ant = ipaddress.ip_address(antenna_ip)
    hosts = list(net.hosts()) if net.num_addresses <= 65536 else []
    for off in (MY_HOST_OFFSET, MY_HOST_OFFSET + 1):
        cand = net.network_address + off
        if cand in net and cand != ant and cand not in (net.network_address, net.broadcast_address):
            return str(cand)
    for h in hosts:
        if h != ant:
            return str(h)
    raise ValueError("в подсети нет свободного адреса")


def validate(antenna_ip, mask, my_ip):
    """Текст ошибки или None."""
    try:
        ant = ipaddress.IPv4Address(antenna_ip)
    except ValueError:
        return "Неверный адрес антенны."
    try:
        net = ipaddress.IPv4Network(f"{antenna_ip}/{mask}", strict=False)
    except ValueError:
        return "Неверная маска."
    if net.prefixlen > 30:
        return "Маска слишком узкая (больше /30)."
    try:
        me = ipaddress.IPv4Address(my_ip)
    except ValueError:
        return "Неверный IP ноутбука."
    if me not in net:
        return f"IP ноутбука {me} не в подсети антенны {net}."
    if me == ant:
        return "IP ноутбука совпадает с адресом антенны."
    if me in (net.network_address, net.broadcast_address):
        return "IP ноутбука — служебный адрес сети."
    if ant in (net.network_address, net.broadcast_address):
        return "Адрес антенны — служебный адрес сети."
    return None


def ping(ip, timeout_s=1.0):
    """True — только если пришёл ответ с TTL (а не «узел недоступен»)."""
    if IS_WIN:
        args = ["ping", "-n", "1", "-w", str(int(timeout_s * 1000)), ip]
    else:
        args = ["ping", "-c", "1", "-W", str(max(1, int(timeout_s))), ip]
    ok, out = run_cmd(args, timeout=timeout_s + 5)
    return ok and "ttl=" in out.lower()


def tcp_open(ip, port, timeout=2.0, src=None):
    try:
        with socket.create_connection((ip, port), timeout=timeout,
                                      source_address=(src, 0) if src else None):
            return True
    except OSError:
        return False


def http_status(ip, timeout=3.0):
    """(код, Location) с порта 80 без перехода по редиректам; None — нет ответа."""
    c = http.client.HTTPConnection(ip, 80, timeout=timeout)
    try:
        c.request("GET", "/", headers={"User-Agent": "antenna_setup"})
        r = c.getresponse()
        return r.status, r.getheader("Location") or ""
    except (OSError, http.client.HTTPException):
        return None
    finally:
        c.close()


def check_antenna(ip, timeout=3.0):
    res = {"ping": ping(ip, min(timeout, 2.0)), "p80": tcp_open(ip, 80, timeout),
           "p443": tcp_open(ip, 443, timeout), "http": None}
    if res["p80"]:
        res["http"] = http_status(ip, timeout)
    res["alive"] = res["ping"] or res["p80"] or res["p443"]
    return res


def parse_subnets(text):
    """«192.168.1, 10.0.0» → [IPv4Network /24]. Кривое пропускаем."""
    out = []
    for part in str(text).replace(";", ",").split(","):
        part = part.strip().rstrip(".")
        if not part:
            continue
        if part.count(".") == 2:
            part += ".0"
        try:
            net = ipaddress.IPv4Network(f"{part}/24", strict=False)
        except ValueError:
            continue
        if net not in out:
            out.append(net)
    return out


def scan_subnet(net, skip=(), src=None, ports=SEARCH_PORTS, timeout=0.5, stopped=lambda: False):
    """Ищет в подсети узлы с открытыми портами (веб антенны). {ip: [порты]} по возрастанию адреса."""
    # свои потоки, без concurrent.futures: в Python 3.15 он падал «'lazy_import' object is not callable»
    hosts = iter([str(h) for h in net.hosts() if str(h) not in skip])
    found, lock = {}, threading.Lock()

    def worker():
        while not stopped():
            with lock:
                ip = next(hosts, None)
            if ip is None:
                return
            opened = [p for p in ports if tcp_open(ip, p, timeout, src)]
            if opened:
                with lock:
                    found[ip] = opened
    threads = [threading.Thread(target=worker, daemon=True) for _ in range(min(64, net.num_addresses))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return dict(sorted(found.items(), key=lambda kv: ipaddress.IPv4Address(kv[0])))


def wait_ip_ready(ip, timeout=15.0, stopped=lambda: False):
    """После netsh Windows проверяет адрес (DAD) — до этого с него ничего не уходит.
    -> "ok" | "dup" (адрес занят) | "timeout"."""
    end = time.monotonic() + timeout
    while time.monotonic() < end and not stopped():
        ok, out = run_ps(f"(Get-NetIPAddress -IPAddress {ps_str(ip)} -EA SilentlyContinue).AddressState", 10)
        if "Preferred" in out:
            return "ok"
        if "Duplicate" in out:
            return "dup"
        time.sleep(0.7)
    return "timeout"


def parse_ubnt(data):
    """Ответ Ubiquiti Discovery (UDP 10001) -> (ip, описание) или None."""
    if len(data) < 4 or data[0] != 1:
        return None
    ip, info, i = "", [], 4
    while i + 3 <= len(data):
        t, n = data[i], int.from_bytes(data[i + 1:i + 3], "big")
        v = data[i + 3:i + 3 + n]
        if t == 0x02 and n >= 10:
            ip = ip or socket.inet_ntoa(v[6:10])
        elif t in (0x0B, 0x0C, 0x14, 0x15):
            info.append(v.decode("utf-8", "replace"))
        i += 3 + n
    return (ip, "Ubiquiti " + " ".join(dict.fromkeys(x for x in info if x))) if ip else None


def parse_mndp(data):
    """Ответ MikroTik MNDP (UDP 5678) -> (ip, описание) или None."""
    ip, info, i = "", [], 4
    while i + 4 <= len(data):
        t, n = int.from_bytes(data[i:i + 2], "big"), int.from_bytes(data[i + 2:i + 4], "big")
        v = data[i + 4:i + 4 + n]
        if t == 0x11 and n == 4:
            ip = socket.inet_ntoa(v)
        elif t in (5, 0x0C):
            info.append(v.decode("utf-8", "replace"))
        i += 4 + n
    return (ip, "MikroTik " + " ".join(x for x in info if x)) if ip else None


def listen_wire(src_ip, seconds=12.0, stopped=lambda: False):
    """Слушать кабель: все IP-пакеты на адаптере (нужны права администратора) + запросы
    обнаружения Ubiquiti/MikroTik. Антенна в любой подсети что-то шлёт — её адрес виден.
    -> {ip: описание}."""
    heard, lock = {}, threading.Lock()
    done = threading.Event()

    def add(ip, what):
        try:
            a = ipaddress.IPv4Address(ip)
        except ValueError:
            return
        if ip == src_ip or a.is_multicast or a.is_unspecified or ip == "255.255.255.255":
            return
        with lock:
            if what or ip not in heard:
                heard[ip] = what or heard.get(ip, "")

    def sniff():
        if not IS_WIN:
            return
        try:
            r = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_IP)
            r.bind((src_ip, 0))
            r.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
            r.ioctl(socket.SIO_RCVALL, socket.RCVALL_ON)
            r.settimeout(0.5)
        except OSError:
            return
        try:
            while not done.is_set():
                try:
                    pkt = r.recv(65535)
                except socket.timeout:
                    continue
                if len(pkt) >= 20 and pkt[0] >> 4 == 4:
                    add(socket.inet_ntoa(pkt[12:16]), "")
        finally:
            try:
                r.ioctl(socket.SIO_RCVALL, socket.RCVALL_OFF)
            except OSError:
                pass
            r.close()

    def discover():
        try:
            u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            u.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            u.bind((src_ip, 0))
            u.settimeout(0.5)
        except OSError:
            return
        last = 0.0
        try:
            while not done.is_set():
                if time.monotonic() - last > 3:
                    last = time.monotonic()
                    for port, msg in ((10001, b"\x01\x00\x00\x00"), (5678, b"\x00\x00\x00\x00")):
                        try:
                            u.sendto(msg, ("255.255.255.255", port))
                        except OSError:
                            pass
                try:
                    data, (ip, _port) = u.recvfrom(4096)
                except (socket.timeout, OSError):
                    continue
                res = parse_ubnt(data) or parse_mndp(data)
                add(ip, res[1] if res else "")
                if res:
                    add(res[0], res[1])
        finally:
            u.close()
    th = [threading.Thread(target=f, daemon=True) for f in (sniff, discover)]
    for t in th:
        t.start()
    end = time.monotonic() + seconds
    while time.monotonic() < end and not stopped():
        time.sleep(0.2)
    done.set()
    for t in th:
        t.join(2)
    return dict(sorted(heard.items(), key=lambda kv: ipaddress.IPv4Address(kv[0])))


def neighbors(name, net, skip=()):
    """Кто ответил на ARP на этом адаптере (антенна без открытого веба тоже видна)."""
    script = (f"Get-NetNeighbor -InterfaceAlias {ps_str(name)} -AddressFamily IPv4 -EA SilentlyContinue|"
              "?{$_.State -in 'Reachable','Stale','Delay','Probe'}|"
              "%{$_.IPAddress}")
    ok, out = run_ps(script, timeout=20)
    res = []
    for line in out.splitlines() if ok else []:
        try:
            ip = ipaddress.IPv4Address(line.strip())
        except ValueError:
            continue
        if ip in net and ip not in (net.network_address, net.broadcast_address) and str(ip) not in skip:
            res.append(str(ip))
    return sorted(set(res), key=ipaddress.IPv4Address)


def web_url(ip, res=None):
    if res and not res.get("p80") and res.get("p443"):
        return f"https://{ip}/"
    if res and res.get("http") and res["http"][1].lower().startswith("https://"):
        return f"https://{ip}/"
    return f"http://{ip}/"

# ───────────────────────── права администратора ─────────────────────────


def is_admin():
    if not IS_WIN:
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin():
    """Перезапуск с UAC. True — новый процесс запущен."""
    try:
        exe = sys.executable
        if FROZEN:
            params = "--no-admin"
        else:
            w = Path(exe).with_name("pythonw.exe")
            exe = str(w) if w.exists() else exe
            params = f'"{os.path.abspath(__file__)}" --no-admin'
        return ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params,
                                                   str(APP_ROOT), 1) > 32
    except Exception:
        return False

# ───────────────────────── фоновая работа ─────────────────────────


_DONE = object()


class Worker:
    """Одно действие за раз в отдельном потоке. Связь с UI — через очередь."""

    def __init__(self, q):
        self.q = q
        self.thread = None
        self.stop_flag = threading.Event()
        self.name = ""
        self.blocking_close = False

    def busy(self):
        return self.thread is not None and self.thread.is_alive()

    def start(self, name, fn, blocking_close=False):
        if self.busy():
            return False
        self.name = name
        self.blocking_close = blocking_close
        self.stop_flag.clear()

        def run():
            try:
                fn(self)
            except Exception as e:
                self.log(f"✗ {name}: {e}")
            finally:
                self.q.put(_DONE)
        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        return True

    def log(self, text):
        self.q.put(("log", text))

    def ui(self, fn):
        self.q.put(fn)

    def stopped(self):
        return self.stop_flag.is_set()

    def sleep(self, sec):
        return self.stop_flag.wait(sec)

# ───────────────────────── тема: QSS + палитра ─────────────────────────


def _rgba(hexc, alpha):
    c = QColor(hexc)
    return f"rgba({c.red()},{c.green()},{c.blue()},{alpha})"


def _qss(p):
    return f"""
    * {{ font-family: "Segoe UI"; font-size: 10pt; }}
    QWidget {{ color: {p['text']}; }}
    QWidget#root, QStackedWidget, QWidget#page {{ background: {p['bg']}; }}
    QDialog, QMessageBox, QFileDialog, QInputDialog {{ background: {p['panel']}; color: {p['text']}; }}
    QMessageBox QLabel, QDialog QLabel {{ color: {p['text']}; background: transparent; }}
    QWidget#titleBar {{ background: {p['side']}; }}
    QLabel#titleText {{ color: {p['side_text']}; font-weight: 600; }}
    QPushButton#winBtn, QPushButton#winClose {{ background: transparent; border: none;
        min-width: 44px; max-width: 44px; padding: 0; border-radius: 0; }}
    QPushButton#winBtn:hover {{ background: rgba(255,255,255,0.12); }}
    QPushButton#winClose:hover {{ background: #e81123; }}
    QWidget#side {{ background: {p['side']}; }}
    QLabel#h1 {{ font-size: 15pt; font-weight: 700; }}
    QLabel#chip {{ border-radius: 11px; padding: 3px 12px; background: {p['panel2']};
        border: 1px solid {p['line']}; font-weight: 600; }}
    QFrame#card, QFrame#tile {{ background: {p['panel']}; border: 1px solid {p['line']}; border-radius: 10px; }}
    QFrame#tile[clickable="true"]:hover {{ border-color: {p['accent']}; }}
    QLabel#cardTitle {{ color: {p['muted']}; font-size: 8pt; font-weight: 700; letter-spacing: 1px; background: transparent; }}
    QLabel#tileCap {{ color: {p['muted']}; font-size: 8pt; background: transparent; }}
    QLabel#tileVal {{ font-size: 13pt; font-weight: 700; background: transparent; }}
    QLabel#tileSub, QLabel#hint {{ color: {p['muted']}; font-size: 9pt; background: transparent; }}
    QLineEdit, QComboBox, QPlainTextEdit, QTextEdit {{ background: {p['panel2']}; color: {p['text']};
        border: 1px solid {p['line']}; border-radius: 7px; padding: 4px 6px;
        selection-background-color: {p['accent']}; selection-color: #ffffff; }}
    QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {{ border-color: {p['accent']}; }}
    QLineEdit:disabled {{ color: {p['muted']}; }}
    QLineEdit#intField {{ padding: 2px; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{ background: {p['panel']}; color: {p['text']};
        border: 1px solid {p['line']}; selection-background-color: {p['accent']}; selection-color: #ffffff; }}
    QPlainTextEdit#log {{ background: {p['log_bg']}; color: {p['log_fg']};
        font-family: Consolas, "DejaVu Sans Mono", monospace; font-size: 9pt; }}
    QListWidget {{ background: {p['panel2']}; color: {p['text']}; border: 1px solid {p['line']};
        border-radius: 7px; padding: 4px; outline: none; }}
    QListWidget::item {{ padding: 6px 8px; border-radius: 6px; }}
    QListWidget::item:hover {{ background: {p['panel']}; }}
    QListWidget::item:selected {{ background: {_rgba(p['accent'], 40)}; color: {p['text']};
        border-left: 3px solid {p['accent']}; }}
    QGroupBox {{ background: {p['panel']}; border: 1px solid {p['line']}; border-radius: 10px;
        margin-top: 16px; padding: 10px 8px 8px 8px; font-weight: 600; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; color: {p['muted']}; }}
    QCheckBox, QRadioButton {{ color: {p['text']}; background: transparent; }}
    QWidget#setinner {{ background: {p['bg']}; }}
    QGroupBox QPushButton {{ padding: 5px 8px; min-width: 0; }}
    QPushButton {{ background: {p['panel2']}; color: {p['text']}; border: 1px solid {p['line']};
        border-radius: 7px; padding: 6px 12px; min-width: 80px; }}
    QPushButton:hover {{ border-color: {p['accent']}; }}
    QPushButton:pressed {{ background: {p['line']}; }}
    QPushButton:disabled {{ color: {p['muted']}; background: {p['panel']}; }}
    QPushButton#primary {{ background: {p['accent']}; color: #ffffff; border: 1px solid {p['accent']}; font-weight: 700; }}
    QPushButton#primary:disabled {{ background: {p['line']}; border-color: {p['line']}; color: {p['muted']}; }}
    QPushButton#danger {{ color: {p['err']}; border: 1px solid {p['err']}; background: transparent; }}
    QPushButton#tool {{ min-width: 34px; max-width: 34px; padding: 4px 0; font-size: 12pt; }}
    QPushButton#step {{ min-width: 26px; max-width: 26px; padding: 2px 0; font-weight: 700; }}
    QProgressBar {{ background: {p['panel2']}; border: none; border-radius: 3px; max-height: 6px; }}
    QProgressBar::chunk {{ background: {p['accent']}; border-radius: 3px; }}
    QMenu {{ background: {p['panel']}; color: {p['text']}; border: 1px solid {p['line']}; padding: 4px; }}
    QMenu::item {{ padding: 5px 22px 5px 14px; border-radius: 5px; }}
    QMenu::item:selected {{ background: {p['accent']}; color: #ffffff; }}
    QMenu::item:disabled {{ color: {p['muted']}; }}
    QMenu::separator {{ height: 1px; background: {p['line']}; margin: 4px 6px; }}
    QToolTip {{ background: {p['panel2']}; color: {p['text']}; border: 1px solid {p['accent']}; padding: 4px; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; }}
    QScrollBar::handle:vertical {{ background: {p['line']}; border-radius: 5px; min-height: 24px; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; }}
    QScrollBar::handle:horizontal {{ background: {p['line']}; border-radius: 5px; min-width: 24px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QSplitter::handle {{ background: transparent; }}
    QWidget#statusbar {{ background: {p['panel']}; border-top: 1px solid {p['line']}; }}
    QLabel#status {{ color: {p['muted']}; font-size: 9pt; background: transparent; }}
    """


def _palette(p):
    pal = QPalette(QColor(p["bg"]))
    roles = {QPalette.Window: p["bg"], QPalette.WindowText: p["text"], QPalette.Base: p["panel2"],
             QPalette.AlternateBase: p["panel"], QPalette.Text: p["text"], QPalette.Button: p["panel2"],
             QPalette.ButtonText: p["text"], QPalette.Highlight: p["accent"],
             QPalette.HighlightedText: "#ffffff", QPalette.PlaceholderText: p["muted"],
             QPalette.ToolTipBase: p["panel2"], QPalette.ToolTipText: p["text"],
             QPalette.BrightText: "#ffffff", QPalette.Link: p["accent"]}
    for grp in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
        for role, c in roles.items():
            pal.setColor(grp, role, QColor(c))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor(p["muted"]))
    return pal


def apply_theme(app, name):
    P.clear()
    P.update(THEMES.get(name, THEMES["dark"]))
    app.setPalette(_palette(P))
    app.setStyleSheet(_qss(P))


def _dwm_paint(w):
    """Системная полоса диалогов в цвет темы (Windows 10/11). Ошибки — молча."""
    if not IS_WIN:
        return
    try:
        hwnd = int(w.winId())
        dark = ctypes.c_int(1 if QColor(P["bg"]).lightness() < 128 else 0)
        dwm = ctypes.windll.dwmapi
        if dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark), 4) != 0:
            dwm.DwmSetWindowAttribute(hwnd, 19, ctypes.byref(dark), 4)

        def colorref(hexc):
            c = QColor(hexc)
            return ctypes.c_int(c.red() | (c.green() << 8) | (c.blue() << 16))
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(colorref(P["panel"])), 4)
        dwm.DwmSetWindowAttribute(hwnd, 36, ctypes.byref(colorref(P["text"])), 4)
        ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0027)  # NOSIZE|NOMOVE|NOZORDER|FRAMECHANGED
    except Exception:
        pass

# ───────────────────────── значки (QPainter) ─────────────────────────


def draw_antenna(p, r, color, width=2.0):
    """Мачта с волнами в прямоугольнике r."""
    cx, w, h = r.center().x(), r.width(), r.height()
    pen = QPen(QColor(color), width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    top = r.top() + h * 0.42
    p.drawLine(QPointF(cx, top), QPointF(cx - w * 0.2, r.bottom() - h * 0.05))
    p.drawLine(QPointF(cx, top), QPointF(cx + w * 0.2, r.bottom() - h * 0.05))
    p.drawLine(QPointF(cx - w * 0.11, r.top() + h * 0.72), QPointF(cx + w * 0.11, r.top() + h * 0.72))
    p.setBrush(QColor(color))
    p.drawEllipse(QPointF(cx, top), width * 1.3, width * 1.3)
    p.setBrush(Qt.NoBrush)
    for k in (0.17, 0.31):
        rr = QRectF(cx - w * k, top - w * k, w * k * 2, w * k * 2)
        p.drawArc(rr, 30 * 16, 120 * 16)


def draw_gear(p, r, color, width=2.0):
    p.setPen(QPen(QColor(color), width, Qt.SolidLine, Qt.RoundCap))
    p.setBrush(Qt.NoBrush)
    c = r.center()
    rad = r.width() * 0.26
    p.drawEllipse(c, rad, rad)
    p.drawEllipse(c, rad * 0.4, rad * 0.4)
    p.save()
    p.translate(c)
    for _ in range(8):
        p.drawLine(QPointF(0, -rad), QPointF(0, -rad * 1.45))
        p.rotate(45)
    p.restore()


def draw_update(p, r, color, width=2.0):
    p.setPen(QPen(QColor(color), width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    c = r.center()
    rad = r.width() * 0.32
    rr = QRectF(c.x() - rad, c.y() - rad, rad * 2, rad * 2)
    p.drawArc(rr, 100 * 16, 250 * 16)
    tip = QPointF(c.x() - rad * 0.17, c.y() - rad)
    p.drawLine(tip, tip + QPointF(rad * 0.45, -rad * 0.35))
    p.drawLine(tip, tip + QPointF(rad * 0.45, rad * 0.35))
    p.drawLine(QPointF(c.x(), c.y() - rad * 0.35), QPointF(c.x(), c.y() + rad * 0.35))
    p.drawLine(QPointF(c.x(), c.y() + rad * 0.35), QPointF(c.x() - rad * 0.25, c.y() + rad * 0.1))
    p.drawLine(QPointF(c.x(), c.y() + rad * 0.35), QPointF(c.x() + rad * 0.25, c.y() + rad * 0.1))


ICON_DRAW = {"antenna": draw_antenna, "settings": draw_gear, "update": draw_update}


def app_icon():
    icon = QIcon()
    for s in (16, 20, 24, 32, 48, 64, 128, 256):
        pm = QPixmap(s, s)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#2f6fe4"))
        p.drawRoundedRect(QRectF(0, 0, s, s), s * 0.22, s * 0.22)
        m = s * 0.12
        draw_antenna(p, QRectF(m, m, s - 2 * m, s - 2 * m), "#ffffff", max(1.2, s / 14))
        p.end()
        icon.addPixmap(pm)
    return icon

# ───────────────────────── виджеты ─────────────────────────


class Toggle(QAbstractButton):
    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(40, 22)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(P["accent"] if self.isChecked() else P["toggle_off"]))
        p.drawRoundedRect(QRectF(0, 0, 40, 22), 11, 11)
        p.setBrush(QColor("#ffffff"))
        x = 21 if self.isChecked() else 3
        p.drawEllipse(QRectF(x, 3, 16, 16))


class Dot(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.color = "muted"
        self.setFixedSize(12, 12)

    def set(self, color):
        self.color = color
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(P.get(self.color, self.color)))
        p.drawEllipse(QRectF(1, 1, 10, 10))


class _IntField(QWidget):
    """Число без QSpinBox: [−] поле [+]; колесо и ↑/↓; ввод по Enter/уходу фокуса, кривой — откат."""
    valueChanged = Signal(int)

    def __init__(self, lo=0, hi=100, value=0, suffix="", parent=None):
        super().__init__(parent)
        self._lo, self._hi, self._val, self._suffix, self._special = lo, hi, value, suffix, ""
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.minus = QPushButton("−")
        self.plus = QPushButton("+")
        for b in (self.minus, self.plus):
            b.setObjectName("step")
            b.setAutoRepeat(True)
            b.setFocusPolicy(Qt.NoFocus)
        self.edit = QLineEdit()
        self.edit.setObjectName("intField")
        self.edit.setAlignment(Qt.AlignCenter)
        self.edit.setFixedWidth(self.edit.fontMetrics().horizontalAdvance("720 мин") + 28)
        self.edit.installEventFilter(self)
        self.edit.editingFinished.connect(self._commit)
        self.minus.clicked.connect(lambda: self.stepBy(-1))
        self.plus.clicked.connect(lambda: self.stepBy(1))
        lay.addWidget(self.minus)
        lay.addWidget(self.edit)
        lay.addWidget(self.plus)
        lay.addStretch()
        self._show()

    def value(self):
        return self._val

    def setRange(self, lo, hi):
        self._lo, self._hi = lo, hi
        self.setValue(self._val)

    def setSuffix(self, s):
        self._suffix = s
        self._show()

    def setSpecialValueText(self, s):
        self._special = s
        self._show()

    def setValue(self, v):
        v = max(self._lo, min(self._hi, int(v)))
        changed = v != self._val
        self._val = v
        self._show()
        if changed:
            self.valueChanged.emit(v)

    def stepBy(self, n):
        self.setValue(self._val + n)

    def _show(self):
        if self._special and self._val == self._lo:
            self.edit.setText(self._special)
        else:
            self.edit.setText(f"{self._val} {self._suffix}".strip())

    def _commit(self):
        t = self.edit.text().strip()
        if self._special and t == self._special:
            self.setValue(self._lo)
            return
        digits = t[:-len(self._suffix)].strip() if self._suffix and t.endswith(self._suffix) else t
        try:
            self.setValue(int(digits))
        except ValueError:
            self._show()

    def eventFilter(self, obj, ev):
        if obj is self.edit:
            if ev.type() == QEvent.Wheel:
                self.stepBy(1 if ev.angleDelta().y() > 0 else -1)
                return True
            if ev.type() == QEvent.KeyPress and ev.key() in (Qt.Key_Up, Qt.Key_Down):
                self.stepBy(1 if ev.key() == Qt.Key_Up else -1)
                return True
        return super().eventFilter(obj, ev)


class SideButton(QAbstractButton):
    """Кнопка боковой панели: значок QPainter (цветной контур) + белая жирная подпись."""

    def __init__(self, key, text, parent=None):
        super().__init__(parent)
        self.key = key
        self.setText(text)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(88, 70)
        self.setToolTip(text)

    def color(self):
        dark, light = PAGE_COLORS[self.key]
        return light if QColor(P["bg"]).lightness() > 128 else dark

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        col = QColor(self.color())
        if self.isChecked() or self.underMouse():
            bg = QColor(col)
            bg.setAlpha(60 if self.isChecked() else 28)
            p.setPen(Qt.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(QRectF(6, 3, self.width() - 10, self.height() - 6), 9, 9)
        if self.isChecked():
            p.setBrush(col)
            p.drawRoundedRect(QRectF(0, 12, 4, self.height() - 24), 2, 2)
        ICON_DRAW[self.key](p, QRectF(self.width() / 2 - 14, 8, 28, 28), col.lighter(115), 2.2)
        f = QFont(self.font())
        f.setPointSizeF(8.5)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(P["side_text"]))
        p.drawText(QRectF(0, 40, self.width(), 24), Qt.AlignHCenter | Qt.AlignVCenter, self.text())

    def enterEvent(self, e):
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.update()
        super().leaveEvent(e)


class _WinBtn(QPushButton):
    def __init__(self, kind, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setObjectName("winClose" if kind == "close" else "winBtn")
        self.setFixedHeight(34)
        self.setFocusPolicy(Qt.NoFocus)
        self.maxed = False

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        col = "#ffffff" if (self.kind == "close" and self.underMouse()) else P["side_text"]
        p.setPen(QPen(QColor(col), 1.2))
        c = self.rect().center()
        x, y, s = c.x() + 0.5, c.y() + 0.5, 5
        if self.kind == "min":
            p.drawLine(QPointF(x - s, y), QPointF(x + s, y))
        elif self.kind == "max":
            if self.maxed:
                p.drawRect(QRectF(x - s, y - s + 2, s * 2 - 2, s * 2 - 2))
                p.drawPolyline([QPointF(x - s + 2, y - s + 2), QPointF(x - s + 2, y - s),
                                QPointF(x + s, y - s), QPointF(x + s, y + s - 2), QPointF(x + s - 2, y + s - 2)])
            else:
                p.drawRect(QRectF(x - s, y - s, s * 2, s * 2))
        else:
            p.drawLine(QPointF(x - s, y - s), QPointF(x + s, y + s))
            p.drawLine(QPointF(x - s, y + s), QPointF(x + s, y - s))


class TitleBar(QWidget):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setObjectName("titleBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(34)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 0, 0)
        lay.setSpacing(8)
        self.icon = QLabel()
        self.icon.setPixmap(app_icon().pixmap(18, 18))
        self.title = QLabel(f"{APP_NAME} — v{VERSION} · Qt6")
        self.title.setObjectName("titleText")
        for w in (self.icon, self.title):
            w.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.b_min, self.b_max, self.b_close = _WinBtn("min"), _WinBtn("max"), _WinBtn("close")
        self.b_min.clicked.connect(win.showMinimized)
        self.b_max.clicked.connect(win.toggle_max)
        self.b_close.clicked.connect(win.close)
        lay.addWidget(self.icon)
        lay.addWidget(self.title)
        lay.addStretch()
        for b in (self.b_min, self.b_max, self.b_close):
            lay.addWidget(b)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.childAt(e.position().toPoint()) is None:
            if self.win.maxed:
                return
            h = self.win.windowHandle()
            if h is not None:
                h.startSystemMove()
        elif e.button() == Qt.RightButton:
            self.win.window_menu(e.globalPosition().toPoint())

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.win.toggle_max()


class _Edge(QWidget):
    """5-пиксельная полоска по краю: тянуть размер + рисует 1px рамку."""

    def __init__(self, win, edges):
        super().__init__(win)
        self.win, self.edges = win, edges
        cur = {Qt.LeftEdge: Qt.SizeHorCursor, Qt.RightEdge: Qt.SizeHorCursor,
               Qt.TopEdge: Qt.SizeVerCursor, Qt.BottomEdge: Qt.SizeVerCursor}
        if edges in cur:
            self.setCursor(cur[edges])
        elif edges in (Qt.TopEdge | Qt.LeftEdge, Qt.BottomEdge | Qt.RightEdge):
            self.setCursor(Qt.SizeFDiagCursor)
        else:
            self.setCursor(Qt.SizeBDiagCursor)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and not self.win.maxed and self.win.windowHandle():
            self.win.windowHandle().startSystemResize(self.edges)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setPen(QColor(P["line"]))
        r = self.rect()
        if self.edges & Qt.LeftEdge:
            p.drawLine(0, 0, 0, r.height())
        if self.edges & Qt.RightEdge:
            p.drawLine(r.width() - 1, 0, r.width() - 1, r.height())
        if self.edges & Qt.TopEdge:
            p.drawLine(0, 0, r.width(), 0)
        if self.edges & Qt.BottomEdge:
            p.drawLine(0, r.height() - 1, r.width(), r.height() - 1)


def _card(title):
    f = QFrame()
    f.setObjectName("card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(14, 10, 14, 12)
    lay.setSpacing(8)
    t = QLabel(title.upper())
    t.setObjectName("cardTitle")
    lay.addWidget(t)
    return f, lay


def _lab(text, name=None):
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    return lab


class Tile(QFrame):
    clicked = Signal(QPoint)   # глобальная точка клика (для меню под плиткой)

    def __init__(self, caption):
        super().__init__()
        self.setObjectName("tile")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 8, 14, 10)
        lay.setSpacing(2)
        self.cap = _lab(caption.upper(), "tileCap")
        self.val = _lab("—", "tileVal")
        self.sub = _lab("", "tileSub")
        for w in (self.cap, self.val, self.sub):
            lay.addWidget(w)
        self._color = None

    def set(self, value, sub="", color=None):
        self.val.setText(value)
        self.sub.setText(sub)
        self._color = color
        self.restyle()

    def restyle(self):
        self.val.setStyleSheet(f"color: {P[self._color]};" if self._color else "")

    def make_clickable(self, tip):
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tip)
        self.setProperty("clickable", True)

    def mousePressEvent(self, e):
        if self.property("clickable") and e.button() == Qt.LeftButton:
            self.clicked.emit(self.mapToGlobal(QPoint(0, self.height())))
            return
        super().mousePressEvent(e)

# ───────────────────────── фильтр событий приложения ─────────────────────────


class AppFilter(QObject):
    """DWM-полоса у диалогов до показа + русское меню по правому клику везде."""

    def __init__(self, win):
        super().__init__()
        self.win = win

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.Show and isinstance(obj, QWidget) and obj.isWindow() \
                and not (obj.windowFlags() & Qt.FramelessWindowHint) \
                and obj.windowType() in (Qt.Window, Qt.Dialog, Qt.Tool):
            _dwm_paint(obj)
        elif t == QEvent.ContextMenu and isinstance(obj, QWidget):
            if self.win.context_menu(obj, ev.globalPos(), own=obj.window() is self.win):
                return True
        return False

# ───────────────────────── главное окно ─────────────────────────


class MainWindow(QWidget):
    def __init__(self, cfg, cfg_writable=True):
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint | Qt.WindowSystemMenuHint
                         | Qt.WindowMinMaxButtonsHint)
        self.cfg = cfg
        self.cfg_writable = cfg_writable
        self._saved_dump = json.dumps(cfg, ensure_ascii=False, sort_keys=True)
        self.q = queue.Queue()
        self.worker = Worker(self.q)
        self.adapters = []
        self.last_check = None
        self.maxed = False
        self._normal_geo = None
        self._closing = False
        self.setWindowTitle(f"{APP_NAME} — v{VERSION}")
        self.setWindowIcon(app_icon())
        self.setMinimumSize(900, 600)
        self._loading = True
        self._build()
        self._load_ui_from_cfg()
        self._loading = False
        self.timer = QTimer(self, interval=150, timeout=self._drain)
        self.timer.start()
        self.autosave = QTimer(self, interval=10000, timeout=self.save_if_changed)
        self.autosave.start()
        self._shortcuts()
        if not cfg_writable:
            self.log("⚠ config.json повреждён, и .bak тоже — настройки не будут записываться.")

    # ── построение ──
    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.titlebar = TitleBar(self)
        outer.addWidget(self.titlebar)

        body = QWidget()
        body.setObjectName("root")
        body.setAttribute(Qt.WA_StyledBackground, True)
        bl = QHBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)
        outer.addWidget(body, 1)

        side = QWidget()
        side.setObjectName("side")
        side.setAttribute(Qt.WA_StyledBackground, True)
        side.setFixedWidth(88)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 8, 0, 8)
        sl.setSpacing(4)
        self.side_group = QButtonGroup(self)
        self.side_btns = []
        for i, (key, text) in enumerate((("antenna", "Антенна"), ("settings", "Настройки"),
                                         ("update", "Обновление"))):
            b = SideButton(key, text)
            self.side_group.addButton(b, i)
            self.side_btns.append(b)
            if key == "update":
                sl.addStretch()  # «Обновление с GitHub» — последней кнопкой
            sl.addWidget(b)
        self.side_group.idClicked.connect(self.set_page)
        bl.addWidget(side)

        right = QWidget()
        right.setObjectName("page")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(16, 12, 16, 0)
        rl.setSpacing(10)
        bl.addWidget(right, 1)

        head = QHBoxLayout()
        ico = QLabel()
        ico.setPixmap(app_icon().pixmap(30, 30))
        head.addWidget(ico)
        head.addWidget(_lab(APP_NAME, "h1"))
        head.addStretch()
        self.chip = _lab("● готов", "chip")
        self.btn_theme = QPushButton("☀")
        self.btn_theme.setObjectName("tool")
        self.btn_theme.setToolTip("Тема (Ctrl+T)")
        self.btn_theme.clicked.connect(self.toggle_theme)
        self.btn_more = QPushButton("⋯")
        self.btn_more.setObjectName("tool")
        self.btn_more.setToolTip("Меню")
        self.btn_more.clicked.connect(lambda: self.main_menu().exec(
            self.btn_more.mapToGlobal(QPoint(0, self.btn_more.height()))))
        for w in (self.chip, self.btn_theme, self.btn_more):
            head.addWidget(w)
        rl.addLayout(head)

        tiles = QHBoxLayout()
        tiles.setSpacing(10)
        self.t_adapter, self.t_myip = Tile("Адаптер ▾"), Tile("IP ноутбука сейчас")
        self.t_adapter.make_clickable("Нажми — выбрать адаптер, к которому подключена антенна.\n"
                                      "Поиск и смена IP — только на нём; Wi-Fi с интернетом не трогается")
        self.t_adapter.clicked.connect(lambda pos: self.adapter_menu().exec(pos))
        self.t_ant, self.t_resp = Tile("Антенна"), Tile("Ответ")
        self.tiles = (self.t_adapter, self.t_myip, self.t_ant, self.t_resp)
        for t in self.tiles:
            tiles.addWidget(t, 1)
        rl.addLayout(tiles)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._page_antenna())
        self.stack.addWidget(self._page_settings())
        self.stack.addWidget(self._page_update())
        rl.addWidget(self.stack, 1)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        outer.addWidget(self.progress)

        sb = QWidget()
        sb.setObjectName("statusbar")
        sb.setAttribute(Qt.WA_StyledBackground, True)
        sb.setFixedHeight(28)
        sbl = QHBoxLayout(sb)
        sbl.setContentsMargins(12, 0, 12, 0)
        adm = "администратор" if is_admin() else "без прав администратора"
        self.status_left = _lab(f"v{VERSION} · {adm}", "status")
        self.status = _lab("", "status")
        sbl.addWidget(self.status_left)
        sbl.addStretch()
        sbl.addWidget(self.status)
        outer.addWidget(sb)

        self.edges = []
        for e in (Qt.LeftEdge, Qt.RightEdge, Qt.TopEdge, Qt.BottomEdge,
                  Qt.TopEdge | Qt.LeftEdge, Qt.TopEdge | Qt.RightEdge,
                  Qt.BottomEdge | Qt.LeftEdge, Qt.BottomEdge | Qt.RightEdge):
            self.edges.append(_Edge(self, e))

    def _page_antenna(self):
        page = QWidget()
        page.setObjectName("page")
        lay = QHBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 8)
        lay.setSpacing(12)

        left = QVBoxLayout()
        left.setSpacing(10)
        c, cl = _card("Найденные антенны")
        self.found = QListWidget()
        self.found.setToolTip("Что нашёл поиск на кабеле. Клик — выбрать. Правый клик — меню")
        self.found.currentRowChanged.connect(self.on_found)
        cl.addWidget(self.found, 1)
        self.l_found = _lab("Пока пусто — нажми «🔎 Найти антенну».\nИли впиши адрес антенны ниже.", "hint")
        self.l_found.setWordWrap(True)
        cl.addWidget(self.l_found)
        c.setFixedWidth(300)
        left.addWidget(c, 1)

        c, cl = _card("Параметры")
        g = QGridLayout()
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(6)
        self.e_ant = QLineEdit()
        self.e_ant.setToolTip("Адрес антенны (можно поменять, если сброшена не на заводской)")
        self.e_mask = QLineEdit()
        self.e_my = QLineEdit()
        self.e_my.setToolTip("Адрес ноутбука на время настройки — в той же подсети, что антенна")
        self.btn_auto = QPushButton("авто")
        self.btn_auto.setObjectName("step")
        self.btn_auto.setStyleSheet("min-width: 44px; max-width: 44px;")
        self.btn_auto.setToolTip("Посчитать IP ноутбука по адресу антенны и маске")
        self.btn_auto.clicked.connect(self.auto_my_ip)
        g.addWidget(_lab("Антенна"), 0, 0)
        g.addWidget(self.e_ant, 0, 1, 1, 2)
        g.addWidget(_lab("Маска"), 1, 0)
        g.addWidget(self.e_mask, 1, 1, 1, 2)
        g.addWidget(_lab("Ноутбук"), 2, 0)
        g.addWidget(self.e_my, 2, 1)
        g.addWidget(self.btn_auto, 2, 2)
        cl.addLayout(g)
        c.setFixedWidth(300)
        left.addWidget(c)
        for e in (self.e_ant, self.e_mask, self.e_my):
            e.textEdited.connect(self._params_edited)
        lay.addLayout(left)

        right = QVBoxLayout()
        right.setSpacing(10)
        c, cl = _card("Сетевой адаптер")
        row = QHBoxLayout()
        self.cb_adapter = QComboBox()
        self.cb_adapter.setToolTip("Адаптер, к которому подключена антенна (обычно Ethernet). Правый клик — обновить")
        self.cb_adapter.currentIndexChanged.connect(self.on_adapter)
        self.btn_refresh = QPushButton("🔄 Обновить")
        self.btn_refresh.setToolTip("Перечитать адаптеры (F5)")
        self.btn_refresh.clicked.connect(self.refresh)
        row.addWidget(self.cb_adapter, 1)
        row.addWidget(self.btn_refresh)
        cl.addLayout(row)
        self.l_adapter = _lab("", "hint")
        self.l_adapter.setWordWrap(True)
        cl.addWidget(self.l_adapter)
        right.addWidget(c)

        c, cl = _card("Действия")
        row = QHBoxLayout()
        self.btn_find = QPushButton("🔎 Найти антенну")
        self.btn_find.setObjectName("primary")
        self.btn_find.setToolTip("Поиск антенны на выбранном адаптере: своя подсеть, потом заводские (F7)")
        self.btn_find.clicked.connect(self.search)
        self.btn_set = QPushButton("⚡ Поставить IP")
        self.btn_set.setToolTip("Запомнить текущие настройки адаптера и поставить статический IP (Ctrl+Enter)")
        self.btn_set.clicked.connect(self.set_static)
        self.btn_check = QPushButton("✔ Проверить")
        self.btn_check.setToolTip("Пинг, порты 80/443 и веб антенны (F6)")
        self.btn_check.clicked.connect(self.check)
        self.btn_open = QPushButton("🌐 Открыть веб")
        self.btn_open.setToolTip("Открыть веб-интерфейс антенны в браузере (Ctrl+O)")
        self.btn_open.clicked.connect(self.open_browser)
        self.btn_restore = QPushButton("↩ Вернуть как было")
        self.btn_restore.setObjectName("danger")
        self.btn_restore.setToolTip("Вернуть адаптеру прежние настройки (или DHCP, если снимка нет)")
        self.btn_restore.clicked.connect(self.restore)
        self.btn_stop = QPushButton("⏹ Стоп")
        self.btn_stop.setToolTip("Остановить поиск / проверку (Esc). Если поиск менял адрес — он вернёт сеть сам")
        self.btn_stop.clicked.connect(self.ask_stop)
        self.btn_stop.setEnabled(False)
        bg = QGridLayout()
        bg.setHorizontalSpacing(8)
        bg.setVerticalSpacing(8)
        for i, b in enumerate((self.btn_find, self.btn_set, self.btn_check, self.btn_open, self.btn_restore,
                               self.btn_stop)):
            bg.addWidget(b, i // 3, i % 3)
        cl.addLayout(bg)
        res = QGridLayout()
        res.setHorizontalSpacing(8)
        self.res_rows = {}
        for i, (k, t) in enumerate((("ping", "Пинг"), ("p80", "Порт 80 (http)"),
                                    ("p443", "Порт 443 (https)"), ("http", "Веб-страница"))):
            d, lab, val = Dot(), _lab(t), _lab("—", "hint")
            res.addWidget(d, i // 2, (i % 2) * 3)
            res.addWidget(lab, i // 2, (i % 2) * 3 + 1)
            res.addWidget(val, i // 2, (i % 2) * 3 + 2)
            self.res_rows[k] = (d, val)
        res.setColumnStretch(2, 1)
        res.setColumnStretch(5, 1)
        cl.addLayout(res)
        right.addWidget(c)

        c, cl = _card("Журнал")
        self.logv = QPlainTextEdit()
        self.logv.setObjectName("log")
        self.logv.setReadOnly(True)
        self.logv.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.logv.setMaximumBlockCount(3000)
        cl.addWidget(self.logv)
        right.addWidget(c, 1)
        lay.addLayout(right, 1)
        return page

    def _page_settings(self):
        page = QWidget()
        page.setObjectName("page")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 8)
        lay.setSpacing(10)
        c, cl = _card("Проверка")
        g = QGridLayout()
        g.setHorizontalSpacing(12)
        self.f_timeout = _IntField(1, 15, 3, "с")
        self.f_timeout.setToolTip("Сколько ждать ответа антенны")
        self.f_retries = _IntField(0, 30, 6, "раз")
        self.f_retries.setSpecialValueText("не ждать")
        self.f_retries.setToolTip("После смены IP Windows нужно несколько секунд — столько раз повторить проверку")
        self.tg_auto = Toggle()
        self.tg_admin = Toggle()
        self.e_subnets = QLineEdit()
        self.e_subnets.setMinimumWidth(600)
        self.e_subnets.setToolTip("Где искать антенну, если в своей подсети пусто. Через запятую, по /24")
        self.e_subnets.textEdited.connect(self._sync_cfg)
        rows = (("Подсети для поиска", self.e_subnets), ("Таймаут проверки", self.f_timeout), ("Повторов после смены IP", self.f_retries),
                ("Проверять антенну сразу после смены IP", self.tg_auto),
                ("Просить права администратора при запуске", self.tg_admin))
        for i, (t, w) in enumerate(rows):
            g.addWidget(_lab(t), i, 0)
            g.addWidget(w, i, 1, Qt.AlignLeft)
        g.setColumnStretch(2, 1)
        cl.addLayout(g)
        lay.addWidget(c)

        c, cl = _card("Сохранённые настройки адаптеров")
        self.l_saved = _lab("", "hint")
        self.l_saved.setWordWrap(True)
        self.l_saved.setTextInteractionFlags(Qt.TextSelectableByMouse)
        cl.addWidget(self.l_saved)
        btn = QPushButton("🗑 Забыть снимки")
        btn.setToolTip("Удалить запомненные прежние настройки (сеть не меняется)")
        btn.clicked.connect(self.forget_snapshots)
        row = QHBoxLayout()
        row.addWidget(btn)
        row.addStretch()
        cl.addLayout(row)
        lay.addWidget(c)

        c, cl = _card("Оформление")
        row = QHBoxLayout()
        b1 = QPushButton("☾ Тёмная")
        b1.clicked.connect(lambda: self.set_theme("dark"))
        b2 = QPushButton("☀ Светлая")
        b2.clicked.connect(lambda: self.set_theme("light"))
        b3 = QPushButton("💾 Сохранить")
        b3.setToolTip("Ctrl+S")
        b3.clicked.connect(self.save_now)
        for b in (b1, b2, b3):
            row.addWidget(b)
        row.addStretch()
        cl.addLayout(row)
        lay.addWidget(c)
        lay.addStretch()
        for w in (self.f_timeout, self.f_retries):
            w.valueChanged.connect(self._sync_cfg)
        for w in (self.tg_auto, self.tg_admin):
            w.toggled.connect(self._sync_cfg)
        return page

    def _page_update(self):
        """Вкладка «Обновление» — общий модуль gh_update (как в SmartMon)."""
        from app import gh_update, gh_update_qt
        gh_update_qt.set_colors(lambda: {"accent": P["accent"], "text": P["text"], "dim": P["muted"],
                                         "panel": P["panel"], "border": P["line"]})
        target = gh_update.UpdateTarget(
            owner=GITHUB_REPO.split("/")[0], repo=GITHUB_REPO.split("/")[1], name="antenna_setup",
            current=VERSION, app_dir=str(APP_ROOT), main_file="antenna_setup.pyw",
            changelog="README.md", version_files=("VERSION",), where="Обновление")

        def cfg_get():
            c = self.cfg
            return {"token": c.get("upd_token") or "", "auto": bool(c.get("upd_auto", True)),
                    "branch": c.get("upd_branch") or GITHUB_BRANCH, "every_h": int(c.get("upd_every_h") or 12)}

        def cfg_set(d):
            self.cfg["upd_token"] = d.get("token") or ""
            self.cfg["upd_auto"] = bool(d.get("auto"))
            self.cfg["upd_branch"] = d.get("branch") or GITHUB_BRANCH
            self.cfg["upd_every_h"] = int(d.get("every_h") or 12)
            self.save_if_changed()

        self.update_page = gh_update_qt.UpdatePage(target, cfg_get, cfg_set, on_quit=self._quit_for_update,
                                                   log=lambda *a: self.q.put(("log", " ".join(str(x) for x in a))))
        self.update_page.box.setFixedWidth(450)   # под шрифт 10pt — кнопки не обрезаются
        self.update_page.box.available.connect(
            lambda v: self.set_status(f"⬆ есть новая версия {v} — вкладка «Обновление»"))
        return self.update_page

    def _quit_for_update(self):
        """Обновлено, новая копия уже запущена — эта закрывается полностью."""
        self.save_now()
        self._force_close = True
        self.close()
        QApplication.instance().quit()

    def update_busy(self):
        return bool(getattr(getattr(self, "update_page", None), "box", None) and self.update_page.box._busy)

    def _shortcuts(self):
        for key, fn in (("F5", self.refresh), ("F6", self.check), ("F7", self.search), ("Ctrl+O", self.open_browser),
                        ("Ctrl+Return", self.set_static), ("Ctrl+S", self.save_now),
                        ("Ctrl+T", self.toggle_theme), ("Esc", self.ask_stop)):
            QShortcut(QKeySequence(key), self, fn)

    # ── окно: рамка, разворот ──
    def resizeEvent(self, e):
        super().resizeEvent(e)
        w, h, b = self.width(), self.height(), 5
        geo = {Qt.LeftEdge: (0, b, b, h - 2 * b), Qt.RightEdge: (w - b, b, b, h - 2 * b),
               Qt.TopEdge: (b, 0, w - 2 * b, b), Qt.BottomEdge: (b, h - b, w - 2 * b, b),
               Qt.TopEdge | Qt.LeftEdge: (0, 0, b, b), Qt.TopEdge | Qt.RightEdge: (w - b, 0, b, b),
               Qt.BottomEdge | Qt.LeftEdge: (0, h - b, b, b),
               Qt.BottomEdge | Qt.RightEdge: (w - b, h - b, b, b)}
        for edge in self.edges:
            edge.setGeometry(*geo[edge.edges])
            edge.setVisible(not self.maxed)
            edge.raise_()

    def toggle_max(self):
        if self.maxed:
            self.maxed = False
            if self._normal_geo:
                self.setGeometry(self._normal_geo)
        else:
            self._normal_geo = self.geometry()
            self.maxed = True
            self.setGeometry(self.screen().availableGeometry())
        self.titlebar.b_max.maxed = self.maxed
        self.titlebar.b_max.update()
        self._relayout_edges()

    def _relayout_edges(self):
        for edge in self.edges:
            edge.setVisible(not self.maxed)
            edge.raise_()

    def changeEvent(self, e):
        if e.type() == QEvent.WindowStateChange and self.windowState() & Qt.WindowMaximized:
            # Win+↑: разворачиваем сами, на рабочую область (не закрывая панель задач)
            QTimer.singleShot(0, self._native_max_to_ours)
        super().changeEvent(e)

    def _native_max_to_ours(self):
        self.setWindowState(Qt.WindowNoState)
        if not self.maxed:
            self.toggle_max()

    def window_menu(self, pos):
        m = QMenu(self)
        m.addAction("Свернуть", self.showMinimized)
        m.addAction("Вернуть" if self.maxed else "Развернуть", self.toggle_max)
        m.addSeparator()
        m.addAction("Закрыть", self.close)
        m.exec(pos)

    # ── меню ──
    def main_menu(self):
        m = QMenu(self)
        m.addAction("🔄 Обновить адаптеры\tF5", self.refresh)
        m.addAction("🔎 Найти антенну\tF7", self.search).setEnabled(not self.worker.busy())
        m.addAction("⬇ Обновить программу с GitHub…", self.update_from_menu)
        m.addAction("💾 Сохранить\tCtrl+S", self.save_now)
        m.addAction("🎨 Тема\tCtrl+T", self.toggle_theme)
        m.addSeparator()
        m.addAction("📂 Папка программы", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(APP_ROOT))))
        m.addAction("♻ Перезапуск", self.restart)
        a = m.addAction("⏹ Стоп\tEsc", self.ask_stop)
        a.setEnabled(self.worker.busy())
        return m

    def context_menu(self, w, pos, own=True):
        """Одно меню на всё приложение. True — показали своё."""
        m = QMenu(w.window())
        if isinstance(w.parent(), QPlainTextEdit) or isinstance(w.parent(), QTextEdit):
            w = w.parent()
        if isinstance(w, QLineEdit) and isinstance(w.parent(), QComboBox):
            w = w.parent()
        if isinstance(w, (QPlainTextEdit, QTextEdit)):
            ro = w.isReadOnly()
            has = w.textCursor().hasSelection()
            if not ro:
                m.addAction("Отменить", w.undo).setEnabled(w.document().isUndoAvailable())
                m.addAction("Вырезать", w.cut).setEnabled(has)
            m.addAction("Копировать", w.copy).setEnabled(has)
            m.addAction("Копировать всё", lambda: QApplication.clipboard().setText(w.toPlainText()))
            if not ro:
                m.addAction("Вставить", w.paste)
            m.addAction("Выделить всё", w.selectAll)
            if w is self.logv:
                m.addSeparator()
                m.addAction("Сохранить в файл…", self.save_log)
                m.addAction("Очистить", w.clear)
        elif isinstance(w, QLineEdit):
            has = w.hasSelectedText()
            pw = w.echoMode() != QLineEdit.Normal
            ro = w.isReadOnly()
            m.addAction("Отменить", w.undo).setEnabled(w.isUndoAvailable() and not ro)
            m.addAction("Вырезать", w.cut).setEnabled(has and not ro and not pw)
            m.addAction("Копировать", w.copy).setEnabled(has and not pw)
            m.addAction("Вставить", w.paste).setEnabled(not ro)
            m.addAction("Удалить", w.del_).setEnabled(has and not ro)
            m.addSeparator()
            m.addAction("Выделить всё", w.selectAll)
        elif not own:
            return False
        elif w is self.found or w.parent() is self.found:
            it = self.found.itemAt(self.found.viewport().mapFromGlobal(pos))
            if it is not None:
                self.found.setCurrentItem(it)
            m.addAction("🔎 Найти антенну\tF7", self.search).setEnabled(not self.worker.busy())
            m.addSeparator()
            m.addAction("🌐 Открыть веб", self.open_browser).setEnabled(it is not None)
            m.addAction("Копировать адрес", lambda: QApplication.clipboard().setText(self.e_ant.text())) \
                .setEnabled(it is not None)
            m.addAction("Очистить список", self.clear_found).setEnabled(self.found.count() > 0)
        elif w is self.t_adapter or w.parent() is self.t_adapter:
            m = self.adapter_menu()
        elif w is self.cb_adapter:
            m.addAction("🔄 Обновить список\tF5", self.refresh)
            m.addAction("Копировать имя", lambda: QApplication.clipboard().setText(self.cb_adapter.currentText()))
        elif isinstance(w, (QPushButton, QAbstractButton, QProgressBar)) and w is not self.btn_more:
            return True  # у кнопок своего меню нет — фон не показываем поверх
        else:
            m = self.main_menu()
        m.exec(pos)
        return True

    # ── конфиг ──
    def _load_ui_from_cfg(self):
        c = self.cfg
        self.f_timeout.setValue(c.get("check_timeout", 3))
        self.f_retries.setValue(c.get("check_retries", 6))
        self.tg_auto.setChecked(bool(c.get("auto_check", True)))
        self.tg_admin.setChecked(bool(c.get("ask_admin", True)))
        c.pop("preset", None)
        c.pop("custom_presets", None)
        if c.get("search_subnets") in OLD_SUBNETS:
            c["search_subnets"] = SEARCH_SUBNETS
        self.e_subnets.setText(c.get("search_subnets") or SEARCH_SUBNETS)
        self.e_subnets.setCursorPosition(0)
        self._found_from = ""
        if c.get("antenna_ip"):
            self.e_ant.setText(c["antenna_ip"])
            self.e_mask.setText(c.get("mask") or "255.255.255.0")
            self.e_my.setText(c.get("my_ip", ""))
        page = int(c.get("page", 0) or 0)
        self.set_page(page if 0 <= page < self.stack.count() else 0)
        self.update_saved_label()
        self.update_tiles()
        g = c.get("geometry")
        if g:
            try:
                x, y, w, h, mx = g
                scr = QApplication.screenAt(QPoint(x + 40, y + 10))
                if scr is not None:
                    self.setGeometry(x, y, max(w, 900), max(h, 600))
                else:
                    self.resize(max(w, 900), max(h, 600))
                if mx:
                    QTimer.singleShot(0, self.toggle_max)
            except Exception:
                self.resize(1080, 720)
        else:
            self.resize(1080, 720)

    def _sync_cfg(self, *_):
        if getattr(self, "_loading", False):
            return
        c = self.cfg
        c["check_timeout"] = self.f_timeout.value()
        c["check_retries"] = self.f_retries.value()
        c["auto_check"] = self.tg_auto.isChecked()
        c["ask_admin"] = self.tg_admin.isChecked()
        c["search_subnets"] = self.e_subnets.text().strip() or SEARCH_SUBNETS
        c["antenna_ip"] = self.e_ant.text().strip()
        c["mask"] = self.e_mask.text().strip()
        c["my_ip"] = self.e_my.text().strip()
        c["adapter"] = self.cb_adapter.currentData() or c.get("adapter", "")
        c["page"] = self.stack.currentIndex()
        geo = self._normal_geo if (self.maxed and self._normal_geo) else self.geometry()
        c["geometry"] = [geo.x(), geo.y(), geo.width(), geo.height(), self.maxed]

    def save_if_changed(self):
        self._sync_cfg()
        dump = json.dumps(self.cfg, ensure_ascii=False, sort_keys=True)
        if dump != self._saved_dump:
            self._write_cfg(dump)

    def save_now(self):
        self._sync_cfg()
        if self._write_cfg(json.dumps(self.cfg, ensure_ascii=False, sort_keys=True)):
            self.set_status("💾 настройки сохранены")

    def _write_cfg(self, dump):
        if not self.cfg_writable:
            return False
        try:
            save_config(self.cfg)
            self._saved_dump = dump
            return True
        except Exception as e:
            self.log(f"✗ не удалось сохранить config.json: {e}")
            return False

    # ── тема ──
    def set_theme(self, name):
        self.cfg["theme"] = name
        apply_theme(QApplication.instance(), name)
        self.btn_theme.setText("☀" if name == "dark" else "☾")
        for t in self.tiles:
            t.restyle()
        self.recolor_log()
        for w in self.findChildren(QWidget):
            w.update()
        self.titlebar.update()
        for e in self.edges:
            e.update()
        self.set_chip(*self._chip_state)

    def toggle_theme(self):
        self.set_theme("light" if self.cfg.get("theme") == "dark" else "dark")

    # ── страницы, состояние, лог ──
    def set_page(self, i):
        self.stack.setCurrentIndex(i)
        self.side_btns[i].setChecked(True)

    _chip_state = ("● готов", "muted")

    def set_chip(self, text, color="muted"):
        self._chip_state = (text, color)
        self.chip.setText(text)
        self.chip.setStyleSheet(f"color: {P.get(color, color)};")

    def set_status(self, text):
        self.status.setText(text)

    def _line_color(self, text):
        if text.startswith(("✗", "⛔")):
            return P["err"]
        if text.startswith("⚠"):
            return P["warn"]
        if text.startswith(("✓", "✅")):
            return P["ok"]
        return P["log_fg"]

    def log(self, text):
        line = f"{time.strftime('%H:%M:%S')}  {text}"
        self._log_lines = getattr(self, "_log_lines", [])
        self._log_lines.append(text)
        self._log_lines = self._log_lines[-3000:]
        self._append_log(line, text)
        self.set_status(text)

    def _append_log(self, line, text):
        sb = self.logv.verticalScrollBar()
        at_bottom = sb.value() >= sb.maximum() - 2
        cur = QTextCursor(self.logv.document())
        cur.movePosition(QTextCursor.End)
        fmt = cur.charFormat()
        fmt.setForeground(QColor(self._line_color(text)))
        if not self.logv.document().isEmpty():
            cur.insertBlock()
        cur.insertText(line, fmt)
        if at_bottom:
            sb.setValue(sb.maximum())

    def recolor_log(self):
        doc = self.logv.document()
        b = doc.firstBlock()
        while b.isValid():
            t = b.text()
            body = t[10:] if len(t) > 10 else t
            cur = QTextCursor(b)
            cur.select(QTextCursor.LineUnderCursor)
            fmt = cur.charFormat()
            fmt.setForeground(QColor(self._line_color(body)))
            cur.setCharFormat(fmt)
            b = b.next()

    def save_log(self):
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить журнал",
                                              str(APP_ROOT / f"antenna_log_{time.strftime('%Y%m%d_%H%M')}.txt"),
                                              "Текст (*.txt)")
        if path:
            try:
                atomic_write_text(path, self.logv.toPlainText())
                self.log(f"✓ журнал сохранён: {path}")
            except Exception as e:
                self.log(f"✗ не сохранил журнал: {e}")

    def _drain(self):
        try:
            while True:
                item = self.q.get_nowait()
                if item is _DONE:
                    self.work_done()
                elif isinstance(item, tuple) and item[0] == "log":
                    self.log(item[1])
                elif callable(item):
                    item()
        except queue.Empty:
            pass

    def run_job(self, name, fn, blocking_close=False):
        if self.worker.busy():
            self.log(f"⚠ уже идёт: {self.worker.name}")
            return False
        self.worker.start(name, fn, blocking_close)
        self.set_chip(f"● работаю: {name}", "accent")
        self.progress.setRange(0, 0)
        self.set_busy(True)
        return True

    def work_done(self):
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.set_busy(False)
        if self._chip_state[1] == "accent":
            self.set_chip("● готов", "muted")
        if self._closing:
            self._closing = False
            self.close()

    def set_busy(self, busy):
        admin = is_admin()
        self.btn_stop.setEnabled(busy)
        self.btn_restore.setEnabled(admin)      # и во время поиска: остановит и вернёт сеть
        self.btn_set.setEnabled(not busy and admin)
        for b in (self.btn_set, self.btn_restore):
            b.setToolTip(b.toolTip() if admin else "Нужны права администратора (перезапусти программу)")
        for b in (self.btn_find, self.btn_check, self.btn_refresh):
            b.setEnabled(not busy)

    def ask_stop(self):
        if not self.worker.busy():
            return
        if self.worker.blocking_close:
            self.log("⚠ установку обновления не останавливаю — дождись конца.")
            return
        if QMessageBox.question(self, "Стоп", f"Остановить «{self.worker.name}»?") == QMessageBox.Yes:
            self.worker.stop_flag.set()
            self.log("⏹ останавливаю…")

    # ── поиск ──
    def search(self):
        """Сначала перечитать адаптеры (адрес мог прийти после запуска), потом искать."""
        if self.worker.busy():
            return
        if not IS_WIN:
            self._search_now()
            return

        def job(w):
            w.log("⏳ перечитываю адаптеры…")
            data = list_adapters()
            w.ui(lambda: self.set_adapters(data))

        def start():
            if self.worker.busy():
                QTimer.singleShot(200, start)
            else:
                self._drain()          # свежие адаптеры из очереди — до поиска
                self._search_now()
        if self.run_job("адаптеры", job):
            QTimer.singleShot(300, start)

    def _search_now(self):
        if self.worker.busy():
            return
        a = self.adapter()
        if not a:
            QMessageBox.warning(self, "Поиск", "Выбери сетевой адаптер, к которому подключена антенна (F5 — обновить список).")
            return
        if a["Wifi"] and QMessageBox.question(
                self, "Wi-Fi", f"«{a['Name']}» — это Wi-Fi. Антенну ищут на кабеле. Всё равно искать?") \
                != QMessageBox.Yes:
            return
        nets = parse_subnets(self.e_subnets.text())
        name, cur, prefix = a["Name"], a.get("IP") or "", int(a.get("Prefix") or 24)
        admin = is_admin()
        saved = dict(self.cfg.get("saved_net") or {})
        mask = "255.255.255.0"

        hints = [x for x in (a.get("Gw"), a.get("DhcpSrv")) if x and x != cur and x != "255.255.255.255"]

        def probe_net(w, net, me, extra=()):
            """Порты 80/443 по всей /24, потом кто ответил на ARP, потом подсказки (пинг)."""
            found = scan_subnet(net, {me}, me, stopped=w.stopped)
            if not found and IS_WIN:
                found = {ip: [] for ip in neighbors(name, net, {me})}
            for ip in extra:
                if ip not in found and ipaddress.IPv4Address(ip) in net and ping(ip, 1.0):
                    found[ip] = []
            return found

        dhcp = (a.get("Dhcp") or "").lower() == "enabled"
        others = [x.get("IP") for x in self.adapters if x["Name"] != name and x.get("IP")
                  and not x["IP"].startswith("169.254.")]
        # свой временный адрес поиска (.247/.246, статический) — не «своя сеть»: антенна его не выдавала
        temp = bool(cur) and not dhcp and cur.rsplit(".", 1)[-1] in (str(SEARCH_HOST), str(SEARCH_HOST - 1))
        usable = bool(cur and not cur.startswith("169.254.") and not temp)
        heard = {}

        def job(w):
            """Этап 1 — только своя сеть, сеть адаптера НЕ меняется."""
            dh = "DHCP" if dhcp else "статический"
            if temp:
                w.log(f"ℹ {cur} — временный адрес, который ставил сам поиск (не от антенны); свою сеть "
                      "не проверяю. «↩ Вернуть как было» вернёт прежние настройки.")
            if cur.startswith("169.254."):
                w.log(f"ℹ у «{name}» автоадрес Windows {cur}: в кабеле никто не раздаёт адреса (DHCP) — "
                      "это не полученный адрес")
            w.log(f"ℹ «{name}»: {cur or 'нет адреса'}{'/' + str(prefix) if cur else ''}, {dh}, "
                  f"шлюз {a.get('Gw') or '—'}, DHCP-сервер {a.get('DhcpSrv') or '—'}")
            if usable:
                own = ipaddress.IPv4Network(f"{cur}/{max(prefix, 24)}", strict=False)
                labels = {}
                for ip, what in ((a.get("Gw"), "шлюз"), (a.get("DhcpSrv"), "DHCP-сервер — раздал ноутбуку IP")):
                    if not ip or ip == cur or ip == "255.255.255.255":
                        continue
                    r = check_antenna(ip, 2.0)
                    labels[ip] = (labels.get(ip, "") + ", " if ip in labels else "") + what
                    w.log(f"{'✓' if r['alive'] else '⚠'} {what} {ip}: пинг {'да' if r['ping'] else 'нет'}, "
                          f"80 {'да' if r['p80'] else 'нет'}, 443 {'да' if r['p443'] else 'нет'}")
                w.log(f"🔎 ищу во всей своей сети {own} (сеть не меняю)…")
                found = scan_subnet(own, {cur}, cur, stopped=w.stopped)
                if IS_WIN:
                    for ip in neighbors(name, own, {cur}):
                        found.setdefault(ip, [])
                for ip in labels:                 # шлюз и DHCP-сервер показываем всегда
                    if ipaddress.IPv4Address(ip) in own:
                        found.setdefault(ip, [])
                found = dict(sorted(found.items(), key=lambda kv: (kv[0] not in labels, ipaddress.IPv4Address(kv[0]))))
                if found:
                    m = str(own.netmask)
                    w.ui(lambda: self.show_found(found, m, cur, str(own), labels))
                    return
                if dhcp:
                    w.log("⚠ адрес получен по DHCP, но в сети никто не отвечает — проверь подключение антенны.")
                    return
            if w.stopped():
                return
            if not admin:
                w.log("⚠ в своей сети пусто. Чтобы слушать кабель и искать в других подсетях, нужны права "
                      "администратора (⋯ → Перезапуск).")
                return
            if cur:
                w.log("👂 слушаю кабель 12 с — антенна в любой подсети что-то шлёт…")
                heard.update(listen_wire(cur, 12, w.stopped))
                self._log_heard(w, heard)
            if w.stopped():
                return
            w.ui(lambda: self._offer_other_subnets(name, cur, dict(heard), job2))

        def job2(w):
            """Этап 2 — только с согласия: временно ставить адреса в других подсетях."""
            if name not in saved:
                snap = snapshot_adapter(name)
                saved[name] = snap
                w.ui(lambda: self._store_snapshot(name, snap))
                w.log("✓ запомнил прежние настройки адаптера")
            order = []
            for ip in heard:           # подсети услышанных адресов — первыми
                n = ipaddress.IPv4Network(f"{ip}/24", strict=False)
                if n not in order:
                    order.append(n)
            order += [n for n in nets if n not in order]
            busy = [n for n in order if any(ipaddress.IPv4Address(x) in n for x in others)]
            if busy:
                w.log("ℹ пропускаю подсети других адаптеров (Wi-Fi/интернет не трогаю): "
                      + ", ".join(str(n) for n in busy))
                order = [n for n in order if n not in busy]
            if usable:
                order = [n for n in order if ipaddress.IPv4Address(cur) not in n]
            listened = bool(cur)
            try:
                for net in order:
                    if w.stopped():
                        break
                    me = str(net.network_address + SEARCH_HOST)
                    if me in heard:
                        me = str(net.network_address + SEARCH_HOST - 1)
                    ok, out = run_cmd(["netsh", "interface", "ipv4", "set", "address", f"name={name}",
                                       "static", me, mask])
                    if not ok:
                        w.log(f"✗ netsh: {out or 'ошибка'}")
                        break
                    w.log(f"🔎 ищу в {net} (ноутбук временно {me})…")
                    st = wait_ip_ready(me, 15, w.stopped)
                    if st == "dup":
                        w.log(f"⚠ адрес {me} кто-то уже занял — значит, в {net} есть устройство")
                    elif st == "timeout":
                        w.log("⚠ Windows долго не готовит адрес — ищу всё равно")
                    if not listened:
                        listened = True
                        w.log("👂 слушаю кабель 12 с…")
                        heard.update(listen_wire(me, 12, w.stopped))
                        self._log_heard(w, heard)
                        new = [ipaddress.IPv4Network(f"{ip}/24", strict=False) for ip in heard]
                        if any(n != net for n in new):
                            for n in reversed(new):
                                if n in order and order.index(n) > order.index(net):
                                    order.remove(n)
                                    order.insert(order.index(net) + 1, n)
                    found = probe_net(w, net, me, [ip for ip in list(heard) + hints
                                                   if ipaddress.IPv4Address(ip) in net])
                    for ip in heard:   # слышен в кабеле, но на порты не ответил — всё равно показать
                        if ipaddress.IPv4Address(ip) in net and ip not in found:
                            found[ip] = []
                    if found:
                        w.ui(lambda f=found, m=me, n=str(net), h=dict(heard): self.show_found(f, mask, m, n, h))
                        w.log(f"ℹ ноутбук оставлен на {me}. Вернуть сеть — «↩ Вернуть как было».")
                        w.ui(self.refresh_quiet)
                        return
            except Exception as e:  # сеть всё равно вернуть
                w.log(f"✗ поиск: {e}")
            if heard:
                w.log("ℹ в кабеле слышны: " + ", ".join(heard) + " — впиши адрес вручную в «Антенна» "
                      "и нажми «авто», затем «⚡ Поставить IP».")
                w.ui(lambda h=dict(heard): self.show_found({ip: [] for ip in h}, mask, "", "кабеле (на порты не ответили)", h))
            w.log("⏹ поиск остановлен" if w.stopped() else
                  ("✗ антенна не ответила ни в одной подсети. Проверь кабель и PoE-блок (антенна грузится "
                   "до минуты), подключение в порт LAN/PoE."))
            snap = saved.get(name) or {"dhcp": True}
            for c in restore_commands(name, snap):
                ok, out = run_cmd(c)
                if not ok:
                    w.log(f"✗ не вернул сеть: {out or 'ошибка'} — нажми «↩ Вернуть как было»")
                    return
            w.log("✓ сеть адаптера возвращена как была")
            w.ui(lambda: self._forget(name))
            w.ui(self.refresh_quiet)
        self.run_job("поиск антенны", job)

    def _offer_other_subnets(self, name, cur, heard, job2):
        """После этапа 1: спросить, можно ли временно менять сеть адаптера."""
        def ask():
            if self.worker.busy():
                QTimer.singleShot(300, ask)
                return
            hint = ("\n\nВ кабеле слышны: " + ", ".join(heard) + " — начну с их подсетей.") if heard else ""
            if cur.rsplit(".", 1)[-1] in (str(SEARCH_HOST), str(SEARCH_HOST - 1)):
                why = (f"{cur} — временный адрес, оставшийся от прошлого поиска, а не адрес от антенны. "
                       "На кабеле никто не раздаёт адреса — у антенны свой постоянный адрес.")
            elif cur.startswith("169.254."):
                why = (f"У «{name}» автоадрес Windows {cur} — так бывает, когда в кабеле никто не раздаёт "
                       "адреса (DHCP). Значит, у антенны свой постоянный адрес в другой подсети.")
            elif cur:
                why = f"В своей сети ({cur}) антенну не нашёл."
            else:
                why = f"У «{name}» нет IPv4-адреса."
            if QMessageBox.question(self, "Поиск", f"{why}\n\nПеребрать другие подсети? Адрес «{name}» "
                                    f"будет временно меняться; не найду — верну как было.{hint}") \
                    == QMessageBox.Yes:
                self.run_job("поиск в других подсетях", job2)
            else:
                self.log("ℹ другие подсети не перебираю. Адрес антенны можно вписать вручную.")
        ask()

    def _log_heard(self, w, heard):
        if heard:
            w.log("✓ в кабеле слышны: " + ", ".join(f"{ip}{' (' + d + ')' if d else ''}" for ip, d in heard.items()))
        else:
            w.log("ℹ в кабеле тихо (или Windows не дала слушать)")

    def show_found(self, found, mask, my_ip, where="", heard=None):
        self.found.blockSignals(True)
        self.found.clear()
        names = {80: "http", 443: "https"}
        for ip, ports in found.items():
            what = ", ".join(names.get(p, str(p)) for p in ports) or "отвечает, веб закрыт"
            if heard and heard.get(ip):
                what += " · " + heard[ip]
            it = QListWidgetItem(f"{ip}\n{what}")
            it.setData(Qt.UserRole, ip)
            self.found.addItem(it)
        self.found.blockSignals(False)
        self.l_found.setVisible(not found)
        self._found_from = where
        self.e_mask.setText(mask)
        if my_ip:
            self.e_my.setText(my_ip)
        self.found.setCurrentRow(0)
        if not my_ip:
            self.auto_my_ip()
        self.log(f"✓ найдено в {where}: " + ", ".join(found) if found else "✗ ничего не найдено")
        self.set_chip(f"● найдено: {len(found)}", "ok")

    def on_found(self, row):
        it = self.found.item(row) if row >= 0 else None
        if it is None:
            return
        self.e_ant.setText(it.data(Qt.UserRole))
        self.last_check = None
        self._params_edited()

    def clear_found(self):
        self.found.clear()
        self.l_found.setVisible(True)

    def auto_my_ip(self):
        try:
            self.e_my.setText(host_ip_for(self.e_ant.text().strip(), self.e_mask.text().strip()))
        except ValueError:
            pass
        self._params_edited()

    def _params_edited(self, *_):
        err = validate(self.e_ant.text().strip(), self.e_mask.text().strip(), self.e_my.text().strip())
        bad = f"border-color: {P['err']};"
        self.e_my.setStyleSheet(bad if err else "")
        self.e_my.setToolTip(err or "Адрес ноутбука на время настройки — в той же подсети, что антенна")
        self.update_tiles()

    # ── адаптеры ──
    def refresh(self):
        if not IS_WIN:
            self.log("⚠ адаптеры читаются только в Windows.")
            return

        def job(w):
            w.log("⏳ читаю сетевые адаптеры…")
            data = list_adapters()
            w.ui(lambda: self.set_adapters(data))
        self.run_job("адаптеры", job)

    def set_adapters(self, data):
        want = self.cb_adapter.currentData() or self.cfg.get("adapter", "")
        self.adapters = data
        self.cb_adapter.blockSignals(True)
        self.cb_adapter.clear()
        for a in data:
            state = "подключён" if a.get("Status") == "Up" else "нет кабеля" if a.get("Status") == "Disconnected" \
                else (a.get("Status") or "?").lower()
            kind = "Wi-Fi" if a["Wifi"] else "кабель"
            self.cb_adapter.addItem(f"{a['Name']}  ·  {kind}, {state}", a["Name"])
        self.cb_adapter.blockSignals(False)
        idx = self.cb_adapter.findData(want)
        self.cb_adapter.setCurrentIndex(idx if idx >= 0 else 0)
        self.on_adapter()
        self.log(f"✓ адаптеров: {len(data)}" if data else "⚠ физических адаптеров не найдено")

    def adapter_menu(self):
        m = QMenu(self)
        cur = self.cb_adapter.currentData()
        for i in range(self.cb_adapter.count()):
            a = m.addAction(self.cb_adapter.itemText(i))
            a.setCheckable(True)
            a.setChecked(self.cb_adapter.itemData(i) == cur)
            a.triggered.connect(lambda _=False, i=i: self.cb_adapter.setCurrentIndex(i))
        if not self.cb_adapter.count():
            m.addAction("адаптеры ещё не прочитаны").setEnabled(False)
        m.addSeparator()
        m.addAction("🔄 Обновить список\tF5", self.refresh)
        return m

    def adapter(self):
        name = self.cb_adapter.currentData()
        return next((a for a in self.adapters if a["Name"] == name), None)

    def on_adapter(self, *_):
        a = self.adapter()
        if a:
            dh = "DHCP" if a.get("Dhcp", "").lower() == "enabled" else "статический"
            apipa = (a.get("IP") or "").startswith("169.254.")
            if apipa:
                dh += " — автоадрес Windows, DHCP не ответил"
            self.l_adapter.setText(f"{a.get('Desc', '')}\nСейчас: {a.get('IP') or 'нет адреса'}"
                                   f"{'/' + str(a['Prefix']) if a.get('IP') else ''}, {dh}"
                                   f"{', шлюз ' + a['Gw'] if a.get('Gw') else ''}"
                                   f"{', DHCP-сервер ' + a['DhcpSrv'] if a.get('DhcpSrv') else ''}")
        else:
            self.l_adapter.setText("")
        self.update_tiles()

    def update_tiles(self):
        a = self.adapter()
        if a:
            up = a.get("Status") == "Up"
            self.t_adapter.set(a["Name"], ("Wi-Fi" if a["Wifi"] else "кабель") + (", подключён" if up else ", нет связи")
                               + " · нажми — сменить", "ok" if up else "warn")
            ip = a.get("IP") or "нет"
            in_net = False
            try:
                net = ipaddress.IPv4Network(f"{self.e_ant.text().strip()}/{self.e_mask.text().strip()}", strict=False)
                in_net = bool(a.get("IP")) and ipaddress.IPv4Address(a["IP"]) in net
            except ValueError:
                pass
            self.t_myip.set(ip, "в подсети антенны" if in_net else "не в подсети антенны", "ok" if in_net else "warn")
        else:
            self.t_adapter.set("—", "нажми или F5 — прочитать адаптеры")
            self.t_myip.set("—", "")
        ant = self.e_ant.text().strip()
        self.t_ant.set(ant or "—", "найдена поиском" if ant and self.found.count() and
                       any(self.found.item(i).data(Qt.UserRole) == ant for i in range(self.found.count()))
                       else ("введена вручную" if ant else "F7 — найти"))
        r = self.last_check
        if r is None:
            self.t_resp.set("—", "F6 — проверить")
        elif r["alive"]:
            self.t_resp.set("отвечает", r.get("when", ""), "ok")
        else:
            self.t_resp.set("нет ответа", r.get("when", ""), "err")

    # ── действия ──
    def _need_admin(self):
        if is_admin():
            return False
        if QMessageBox.question(self, "Права администратора",
                                "Менять IP можно только с правами администратора.\nПерезапустить программу с правами?") \
                == QMessageBox.Yes:
            self.restart(admin=True)
        return True

    def set_static(self):
        if self.worker.busy():
            return
        a = self.adapter()
        ant, mask, me = self.e_ant.text().strip(), self.e_mask.text().strip(), self.e_my.text().strip()
        if not a:
            QMessageBox.warning(self, "Адаптер", "Выбери сетевой адаптер (F5 — обновить список).")
            return
        err = validate(ant, mask, me)
        if err:
            QMessageBox.warning(self, "Параметры", err)
            return
        if a["Wifi"] and QMessageBox.question(
                self, "Wi-Fi", f"«{a['Name']}» — это Wi-Fi. Антенна обычно подключена кабелем, "
                               "а на Wi-Fi пропадёт интернет. Всё равно ставить?") != QMessageBox.Yes:
            return
        if self._need_admin():
            return
        name = a["Name"]
        timeout, retries, auto = self.f_timeout.value(), self.f_retries.value(), self.tg_auto.isChecked()
        saved = dict(self.cfg.get("saved_net") or {})

        def job(w):
            if name not in saved:
                w.log(f"⏳ запоминаю настройки «{name}»…")
                snap = snapshot_adapter(name)
                saved[name] = snap
                w.ui(lambda: self._store_snapshot(name, snap))
                w.log("✓ запомнил: " + ("DHCP" if snap["dhcp"] else f"{snap['ip']} / {snap['mask']}, шлюз "
                                         f"{snap['gw'] or '—'}, DNS {', '.join(snap['dns']) or '—'}"))
            else:
                w.log(f"ℹ прежние настройки «{name}» уже запомнены — не перезаписываю.")
            if ping(me, 1.0):
                w.log(f"⚠ адрес {me} уже кто-то занимает в сети — возможен конфликт.")
            ok, out = run_cmd(["netsh", "interface", "ipv4", "set", "address", f"name={name}",
                               "static", me, mask])
            if not ok:
                w.log(f"✗ netsh: {out or 'ошибка'}")
                w.ui(lambda: self.set_chip("● ошибка", "err"))
                return
            w.log(f"✓ на «{name}» стоит {me} / {mask}")
            w.ui(lambda: self.set_chip("● IP задан", "ok"))
            w.ui(self.refresh_quiet)
            if auto:
                self._check_loop(w, ant, timeout, retries)
        self.run_job("ставлю IP", job)

    def _store_snapshot(self, name, snap):
        self.cfg.setdefault("saved_net", {})[name] = snap
        self.save_if_changed()
        self.update_saved_label()

    def refresh_quiet(self):
        """Перечитать адаптеры после текущей работы (без записи в журнал «читаю…»)."""
        def later():
            if self.worker.busy():
                QTimer.singleShot(500, later)
            else:
                self.refresh()
        QTimer.singleShot(500, later)

    def _check_loop(self, w, ip, timeout, retries):
        for i in range(retries + 1):
            if w.stopped():
                w.log("⏹ проверка остановлена")
                return
            res = check_antenna(ip, timeout)
            if res["alive"] or i == retries:
                w.ui(lambda r=res: self.show_check(ip, r))
                return
            w.log(f"… {ip} пока не отвечает, жду ({i + 1}/{retries})")
            if w.sleep(2):
                w.log("⏹ проверка остановлена")
                return

    def check(self):
        ip = self.e_ant.text().strip()
        try:
            ipaddress.IPv4Address(ip)
        except ValueError:
            QMessageBox.warning(self, "Проверка", "Неверный адрес антенны.")
            return
        timeout = self.f_timeout.value()

        def job(w):
            w.log(f"🔎 проверяю {ip}…")
            self._check_loop(w, ip, timeout, 0)
        self.run_job("проверка", job)

    def show_check(self, ip, r):
        r["when"] = time.strftime("%H:%M:%S")
        r["ip"] = ip
        self.last_check = r
        marks = {"ping": (r["ping"], "есть" if r["ping"] else "нет"),
                 "p80": (r["p80"], "открыт" if r["p80"] else "закрыт"),
                 "p443": (r["p443"], "открыт" if r["p443"] else "закрыт")}
        h = r.get("http")
        if h:
            code, loc = h
            marks["http"] = (True, f"HTTP {code}" + (f" → {loc}" if loc else ""))
        else:
            marks["http"] = (False, "нет")
        for k, (ok, text) in marks.items():
            d, lab = self.res_rows[k]
            d.set("ok" if ok else "err")
            lab.setText(text)
        if r["alive"]:
            self.set_chip("● антенна отвечает", "ok")
            self.log(f"✓ {ip} отвечает: пинг {marks['ping'][1]}, 80 {marks['p80'][1]}, 443 {marks['p443'][1]}"
                     + (f", {marks['http'][1]}" if h else ""))
            if not r["ping"]:
                self.log("ℹ на пинг не отвечает, но порты открыты — это нормально для некоторых антенн.")
        else:
            self.set_chip("● нет ответа", "err")
            self.log(f"✗ {ip}: нет ответа. Проверь кабель и PoE-блок, адаптер и IP ноутбука "
                     "(должен быть в подсети антенны).")
        self.update_tiles()

    def open_browser(self):
        ip = self.e_ant.text().strip()
        try:
            ipaddress.IPv4Address(ip)
        except ValueError:
            QMessageBox.warning(self, "Браузер", "Неверный адрес антенны.")
            return
        r = self.last_check if self.last_check and self.last_check.get("ip") in (None, ip) else None
        url = web_url(ip, r)
        QDesktopServices.openUrl(QUrl(url))
        self.log(f"🌐 открываю {url}")
        if url.startswith("https"):
            self.log("ℹ у антенны свой сертификат — браузер может предупредить, это ожидаемо.")

    def restore(self):
        if self.worker.busy():
            if self.worker.blocking_close:
                return
            if QMessageBox.question(self, "Вернуть как было", f"Остановить «{self.worker.name}» и вернуть "
                                    "сеть адаптера как было?") != QMessageBox.Yes:
                return
            name = (self.adapter() or {}).get("Name", "")
            self.worker.stop_flag.set()
            self.log("⏹ останавливаю, потом верну сеть…")

            def later():
                if self.worker.busy():
                    QTimer.singleShot(300, later)
                elif name and name in (self.cfg.get("saved_net") or {}):
                    self._restore_now()
                else:
                    self.log("✓ сеть адаптера уже как была")
            QTimer.singleShot(300, later)
            return
        self._restore_now(ask=True)

    def _restore_now(self, ask=False):
        if self.worker.busy():
            return
        a = self.adapter()
        if not a:
            QMessageBox.warning(self, "Адаптер", "Выбери сетевой адаптер.")
            return
        name = a["Name"]
        snap = (self.cfg.get("saved_net") or {}).get(name)
        what = ("DHCP (автоматически)" if not snap or snap.get("dhcp") or not snap.get("ip")
                else f"{snap['ip']} / {snap['mask']}, шлюз {snap.get('gw') or '—'}")
        extra = "" if snap else "\n\nПрежние настройки не запомнены — будет DHCP."
        if ask and QMessageBox.question(self, "Вернуть как было",
                                        f"Вернуть «{name}»: {what}?{extra}") != QMessageBox.Yes:
            return
        if self._need_admin():
            return
        cmds = restore_commands(name, snap or {"dhcp": True})

        def job(w):
            for c in cmds:
                ok, out = run_cmd(c)
                if not ok:
                    w.log(f"✗ netsh: {out or 'ошибка'}")
                    w.ui(lambda: self.set_chip("● ошибка", "err"))
                    return
            w.log(f"✓ «{name}» возвращён: {what}")
            w.ui(lambda: self._forget(name))
            w.ui(lambda: self.set_chip("● сеть возвращена", "ok"))
            w.ui(self.refresh_quiet)
        self.run_job("возвращаю сеть", job)

    def _forget(self, name):
        (self.cfg.get("saved_net") or {}).pop(name, None)
        self.save_if_changed()
        self.update_saved_label()

    def forget_snapshots(self):
        if not self.cfg.get("saved_net"):
            return
        if QMessageBox.question(self, "Забыть снимки",
                                "Забыть прежние настройки всех адаптеров? Потом «Вернуть как было» поставит DHCP.") \
                == QMessageBox.Yes:
            self.cfg["saved_net"] = {}
            self.update_saved_label()
            self.log("🗑 снимки настроек забыты")

    def update_saved_label(self):
        s = self.cfg.get("saved_net") or {}
        if not s:
            self.l_saved.setText("Нет. Снимок делается сам перед первой сменой IP.")
            return
        lines = []
        for n, v in s.items():
            lines.append(f"{n}: " + ("DHCP" if v.get("dhcp") else
                                     f"{v.get('ip')} / {v.get('mask')}, шлюз {v.get('gw') or '—'}, "
                                     f"DNS {', '.join(v.get('dns') or []) or '—'}"))
        self.l_saved.setText("\n".join(lines))

    # ── обновление ──
    def update_from_menu(self):
        """⋯ → «Обновить программу с GitHub»: проверить, скачать, поставить, перезапустить.
        Репозиторий публичный — токен не обязателен (вписан — используется)."""
        if FROZEN:
            QMessageBox.information(self, "Обновление", "Это EXE — обнови на вкладке «Обновление».")
            return
        if self.worker.busy() or self.update_busy():
            QMessageBox.information(self, "Обновление", f"Сейчас идёт «{self.worker.name or 'обновление'}» — "
                                                       "дождись конца (или Esc — стоп) и нажми ещё раз.")
            return
        import dataclasses
        from app import gh_update
        t = dataclasses.replace(self.update_page.box.t, branch=self.cfg.get("upd_branch") or GITHUB_BRANCH)
        token = self.cfg.get("upd_token") or ""
        self.set_page(2)

        def job(w):
            w.log(f"🔎 смотрю версию на GitHub ({t.owner}/{t.repo}, {t.branch})…")
            rel, new = gh_update.check(t, token)
            if rel is None:
                w.log("✗ на GitHub нет архива программы в release/")
                return
            if not new:
                w.log(f"✓ у тебя последняя версия v{VERSION} (на GitHub v{rel.version})")
                return
            w.blocking_close = True
            w.log(f"⬇ качаю v{rel.version}…")
            z = gh_update.download(t, token, rel)
            gh_update.install(t, z, rel.version, lambda *a: w.log(" ".join(str(x) for x in a)))
            w.log(f"✓ установлена v{rel.version} — перезапускаю")
            w.ui(self._restart_after_update)
        self.run_job("обновление", job)

    def _restart_after_update(self):
        from app import gh_update
        try:
            gh_update.restart([str(APP_ROOT / "antenna_setup.pyw")])
        except Exception as e:
            QMessageBox.information(self, "Обновление", f"Обновлено, но перезапустить не вышло ({e}). "
                                                       "Закрой и открой программу.")
            return
        QTimer.singleShot(0, self._quit_for_update)

    def restart(self, admin=False):
        if self.worker.busy() or self.update_busy():
            QMessageBox.information(self, "Перезапуск", "Дождись конца работы.")
            return
        self.save_now()
        if admin and IS_WIN:
            if not relaunch_as_admin():
                self.log("⚠ права администратора не получены")
                return
        else:
            if FROZEN:
                QProcess.startDetached(sys.executable, ["--no-admin"])
            else:
                QProcess.startDetached(sys.executable, [os.path.abspath(__file__), "--no-admin"])
        self._force_close = True
        QApplication.instance().quit()

    # ── закрытие ──
    def closeEvent(self, e):
        if getattr(self, "_force_close", False):
            e.accept()
            return
        if self.update_busy():
            QMessageBox.information(self, "Закрытие", "Идёт обновление программы — дождись конца.")
            e.ignore()
            return
        if self.worker.busy():
            if QMessageBox.question(self, "Закрытие", f"Идёт «{self.worker.name}». Остановить и закрыть?") \
                    != QMessageBox.Yes:
                e.ignore()
                return
            self.worker.stop_flag.set()
            self._closing = True
            self.set_chip("● останавливаю…", "warn")
            e.ignore()
            return
        self.save_now()
        e.accept()

# ───────────────────────── selftest ─────────────────────────


LEAK_PATTERNS = ("github_pat_", "ghp_", "gho_", "ghs_")


def leak_scan(root):
    hits = []
    for p in Path(root).rglob("*"):
        if not p.is_file() or p.name in ("config.json", "config.json.bak") or ".git" in p.parts \
                or "_backup" in p.parts or p.suffix in (".zip", ".pyc"):
            continue
        try:
            t = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for pat in LEAK_PATTERNS:
            i = t.find(pat)
            while i >= 0:
                tail = t[i + len(pat): i + len(pat) + 20]
                if len(tail) >= 20 and all(ch.isalnum() or ch == "_" for ch in tail):
                    hits.append(f"{p.name}: {pat}…")
                i = t.find(pat, i + 1)
    return hits


def selftest():
    res = []

    def ok(name, cond):
        res.append(("✓" if cond else "✗") + " " + name)
        return cond
    ok("host_ip /24", host_ip_for("192.168.10.1") == "192.168.10.50")
    ok("host_ip антенна .50", host_ip_for("192.168.1.50") == "192.168.1.51")
    ok("host_ip /16", host_ip_for("10.0.0.1", "255.255.0.0") == "10.0.0.50")
    ok("host_ip /29", host_ip_for("192.168.1.1", "255.255.255.248") == "192.168.1.2")
    ok("validate ok", validate("192.168.1.20", "255.255.255.0", "192.168.1.50") is None)
    ok("validate чужая подсеть", validate("192.168.1.20", "255.255.255.0", "192.168.2.50") is not None)
    ok("validate совпадает", validate("192.168.1.20", "255.255.255.0", "192.168.1.20") is not None)
    ok("validate маска", validate("192.168.1.20", "255.0.255.0", "192.168.1.50") is not None)
    ok("validate broadcast", validate("192.168.1.20", "255.255.255.0", "192.168.1.255") is not None)
    ok("подсети поиска", [str(n) for n in parse_subnets("192.168.1, 10.0.0.5; кривое, 192.168.1")]
       == ["192.168.1.0/24", "10.0.0.0/24"])
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    port = srv.getsockname()[1]
    ub = b"\x01\x00\x00\x20" + b"\x02\x00\x0a" + bytes(6) + socket.inet_aton("192.168.1.20") \
        + b"\x0b\x00\x03" + b"NSM"
    ok("ответ Ubiquiti", parse_ubnt(ub) == ("192.168.1.20", "Ubiquiti NSM"))
    mk = bytes(4) + b"\x00\x11\x00\x04" + socket.inet_aton("192.168.88.1") + b"\x00\x05\x00\x02" + b"MT"
    ok("ответ MikroTik", parse_mndp(mk) == ("192.168.88.1", "MikroTik MT"))
    ok("поиск находит узел", list(scan_subnet(ipaddress.IPv4Network("127.0.0.0/30"), ports=(port,))) == ["127.0.0.1"])
    srv.close()
    try:
        import importlib as _il
        gh_update = _il.import_module("app.gh_update")
        for m in ("app.gh_update_qt", "app.gh_update_help"):
            _il.import_module(m)
        ok(f"модуль обновления gh_update {gh_update.VERSION}",
           gh_update.newer("0.3.1", "0.3.0") and not gh_update.newer("0.2.9", "0.3.0"))
    except Exception as e:
        ok(f"модуль обновления: {e}", False)
    ok("decode cp866", decode_out("Ошибка".encode("cp866")) == "Ошибка")
    ok("restore dhcp", restore_commands("Ethernet 2", {"dhcp": True})[0][-1] == "source=dhcp")
    rc = restore_commands("E", {"dhcp": False, "ip": "10.0.0.5", "mask": "255.255.255.0",
                                "gw": "10.0.0.1", "dns": ["1.1.1.1", "8.8.8.8"]})
    ok("restore static", rc[0][-3:] == ["10.0.0.5", "255.255.255.0", "10.0.0.1"] and len(rc) == 3)
    with tempfile.TemporaryDirectory() as d:
        cp = Path(d) / "config.json"
        save_config({"a": 1}, cp)
        save_config({"a": 2}, cp)
        cp.write_text("{битый", encoding="utf-8")
        c, w = load_config(cp)
        ok("config: битый → .bak", c.get("a") == 1 and w)
        (Path(d) / "config.json.bak").write_text("{", encoding="utf-8")
        c, w = load_config(cp)
        ok("config: оба битые → не писать", not w)
    ok("утечек токенов нет", not leak_scan(APP_ROOT))
    if not IS_WIN:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication(sys.argv)
    if not install_ru(app):
        res.append("ℹ русского перевода Qt нет — кнопки диалогов будут по-английски")
    app.setStyle("Fusion")
    apply_theme(app, "dark")
    f = _IntField(1, 15, 3, "с")
    f.stepBy(20)
    f.edit.setText("abc")
    f._commit()
    ok("_IntField: предел и откат", f.value() == 15 and f.edit.text() == "15 с")
    cfg = dict(DEFAULT_CONFIG)
    w = MainWindow(cfg, cfg_writable=False)
    ok("окно создаётся", w.found.count() == 0 and w.e_ant.text() == "")
    w.show_found({"192.168.1.20": [80, 443]}, "255.255.255.0", "192.168.1.247", "192.168.1.0/24")
    ok("найденная антенна подставляется", w.e_ant.text() == "192.168.1.20" and w.e_my.text() == "192.168.1.247"
       and validate(w.e_ant.text(), w.e_mask.text(), w.e_my.text()) is None)
    w.set_theme("light")
    w.set_theme("dark")
    ok("смена темы", w.btn_theme.text() == "☀")
    ok("меню ⋯: обновление с GitHub", any("GitHub" in a.text() for a in w.main_menu().actions()))
    text = "\n".join(res)
    fail = any(r.startswith("✗") for r in res)
    text += f"\n\nselftest v{VERSION}: {'ОШИБКИ' if fail else 'всё в порядке'}"
    print(text)
    try:
        (APP_ROOT / "selftest.txt").write_text(text, encoding="utf-8")
    except Exception:
        pass
    return 1 if fail else 0

# ───────────────────────── запуск ─────────────────────────


def install_ru(app):
    """Русские кнопки стандартных диалогов (Да/Нет, Сохранить…)."""
    path = QLibraryInfo.path(QLibraryInfo.TranslationsPath)
    app._tr = []
    for name in ("qtbase_ru", "qt_ru"):
        t = QTranslator(app)
        if t.load(name, path):
            app.installTranslator(t)
            app._tr.append(t)
    return bool(app._tr)


def main():
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    from app import gh_update
    gh_update.wait_previous(sys.argv)   # после обновления — дождаться закрытия старой копии
    if IS_WIN:
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:
            pass
    cfg, writable = load_config()
    if cfg.get("github_token") and not cfg.get("upd_token"):   # токен из v0.2.x
        cfg["upd_token"] = cfg["github_token"]
    for k in ("github_token", "github_repo", "github_branch", "check_updates"):
        cfg.pop(k, None)
    if IS_WIN and cfg.get("ask_admin", True) and "--no-admin" not in sys.argv \
            and "--after-update" not in sys.argv and not is_admin():
        if relaunch_as_admin():
            sys.exit(0)
    QApplication.setAttribute(Qt.AA_DontUseNativeDialogs, True)
    app = QApplication(sys.argv)
    install_ru(app)
    app.setStyle("Fusion")
    app.setWindowIcon(app_icon())
    apply_theme(app, cfg.get("theme", "dark"))
    win = MainWindow(cfg, writable)
    flt = AppFilter(win)
    app.installEventFilter(flt)
    win.set_theme(cfg.get("theme", "dark"))
    win.show()
    if not is_admin():
        win.log("⚠ нет прав администратора — смена IP недоступна (⋯ → Перезапуск или ответь «да» при запуске).")
    win.set_busy(False)
    QTimer.singleShot(200, win.refresh)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
