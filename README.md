# FrameLab

FrameLab is a Windows application for frame-accurate video navigation, trimming, and image extraction. It is designed for machine vision and industrial automation workflows where precise frame selection and repeatable exports are important.

## Features

* Frame-by-frame video navigation
* Trim and export video clips
* Export individual frames or frame ranges
* Optional monochrome image export
* Copy the current frame directly to the clipboard
* Modern, responsive user interface

## Installation

Download the latest release from the project's **Releases** page and extract the ZIP file.

Run:

```text
FrameLab.exe
```

No Python installation is required.

## System Requirements

* Windows 10 or Windows 11
* 64-bit operating system

## Documentation

User documentation will be available in the project Wiki.

---

# Development

## Requirements

* Python 3.11

## Create a Development Environment

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install -e .
python -m pip install pyinstaller
```

Run from source:

```powershell
python -m framelab
```

## Build

Create a standalone executable:

```powershell
python -m PyInstaller --clean FrameLab.spec
```

The packaged application will be generated in:

```text
dist\FrameLab\
```

Run the packaged version:

```powershell
.\dist\FrameLab\FrameLab.exe
```

## Project Structure

```text
FrameLab/
├── src/
├── pyproject.toml
├── FrameLab.spec
├── README.md
├── .venv/      (generated)
├── build/      (generated)
└── dist/       (generated)
```

The `.venv`, `build`, and `dist` directories are generated automatically and should not be committed to Git.

## Technologies

* Python 3.11
* Tkinter
* OpenCV
* Pillow
* NumPy
* imageio-ffmpeg
* sv_ttk
* PyInstaller
