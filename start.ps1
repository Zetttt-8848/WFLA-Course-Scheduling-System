$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONUTF8 = '1'
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    $launcher = Get-Command python -ErrorAction SilentlyContinue
    if (-not $launcher) { throw 'Install Python 3.11-3.13 and enable Add Python to PATH, then run again.' }
    & $launcher.Source -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create Python environment.' }
}
& $taskPython -X utf8 -m pip install --disable-pip-version-check --progress-bar off -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check internet access and try again.' }
& $taskPython -X utf8 run.py --open
