"""bump_version.py  v1.0.0 — общая утилита для всех проектов: подъём версии во всех местах сразу.

Журнал:
v1.0.0: первая версия (на основе bump_version.py SmartView 2.10.2): места версии — в release.json;
        проверка, что везде одна версия; шапки изменённых файлов; запись в журнал изменений.

Общая утилита: одинаковая во всех проектах. Правка — поднять версию и перенести файл ЦЕЛИКОМ
во все проекты. Где версия у проекта — в release.json (описание формата — в release.py).

Запуск (из папки репозитория):
    python bump_version.py                     # 2.0.0 -> 2.0.1 (единственная программа)
    python bump_version.py minor               # 2.0.0 -> 2.1.0
    python bump_version.py major               # 2.0.0 -> 3.0.0
    python bump_version.py 2.1.0               # задать явно
    python bump_version.py mini minor          # программа «mini» из release.json (если их несколько)
    python bump_version.py minor -m "Что сделано" -m "Ещё строка"    # + запись в журнал изменений
    python bump_version.py --check             # версии всех программ и расхождения
Если хоть в одном файле версия не найдена или не та — ничего не меняется (обойти: --force).
Версии вида X.Y и одно число тоже понимает: patch / minor поднимают последнюю / вторую часть.
"""
import datetime
import fnmatch
import os
import re
import subprocess
import sys

VERSION = "1.0.0"
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
import release as R          # noqa: E402 — release.json, шаблоны, чтение и запись файлов

HOW = ("patch", "minor", "major")
HEADER_RX = re.compile(r"\bv(\d+(?:\.\d+)+)\b")
HEADER_EXT = (".py", ".pyw", ".bat", ".cmd", ".spec", ".ps1")
# общие модули — со своей версией; их шапки программа не трогает (+ "headers_skip" в release.json)
SHARED = ("gh_update*.py", "test_gh_update.pyw", "app_icon*.py", "app_icon_pack_build.pyw", "safe_json.py",
          "app_log.py", "bump_version.py", "release.py", "check_leaks.py", "int_field.py",
          "window_frame.py", "dialog_frame.py", "win_frame.py")


def bump(cur, how):
    if re.fullmatch(r"\d+(?:\.\d+)*", how):
        return how
    if how not in HOW:
        # опечатка («mnior», «2.11.») не должна молча поднимать patch и править файлы
        raise R.ReleaseError(f"непонятно, как поднять версию: {how!r} (patch | minor | major | X.Y.Z)")
    parts = [int(x) for x in cur.split(".")]
    if how == "major" or len(parts) == 1:
        i = 0 if how == "major" else len(parts) - 1
    elif how == "minor":
        i = 1
    else:
        i = len(parts) - 1
    parts[i] += 1
    for j in range(i + 1, len(parts)):
        parts[j] = 0
    return ".".join(str(x) for x in parts)


def changed_files(prog, root=R.ROOT):
    """Изменённые (и новые, не в .gitignore) файлы программы — для шапок."""
    sub = (prog.get("dir") or "").strip("/\\") or "."
    out = R.git("diff", "--name-only", "HEAD", "--", sub, root=root, check=False).split("\n")
    out += R.git("ls-files", "--others", "--exclude-standard", "--", sub, root=root, check=False).split("\n")
    return sorted({p for p in out if p.strip() and p.lower().endswith(HEADER_EXT)})


def update_header(text, new):
    """В первых 3 строках — первое «vX.Y…» -> v<new>. (новый текст, было ли что менять)"""
    lines = text.split("\n")
    for i in range(min(3, len(lines))):
        m = HEADER_RX.search(lines[i])
        if m:
            if m.group(1) == new:
                return text, False
            lines[i] = lines[i][:m.start()] + "v" + new + lines[i][m.end():]
            return "\n".join(lines), True
    return text, False


