"""Compare FrameLab's current H.264 proxy with an OpenCV MJPEG proxy."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import cv2


def media_info(path: Path) -> tuple[float, int, int, int]:
    capture = cv2.VideoCapture(str(path), cv2.CAP_FFMPEG)
    if not capture.isOpened():
        raise RuntimeError(f"OpenCV could not open {path}")
    try:
        return (
            capture.get(cv2.CAP_PROP_FPS),
            int(capture.get(cv2.CAP_PROP_FRAME_COUNT)),
            int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
            int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        )
    finally:
        capture.release()


def make_h264(source: Path, output: Path, ffmpeg: str) -> tuple[float, int]:
    command = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "23",
        "-x264-params",
        "keyint=1:min-keyint=1:scenecut=0",
        str(output),
    ]
    started = time.perf_counter()
    subprocess.run(command, check=True)
    return time.perf_counter() - started, media_info(output)[1]


def make_mjpeg(source: Path, output: Path) -> tuple[float, int]:
    capture = cv2.VideoCapture(str(source), cv2.CAP_FFMPEG)
    if not capture.isOpened():
        raise RuntimeError(f"OpenCV could not open {source}")

    fps = capture.get(cv2.CAP_PROP_FPS)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    writer = cv2.VideoWriter(
        str(output),
        cv2.CAP_FFMPEG,
        cv2.VideoWriter_fourcc(*"MJPG"),
        fps,
        (width, height),
    )
    if not writer.isOpened():
        capture.release()
        raise RuntimeError(f"OpenCV could not create {output}")

    started = time.perf_counter()
    frames = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            writer.write(frame)
            frames += 1
    finally:
        writer.release()
        capture.release()
    return time.perf_counter() - started, frames


def seek_benchmark(path: Path, frame_count: int, samples: int = 25) -> tuple[float, int]:
    capture = cv2.VideoCapture(str(path), cv2.CAP_FFMPEG)
    if not capture.isOpened() or frame_count < 1:
        return 0.0, samples
    positions = [round(index * (frame_count - 1) / max(samples - 1, 1)) for index in range(samples)]
    started = time.perf_counter()
    failures = 0
    try:
        for position in positions:
            capture.set(cv2.CAP_PROP_POS_FRAMES, position)
            ok, _ = capture.read()
            failures += int(not ok)
    finally:
        capture.release()
    return (time.perf_counter() - started) * 1000 / samples, failures


def benchmark(source: Path, output_dir: Path, ffmpeg: str) -> list[dict[str, object]]:
    fps, source_frames, width, height = media_info(source)
    stem = source.stem
    variants = (
        ("h264-all-intra", output_dir / f"{stem}.h264-all-intra.mp4", make_h264),
        ("mjpeg", output_dir / f"{stem}.mjpeg.avi", make_mjpeg),
    )
    rows = []
    for name, output, creator in variants:
        print(f"Encoding {source.name}: {name} ...", flush=True)
        elapsed, frames_written = creator(source, output, ffmpeg) if name == "h264-all-intra" else creator(source, output)
        seek_ms, seek_failures = seek_benchmark(output, frames_written)
        size = output.stat().st_size
        rows.append(
            {
                "source": str(source),
                "variant": name,
                "output": str(output),
                "resolution": f"{width}x{height}",
                "fps": round(fps, 3),
                "source_frames": source_frames,
                "frames_written": frames_written,
                "encode_seconds": round(elapsed, 3),
                "size_bytes": size,
                "size_mib": round(size / 1024**2, 2),
                "avg_seek_ms": round(seek_ms, 2),
                "seek_failures": seek_failures,
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("videos", nargs="+", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("benchmark-results"))
    parser.add_argument("--ffmpeg", default=shutil.which("ffmpeg"))
    args = parser.parse_args()
    if not args.ffmpeg:
        parser.error("ffmpeg was not found; pass its location with --ffmpeg")

    sources = [path.resolve() for path in args.videos]
    missing = [str(path) for path in sources if not path.is_file()]
    if missing:
        parser.error("video file not found: " + ", ".join(missing))
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for source in sources:
        rows.extend(benchmark(source, output_dir, args.ffmpeg))

    json_path = output_dir / "proxy-benchmark.json"
    csv_path = output_dir / "proxy-benchmark.csv"
    json_path.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n{'Video':30} {'Format':16} {'Size MiB':>9} {'Encode s':>9} {'Seek ms':>9}")
    for row in rows:
        print(
            f"{Path(str(row['source'])).name[:30]:30} {row['variant']:16} "
            f"{row['size_mib']:9.2f} {row['encode_seconds']:9.3f} {row['avg_seek_ms']:9.2f}"
        )
    print(f"\nReports: {csv_path} and {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
