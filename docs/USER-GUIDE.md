# FrameLab user guide

## Open a video

Select **Browse Video** and choose a video. FrameLab creates a seek-friendly
proxy beside the source file. The progress panel reports when import is
complete, and editing controls remain unavailable while the proxy is built.

![FrameLab before a video is opened](screenshots/initial-window.png)

![Video import and proxy creation in progress](screenshots/video-import-progress.png)

## Navigate and mark a range

The sidebar shows the filename, current frame and time, total duration, and
source frame rate. Use the timeline, frame-step buttons, time-step buttons, or
**Jump to frame** to select an exact frame.

Select **Set START (S)** and **Set STOP (E)** to mark a range. Both export tabs
can reuse the same range.

![A loaded video in the navigation workspace](screenshots/video-loaded.png)

Enable **Delete proxy on Browse or Close** if you do not want to retain the
generated proxy after switching videos or closing FrameLab.

## Export a clip

Open **Clip Export**, select an output speed, review the generated filename,
and select **Export Clip**. A speed of `1.0` is normal speed; lower values
create slow-motion output. Exported clips use 30 FPS and contain no audio.

![Clip Export controls](screenshots/clip-export-controls.png)

## Export frame images

Open **Frame Images** and enter the first frame, last frame, and step interval.
**Use START/STOP** fills the range from the current markers. Enable **Save to
Frames subfolder** to group the images, or **Monochrome** for grayscale BMP
output.

![Frame Images controls](screenshots/frame-image-export-controls.png)

The toolbar's **Copy Frame** command places the current frame on the clipboard.
**Save Frame BMP** writes it directly to disk. A green preview border and a
message in the progress panel confirm a successful save.

![Confirmation after saving the current frame](screenshots/saved-frame-feedback.png)

## Generated files

By default, FrameLab keeps its proxy beside the source video and can place
exported bitmaps in a `Frames` subfolder.

![Source video, generated proxy, and Frames folder](screenshots/generated-proxy-and-frames-folder.png)

Exported filenames include the source name, zero-padded frame number, and
timestamp in milliseconds.

![Exported bitmap frame sequence](screenshots/exported-frame-images.png)

[Return to the project overview](../README.md)