def changelog_insert(text, cl, new, msgs):
    nl = "\r\n" if "\r\n" in text else "\n"
    tpl = cl.get("template", "{v}:\n- {msg}\n")
    tl = tpl.split("\n")
    body = []
    for line in tl:
        if "{msg}" in line:
            body.extend(line.replace("{msg}", m) for m in msgs)
        else:
            body.append(line)
    block = "\n".join(body).replace("{v}", new).replace(
        "{date}", datetime.date.today().isoformat()).replace("\n", nl)
    lines = text.split(nl)

    def find(spec):
        rx = re.compile(spec[3:]) if spec.startswith("re:") else None
        for i, line in enumerate(lines):
            if (rx.search(line) if rx else spec in line):
                return i
        return None

    if cl.get("before"):
        i = find(cl["before"])
        if i is None:
            raise R.ReleaseError(f"{cl['file']}: строка {cl['before']!r} не найдена")
        pos = i
    elif cl.get("after"):
        i = find(cl["after"])
        if i is None:
            raise R.ReleaseError(f"{cl['file']}: строка {cl['after']!r} не найдена")
        pos = i + 1
    else:
        pos = 0
    head = nl.join(lines[:pos])
    tail = nl.join(lines[pos:])
    return (head + nl if pos else "") + block + tail


def plan(prog, how, msgs, root=R.ROOT, force=False):
    """Все правки заранее: {путь: (текст, кодировка, BOM)}, старая и новая версия, заметки."""
    cur, bad = R.check_versions(prog, root)
    new = bump(cur, how)
    if new == cur:
        raise R.ReleaseError(f"версия уже {cur}")
    if bad and not force:
        raise R.ReleaseError("версии не совпадают — ничего не меняю (обойти: --force):\n  "
                             + "\n  ".join(f"{p}: {t}" for p, t in bad))
    edits, notes = {}, []

    def get(path):
        full = os.path.join(root, path)
        if path not in edits:
            edits[path] = list(R.read_text(full))
        return edits[path]

    for e in prog["files"]:
        path, pat, count = R.entry(e)
        if not os.path.exists(os.path.join(root, path)):
            notes.append(f"{path}: нет файла — пропущен")
            continue
        rec = get(path)
        rx = R.compile_pattern(pat)
        rec[0], n = rx.subn(lambda m: m.group(0)[:m.start("v") - m.start()] + new
                            + m.group(0)[m.end("v") - m.start():], rec[0], count=count)
        notes.append(f"{path}: {'обновлён' if n else 'версия не найдена'}")
    if prog.get("headers"):
        skip = SHARED + tuple(prog.get("headers_skip", ()))
        for path in changed_files(prog, root):
            if any(fnmatch.fnmatch(os.path.basename(path), g) or fnmatch.fnmatch(path, g) for g in skip):
                continue
            full = os.path.join(root, path)
            if not os.path.isfile(full):
                continue
            rec = get(path)
            rec[0], ch = update_header(rec[0], new)
            if ch:
                notes.append(f"{path}: шапка -> v{new}")
    cl = prog.get("changelog")
    if cl and msgs:
        rec = get(cl["file"])
        rec[0] = changelog_insert(rec[0], cl, new, msgs)
        notes.append(f"{cl['file']}: запись о {new}")
    elif cl:
        notes.append(f"{cl['file']}: запись о {new} — допишите (или -m \"текст\")")
    return cur, new, edits, notes


def apply(edits, root=R.ROOT):
    for path, (text, enc, bom) in edits.items():
        R.write_text(os.path.join(root, path), text, enc, bom)


