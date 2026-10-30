# -*- coding: utf-8 -*-
"""gh_update — обновление программы из приватного репозитория GitHub.

ОБЩИЙ модуль для всех наших приложений (только стандартная библиотека):
вставить файл в проект, задать UpdateTarget — и всё работает одинаково.

Откуда берётся версия. В репозитории лежит release/<имя>_vX.Y.Z.zip
(правило выдачи: внутри архива папка <имя>/ со всеми файлами проекта).
Программа спрашивает GitHub API, какой архив лежит в release/ нужной
ветки, сравнивает номер со своей версией, скачивает, сверяет контрольную
сумму (git blob sha1 из ответа GitHub), ставит поверх и перезапускается.

Доступ — токен GitHub «только чтение» (fine-grained PAT, Contents: Read)
на выбранные репозитории. Хранится в настройках программы.

Что делает install():
  * распаковывает во временную папку и проверяет, что внутри — та самая
    программа (есть главный файл и номер версии совпадает с именем архива);
  * ставит новые файлы поверх старых;
  * стирает то, что ставил сам в прошлый раз и чего в новой версии нет
    (удалённые и разбитые на части модули, их .pyc, опустевшие папки).
    Что ставил — помнит список MANIFEST в папке программы; списка ещё нет
    (первое обновление этим модулем) — старый код (CODE_EXT) в папках,
    которые есть в архиве (корень — нет: там могут лежать свои скрипты),
    мимо папок данных (KEEP_DIRS);
  * НИКОГДА не трогает и не перезаписывает настройки, журналы, записи,
    скачанное, DLL и EXE (KEEP — маски, KEEP_DIRS — папки);
  * при ошибке посреди копирования возвращает старые файлы (временная
    копия вне папки программы; папки backup/ больше нет — старая
    удаляется).

Перезапуск: restart() запускает программу заново с ключом
--after-update <pid> и закрывает текущую. Новая копия в самом начале зовёт
wait_previous(sys.argv) — ждёт, пока старая завершится (иначе защита от
второго запуска приняла бы её за «уже запущено»).

1.3.1: прежняя сборка exe (.gh_update_old) стирается и при обычном запуске
(раньше — только при запуске с --after-update); токен отвергнут (401 / 403)
посреди закачки — так и сказано сразу, а не «скачалась не целиком».

1.3.0: программа сама знает, как она запущена (run_kind): из исходников
(Python) — как раньше, архив release/<имя>_vX.Y.Z.zip поверх папки; собранный
exe — готовая сборка <имя>_exe_vX.Y.Z.zip из GitHub Releases (её собирает
GitHub Actions, .github/workflows/build_exe.yml, на каждую версию в main):
скачать (докачка, sha256 из ответа GitHub) → распаковать в .gh_update_new
(stage_exe) → программа закрывается, помощник .gh_update_swap.bat ждёт её
выхода, убирает старое в .gh_update_old, ставит новое и запускает новую
версию (launch_swap); не вышло — возвращает старое и запускает его, причина
— в .gh_update_failed.txt (swap_failed). Настройки, журналы, записи и свои
файлы в папке exe не трогаются; vendor\\ дополняется, а не заменяется.
Версия уже в main, а exe GitHub ещё собирает — Release(kind="wait").
1.2.0: обновление больше не копит мусор: стирается то, что модуль ставил
сам и чего нет в новой версии (список MANIFEST — .gh_update_files.txt;
без списка — stale_files: код в папках архива, мимо KEEP_DIRS — logs, libs,
Rec, Archive, Bin, sdk, venv …); настройки и всё по KEEP — никогда.
backup/ не ведётся (старый удаляется), откат при ошибке — из временной
копии вне папки программы.
1.1.3: в облаке анимации обновления — значок GitHub над надписью (gh_update_qt; без QtSvg —
только надпись, как раньше).
1.1.2: архив качается по ссылке на файл (download_url из списка release/,
raw.githubusercontent.com), а не через API: API обрывает ответ через ~10 с,
и архив ~39 МБ приходил не целиком (38765774 из 38982176 байт, сколько ни
пробуй). Оборвалось — докачка с места обрыва (Range), до DL_TRIES попыток;
ссылки нет или она не открылась — по-старому через API, тоже с докачкой.
1.1.1: «Что нового» понимает и заголовки «v1.2.3: …», «## v1.2.3», «Версия
1.2.3 — …»; инструкция показывает настоящий файл с номером версии.
1.1.0: version_files — где искать номер версии в архиве (кроме
app/version.py, version.py, VERSION и главного файла); where — где в
программе вкладка (для инструкции); работает и как пакет (app/), и как
отдельные файлы рядом с главным .pyw.

Собранный .exe обновляется готовой сборкой из GitHub Releases (1.3.0, см.
выше): exe не перезаписать, пока он работает, поэтому подмену делает
помощник после выхода программы.
"""
import fnmatch
import hashlib
import http.client
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field

VERSION = "1.3.1"
API = "https://api.github.com"
TIMEOUT = 30

# что не трогаем при обновлении никогда (маски путей относительно папки программы)
KEEP_DEFAULT = (
    "*.json", "*.log", "*.log.*", "*.bak*", "*.tmp*",
    "libs/*", "logs/*", ".runtime/*", "backup/*", "firmware/*",
    "cloud_history/*", "*.exe", "*.dll", "release/*", ".git/*",
)

# ★ 1.2.0: список файлов, поставленных обновлением (по нему в следующий раз
# стирается то, чего в новой версии нет)
MANIFEST = ".gh_update_files.txt"

# ★ 1.2.0: без списка (первое обновление этим модулем) — что из старых
# файлов стирается, если его нет в новой версии, —
# только код (настройки, журналы, записи, DLL — никогда)
CODE_EXT = (".py", ".pyw", ".pyc", ".pyo", ".bat", ".cmd", ".spec", ".md",
            ".qss")
# папки данных и чужого кода: туда чистка не заходит ни на каком уровне
KEEP_DIRS = frozenset((
    "logs", "libs", "rec", "archive", "bin", "sdk", ".runtime", "firmware",
    "cloud_history", "release", "backup", ".git", ".smartmon_parts", "build",
    "dist", "venv", ".venv", "env", "site-packages", "lib", "scripts",
    "node_modules", "downloads", "download", ".gh_update_new",
    ".gh_update_old"))

