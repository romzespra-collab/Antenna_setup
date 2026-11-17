"""safe_json.py  v1.0.0 — общий модуль для всех проектов: надёжное чтение и запись JSON
(config.json, файлы состояния).

Журнал:
v1.0.0: первая версия: load / save / AutoSaver / start_autosave.

Общий модуль: одинаковый во всех проектах. Правка — поднять версию в шапке и в VERSION ниже,
затем перенести файл ЦЕЛИКОМ во все проекты (свежий — с большим номером).

Правила:
- запись атомарная: <файл>.<pid>-<n>.tmp -> os.replace; повтор, если файл держат антивирус /
  OneDrive / вторая копия программы (WinError 5 / 32);
- перед заменой прежний ЦЕЛЫЙ файл копируется в <файл>.bak (тоже атомарно);
- чтение — с повтором (файл держат) и utf-8-sig (файл правили Блокнотом с BOM);
- битый JSON не читается как пустой: берётся <файл>.bak; копия битого — <файл>.bad-<время>;
  если и .bak нет / битый — настройки по умолчанию, а сам файл НЕ перезаписывается
  (save -> False), пока его не исправят или не удалят;
- файл есть, но не читается совсем (нет прав, занят) — то же: значения по умолчанию, запись запрещена.

API:
    data = safe_json.load(path, default)     # default копируется (deepcopy); тип проверяется по default
    ok = safe_json.save(path, data)          # True / False; причина — safe_json.last_error(path)
    safe_json.is_protected(path)             # файл испорчен / не читался — запись запрещена
    saver = safe_json.AutoSaver(path, get_data, every=10)   # пишет, только если данные изменились
    saver.mark_saved(data)                   # после load: «это уже на диске»
    saver.tick() / saver.flush()             # по таймеру / при закрытии
    timer = safe_json.start_autosave(window, saver)          # QTimer раз в every с + запись при выходе

Журнал модуля — logging.getLogger("safe_json") (app_log.setup подключает его к журналу программы).
"""
import copy
import json
import logging
import os
import shutil
import threading
import time

VERSION = "1.0.0"

log = logging.getLogger("safe_json")

_lock = threading.RLock()
_protected = {}      # ключ пути -> почему запись запрещена
_errors = {}         # ключ пути -> текст последней ошибки
_good = set()        # ключи путей, где на диске — целый файл (прочитан или записан нами)
_tmp_n = 0


def _key(path):
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _is_busy(e):
    """Файл держит другой процесс (WinError 5 / 32) — стоит повторить."""
    return isinstance(e, PermissionError) or getattr(e, "winerror", None) in (5, 32, 33)


def _read_text(path, tries=5):
    """Текст файла. FileNotFoundError — как есть; не читается после повторов — OSError;
    не UTF-8 — ValueError (содержимое испорчено)."""
    last = None
    for i in range(tries):
        try:
            with open(path, "rb") as f:
                raw = f.read()
            try:
                return raw.decode("utf-8-sig")
            except UnicodeDecodeError as e:
                raise ValueError(f"не UTF-8: {e}") from None
        except FileNotFoundError:
            raise
        except OSError as e:
            last = e
            time.sleep(0.2 * (i + 1))
    raise last


def _kind_of(default, kind):
    if kind is not None:
        return kind
    if isinstance(default, (dict, list)):
        return type(default)
    return None


def _parse(text, kind):
    """(True, данные) или (False, причина)."""
    try:
        data = json.loads(text)
    except ValueError as e:
        return False, f"битый JSON: {e}"
    if kind is not None and not isinstance(data, kind):
        return False, f"ожидался {kind.__name__}, а в файле {type(data).__name__}"
    return True, data


