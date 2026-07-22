# Third-Party Notices

FrameLab is distributed with third-party software. FrameLab's own license does
not replace or limit the licenses listed below.

The release package contains a `licenses` directory generated from the exact
Python environment used for the build. That directory is the authoritative
record for a particular release and includes package versions, copyright, and
license texts.

## Runtime components

| Component | Expected license | Notes |
| --- | --- | --- |
| CPython | Python Software Foundation License | Python runtime and standard library |
| Tcl/Tk | Tcl/Tk license | GUI runtime bundled by PyInstaller |
| opencv-python packaging | MIT | Python wheel packaging |
| OpenCV | Apache License 2.0 | The optional OpenCV FFmpeg video-I/O plugin is excluded from the release |
| NumPy | BSD 3-Clause | Runtime dependency of OpenCV |
| Pillow | MIT-CMU | Image processing |
| sv-ttk | MIT | Tk theme |
| PyInstaller bootloader | GPL-2.0 with bootloader exception | The exception permits distribution of the generated application under a license of the application's author’s choice |

This list is informational. Always use the license files generated from the
actual release environment because dependencies and their bundled libraries can
change between versions.

## Separately installed FFmpeg

FrameLab does not distribute FFmpeg. Users install it separately and FrameLab
invokes the `ffmpeg` executable found on the system `PATH`. That installation
must provide the `libx264` encoder. FFmpeg and its enabled libraries remain
subject to the terms supplied by the user's chosen FFmpeg distributor.

## Patents

Copyright licenses do not grant patent rights for every media codec. A
distributor should separately evaluate codec-patent requirements for the
markets and uses in which FrameLab is released.
