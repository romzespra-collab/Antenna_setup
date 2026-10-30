# setup.ps1  v0.2.3 — ставит Python (с python.org, без winget) и PySide6, проверяет и запускает программу
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $here
try { $Host.UI.RawUI.WindowTitle = 'Настройка антенны - установка' } catch {}
try { Start-Transcript -Path (Join-Path $here 'setup.log') -Force | Out-Null } catch {}

function Find-Pythonw {
    $c = Get-Command pythonw.exe -ErrorAction SilentlyContinue |
        Where-Object { $_.Source -notmatch 'WindowsApps' } | Select-Object -First 1
    if ($c) { return $c.Source }
    foreach ($d in @("$env:LOCALAPPDATA\Programs\Python", $env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if (-not $d -or -not (Test-Path -LiteralPath $d)) { continue }
        $hit = Get-ChildItem -LiteralPath $d -Directory -Filter 'Python3*' -ErrorAction SilentlyContinue |
            Sort-Object { [int](($_.Name -replace '^Python(\d+).*$', '$1') -replace '\D', '0') } -Descending |
            ForEach-Object { Join-Path $_.FullName 'pythonw.exe' } |
            Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
        if ($hit) { return $hit }
    }
    return $null
}

function Install-Python {
    $ver = '3.12.8'
    $arch = if ([Environment]::Is64BitOperatingSystem) { '-amd64' } else { '' }
    $url = "https://www.python.org/ftp/python/$ver/python-$ver$arch.exe"
    $exe = Join-Path $env:TEMP "python-$ver-setup.exe"
    Write-Host "Python не найден. Скачиваю Python $ver с python.org (27 МБ) ..."
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $exe
    Write-Host 'Ставлю Python, 1-2 минуты, окно не закрывай ...'
    $p = Start-Process -FilePath $exe -ArgumentList '/quiet', 'InstallAllUsers=0', 'PrependPath=1', 'Include_launcher=1', 'Include_test=0' -Wait -PassThru
    Remove-Item -LiteralPath $exe -ErrorAction SilentlyContinue
    if ($p.ExitCode -ne 0) { throw "установщик Python вернул код $($p.ExitCode)" }
}

try {
    $pyw = Find-Pythonw
    if (-not $pyw) { Install-Python; $pyw = Find-Pythonw }
    if (-not $pyw) { throw 'Python не найден и после установки.' }
    $py = Join-Path (Split-Path -Parent $pyw) 'python.exe'
    Write-Host "Python: $py"
    & $py --version

    Write-Host 'Ставлю PySide6 (один раз, может занять пару минут) ...'
    $req = Join-Path $here 'requirements.txt'
    & $py -m pip install --disable-pip-version-check --upgrade -r $req
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Пробую ещё раз (ensurepip, --user) ...'
        & $py -m ensurepip --upgrade
        & $py -m pip install --disable-pip-version-check --user --upgrade -r $req
        if ($LASTEXITCODE -ne 0) { throw 'pip не смог поставить PySide6 — проверь интернет.' }
    }

    Write-Host 'Самопроверка программы ...'
    $app = Join-Path $here 'antenna_setup.pyw'
    & $py $app --selftest
    $selfOk = ($LASTEXITCODE -eq 0)

    Write-Host 'Запускаю программу ...' -ForegroundColor Green
    Start-Process -FilePath $pyw -ArgumentList ('"' + $app + '"') -WorkingDirectory $here
    Start-Sleep -Seconds 3
    try { Stop-Transcript | Out-Null } catch {}
    if (-not $selfOk) {
        Write-Host 'ВНИМАНИЕ: самопроверка нашла ошибки (строки с ✗ выше). Сфотографируй это окно.' -ForegroundColor Yellow
        exit 1
    }
    exit 0
}
catch {
    Write-Host ''
    Write-Host "ОШИБКА: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'Сфотографируй это окно или пришли файл setup.log из папки программы.'
    try { Stop-Transcript | Out-Null } catch {}
    exit 1
}
