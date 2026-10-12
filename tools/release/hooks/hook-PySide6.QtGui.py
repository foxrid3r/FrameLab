"""Keep QtGui's standard collection except unused PDF and virtual keyboard plugins."""
from pathlib import Path

from PyInstaller.utils.hooks.qt import add_qt6_dependencies

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)

# Filter before PyInstaller scans native dependencies: these plugins otherwise
# pull QtPdf and the Qt Quick/QML stack into this Widgets-only application.
binaries = [
    (source, destination)
    for source, destination in binaries
    if Path(source).name.lower() not in {"qpdf.dll", "qtvirtualkeyboardplugin.dll"}
]
