$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Missing .venv. Create it with Python 3.14 and install the build dependencies first."
}

& $python -c "import sys; assert sys.version_info[:2] == (3, 14), f'FrameLab releases require Python 3.14, found {sys.version.split()[0]}'; import tkinter; tkinter.Tcl()"

& $python (Join-Path $repoRoot "tools\collect_release_licenses.py") `
    --output (Join-Path $repoRoot "release-licenses")

Push-Location $repoRoot
try {
    & $python -m PyInstaller `
        --noconfirm `
        --clean `
        (Join-Path $PSScriptRoot "FrameLab.spec")
}
finally {
    Pop-Location
}