# ----------------------------------------------------------------- самопроверка
def selftest():
    import tempfile
    errs = []

    def check(cond, text):
        if not cond:
            errs.append(text)

    for cur, how, want in (("1.2.3", "patch", "1.2.4"), ("1.2.3", "minor", "1.3.0"), ("1.2.3", "major", "2.0.0"),
                           ("2.13", "patch", "2.14"), ("2.13", "minor", "2.14"), ("516", "minor", "517"),
                           ("5.65", "major", "6.0"), ("1.2.3", "4.0.0", "4.0.0")):
        got = bump(cur, how)
        check(got == want, f"bump({cur}, {how}) = {got}, а нужно {want}")
    try:
        bump("1.2.3", "mnior")
        errs.append("опечатка — должна быть ошибка")
    except R.ReleaseError:
        pass
    with tempfile.TemporaryDirectory() as d:
        def run(*a):
            subprocess.run(["git", "-C", d, *a], check=True, capture_output=True)
        files = {"VERSION": "1.2.0\n", "app.py": '"""app.py  v1.1.0\nЖурнал:\nv1.1.0: было\n"""\nVERSION = "1.2.0"\n',
                 "lib.py": '"""lib.py  v1.0.5 — модуль\n"""\nx = 1\n',
                 "safe_json.py": '"""safe_json.py  v1.0.0 — общий\n"""\n',
                 "build.bat": "@echo off\r\nchcp 65001\r\necho App v1.2.0\r\n",
                 "CHANGELOG.txt": "История\n=======\n\n1.2.0:\n- старое\n"}
        for fn, text in files.items():
            with open(os.path.join(d, fn), "w", encoding="utf-8", newline="") as f:
                f.write(text)
        run("init", "-q")
        run("config", "user.email", "t@t")
        run("config", "user.name", "t")
        run("add", "-A")
        run("commit", "-qm", "init")
        for fn in ("app.py", "safe_json.py"):
            with open(os.path.join(d, fn), "a", encoding="utf-8") as f:
                f.write("# правка\n")
        prog = {"name": "app", "files": [["VERSION", "{v}"], ["app.py", 'VERSION = "{v}"'], ["build.bat", "App v{v}"]],
                "headers": True, "changelog": {"file": "CHANGELOG.txt", "before": "re:^\\d+\\.\\d+",
                                               "template": "{v}:\n- {msg}\n"}}
        cur, new, edits, notes = plan(prog, "minor", ["новое", "ещё"], root=d)
        apply(edits, root=d)
        rd = lambda fn: open(os.path.join(d, fn), encoding="utf-8", newline="").read()   # noqa: E731
        check(cur == "1.2.0" and new == "1.3.0", f"{cur} -> {new}")
        check(rd("VERSION") == "1.3.0\n", "VERSION")
        check('VERSION = "1.3.0"' in rd("app.py") and rd("app.py").startswith('"""app.py  v1.3.0\n'),
              "app.py: константа и шапка")
        check("v1.1.0: было" in rd("app.py"), "строка журнала в шапке не тронута")
        check(rd("lib.py").startswith('"""lib.py  v1.0.5'), "шапка НЕизменённого файла не тронута")
        check(rd("safe_json.py").startswith('"""safe_json.py  v1.0.0'), "шапка общего модуля не тронута")
        check(rd("build.bat") == "@echo off\r\nchcp 65001\r\necho App v1.3.0\r\n", "bat: CRLF сохранён")
        check(rd("CHANGELOG.txt") == "История\n=======\n\n1.3.0:\n- новое\n- ещё\n1.2.0:\n- старое\n",
              "журнал изменений: " + repr(rd("CHANGELOG.txt")))
        # расхождение — ничего не меняется
        with open(os.path.join(d, "build.bat"), "w", encoding="utf-8", newline="") as f:
            f.write("echo App v1.0.0\r\n")
        try:
            plan(prog, "patch", [], root=d)
            errs.append("расхождение версий — должна быть ошибка")
        except R.ReleaseError as e:
            check("build.bat" in str(e), f"в ошибке нет файла: {e}")
        check(rd("VERSION") == "1.3.0\n", "при ошибке файлы не тронуты")
    return errs


def main(argv):
    if "--selftest" in argv:
        problems = selftest()
        print(f"bump_version {VERSION}: " + ("OK" if not problems else "ОШИБКИ:\n  " + "\n  ".join(problems)))
        return 1 if problems else 0
    if "--check" in argv:
        return R.main(["--check"])
    msgs, rest, force = [], [], False
    it = iter(argv)
    for a in it:
        if a == "-m":
            msgs.append(next(it, ""))
        elif a == "--force":
            force = True
        else:
            rest.append(a)
    try:
        cfg = R.load_config()
        names = {p["name"] for p in cfg["programs"]}
        prog_names = [a for a in rest if a in names]
        hows = [a for a in rest if a not in names]
        if len(hows) > 1:
            raise R.ReleaseError("лишние аргументы: " + " ".join(hows))
        how = hows[0] if hows else "patch"
        progs = R.pick(cfg, prog_names)
        for p in progs:
            cur, new, edits, notes = plan(p, how, msgs, force=force)
            apply(edits)
            print(f"{p['name']}: {cur} -> {new}")
            for n in notes:
                print("  " + n)
        print("Шапки остальных изменённых файлов и описание — проверьте вручную; потом commit и"
              " python release.py")
    except R.ReleaseError as e:
        print(f"ОШИБКА: {e} — файлы не тронуты")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
