$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $true

python .\tools\collect_release_licenses.py `
    --output .\release-licenses

python -m PyInstaller `
    --noconfirm `
    --clean `
    .\FrameLab.spec
