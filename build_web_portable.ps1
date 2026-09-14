param([switch]$SkipBrowserInstall)

$ErrorActionPreference = "Stop"
$AppName = "ChatGPT Batch Translator Web"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$DistApp = Join-Path $Root "dist\$AppName"
$WorkPath = Join-Path $Root "build\web"
Set-Location $Root

$PythonExe = $env:PYTHON_EXE
if (-not $PythonExe) {
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($command) { $PythonExe = $command.Source }
}
if (-not $PythonExe) {
    $PythonExe = Get-ChildItem -Path "$env:LOCALAPPDATA\Programs\Python" -Filter python.exe -Recurse -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending |
        Select-Object -ExpandProperty FullName -First 1
}
if (-not $PythonExe -or -not (Test-Path -LiteralPath $PythonExe)) {
    throw "Python was not found. Set PYTHON_EXE to a Python 3.9+ executable."
}

function Invoke-Python {
    & $PythonExe @args
    if ($LASTEXITCODE -ne 0) { throw "Python command failed with exit code $LASTEXITCODE." }
}

Invoke-Python -m pip install -r requirements.txt
if (Test-Path -LiteralPath $DistApp) { Remove-Item -LiteralPath $DistApp -Recurse -Force }
if (Test-Path -LiteralPath $WorkPath) { Remove-Item -LiteralPath $WorkPath -Recurse -Force }

Invoke-Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --windowed `
    --noupx `
    --name "$AppName" `
    --workpath $WorkPath `
    --specpath $WorkPath `
    --icon (Join-Path $Root "assets\app-icon.ico") `
    --add-data "$(Join-Path $Root 'ui');ui" `
    --add-data "$(Join-Path $Root 'assets\app-icon.png');assets" `
    --collect-all webview `
    --collect-all playwright `
    --hidden-import run_chatgpt_batch `
    --hidden-import pygetwindow `
    --hidden-import win32process `
    --hidden-import sqlite3 `
    --collect-binaries sqlite3 `
    desktop\webview_app.py

$PythonRoot = (& $PythonExe -c "import sys; print(sys.prefix)").Trim()
$SqliteDll = @(
    (Join-Path $PythonRoot "DLLs\sqlite3.dll"),
    (Join-Path $PythonRoot "Library\bin\sqlite3.dll"),
    (Join-Path $PythonRoot "sqlite3.dll")
) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $SqliteDll) { throw "sqlite3.dll was not found in the selected Python runtime: $PythonRoot" }
Copy-Item -LiteralPath $SqliteDll -Destination $DistApp -Force

if (-not $SkipBrowserInstall) {
    $env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $DistApp "ms-playwright"
    Invoke-Python -m playwright install chromium
}

$Exe = Join-Path $DistApp "$AppName.exe"
if (-not (Test-Path -LiteralPath $Exe)) { throw "PyInstaller did not create $Exe" }
Write-Host "Alternate web shell built at: $Exe"
