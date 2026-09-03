# Building FrameLab

## Development environment

FrameLab supports Python 3.11 or later for development. From the repository
root, create a virtual environment and install the project with its build
tools:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[build]"
```

Run FrameLab from source:

```powershell
python -m framelab
```

When running from source, FrameLab uses `vendor\ffmpeg\ffmpeg.exe` when it is
available and otherwise looks for FFmpeg on `PATH`.

## Reproducible Windows release

Official release builds use Python 3.14 and the exact package versions pinned
in `requirements-release.txt`:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-release.txt
.\tools\release\package-release.ps1
```

The packaging script builds the application and creates versioned application
and corresponding-source archives under `release\`, together with SHA-256
checksums.

To build the unpackaged application without creating release archives, run:

```powershell
.\tools\release\build.ps1
```

The output is written to `dist\FrameLab\`.

## Bundled FFmpeg

Release builds bundle the pinned FFmpeg executable in `vendor\ffmpeg`. Its
license texts and sanitized build information are included in the application.
The reproducible MSYS2 build recipe is `tools/build_minimal_ffmpeg.sh`.

Run that script from the repository root in an MSYS2 UCRT64 shell. It produces
the executable, license files, build information, corresponding source
archives, and checksums under `build/ffmpeg-minimal/dist`.

See [Third-Party Notices](../THIRD-PARTY-NOTICES.md) for redistribution details.

## Repository layout

```text
FrameLab/
├── docs/                     User and build documentation
├── src/framelab/             Application source
├── tools/release/            Windows build and packaging scripts
├── tools/                    Supporting build and development utilities
├── vendor/ffmpeg/            Bundled FFmpeg executable and notices
├── pyproject.toml            Project metadata and development dependencies
└── requirements-release.txt Pinned release environment
```
