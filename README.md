# FrameLab

FrameLab is a Windows desktop application for frame-accurate video inspection, trimming, slow-motion export, and frame extraction.

## Features

* Frame-by-frame video navigation
* Time-based navigation
* Start and stop frame selection
* Slow-motion clip export
* Individual frame export
* Batch frame export
* Monochrome image export
* Copying frames to the Windows clipboard
* Proxy-video generation for more responsive seeking

---

# Installing FrameLab from GitHub

FrameLab is currently distributed as Python source code. A standalone Windows installer is not yet available.

The following instructions are intended for Windows 10 and Windows 11.

## 1. Install Python

FrameLab requires Python 3.11 or later.

Download and install Python from the official Python website.

During installation, enable:

```text
Add python.exe to PATH
```

After installation, open PowerShell and verify Python:

```powershell
python --version
```

You should see Python 3.11 or newer, for example:

```text
Python 3.13.5
```

If `python` is not recognized, close and reopen PowerShell after installing Python.

---

## 2. Download FrameLab

On the FrameLab GitHub page:

1. Select **Code**.
2. Select **Download ZIP**.
3. Extract the ZIP file.
4. Open the extracted `FrameLab` folder.

The folder containing `pyproject.toml` is the FrameLab project folder.

It should contain files and folders similar to:

```text
FrameLab/
├── pyproject.toml
├── README.md
├── src/
│   └── framelab/
└── tests/
```

Do not run the installation commands from inside `src` or `src\framelab`.

---

## 3. Open PowerShell in the FrameLab folder

In File Explorer:

1. Open the extracted FrameLab folder.
2. Click the address bar.
3. Type:

```text
powershell
```

4. Press Enter.

PowerShell should open directly in the FrameLab project folder.

Verify the current folder:

```powershell
Get-Location
```

Verify that `pyproject.toml` is present:

```powershell
Test-Path .\pyproject.toml
```

The result should be:

```text
True
```

If it returns `False`, navigate to the folder containing `pyproject.toml` before continuing.

---

## 4. Create a virtual environment

Run:

```powershell
python -m venv .venv
```

This creates an isolated Python environment for FrameLab and its dependencies.

---

## 5. Activate the virtual environment

Run:

```powershell
.\.venv\Scripts\Activate.ps1
```

After activation, the PowerShell prompt should begin with:

```text
(.venv)
```

For example:

```text
(.venv) PS C:\Users\YourName\Downloads\FrameLab>
```

### PowerShell execution-policy error

If PowerShell reports that running scripts is disabled, run:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Press `Y` when prompted.

Then activate the environment again:

```powershell
.\.venv\Scripts\Activate.ps1
```

This setting only needs to be changed once for the current Windows user.

---

## 6. Install FrameLab

With the virtual environment active, run:

```powershell
python -m pip install --upgrade pip
python -m pip install .
```

The second command installs FrameLab and all required Python packages.

Wait for the installation to finish. It should end without an error.

---

## 7. Launch FrameLab

Run:

```powershell
framelab
```

You may also launch it with:

```powershell
python -m framelab
```

The FrameLab window should open.

---

# Launching FrameLab later

Each time you want to use FrameLab from the source-code installation:

1. Open PowerShell in the FrameLab project folder.
2. Activate the virtual environment.
3. Launch FrameLab.

```powershell
.\.venv\Scripts\Activate.ps1
framelab
```

Alternatively:

```powershell
.\.venv\Scripts\Activate.ps1
python -m framelab
```

---

# Updating FrameLab

If you downloaded FrameLab as a ZIP file, download and extract the latest ZIP from GitHub.

Then open PowerShell in the new project folder and repeat the installation process:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install .
```

If you cloned FrameLab using Git, update it with:

```powershell
git pull
```

Then reinstall it:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install .
```

---

# Uninstalling FrameLab

Activate the FrameLab virtual environment:

```powershell
.\.venv\Scripts\Activate.ps1
```

Then uninstall FrameLab:

```powershell
python -m pip uninstall framelab
```

To completely remove the local installation, delete the extracted FrameLab folder, including its `.venv` folder.

---

# Troubleshooting

## `python` is not recognized

Python is either not installed or was not added to `PATH`.

Try:

```powershell
py --version
```

If that works, substitute `py` for `python` when creating the virtual environment:

```powershell
py -m venv .venv
```

After activating the virtual environment, use `python` normally.

---

## `pyproject.toml` cannot be found

You are running the installation command from the wrong folder.

Run:

```powershell
Get-ChildItem
```

The output should include:

```text
pyproject.toml
README.md
src
```

Navigate to the correct folder using:

```powershell
cd "C:\Path\To\FrameLab"
```

Then run:

```powershell
python -m pip install .
```

---

## Activating the virtual environment fails

Confirm that the environment was created:

```powershell
Test-Path .\.venv\Scripts\Activate.ps1
```

If the result is `False`, recreate it:

```powershell
python -m venv .venv
```

Then activate it:

```powershell
.\.venv\Scripts\Activate.ps1
```

---

## `framelab` is not recognized

Confirm that the virtual environment is active. The prompt should begin with:

```text
(.venv)
```

Then reinstall FrameLab:

```powershell
python -m pip install .
```

You can also launch it directly through Python:

```powershell
python -m framelab
```

---

## `No module named framelab`

The application has not been installed into the currently active Python environment.

From the folder containing `pyproject.toml`, run:

```powershell
python -m pip install .
```

Then retry:

```powershell
python -m framelab
```

---

## Verify the installation

Run:

```powershell
python -m pip show framelab
```

The output should include:

```text
Name: framelab
Version: 0.1.0
```

Check which Python executable is being used:

```powershell
python -c "import sys; print(sys.executable)"
```

It should point into the FrameLab virtual environment, similar to:

```text
C:\Path\To\FrameLab\.venv\Scripts\python.exe
```

Check that the FrameLab package can be imported:

```powershell
python -c "import framelab; print(framelab.__file__)"
```

---

# Development setup

The following installation is intended for developers who plan to modify FrameLab.

Clone the repository:

```powershell
git clone https://github.com/YOUR-USERNAME/FrameLab.git
cd FrameLab
```

Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install FrameLab in editable mode:

```powershell
python -m pip install --upgrade pip
python -m pip install --editable .
```

Launch FrameLab:

```powershell
python -m framelab
```

An editable installation uses the source files in the repository directly, so most Python code changes do not require reinstalling FrameLab.

---

# Project structure

```text
FrameLab/
├── pyproject.toml
├── README.md
├── src/
│   └── framelab/
│       ├── __init__.py
│       ├── __main__.py
│       └── app.py
└── tests/
```

---

# Project status

FrameLab is under active development.

A packaged Windows executable and installer are planned for a future release.
