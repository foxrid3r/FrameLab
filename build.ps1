$ErrorActionPreference = "Stop"

python -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --windowed `
    --name FrameLab `
    .\src\framelab\app.py