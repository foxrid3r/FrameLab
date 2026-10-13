"""Collect release notices from the exact environment used by PyInstaller."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import shutil
import sys
from pathlib import Path


PACKAGES = (
    "opencv-python",
    "numpy",
    "Pillow",
    "PySide6",
    "PySide6-Essentials",
    "shiboken6",
    "pyinstaller",
)
NOTICE_NAMES = ("license", "copying", "notice", "authors")

# Reviewed notices without a binary-redistribution notice requirement:
# pythoncapi-compat (0BSD), libdivide (zlib; no headers shipped), SplitMix64 (CC0).
# Match contents so a changed upstream license is collected for review.
OPTIONAL_NUMPY_NOTICE_HASHES = {
    "aea41976c720f91bd19725c16916a1ace40eb1ea42620d340e587a5de4bbcea0",
    "d544761558b510866c21f7e8a2d5716fca76e0b98117e3b6b86314db7244d150",
    "454ec7350e478e037061850b67395753b425b1cb0a34bbc26290b020bf89d763",
}


def safe_name(value: str) -> str:
    return "".join(character if character.isalnum() or character in ".-_" else "-" for character in value)


def copy_distribution_notices(distribution_name: str, output: Path) -> tuple[str, int]:
    distribution = importlib.metadata.distribution(distribution_name)
    project_name = distribution.metadata.get("Name", distribution_name)
    version = distribution.version
    copied = 0
    seen_contents: set[bytes] = set()

    for relative_file in distribution.files or ():
        basename = Path(str(relative_file)).name.lower()
        if not any(basename.startswith(name) or f"_{name}" in basename for name in NOTICE_NAMES):
            continue
        source = Path(distribution.locate_file(relative_file))
        if not source.is_file():
            continue
        contents = source.read_bytes()
        if distribution_name == "numpy" and hashlib.sha256(contents).hexdigest() in OPTIONAL_NUMPY_NOTICE_HASHES:
            continue
        if contents in seen_contents:
            continue
        seen_contents.add(contents)
        if distribution_name == "numpy":
            # Keep upstream component paths beneath one readable package folder.
            parts = Path(str(relative_file)).parts
            if "licenses" in parts:
                parts = parts[parts.index("licenses") + 1:]
            if parts[0] == "numpy":
                parts = parts[1:]
            destination = output / "numpy" / Path(*parts)
        else:
            destination_name = f"{safe_name(project_name)}-{safe_name(version)}-{safe_name(str(relative_file))}"
            destination = output / destination_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
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

    shutil.copy2(Path(__file__).parents[1] / "THIRD-PARTY-NOTICES.md", output / "THIRD-PARTY-NOTICES.md")
    (output / "PACKAGE-VERSIONS.txt").write_text("\n".join(versions) + "\n", encoding="utf-8")

    print(f"Collected release licenses in {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