def _keep_bad_copy(path):
    """Копия испорченного файла рядом: <файл>.bad-<время> (байт в байт). Имя копии или None."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    bad = f"{path}.bad-{stamp}"
    n = 1
    while os.path.exists(bad):
        n += 1
        bad = f"{path}.bad-{stamp}-{n}"
    try:
        shutil.copyfile(path, bad)
        return bad
    except OSError as e:
        log.error("копию испорченного %s не сделать: %s", path, e)
        return None


def load(path, default=None, *, bak=True, kind=None):
    """Прочитать JSON. Нет файла — копия default. Испорчен — .bak, иначе default и запрет записи.
    kind — нужный тип (dict / list); по умолчанию — тип default, если это dict / list."""
    p = os.fspath(path)
    k = _key(p)
    want = _kind_of(default, kind)
    with _lock:
        _protected.pop(k, None)
        _errors.pop(k, None)
        _good.discard(k)
        try:
            text = _read_text(p)
        except FileNotFoundError:
            return copy.deepcopy(default)
        except ValueError as e:          # не UTF-8 — как битый JSON
            reason = str(e)
        except OSError as e:
            _protected[k] = f"файл не читается: {e}"
            _errors[k] = _protected[k]
            log.error("%s не читается (%s) — значения по умолчанию, файл не перезаписываю", p, e)
            return copy.deepcopy(default)
        else:
            ok, res = _parse(text, want)
            if ok:
                _good.add(k)
                return res
            reason = res
        # файл испорчен
        bad_copy = _keep_bad_copy(p)
        if bak and os.path.exists(p + ".bak"):
            try:
                ok, res = _parse(_read_text(p + ".bak"), want)
            except (OSError, ValueError) as e:
                ok, res = False, str(e)
            if ok:
                log.warning("%s испорчен (%s) — взята резервная копия .bak%s", p, reason,
                            f"; испорченный сохранён: {os.path.basename(bad_copy)}" if bad_copy else "")
                if not bad_copy:
                    # копию испорченного не сделать — его не затираем
                    _protected[k] = "испорченный файл не удалось сохранить в копию"
                return res
        _protected[k] = (f"файл испорчен ({reason}); исправьте или удалите его"
                         + (f" (копия: {os.path.basename(bad_copy)})" if bad_copy else ""))
        _errors[k] = _protected[k]
        log.error("%s: %s — значения по умолчанию, файл не перезаписываю", p, _protected[k])
        return copy.deepcopy(default)


def is_protected(path):
    return _key(path) in _protected


def last_error(path):
    return _errors.get(_key(path), "")


def _still_protected(p, k):
    """Запрет снимается, если файл удалили или исправили."""
    if not os.path.exists(p):
        return False
    try:
        ok, _ = _parse(_read_text(p, tries=1), None)
    except (OSError, ValueError):
        return True
    return not ok


def dumps(data, indent=2):
    return json.dumps(data, ensure_ascii=False, indent=indent)


def _replace(src, dst, tries=8):
    for i in range(tries):
        try:
            os.replace(src, dst)
            return
        except OSError as e:
            if not _is_busy(e) or i == tries - 1:
                raise
            time.sleep(0.05 * (i + 1))


def _backup(p, k):
    """Прежний целый файл -> <файл>.bak (через .tmp и replace). Ошибка копии не мешает записи."""
    if not os.path.exists(p):
        return
    if k not in _good:
        try:
            ok, _ = _parse(_read_text(p, tries=2), None)
        except (OSError, ValueError):
            ok = False
        if not ok:
            return                      # испорченный файл в .bak не кладём
    tmp = _tmp_name(p + ".bak")
    try:
        shutil.copyfile(p, tmp)
        _replace(tmp, p + ".bak")
    except OSError as e:
        log.warning("резервная копия %s.bak не сделана: %s", p, e)
        try:
            os.remove(tmp)
        except OSError:
            pass


def _tmp_name(p):
    global _tmp_n
    _tmp_n += 1
    return f"{p}.{os.getpid()}-{_tmp_n}.tmp"


def save_text(path, text, *, bak=True):
    """Записать готовый текст JSON атомарно. True / False (причина — last_error)."""
    p = os.fspath(path)
    k = _key(p)
    with _lock:
        if k in _protected:
            if _still_protected(p, k):
                _errors[k] = _protected[k]
                return False
            log.info("%s исправлен или удалён — запись снова разрешена", p)
            _protected.pop(k, None)
        d = os.path.dirname(os.path.abspath(p))
        tmp = _tmp_name(p)
        try:
            os.makedirs(d, exist_ok=True)
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            if bak:
                _backup(p, k)
            _replace(tmp, p)
        except OSError as e:
            _errors[k] = str(e)
            _good.discard(k)
            log.error("%s НЕ сохранён: %s", p, e)
            try:
                os.remove(tmp)
            except OSError:
                pass
            return False
        _errors.pop(k, None)
        _good.add(k)
        return True


def save(path, data, *, bak=True, indent=2):
    """Записать данные атомарно. Не сериализуется — False, файл не тронут."""
    try:
        text = dumps(data, indent)
    except (TypeError, ValueError) as e:
        _errors[_key(path)] = f"данные не записать в JSON: {e}"
        log.error("%s НЕ сохранён: %s", os.fspath(path), _errors[_key(path)])
        return False
    return save_text(path, text, bak=bak)


class AutoSaver:
    """Автосохранение: tick() пишет файл, только если данные изменились (и не чаще every с)."""

    def __init__(self, path, get_data, every=10.0, *, bak=True, indent=2):
        self.path = path
        self.get_data = get_data
        self.every = float(every)
        self.bak = bak
        self.indent = indent
        self._last = None
        self._next = 0.0

    def mark_saved(self, data=None):
        """Данные уже на диске (сразу после load) — первый tick не пишет без изменений."""
        try:
            self._last = dumps(self.get_data() if data is None else data, self.indent)
        except (TypeError, ValueError):
            self._last = None

    def changed(self):
        try:
            return dumps(self.get_data(), self.indent) != self._last
        except (TypeError, ValueError):
            return True

    def tick(self, force=False):
        """None — писать нечего / рано; True / False — итог записи."""
        now = time.monotonic()
        if not force and now < self._next:
            return None
        self._next = now + self.every
        try:
            text = dumps(self.get_data(), self.indent)
        except Exception as e:                      # noqa: BLE001 — данные программы
            log.error("%s: данные не собрать для записи: %s", os.fspath(self.path), e)
            return False
        if text == self._last:
            return None
        ok = save_text(self.path, text, bak=self.bak)
        if ok:
            self._last = text
        return ok

    def flush(self):
        return self.tick(force=True)


def start_autosave(parent, saver):
    """QTimer (PySide6) раз в saver.every с + запись при выходе из программы. Возвращает таймер."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    t = QTimer(parent)
    t.setInterval(max(1000, int(saver.every * 1000)))
    t.timeout.connect(lambda: saver.tick(force=True))
    t.start()
    app = QApplication.instance()
    if app is not None:
        app.aboutToQuit.connect(saver.flush)
    return t