# ★ 1.3.0: обновление собранного exe (папки и файлы в папке exe)
EXE_NEW = ".gh_update_new"         # распакованная новая сборка
EXE_OLD = ".gh_update_old"         # прежняя сборка (стирается после запуска новой)
EXE_READY = ".gh_update_ready"     # метка «распаковано целиком» (внутри EXE_NEW)
EXE_SWAP = ".gh_update_swap.bat"   # помощник подмены
EXE_FAILED = ".gh_update_failed.txt"   # подмена не удалась — причина
EXE_DL = ".gh_update_dl.part"      # недокачанный архив сборки
EXE_VERSION = "exe_version.txt"    # номер версии внутри сборки (пишет GitHub)
EXE_MERGE = ("vendor",)            # папки сборки, которые дополняются, а не меняются


class UpdateError(Exception):
    """Ошибка обновления; текст — по-русски, для пользователя.
    code — HTTP-код ответа GitHub (0 — не HTTP)."""

    def __init__(self, text, code=0):
        super().__init__(text)
        self.code = code


@dataclass
class UpdateTarget:
    """Что и откуда обновлять — своё у каждого приложения."""
    owner: str                    # romzespra-collab
    repo: str                     # Smart_BMS
    name: str                     # smart_bms — префикс архива и папка внутри
    current: str                  # текущая версия программы, «4.88»
    app_dir: str                  # куда ставить (папка программы)
    main_file: str                # главный файл внутри архива: Smart_BMS.pyw
    subdir: str = ""              # если в репозитории проект лежит в подпапке
    branch: str = "main"
    changelog: str = ""           # путь к CHANGELOG в репозитории — «Что нового»
    keep: tuple = field(default_factory=lambda: KEEP_DEFAULT)
    version_files: tuple = ()     # где ещё искать VERSION = "…" в архиве
    where: str = "Настройки → 🔄 Обновление"   # где вкладка (для инструкции)
    removed: list = field(default_factory=list)  # ★ 1.2.0: что стёрла install()


@dataclass
class Release:
    version: str
    path: str                     # release/smart_bms_v4.89.zip
    sha: str                      # git blob sha1 (сверка после скачивания)
    size: int
    url: str = ""                 # download_url (raw.githubusercontent.com)
    kind: str = "src"             # ★ 1.3.0: src — архив исходников, exe — сборка
                                  # из Releases, wait — версия есть, exe ещё нет
    sha256: str = ""              # ★ 1.3.0: sha256 сборки (digest из Releases)


# ---------------- версии ----------------

def vtuple(v):
    """«4.88» / «v6.63.44» -> (4, 88) / (6, 63, 44); мусор -> ()."""
    nums = re.findall(r"\d+", str(v or ""))
    return tuple(int(x) for x in nums)


def newer(a, b):
    """a новее b? (сравнение по числам; «4.9» < «4.10»)."""
    ta, tb = vtuple(a), vtuple(b)
    n = max(len(ta), len(tb))
    return ta + (0,) * (n - len(ta)) > tb + (0,) * (n - len(tb))


# ---------------- GitHub ----------------

def _ctx():
    if os.environ.get("SSL_CERT_FILE"):           # свой корневой (прокси/фирма)
        return ssl.create_default_context()
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:                                  # noqa: BLE001
        return ssl.create_default_context()


