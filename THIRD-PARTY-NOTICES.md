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
| OpenCV | Apache License 2.0 | The wheel includes its LGPL FFmpeg video-I/O plugin for OpenCV decoding and encoding |
| NumPy | BSD 3-Clause | Runtime dependency of OpenCV |
| Pillow | MIT-CMU | Image processing |
| sv-ttk | MIT | Tk theme |
| PyInstaller bootloader | GPL-2.0 with bootloader exception | The exception permits distribution of the generated application under a license of the application's author’s choice |

This list is informational. Always use the license files generated from the
actual release environment because dependencies and their bundled libraries can
change between versions.

## Bundled FFmpeg executable

FrameLab distributes a separate, statically linked FFmpeg executable built with
the `libx264` encoder. The executable is licensed under the GNU General Public
License version 2 or later. Its build information and the FFmpeg and x264
license texts are included under `licenses\ffmpeg` in the release. The exact
source revisions and reproducible build recipe are recorded in
`tools/build_minimal_ffmpeg.sh`; corresponding source archives must accompany
published binary releases or be made available in accordance with the GPL.

## Patents

Copyright licenses do not grant patent rights for every media codec. A
distributor should separately evaluate codec-patent requirements for the
markets and uses in which FrameLab is released.