# ----------------------------------------------------------------- самопроверка
def selftest():
    """Пустой список — всё в порядке, иначе — тексты ошибок."""
    errs = []

    def check(cond, text):
        if not cond:
            errs.append(text)

    was = log.disabled
    log.disabled = True              # проверочные «ошибки» — не в журнал программы
    try:
        _selftest_body(check)
    finally:
        log.disabled = was
    return errs


def _selftest_body(check):
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "sub", "config.json")
        dflt = {"a": 1, "list": [1]}
        x = load(p, dflt)
        check(x == dflt and x is not dflt and x["list"] is not dflt["list"], "нет файла -> копия default")
        check(save(p, {"a": 2, "т": "я"}), "первая запись")
        check(load(p, dflt) == {"a": 2, "т": "я"}, "чтение записанного")
        check(not os.path.exists(p + ".bak"), "нет .bak до второй записи")
        check(save(p, {"a": 3}), "вторая запись")
        check(load(p + ".bak", {}) == {"a": 2, "т": "я"}, ".bak — прежняя версия")
        check(not [f for f in os.listdir(os.path.dirname(p)) if f.endswith(".tmp")], "нет .tmp после записи")
        # BOM (Блокнот)
        with open(p, "w", encoding="utf-8-sig") as f:
            f.write('{"a": 4}')
        check(load(p, dflt) == {"a": 4}, "utf-8-sig")
        check(save(p, {"a": 5}), "запись после BOM")
        # битый -> .bak
        with open(p, "w", encoding="utf-8") as f:
            f.write('{"a": 6,')
        x = load(p, dflt)
        check(x == {"a": 4}, f"битый -> .bak (получено {x})")
        check(any(".bad-" in f for f in os.listdir(os.path.dirname(p))), "копия битого .bad-")
        check(not is_protected(p), "с целым .bak запись разрешена")
        check(save(p, {"a": 7}) and load(p, dflt) == {"a": 7}, "запись после восстановления из .bak")
        # битый и .bak битый -> default + запрет записи
        with open(p, "w", encoding="utf-8") as f:
            f.write("мусор")
        with open(p + ".bak", "w", encoding="utf-8") as f:
            f.write("[")
        x = load(p, dflt)
        check(x == dflt, "битый без .bak -> default")
        check(is_protected(p) and not save(p, {"a": 8}), "битый без .bak -> запись запрещена")
        with open(p, encoding="utf-8") as f:
            check(f.read() == "мусор", "испорченный файл не затёрт")
        check("испорчен" in last_error(p), "причина в last_error")
        os.remove(p)
        check(save(p, {"a": 9}) and not is_protected(p), "файл удалён -> запись снова можно")
        # не тот тип
        with open(p, "w", encoding="utf-8") as f:
            f.write("[1, 2]")
        x = load(p, dflt)
        check(x == {"a": 9} or x == dflt, "список вместо словаря -> .bak / default")
        # не UTF-8 -> как битый: копия байт в байт, .bak
        check(save(p, {"a": 10}) and save(p, {"a": 11}), "две записи перед не-UTF-8")
        with open(p, "wb") as f:
            f.write(b'{"a": "\xff"}')
        check(load(p, dflt) == {"a": 10}, "не UTF-8 -> .bak")
        bads = [f for f in os.listdir(os.path.dirname(p)) if ".bad-" in f]
        check(any(open(os.path.join(os.path.dirname(p), f), "rb").read() == b'{"a": "\xff"}' for f in bads),
              "копия не-UTF-8 байт в байт")
        # не сериализуется
        check(not save(os.path.join(d, "b.json"), {"x": object()}), "несериализуемое -> False")
        check(not os.path.exists(os.path.join(d, "b.json")), "несериализуемое -> файла нет")
        # AutoSaver
        state = {"n": 1}
        q = os.path.join(d, "state.json")
        s = AutoSaver(q, lambda: state, every=100)
        s.mark_saved()
        check(s.tick(force=True) is None and not os.path.exists(q), "AutoSaver: без изменений не пишет")
        state["n"] = 2
        check(s.changed(), "AutoSaver.changed")
        check(s.tick(force=True) is True and load(q, {}) == {"n": 2}, "AutoSaver пишет изменения")
        check(s.tick() is None, "AutoSaver: не чаще every")
        state["n"] = 3
        check(s.flush() is True and load(q, {}) == {"n": 3}, "AutoSaver.flush")


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.CRITICAL)
    problems = selftest()
    print(f"safe_json {VERSION}: " + ("OK" if not problems else "ОШИБКИ:\n  " + "\n  ".join(problems)))
    sys.exit(1 if problems else 0)