def _req(url, token, accept="application/vnd.github+json", headers=None):
    h = {"Accept": accept, "User-Agent": "gh_update/" + VERSION,
         "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        h["Authorization"] = "Bearer " + token.strip()
    if headers:
        h.update(headers)
    return urllib.request.Request(url, headers=h)


def _open(url, token, accept="application/vnd.github+json", timeout=TIMEOUT,
          headers=None):
    try:
        return urllib.request.urlopen(_req(url, token, accept, headers),
                                      timeout=timeout, context=_ctx())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise UpdateError("токен GitHub не подошёл (401): проверь, что он "
                              "вставлен целиком и не истёк", 401) from e
        if e.code == 403:
            raise UpdateError("GitHub не дал доступ (403): у токена нет права "
                              "Contents: Read на этот репозиторий, или лимит "
                              "запросов — попробуй позже", 403) from e
        if e.code == 404:
            raise UpdateError("не найдено (404): репозиторий/ветка/папка release "
                              "не те, или токен не видит приватный репозиторий",
                              404) from e
        raise UpdateError("GitHub ответил %s" % e.code, e.code) from e
    except (urllib.error.URLError, OSError) as e:
        raise UpdateError("нет связи с GitHub (%s)" % getattr(e, "reason", e)) from e


def latest(t, token):
    """Последний архив в release/ ветки -> Release или None (архивов нет)."""
    folder = (t.subdir.strip("/") + "/release") if t.subdir else "release"
    url = "%s/repos/%s/%s/contents/%s?ref=%s" % (
        API, t.owner, t.repo, urllib.parse.quote(folder),
        urllib.parse.quote(t.branch))
    try:
        with _open(url, token) as r:
            items = json.loads(r.read().decode("utf-8"))
    except UpdateError as e:
        if e.code in (403, 404):
            raise UpdateError(diagnose(t, token, folder), e.code) from e
        raise
    if not isinstance(items, list):
        raise UpdateError("GitHub вернул не список файлов папки release")
    pat = re.compile(r"^%s_v?(\d+(?:\.\d+)*)\.zip$" % re.escape(t.name), re.I)
    best = None
    for it in items:
        m = pat.match(str(it.get("name") or ""))
        if not m or it.get("type") != "file":
            continue
        rel = Release(m.group(1), it["path"], it.get("sha") or "",
                      int(it.get("size") or 0), it.get("download_url") or "")
        if best is None or newer(rel.version, best.version):
            best = rel
    return best


def _code(url, token):
    """HTTP-код запроса (200/401/403/404…), 0 — нет связи."""
    try:
        with _open(url, token):
            return 200
    except UpdateError as e:
        return e.code


def diagnose(t, token, folder="release"):
    """После 403/404: по шагам выяснить, ЧТО не так, и сказать, как
    исправить (GitHub на приватный репозиторий без доступа отвечает 404 —
    по одному коду не понять)."""
    q = urllib.parse.quote
    full = "%s/%s" % (t.owner, t.repo)
    c = _code("%s/user" % API, token)
    if c == 401:
        return ("токен GitHub недействителен (удалён, истёк или вставлен не "
                "целиком) — сделайте новый, кнопка «?»")
    c = _code("%s/repos/%s" % (API, full), token)
    if c in (403, 404):
        return ("токен не видит репозиторий %s. На GitHub: токен → Edit → "
                "Repository access → Only select repositories → добавьте %s "
                "(и Resource owner — %s)" % (full, full, t.owner))
    if c != 200:
        return "GitHub не отвечает на запрос репозитория (код %s)" % c
    c = _code("%s/repos/%s/branches/%s" % (API, full, q(t.branch)), token)
    if c == 404:
        return ("в репозитории %s нет ветки «%s» — впишите в поле «Ветка» "
                "правильную (обычно main)" % (full, t.branch))
    c = _code("%s/repos/%s/contents/?ref=%s" % (API, full, q(t.branch)), token)
    if c in (403, 404):
        return ("у токена нет права читать файлы. На GitHub: токен → Edit → "
                "Permissions → Repositories → Add permissions → Contents → "
                "Read-only → Update")
    return ("в ветке «%s» нет папки %s с архивами программы" % (t.branch, folder))


def check(t, token):
    """-> (Release, есть_новее). Release=None — архивов в release/ нет.
    ★ 1.3.0: собранный exe — сборка из Releases (check_exe)."""
    if is_frozen():
        return check_exe(t, token)
    rel = latest(t, token)
    return rel, bool(rel and newer(rel.version, t.current))


# ---------------- собранный exe (★ 1.3.0) ----------------

def run_kind():
    """Как запущена программа: "exe" (собранная PyInstaller) или "python"."""
    return "exe" if is_frozen() else "python"


def run_kind_text():
    return ("собранный exe — обновляется готовой сборкой с GitHub"
            if is_frozen() else
            "Python (исходники) — обновляется архивом исходников")


def exe_name(t):
    """Имя exe программы: SmartMon.pyw -> SmartMon.exe."""
    return os.path.splitext(os.path.basename(t.main_file))[0] + ".exe"


def latest_exe(t, token):
    """Последняя сборка <имя>_exe_vX.Y.Z.zip в GitHub Releases -> Release
    (kind="exe") или None."""
    url = "%s/repos/%s/%s/releases?per_page=50" % (API, t.owner, t.repo)
    try:
        with _open(url, token) as r:
            items = json.loads(r.read().decode("utf-8"))
    except UpdateError as e:
        if e.code in (403, 404):
            raise UpdateError(diagnose(t, token), e.code) from e
        raise
    if not isinstance(items, list):
        raise UpdateError("GitHub вернул не список выпусков (Releases)")
    pat = re.compile(r"^%s_exe_v?(\d+(?:\.\d+)*)\.zip$" % re.escape(t.name),
                     re.I)
    best = None
    for it in items:
        if not isinstance(it, dict) or it.get("draft"):
            continue
        for a in it.get("assets") or ():
            m = pat.match(str(a.get("name") or ""))
            if not m or (a.get("state") or "uploaded") != "uploaded":
                continue
            dg = str(a.get("digest") or "")
            rel = Release(m.group(1), a["name"], "", int(a.get("size") or 0),
                          a.get("url") or "", kind="exe",
                          sha256=dg[7:].lower() if dg.lower().startswith(
                              "sha256:") else "")
            if best is None or newer(rel.version, best.version):
                best = rel
    return best


def check_exe(t, token):
    """-> (Release, есть_новее) для собранного exe. Есть сборка новее —
    она. Нет, а в release/ версия новее — Release(kind="wait"): GitHub её
    ещё собирает (или сборка не удалась)."""
    exe = latest_exe(t, token)
    if exe is not None and newer(exe.version, t.current):
        return exe, True
    try:
        src = latest(t, token)
    except UpdateError:
        if exe is None:
            raise
        src = None
    if src is not None and newer(src.version, t.current):
        return Release(src.version, src.path, "", src.size, kind="wait"), False
    return (exe or src), False


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_a, **_k):
        return None                    # 302 -> HTTPError, адрес берём сами


def _asset_link(api_url, token):
    """Ссылка на файл сборки. GitHub отвечает 302 на временный адрес
    хранилища — туда идём БЕЗ токена (с чужим токеном хранилище отказывает).
    -> (ссылка, нужен_ли_токен)."""
    op = urllib.request.build_opener(
        _NoRedirect, urllib.request.HTTPSHandler(context=_ctx()))
    req = _req(api_url, token, accept="application/octet-stream")
    try:
        r = op.open(req, timeout=TIMEOUT)
    except urllib.error.HTTPError as e:
        loc = e.headers.get("Location") if e.headers else None
        if e.code in (301, 302, 303, 307, 308) and loc:
            return loc, False
        if e.code == 401:
            raise UpdateError("токен GitHub не подошёл (401)", 401) from e
        if e.code in (403, 404):
            raise UpdateError("GitHub не отдал сборку exe (%s): у токена нет "
                              "права Contents: Read на этот репозиторий"
                              % e.code, e.code) from e
        raise UpdateError("GitHub ответил %s" % e.code, e.code) from e
    except (urllib.error.URLError, OSError) as e:
        raise UpdateError("нет связи с GitHub (%s)"
                          % getattr(e, "reason", e)) from e
    r.close()
    return api_url, True


def _fetch_file(url, token, fh, total, progress):
    """Одна попытка: дописать url в открытый файл с его конца (Range).
    -> (total, прибавилось байт)."""
    got0 = fh.tell()
    hdr = {"Range": "bytes=%d-" % got0} if got0 else None
    with _open(url, token, accept="application/octet-stream", timeout=120,
               headers=hdr) as r:
        st = int(getattr(r, "status", 0) or getattr(r, "code", 0) or 200)
        if got0 and st != 206:                 # Range не понят — с начала
            fh.seek(0)
            fh.truncate()
            got0 = 0
        if not total:
            n = int(r.headers.get("Content-Length") or 0)
            total = n + got0 if n else 0
        try:
            while True:
                chunk = r.read(262144)
                if not chunk:
                    break
                fh.write(chunk)
                if progress:
                    progress(fh.tell(), total)
        except (OSError, ValueError, http.client.HTTPException):
            pass                               # обрыв — докачаем
    fh.flush()
    return total, fh.tell() - got0


