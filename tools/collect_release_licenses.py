"""Collect release notices from the exact environment used by PyInstaller."""

from __future__ import annotations

import argparse
import importlib.metadata
import shutil
import sys
from pathlib import Path


PACKAGES = (
    "opencv-python",
    "numpy",
    "Pillow",
    "sv-ttk",
    "pyinstaller",
)
NOTICE_NAMES = ("license", "copying", "notice", "authors")


def safe_name(value: str) -> str:
    return "".join(character if character.isalnum() or character in ".-_" else "-" for character in value)


def copy_distribution_notices(distribution_name: str, output: Path) -> tuple[str, int]:
    distribution = importlib.metadata.distribution(distribution_name)
    project_name = distribution.metadata.get("Name", distribution_name)
    version = distribution.version
    copied = 0

    for relative_file in distribution.files or ():
        basename = Path(str(relative_file)).name.lower()
        if not any(basename.startswith(name) for name in NOTICE_NAMES):
            continue
        source = Path(distribution.locate_file(relative_file))
        if not source.is_file():
            continue
        destination_name = f"{safe_name(project_name)}-{safe_name(version)}-{safe_name(Path(str(relative_file)).name)}"
        shutil.copy2(source, output / destination_name)
        copied += 1

    return version, copied


def copy_first_existing(candidates: tuple[Path, ...], destination: Path, label: str) -> None:
    for candidate in candidates:
        if candidate.is_file():
            shutil.copy2(candidate, destination)
            return
    raise RuntimeError(f"Could not locate the {label} license in this Python installation")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    output = args.output.resolve()
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    versions: list[str] = [f"Python: {sys.version.split()[0]}"]
    missing_notices: list[str] = []
    for package in PACKAGES:
        version, copied = copy_distribution_notices(package, output)
        versions.append(f"{package}: {version}")
        if copied == 0:
            missing_notices.append(package)

    if missing_notices:
        raise RuntimeError("No installed license/notice files found for: " + ", ".join(missing_notices))

    base = Path(sys.base_prefix)
    copy_first_existing(
        (base / "LICENSE.txt", base / "LICENSE"),
        output / "CPython-LICENSE.txt",
        "CPython",
    )
    copy_first_existing(
        (
            base / "tcl" / "tcl8.6" / "license.terms",
            base / "tcl" / "tcl9.0" / "license.terms",
            base / "tcl" / "tk8.6" / "license.terms",
            base / "tcl" / "tk9.0" / "license.terms",
        ),
        output / "Tcl-Tk-license.terms",
        "Tcl/Tk",
    )

    shutil.copy2(Path(__file__).parents[1] / "THIRD-PARTY-NOTICES.md", output / "THIRD-PARTY-NOTICES.md")
    (output / "PACKAGE-VERSIONS.txt").write_text("\n".join(versions) + "\n", encoding="utf-8")

    print(f"Collected release licenses in {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