def _writable_dir(app_dir):
    try:
        test = os.path.join(app_dir, ".gh_update_write_test")
        with open(test, "w") as fh:
            fh.write("1")
        os.remove(test)
        return True
    except OSError:
        return False


def download_exe(t, token, rel, progress=None):
    """Скачать сборку exe в папку программы (там же её и ставить — тот же
    диск), докачка с места обрыва, сверка размера и sha256. -> путь."""
    app_dir = os.path.abspath(t.app_dir)
    if not _writable_dir(app_dir):
        raise UpdateError("в папку программы нельзя писать (%s) — запустите "
                          "программу от имени администратора или перенесите "
                          "папку туда, где можно писать (например, на диск D:)"
                          % app_dir)
    part = os.path.join(app_dir, EXE_DL)
    tag = part + ".ver"
    try:                                       # недокачанное другой версии — заново
        with open(tag, encoding="utf-8") as fh:
            same = fh.read().strip() == rel.path
    except OSError:
        same = False
    if not same:
        for x in (part, tag):
            try:
                os.remove(x)
            except OSError:
                pass
        with open(tag, "w", encoding="utf-8") as fh:
            fh.write(rel.path)
    total = rel.size or 0
    last = None
    idle = 0
    with open(part, "ab") as fh:
        for _ in range(DL_TRIES * 2):
            if total and fh.tell() >= total:
                break
            add = 0
            try:
                link, need_token = _asset_link(rel.url, token)   # ссылка живёт минуты
                total, add = _fetch_file(link, token if need_token else "",
                                         fh, total, progress)
            except UpdateError as e:
                last = e
                # ★ 1.3.1: токен отвергнут — сразу (с недокачанным куском
                # раньше 4 круга и «скачалась не целиком, нажмите ещё раз»)
                if e.code in (401, 403) or (e.code == 404 and fh.tell() == 0):
                    raise
            except (OSError, ValueError, http.client.HTTPException) as e:
                last = UpdateError("нет связи с GitHub (%s)" % e)
            if total and fh.tell() >= total:
                break
            idle = 0 if add > 0 else idle + 1
            if idle >= 4:
                break
            time.sleep(1.0)
        got = fh.tell()
    if rel.size and got != rel.size:
        if got > rel.size:
            os.remove(part)
        if not got and last is not None:
            raise last
        raise UpdateError("сборка exe скачалась не целиком (%d из %d байт) — "
                          "нажмите «Обновить» ещё раз, докачается с места "
                          "обрыва" % (got, rel.size))
    if rel.sha256:
        h = hashlib.sha256()
        with open(part, "rb") as fh:
            for chunk in iter(lambda: fh.read(1048576), b""):
                h.update(chunk)
        if h.hexdigest() != rel.sha256:
            os.remove(part)
            raise UpdateError("контрольная сумма сборки exe не совпала — "
                              "скачивание испорчено, обновление отменено")
    return part


def staged_exe(t):
    """Версия сборки, уже распакованной в .gh_update_new и готовой к
    подмене, или "" (нет / распакована не целиком)."""
    try:
        with open(os.path.join(os.path.abspath(t.app_dir), EXE_NEW,
                               EXE_READY), encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


_SAFE_ITEM = re.compile(r"^[A-Za-z0-9_.\- ]+$")


def stage_exe(t, zip_path, rel_version, log=None):
    """Распаковать сборку в .gh_update_new и проверить, что это та
    программа и та версия. -> список верхних файлов и папок сборки."""
    log = log or (lambda *_a: None)
    app_dir = os.path.abspath(t.app_dir)
    new = os.path.join(app_dir, EXE_NEW)
    shutil.rmtree(new, ignore_errors=True)
    try:
        os.makedirs(new)
        with zipfile.ZipFile(zip_path) as z:
            bad = z.testzip()
            if bad:
                raise UpdateError("архив сборки повреждён: %s" % bad)
            names = [n for n in z.namelist() if not n.endswith("/")]
            tops = set(n.split("/", 1)[0] for n in names)
            strip = 0
            if len(tops) == 1 and all("/" in n for n in names):
                strip = len(tops.pop()) + 1        # папка <имя>/ внутри архива
            for n in names:
                rel = n[strip:]
                if not rel:
                    continue
                dst = _safe(new, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with z.open(n) as src, open(dst, "wb") as out:
                    shutil.copyfileobj(src, out, 1048576)
        exe = exe_name(t)
        if not os.path.isfile(os.path.join(new, exe)):
            raise UpdateError("в сборке нет %s — это не та программа" % exe)
        try:
            with open(os.path.join(new, EXE_VERSION), encoding="utf-8") as fh:
                found = fh.read().strip()
        except OSError:
            found = ""
        if found and vtuple(found) != vtuple(rel_version):
            raise UpdateError("внутри сборки версия %s, а не %s — обновление "
                              "отменено" % (found, rel_version))
        items = sorted(os.listdir(new))
        odd = [x for x in items if not _SAFE_ITEM.match(x)]
        if odd:
            raise UpdateError("в сборке странные имена: %s" % ", ".join(odd))
        with open(os.path.join(new, EXE_READY), "w", encoding="utf-8") as fh:
            fh.write(str(rel_version))
    except UpdateError:
        shutil.rmtree(new, ignore_errors=True)
        raise
    except (OSError, zipfile.BadZipFile) as exc:
        shutil.rmtree(new, ignore_errors=True)
        raise UpdateError("сборку не распаковать (%s)" % exc) from exc
    finally:
        for x in (zip_path, zip_path + ".ver"):
            try:
                os.remove(x)
            except OSError:
                pass
    log("обновление: сборка exe %s распакована (%s)"
        % (rel_version, ", ".join(items)))
    return items


def swap_script(items, exe, pid, merge=EXE_MERGE):
    """Текст .gh_update_swap.bat (только ASCII, CRLF). Ждёт выхода
    программы (pid), убирает старое в .gh_update_old, ставит новое, запускает
    новую версию; на любом сбое возвращает старое и запускает его."""
    pid = int(pid)
    for x in list(items) + [exe]:
        if not _SAFE_ITEM.match(x):
            raise UpdateError("странное имя для подмены: %s" % x)
    merge_l = set(m.lower() for m in merge)
    swap = [x for x in items if x != EXE_READY
            and x.lower() not in merge_l]
    mrg = [x for x in items if x.lower() in merge_l]
    L = []
    a = L.append
    a("@echo off")
    a("rem gh_update %s: exe update helper (deletes itself)" % VERSION)
    a("setlocal EnableExtensions EnableDelayedExpansion")
    a('cd /d "%~dp0"')
    a("if not exist logs mkdir logs")
    a('set "L=logs\\gh_update_swap.log"')
    a('>>"%%L%%" echo [%%date%% %%time%%] update: wait for pid %d' % pid)
    a("set /a N=0")
    a(":waitmain")
    a('tasklist /FI "PID eq %d" /NH 2>nul | find " %d " >nul' % (pid, pid))
    a("if errorlevel 1 goto mainok")
    a("set /a N+=1")
    a("if !N! GEQ 90 (")
    a('  >>"%L%" echo still running after 90 s - taskkill')
    a("  taskkill /F /PID %d >nul 2>&1" % pid)
    a("  ping -n 3 127.0.0.1 >nul")
    a("  goto mainok")
    a(")")
    a("ping -n 2 127.0.0.1 >nul")
    a("goto waitmain")
    a(":mainok")
    a('if exist "%s" rmdir /s /q "%s"' % (EXE_OLD, EXE_OLD))
    a('if exist "%s" del /f /q "%s"' % (EXE_OLD, EXE_OLD))
    a('mkdir "%s"' % EXE_OLD)
    a('if exist "%s" del /f /q "%s"' % (EXE_FAILED, EXE_FAILED))
    a('set "WHY="')
    # 1) старое — в .gh_update_old (повторы: файлы держат дочерние процессы)
    for i, x in enumerate(swap):
        a("set /a T=0")
        a(":old%d" % i)
        a('if not exist "%s" goto oldok%d' % (x, i))
        a('move /y "%s" "%s\\%s" >nul 2>&1' % (x, EXE_OLD, x))
        a('if not exist "%s" goto oldok%d' % (x, i))
        a("set /a T+=1")
        a('if !T! GEQ 60 (set "WHY=busy: %s" & goto rollback)' % x)
        a("ping -n 2 127.0.0.1 >nul")
        a("goto old%d" % i)
        a(":oldok%d" % i)
    # 2) новое — на место (повторы: антивирус может держать новый exe)
    for i, x in enumerate(swap):
        a("set /a T=0")
        a(":new%d" % i)
        a('move /y "%s\\%s" "%s" >nul 2>&1' % (EXE_NEW, x, x))
        a('if exist "%s" goto newok%d' % (x, i))
        a("set /a T+=1")
        a('if !T! GEQ 15 (set "WHY=move: %s" & goto rollback)' % x)
        a("ping -n 2 127.0.0.1 >nul")
        a("goto new%d" % i)
        a(":newok%d" % i)
    # 3) папки, которые дополняются (vendor): свои файлы пользователя целы
    for x in mrg:
        a('xcopy "%s\\%s" "%s\\" /E /I /Y /Q >nul 2>&1' % (EXE_NEW, x, x))
        a('if errorlevel 1 >>"%%L%%" echo warning: %s not merged' % x)
    a('>>"%L%" echo [%date% %time%] update: ok')
    a('rmdir /s /q "%s" >nul 2>&1' % EXE_NEW)
    a('start "" "%s" --after-update %d' % (exe, pid))
    a("goto end")
    a(":rollback")
    a('>>"%L%" echo [%date% %time%] update FAILED: !WHY! - rollback')
    for x in swap:
        a('if exist "%s\\%s" (' % (EXE_OLD, x))
        a('  if exist "%s\\" (rmdir /s /q "%s") else if exist "%s" del /f /q "%s"'
          % (x, x, x, x))
        a('  move /y "%s\\%s" "%s" >nul 2>&1' % (EXE_OLD, x, x))
        a(")")
    a('>"%s" echo !WHY!' % EXE_FAILED)
    a('rmdir /s /q "%s" >nul 2>&1' % EXE_NEW)
    a('start "" "%s"' % exe)
    a(":end")
    a('(goto) 2>nul & del /f /q "%~f0"')
    return "\r\n".join(L) + "\r\n"


def launch_swap(t, pid=None, log=None):
    """Запустить подмену сборки. Программу после этого закрыть ПОЛНОСТЬЮ
    (дело вызывающего): помощник ждёт её выхода. -> путь к помощнику."""
    log = log or (lambda *_a: None)
    if os.name != "nt":
        raise UpdateError("подмена exe — только в Windows")
    app_dir = os.path.abspath(t.app_dir)
    new = os.path.join(app_dir, EXE_NEW)
    if not staged_exe(t):
        raise UpdateError("новая сборка не распакована — нажмите «Обновить»")
    items = sorted(x for x in os.listdir(new) if x != EXE_READY)
    text = swap_script(items, exe_name(t), pid or os.getpid())
    bat = os.path.join(app_dir, EXE_SWAP)
    with open(bat, "w", encoding="ascii", newline="") as fh:
        fh.write(text)
    base = 0x08000000 | 0x00000200       # CREATE_NO_WINDOW | NEW_PROCESS_GROUP
    last = None
    # BREAKAWAY_FROM_JOB: помощник не должен умереть вместе с программой
    for flags in (base | 0x01000000, base):
        try:
            subprocess.Popen(["cmd.exe", "/d", "/c", bat], cwd=app_dir,
                             creationflags=flags, close_fds=True)
            log("обновление: помощник подмены exe запущен — программа "
                "закрывается, новая версия откроется сама")
            return bat
        except OSError as exc:
            last = exc
    raise UpdateError("помощник подмены не запустился (%s)" % last)


def swap_failed(app_dir):
    """Прошлая подмена exe не удалась -> причина (файл стирается) или ""."""
    p = os.path.join(os.path.abspath(app_dir), EXE_FAILED)
    try:
        with open(p, encoding="utf-8", errors="replace") as fh:
            why = fh.read().strip()
        os.remove(p)
    except OSError:
        return ""
    if why.startswith("busy:"):
        return ("файлы программы заняты (%s) — закройте все её окна и "
                "попробуйте ещё раз" % why[5:].strip())
    return why or "причина не записана (logs\\gh_update_swap.log)"


def finish_exe_update(app_dir=None, delay=60.0):
    """После подмены: прежняя сборка (.gh_update_old) стирается, когда новая
    проработала delay секунд (вылетит сразу — старая останется, её можно
    вернуть руками)."""
    if not is_frozen():
        return False
    app_dir = os.path.abspath(app_dir or os.path.dirname(sys.executable))
    old = os.path.join(app_dir, EXE_OLD)
    if not os.path.isdir(old):
        return False

    def work():
        time.sleep(delay)
        shutil.rmtree(old, ignore_errors=True)
    import threading
    threading.Thread(target=work, daemon=True, name="gh-exe-old").start()
    return True


def whats_new(t, token, upto=None, limit=6000):
    """Разделы CHANGELOG новее установленной версии (до upto включительно).
    Раздел начинается строкой «4.90:» или «6.63.45 (= полная 4.90):».
    -> текст или "" (нет файла/разделов — не ошибка)."""
    if not t.changelog:
        return ""
    url = "%s/repos/%s/%s/contents/%s?ref=%s" % (
        API, t.owner, t.repo, urllib.parse.quote(t.changelog),
        urllib.parse.quote(t.branch))
    try:
        with _open(url, token, accept="application/vnd.github.raw") as r:
            text = r.read().decode("utf-8", errors="replace")
    except UpdateError:
        return ""
    return changelog_since(text, t.current, upto, limit)


def changelog_since(text, current, upto=None, limit=6000):
    # «4.90:», «6.63.45 (= полная 4.90):», «v1.2.3: текст», «## v1.2.3 — …»,
    # «# v1.2.3: …» (журнал в шапке .pyw), «Версия 1.2.3 — …»
    # одно число («v436:») — только с «v»/«Версия» впереди
    head = re.compile(r"^(?:#{1,4}\s*|\[)?(?:(?:[vV]|(?:[Вв]ерсия|[Ии]зменения(?:\s+в)?)\s+v?)(\d+(?:\.\d+)*)|"
                      r"(\d+(?:\.\d+)+))\b"
                      r"(?:[^\n]*:\s*$|\]?\s*(?:[:—–(-]|\s*$))")
    out, take = [], False
    stop = re.compile(r'^\s*("""|\'\'\'|import |from \S+ import |def |class )')
    for line in text.splitlines():
        if take and stop.match(line):          # журнал в шапке .pyw — дальше код
            break
        m = head.match(line)
        if m:
            v = m.group(1) or m.group(2)
            take = newer(v, current) and (upto is None or not newer(v, upto))
        if take:
            out.append(line.rstrip())
    res = "\n".join(out).strip()
    return res[:limit] + ("\n…" if len(res) > limit else "")


def _blob_sha1(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


DL_TRIES = 12          # попыток на источник; 3 подряд без прибавки — следующий


def _fetch(url, token, accept, buf, total, progress):
    """Одна попытка: дочитать url в buf с места len(buf) (Range).
    -> (total, прибавилось байт). Обрыв посреди — не ошибка: вызывающий
    докачает следующей попыткой."""
    got0 = len(buf)
    hdr = {"Range": "bytes=%d-" % got0} if got0 else None
    with _open(url, token, accept=accept, timeout=120, headers=hdr) as r:
        st = int(getattr(r, "status", 0) or getattr(r, "code", 0) or 200)
        if got0 and st != 206:
            del buf[:]                         # Range не понят — с начала
            got0 = 0
        if not total:
            n = int(r.headers.get("Content-Length") or 0)
            total = n + got0 if n else 0
        try:
            while True:
                chunk = r.read(65536)
                if not chunk:
                    break
                buf += chunk
                if progress:
                    progress(len(buf), total)
        except (OSError, ValueError, http.client.HTTPException):
            pass                               # обрыв посреди — докачаем
    return total, len(buf) - got0


def download(t, token, rel, progress=None):
    """Скачать архив во временный файл, сверить размер и sha. -> путь.
    ★ 1.1.2: по ссылке на файл (у API ответ рвётся через ~10 с), обрыв —
    докачка с места обрыва."""
    api = "%s/repos/%s/%s/contents/%s?ref=%s" % (
        API, t.owner, t.repo, urllib.parse.quote(rel.path),
        urllib.parse.quote(t.branch))
    url = rel.url
    try:                                       # ссылка живёт минуты — свежая
        fresh = latest(t, token)
        if fresh is not None and fresh.path == rel.path and fresh.url:
            url = fresh.url
    except Exception:                          # noqa: BLE001
        pass
    srcs = [(url, "application/octet-stream")] if url else []
    srcs.append((api, "application/vnd.github.raw"))
    buf = bytearray()
    total = rel.size or 0
    last = None
    for src, accept in srcs:
        idle = 0
        for _ in range(DL_TRIES):
            try:
                total, add = _fetch(src, token, accept, buf, total, progress)
            except UpdateError as e:
                last = e
                if len(buf) == 0 and e.code:   # ссылка не открылась вовсе
                    break
                add = 0
            except (OSError, ValueError, http.client.HTTPException) as e:
                last = UpdateError("нет связи с GitHub (%s)" % e)
                add = 0
            if total and len(buf) >= total:
                break
            idle = 0 if add > 0 else idle + 1
            if idle >= 3:
                break
            time.sleep(1.0)
        if total and len(buf) >= total:
            break
    data = bytes(buf)
    if rel.size and len(data) != rel.size:
        if not data and last is not None:
            raise last
        raise UpdateError("архив скачался не целиком (%d из %d байт)"
                          % (len(data), rel.size))
    if rel.sha and _blob_sha1(data) != rel.sha:
        raise UpdateError("контрольная сумма архива не совпала — "
                          "скачивание испорчено, обновление отменено")
    fd, path = tempfile.mkstemp(prefix=t.name + "_", suffix=".zip")
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    return path


# ---------------- установка ----------------

def _kept(rel_path, keep):
    p = rel_path.replace("\\", "/")
    return any(fnmatch.fnmatch(p, k) for k in keep)


def _safe(root, rel):
    dst = os.path.normpath(os.path.join(root, rel))
    if not (dst == root or dst.startswith(root + os.sep)):
        raise UpdateError("в архиве опасный путь: %s" % rel)
    return dst


def _keep_dir(name):
    return name.lower() in KEEP_DIRS


def stale_files(app_dir, new_files, keep=KEEP_DEFAULT):
    """★ 1.2.0: старые файлы кода, которых нет в новой версии -> список
    путей (относительно app_dir, через «/»). Только когда списка MANIFEST
    ещё нет. Смотрим только папки, которые есть в архиве (app/, tests/ …):
    корень (свои скрипты рядом с программой), папки данных (KEEP_DIRS) и
    виртуальные окружения (pyvenv.cfg) — мимо."""
    app_dir = os.path.abspath(app_dir)
    new = set(f.replace("\\", "/") for f in new_files)
    out = []
    tops = sorted(set(f.split("/", 1)[0] for f in new if "/" in f))
    for top in tops:
        root = os.path.join(app_dir, top)
        if _keep_dir(top) or not os.path.isdir(root):
            continue
        for dp, dns, fns in os.walk(root):
            if "pyvenv.cfg" in fns:
                dns[:] = []
                continue
            dns[:] = [d for d in dns if not _keep_dir(d)]
            for fn in fns:
                rel = os.path.relpath(os.path.join(dp, fn),
                                      app_dir).replace(os.sep, "/")
                if rel in new or _kept(rel, keep):
                    continue
                if os.path.splitext(fn)[1].lower() in CODE_EXT:
                    out.append(rel)
    return out


def read_manifest(app_dir):
    """Что поставило прошлое обновление -> set или None (списка нет)."""
    try:
        with open(os.path.join(app_dir, MANIFEST), encoding="utf-8") as fh:
            return set(x.strip().replace("\\", "/") for x in fh
                       if x.strip() and not x.startswith("#"))
    except OSError:
        return None


def write_manifest(app_dir, files):
    tmp = os.path.join(app_dir, MANIFEST + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("# gh_update: файлы, поставленные обновлением (не править)\n")
        fh.write("\n".join(sorted(files)) + "\n")
    os.replace(tmp, os.path.join(app_dir, MANIFEST))


def _drop_stale(app_dir, files, installed, keep, log):
    """Стереть старое -> список стёртого. Затем — новый список MANIFEST."""
    prev = read_manifest(app_dir)
    new = set(f.replace("\\", "/") for f in files)
    if prev is None:
        cand = stale_files(app_dir, files, keep)
    else:
        cand = sorted(r for r in prev - new if not _kept(r, keep))
    removed, dirs = [], set()
    for rel in cand:
        try:
            dst = _safe(app_dir, rel)
            if not os.path.isfile(dst):
                continue
            os.remove(dst)
        except (OSError, UpdateError) as exc:
            log("обновление: не стёр %s: %s" % (rel, exc))
            continue
        removed.append(rel)
        dirs.add(os.path.dirname(dst))
        # .pyc стёртого модуля
        stem, ext = os.path.splitext(os.path.basename(rel))
        pyc = os.path.join(os.path.dirname(dst), "__pycache__")
        if ext.lower() in (".py", ".pyw") and os.path.isdir(pyc):
            for x in os.listdir(pyc):
                if x.split(".", 1)[0] == stem and x.endswith(".pyc"):
                    try:
                        os.remove(os.path.join(pyc, x))
                        dirs.add(pyc)
                    except OSError:
                        pass
    # опустевшие папки — снизу вверх, до папки программы
    for d in sorted(dirs, key=len, reverse=True):
        while d != app_dir and d.startswith(app_dir + os.sep):
            try:
                os.rmdir(d)                        # только пустую
            except OSError:
                break
            d = os.path.dirname(d)
    try:
        write_manifest(app_dir, installed)
    except OSError as exc:
        log("обновление: список файлов не записан: %s" % exc)
    return removed


def drop_old_backup(app_dir, log=None):
    """★ 1.2.0: папка backup/ прежних обновлений (backup/v<версия>/…) —
    удалить. Только если в ней одни папки «v…» (чужое — не трогаем)."""
    b = os.path.join(os.path.abspath(app_dir), "backup")
    if not os.path.isdir(b):
        return False
    try:
        items = os.listdir(b)
        if any(not (x.lower().startswith("v")
                    and os.path.isdir(os.path.join(b, x))) for x in items):
            return False
        shutil.rmtree(b)
    except OSError as e:
        if log:
            log("обновление: старую папку backup не удалить: %s" % e)
        return False
    if log:
        log("обновление: старая папка backup удалена (резервных копий "
            "больше нет)")
    return True


def drop_leftovers(app_dir, gone=(), log=None):
    """★ 1.2.0: разово при запуске — то, что оставили обновления до 1.2.0:
    папка backup/ и модули, удалённые из программы (gone — пути вида
    «app/quick_fill.py»; заодно их .pyc в __pycache__). -> что стёрто."""
    app_dir = os.path.abspath(app_dir)
    out = []
    for rel in gone:
        d, fn = os.path.split(rel.replace("/", os.sep))
        stem = os.path.splitext(fn)[0]
        cands = [os.path.join(app_dir, d, fn)]
        pyc = os.path.join(app_dir, d, "__pycache__")
        if os.path.isdir(pyc):
            cands += [os.path.join(pyc, x) for x in os.listdir(pyc)
                      if x.split(".", 1)[0] == stem and x.endswith(".pyc")]
        for c in cands:
            if os.path.isfile(c):
                try:
                    os.remove(c)
                    out.append(os.path.relpath(c, app_dir))
                except OSError:
                    pass
    if out and log:
        log("обновление: стёрт старый код, оставшийся от прежних версий: "
            "%s" % ", ".join(x for x in out if not x.endswith(".pyc")))
    if drop_old_backup(app_dir, log):
        out.append("backup")
    return out


def install(t, zip_path, rel_version, log=None):
    """Поставить архив поверх t.app_dir. -> список заменённых файлов.
    ★ 1.2.0: старый код, которого нет в архиве, стирается (stale_files);
    t.removed — что стёрто."""
    log = log or (lambda *_a: None)
    app_dir = os.path.abspath(t.app_dir)
    stage = tempfile.mkdtemp(prefix=t.name + "_upd_")
    bdir = None
    try:
        with zipfile.ZipFile(zip_path) as z:
            bad = z.testzip()
            if bad:
                raise UpdateError("архив повреждён: %s" % bad)
            names = [n for n in z.namelist() if not n.endswith("/")]
            prefix = t.name + "/"
            if names and all(n.startswith(prefix) for n in names):
                strip = len(prefix)
            else:
                strip = 0
            files = []
            for n in names:
                rel = n[strip:]
                if not rel or "__pycache__" in rel:
                    continue
                dst = _safe(stage, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with z.open(n) as src, open(dst, "wb") as out:
                    shutil.copyfileobj(src, out)
                files.append(rel)
        if t.main_file not in files:
            raise UpdateError("в архиве нет %s — это не та программа" % t.main_file)
        # номер версии внутри архива должен совпасть с именем архива
        found = ""
        for cand in tuple(t.version_files) + ("app/version.py", "version.py",
                                               "VERSION", t.main_file):
            pth = os.path.join(stage, cand)
            if os.path.exists(pth):
                with open(pth, encoding="utf-8", errors="replace") as fh:
                    txt = fh.read()
                if os.path.basename(cand) == "VERSION":
                    m = re.match(r"\s*v?(\d+(?:\.\d+)*)\s*$", txt)
                else:
                    m = re.search(r'(?:APP_)?(?:VERSION|__version__)\s*=\s*'
                                  r'["\']v?(\d+(?:\.\d+)*)', txt)
                if m:
                    found = m.group(1)
                    break
        if found and vtuple(found) != vtuple(rel_version):
            raise UpdateError("внутри архива версия %s, а не %s — обновление "
                              "отменено" % (found, rel_version))
        # ★ 1.2.0: копия заменяемого — только на случай отката, во временной
        # папке (не в папке программы), после установки удаляется
        bdir = tempfile.mkdtemp(prefix=t.name + "_old_")
        todo = [f for f in files if not _kept(f, t.keep)]
        replaced = []
        try:
            for rel in todo:
                dst = _safe(app_dir, rel)
                if os.path.exists(dst):
                    b = _safe(bdir, rel)
                    os.makedirs(os.path.dirname(b), exist_ok=True)
                    shutil.copy2(dst, b)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                tmp = dst + ".upd"
                shutil.copy2(os.path.join(stage, rel), tmp)
                os.replace(tmp, dst)
                replaced.append(rel)
        except Exception as exc:                       # noqa: BLE001
            log("обновление: ошибка (%s) — возвращаю старые файлы" % exc)
            for rel in replaced:
                b = os.path.join(bdir, rel)
                dst = os.path.join(app_dir, rel)
                try:
                    if os.path.exists(b):
                        shutil.copy2(b, dst)
                    else:
                        os.remove(dst)
                except OSError:
                    pass
            raise UpdateError("не удалось заменить файлы (%s) — оставлена "
                              "прежняя версия" % exc) from exc
        # ★ 1.2.0: то, что ставили в прошлый раз и чего в новой версии нет,
        # — стереть (без списка — старый код по stale_files)
        removed = _drop_stale(app_dir, files, todo, t.keep, log)
        drop_old_backup(app_dir, log)
        t.removed = removed
        code = [r for r in removed if not r.endswith((".pyc", ".pyo"))]
        log("обновление: заменено файлов %d, стёрто старых %d%s"
            % (len(replaced), len(removed),
               (" (%s)" % ", ".join(code)[:400]) if code else ""))
        return replaced
    finally:
        shutil.rmtree(stage, ignore_errors=True)
        if bdir:
            shutil.rmtree(bdir, ignore_errors=True)
        try:
            os.remove(zip_path)
        except OSError:
            pass


# ---------------- перезапуск ----------------

def is_frozen():
    return bool(getattr(sys, "frozen", False))


def restart(argv=None):
    """Запустить программу заново (с --after-update <pid>). Закрыть текущую
    — дело вызывающего (обычно QApplication.quit() сразу после)."""
    argv = list(sys.argv if argv is None else argv)
    clean, skip = [], False
    for a in argv[1:]:
        if skip:
            skip = False
            continue
        if a == "--after-update":
            skip = True
            continue
        clean.append(a)
    exe = sys.executable
    if os.name == "nt" and exe.lower().endswith("python.exe"):
        w = exe[:-len("python.exe")] + "pythonw.exe"
        if os.path.exists(w):
            exe = w
    cmd = [exe] + ([] if is_frozen() else [os.path.abspath(argv[0])]) + clean \
        + ["--after-update", str(os.getpid())]
    flags = 0
    if os.name == "nt":
        flags = 0x00000008 | 0x00000200        # DETACHED_PROCESS | NEW_PROCESS_GROUP
    subprocess.Popen(cmd, cwd=os.path.dirname(os.path.abspath(argv[0])),
                     creationflags=flags, close_fds=True)
    return cmd


def wait_previous(argv=None, timeout=20.0):
    """Звать В САМОМ НАЧАЛЕ программы: если запущены после обновления —
    подождать, пока старая копия завершится. -> True, если ждали."""
    argv = sys.argv if argv is None else argv
    if "--after-update" not in argv:
        # ★ 1.3.1: прежняя сборка exe стирается и при обычном запуске —
        # раньше только при запуске с --after-update: закрыли новую раньше
        # чем через минуту — сотни МБ лежали до следующего обновления
        try:
            finish_exe_update()
        except Exception:                      # noqa: BLE001
            pass
        return False
    try:
        pid = int(argv[argv.index("--after-update") + 1])
    except (ValueError, IndexError):
        return False
    end = time.monotonic() + timeout
    while time.monotonic() < end and _alive(pid):
        time.sleep(0.25)
    try:                                       # ★ 1.3.0: после подмены exe
        finish_exe_update()
    except Exception:                          # noqa: BLE001
        pass
    return True


def _alive(pid):
    if os.name == "nt":
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x00100000 | 0x1000, False, pid)   # SYNCHRONIZE | QUERY_LIMITED
        if not h:
            return False
        try:
            return k32.WaitForSingleObject(h, 0) == 0x102            # WAIT_TIMEOUT
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
