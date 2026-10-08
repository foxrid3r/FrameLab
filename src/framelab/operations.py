"""Video processing, export, and timestamp operations shared by the Qt window.

Workers only post messages to ui_queue; the Qt event loop owns all UI updates.
"""
import csv
import os
import re
import shutil
import subprocess
import sys
import threading
import zipfile
from pathlib import Path
import cv2
from PIL import Image
from framelab import spreadsheet
DEFAULT_OUTPUT_SPEED = 0.1
OUTPUT_FPS = 30.0
FLAG_STRIP_HEIGHT = 20
TIMESTAMP_COLORS = ('#ef4444', '#f59e0b', '#22c55e', '#06b6d4', '#3b82f6', '#a855f7', '#ec4899', '#eab308')
PROXY_CRF = '23'
PROXY_PRESET = 'ultrafast'
PREVIEW_MAX_UPSCALE = 1.0
POLL_MS = 50
MAX_PIXEL_SCALE = 16.0
ZOOM_STEP = 1.25

def open_video_capture(path):
    """Open a video with OpenCV's FFmpeg backend for responsive seeking."""
    return cv2.VideoCapture(path, cv2.CAP_FFMPEG)

def find_ffmpeg_executable():
    """Return FrameLab's bundled FFmpeg, falling back to the system PATH."""
    candidates = []
    if getattr(sys, 'frozen', False):
        bundle_root = Path(getattr(sys, '_MEIPASS', Path(sys.executable).resolve().parent))
        candidates.extend((bundle_root / 'ffmpeg' / 'ffmpeg.exe', Path(sys.executable).resolve().parent / 'ffmpeg' / 'ffmpeg.exe'))
    else:
        project_root = Path(__file__).resolve().parents[2]
        candidates.append(project_root / 'vendor' / 'ffmpeg' / 'ffmpeg.exe')
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return shutil.which('ffmpeg')

class VideoOperations:

    def frame_to_seconds(self, frame_num):
        return 0.0 if self.fps <= 0 else frame_num / self.fps

    def seconds_to_frames(self, seconds):
        return round(seconds * self.fps)

    @staticmethod
    def format_time(seconds):
        minutes = int(seconds // 60)
        seconds = seconds % 60
        return f'{minutes:02d}:{seconds:06.3f}'

    @staticmethod
    def sanitize_filename_part(text):
        invalid = '<>:"/\\|?*'
        cleaned = ''.join(('_' if ch in invalid else ch for ch in text))
        cleaned = cleaned.strip().strip('.')
        return cleaned or 'frame'

    @staticmethod
    def get_unique_path(path):
        """Return an unused path by appending a numeric suffix when necessary."""
        base, extension = os.path.splitext(path)
        candidate = path
        idx = 1
        while os.path.exists(candidate):
            candidate = f'{base}_{idx:03d}{extension}'
            idx += 1
        return candidate

    def update_info(self):
        self.update_frame_rate_controls()
        if self.cap is None:
            self.info_label.setText('No video loaded')
            self.frame_entry.setText('0')
            return
        current_time = self.format_time(self.frame_to_seconds(self.current_frame))
        total_time = self.format_time(self.frame_to_seconds(self.frame_count - 1))
        self.frame_entry.setText(str(self.current_frame))
        self.info_label.setText(f'File:\n{self.filename}\n\nCurrent Frame:\n{self.current_frame} / {self.frame_count - 1}\n\nCurrent Time:\n{current_time} / {total_time}\n\nSource FPS:\n{self.original_fps:.3f}' + (f'\n\nOverride FPS:\n{self.fps:.3f} (overridden)' if self.frame_rate_overridden() else ''))

    def frame_rate_overridden(self):
        return self.original_fps > 0 and abs(self.fps - self.original_fps) > 1e-06

    def update_mark_status(self):
        start_text = f'Frame {self.start_frame} @ {self.format_time(self.frame_to_seconds(self.start_frame))}' if self.start_frame is not None else 'Not set'
        stop_text = f'Frame {self.stop_frame} @ {self.format_time(self.frame_to_seconds(self.stop_frame))}' if self.stop_frame is not None else 'Not set'
        self.mark_label.setText(f'Start: {start_text}\nStop:  {stop_text}')

    def get_output_speed(self):
        try:
            speed = float(self.speed_entry.text())
            if speed <= 0:
                raise ValueError
            return speed
        except ValueError:
            self._error('Invalid Speed', 'Output speed must be a positive number.')
            return None

    def default_output_filename(self, speed=None):
        if not self.name or not self.ext:
            return ''
        if speed is None:
            try:
                speed = float(self.speed_entry.text())
            except ValueError:
                speed = DEFAULT_OUTPUT_SPEED
        if speed == 1.0:
            return f'{self.name}_trimmed_30fps_no_audio{self.ext}'
        return f'{self.name}_trimmed_{speed}x_30fps_no_audio{self.ext}'

    def mark_output_filename_edited(self):
        self.output_filename_user_edited = True

    def update_default_output_filename_if_allowed(self):
        if not self.output_filename_user_edited:
            speed = self.get_output_speed()
            if speed is not None:
                self.output_filename_entry.setText(self.default_output_filename(speed))

    def get_output_path(self):
        proposed = self.output_filename_entry.text().strip() or self.default_output_filename(self.get_output_speed())
        proposed = os.path.basename(proposed)
        _, proposed_ext = os.path.splitext(proposed)
        if not proposed_ext:
            proposed += self.ext
        return os.path.join(self.folder, proposed)

    def clear_current_video(self, delete_proxy=None):
        """Release the active video and restore the unloaded UI state."""
        if delete_proxy is None:
            delete_proxy = self.delete_proxy_checkbox.isChecked()
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        if delete_proxy and self.proxy_path and os.path.exists(self.proxy_path):
            try:
                os.remove(self.proxy_path)
            except Exception as e:
                print(f'Could not delete proxy file: {e}')
        self.source_path = None
        self.proxy_path = None
        self.folder = None
        self.filename = None
        self.name = None
        self.ext = None
        self.fps = 0.0
        self.original_fps = 0.0
        self.frame_count = 0
        self.current_frame = 0
        self.start_frame = None
        self.stop_frame = None
        self._frame_bgr = None
        self._preview_box = None
        self.zoom, self.view_x, self.view_y = (1.0, 0.0, 0.0)
        self.timestamps = []
        self.output_filename_user_edited = False
        self.video_canvas.clear()
        self.file_label.setToolTip('No video loaded')
        self.file_label.setText('No video loaded')
        self.output_filename_entry.setText('')
        self.image_basename_entry.setText('')
        self.image_start_entry.setText('')
        self.image_stop_entry.setText('')
        self.image_step_entry.setText('1')
        self.slider.setRange(0, 1)
        self.slider.setEnabled(False)
        self.update_mark_status()
        self.update_info()
        self.refresh_timestamps()
        self.setWindowTitle('FrameLab')

    def browse_video(self):
        if self.busy:
            self._info('Busy', 'Please wait for the current operation to finish.')
            return
        path = self._open_file(title='Select video file', filetypes=[('Video files', '*.mp4 *.mov *.avi *.mkv *.wmv'), ('All files', '*.*')])
        if path:
            self.start_load_video(path)

    def start_load_video(self, path):
        if self.busy:
            return
        self.ffmpeg_exe = find_ffmpeg_executable()
        if self.ffmpeg_exe is None:
            self._error('FFmpeg Required', "FrameLab's bundled FFmpeg executable could not be found.\n\nReinstall FrameLab or provide an FFmpeg installation with libx264 on PATH.")
            return
        self.clear_current_video(delete_proxy=self.delete_proxy_checkbox.isChecked())
        self.source_path = path
        self.folder, self.filename = os.path.split(self.source_path)
        self.name, self.ext = os.path.splitext(self.filename)
        self.image_basename_entry.setText(self.name)
        self.proxy_path = os.path.join(self.folder, f'{self.name}_proxy_all_i.mp4')
        self.output_filename_user_edited = False
        self.output_filename_entry.setText(self.default_output_filename())
        self.file_label.setText(f'Loading: {self.filename}')
        self.setWindowTitle(f'FrameLab - Loading {self.filename}')
        self.set_busy(True, 'Importing video / creating proxy...')
        self.set_progress('Importing video / creating proxy...', 0)
        threading.Thread(target=self._create_proxy, args=(self.source_path, self.proxy_path), daemon=True).start()

    def _create_proxy(self, path, proxy):
        """Create a seek-friendly proxy and post progress to ``ui_queue``."""
        if os.path.exists(proxy):
            self.ui_queue.put(('progress', 'Using existing proxy', 100))
            self.ui_queue.put(('proxy_done', path))
            return
        cmd_proxy = [self.ffmpeg_exe, '-y', '-progress', 'pipe:2', '-nostats', '-i', path, '-an', '-c:v', 'libx264', '-preset', PROXY_PRESET, '-crf', PROXY_CRF, '-x264-params', 'keyint=1:min-keyint=1:scenecut=0', proxy]
        try:
            with subprocess.Popen(cmd_proxy, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, universal_newlines=True, errors='replace', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)) as process:
                timestamp_re = re.compile('(?:Duration: |time=)(\\d+):(\\d+):(\\d+(?:\\.\\d+)?)')
                duration_seconds = None
                for line in process.stderr:
                    match = timestamp_re.search(line)
                    if match and line.lstrip().startswith('Duration:'):
                        hours = int(match.group(1))
                        minutes = int(match.group(2))
                        seconds = float(match.group(3))
                        duration_seconds = hours * 3600 + minutes * 60 + seconds
                        continue
                    if duration_seconds and duration_seconds > 0:
                        match = timestamp_re.search(line)
                        if match:
                            hours = int(match.group(1))
                            minutes = int(match.group(2))
                            seconds = float(match.group(3))
                            current = hours * 3600 + minutes * 60 + seconds
                            percent = min(100, current / duration_seconds * 100)
                            self.ui_queue.put(('progress', f'Importing video / creating proxy... {percent:0.1f}%', percent))
                rc = process.wait()
                if rc != 0:
                    raise subprocess.CalledProcessError(rc, cmd_proxy)
                self.ui_queue.put(('progress', 'Import complete', 100))
                self.ui_queue.put(('proxy_done', path))
        except Exception as e:
            self.ui_queue.put(('error', 'Proxy Error', f'Failed to create proxy:\n{e}'))

    def _finish_loading_proxy(self, path):
        self.file_label.setToolTip(self.source_path or '')
        if path != self.source_path:
            return
        if not self._open_proxy():
            self.clear_current_video(delete_proxy=self.delete_proxy_checkbox.isChecked())
            self.set_busy(False, 'Idle')
            return
        self.file_label.setText(self.source_path)
        self.setWindowTitle(f'FrameLab - {self.filename}')
        self.update_mark_status()
        self.show_frame(0)
        self.draw_flags()
        self.set_busy(False, 'Import complete')
        self.set_progress('Import complete', 100)

    def _open_proxy(self):
        self.cap = open_video_capture(self.proxy_path)
        if not self.cap.isOpened():
            self._error('Error', 'Could not open proxy video.')
            return False
        self.fps = self.cap.get(cv2.CAP_PROP_FPS)
        self.original_fps = self.fps
        self.frame_count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if self.fps <= 0 or self.frame_count <= 0:
            self._error('Error', 'Could not read video FPS or frame count.')
            return False
        self.slider.setRange(0, self.frame_count - 1)
        self.slider.setEnabled(True)
        return True

    @staticmethod
    def timestamp_color(index):
        return TIMESTAMP_COLORS[index % len(TIMESTAMP_COLORS)]

    def timestamp_rows(self, include_fps=False):
        """Return a header row plus one [#, seconds, frame, description] row per timestamp.

        Seconds are numeric (rounded to milliseconds) so Excel can calculate with them.
        ``include_fps`` appends an FPS column so the frame rate travels with the file.
        """
        rows = [['#', 'Time (s)', 'Frame', 'Description'] + (['FPS'] if include_fps else [])]
        fps = round(self.fps, 3)
        for index in self.timestamp_view_order():
            entry = self.timestamps[index]
            rows.append([index + 1, round(self.frame_to_seconds(entry['frame']), 3), entry['frame'], entry['description']] + ([fps] if include_fps else []))
        return rows

    def timestamp_text_rows(self, include_fps=False):
        """Rows with the seconds column formatted to a fixed three decimals (text)."""
        return [[f'{value:.3f}' if column == 1 and row_index else value for column, value in enumerate(row)] for row_index, row in enumerate(self.timestamp_rows(include_fps))]

    def export_timestamps(self):
        """Save timestamps as an Excel workbook (.xlsx) or CSV, chosen by file extension."""
        if not self.timestamps:
            self._info('No Timestamps', 'Add at least one timestamp first.')
            return
        path = self._save_file(title='Export timestamps', defaultextension='.xlsx', initialdir=self.folder, initialfile=f'{self.name}_timestamps.xlsx', filetypes=[('Excel workbook', '*.xlsx'), ('CSV files', '*.csv')])
        if not path:
            return
        try:
            if path.lower().endswith('.csv'):
                with open(path, 'w', newline='', encoding='utf-8-sig') as handle:
                    csv.writer(handle).writerows(self.timestamp_text_rows(include_fps=True))
            else:
                spreadsheet.write_xlsx(path, self.timestamp_rows(include_fps=True), seconds_column=1, column_widths=[6, 12, 10, 50, 8])
        except OSError as e:
            self._error('Export Error', f'Could not write file:\n{e}')
            return
        self.progress_label.setText(f'Exported timestamps: {os.path.basename(path)}')

    @staticmethod
    def parse_seconds(value):
        """Parse seconds from a number, ``1.234``, ``mm:ss.mmm`` or ``h:mm:ss.mmm``; else None."""
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value or '').strip()
        match = re.fullmatch('(?:(\\d+):)?(\\d+):(\\d+(?:\\.\\d+)?)', text)
        if match:
            hours, minutes, seconds = match.groups()
            return int(hours or 0) * 3600 + int(minutes) * 60 + float(seconds)
        try:
            return float(text)
        except ValueError:
            return None

    def timestamps_from_rows(self, rows):
        """Convert spreadsheet rows to timestamp entries. Returns (entries, skipped_count, fps).

        Uses the header row to find Frame / Time / Description / FPS columns
        (falling back to FrameLab's export layout). A Frame value wins over
        Time. ``fps`` is the frame rate stored in the file, or None. Times are
        converted to frames at that rate when present, else at the current one.
        """
        rows = [row for row in rows if any((cell not in (None, '') for cell in row))]
        if not rows:
            raise ValueError('The file contains no rows.')
        header = [str(cell or '').strip().lower() for cell in rows[0]]

        def find(*prefixes):
            for index, name in enumerate(header):
                if name.startswith(prefixes):
                    return index
            return None
        frame_col, time_col, desc_col = (find('frame'), find('time'), find('desc', 'note', 'comment', 'label'))
        fps_col = find('fps')
        if frame_col is None and time_col is None:
            if len(rows[0]) < 4:
                raise ValueError('Could not find Time or Frame columns.')
            time_col, frame_col, desc_col = (1, 2, 3)
            data_rows = rows
        else:
            data_rows = rows[1:]

        def cell_of(row, index):
            return row[index] if index is not None and index < len(row) else None
        file_fps = None
        for row in data_rows:
            candidate = self.parse_seconds(cell_of(row, fps_col))
            if candidate is not None and candidate > 0:
                file_fps = candidate
                break
        fps = file_fps or self.fps
        entries, skipped = ([], 0)
        for row in data_rows:

            def cell(index):
                return cell_of(row, index)
            frame = None
            raw_frame = cell(frame_col)
            if raw_frame not in (None, ''):
                try:
                    frame = int(round(float(raw_frame)))
                except (TypeError, ValueError):
                    frame = None
            if frame is None:
                seconds = self.parse_seconds(cell(time_col))
                if seconds is not None:
                    frame = round(seconds * fps)
            if frame is None or not 0 <= frame < self.frame_count:
                skipped += 1
                continue
            description = cell(desc_col)
            entries.append({'frame': frame, 'description': '' if description is None else str(description).strip()})
        return (entries, skipped, file_fps)

    def import_timestamps(self):
        """Load timestamps from an .xlsx or .csv file (such as one exported by FrameLab)."""
        if self.cap is None or self.busy:
            self._info('Import Timestamps', 'Load a video first so times can be mapped to frames.')
            return
        path = self._open_file(title='Import timestamps', initialdir=self.folder, filetypes=[('Timestamp files', '*.xlsx *.csv'), ('All files', '*.*')])
        if not path:
            return
        try:
            if path.lower().endswith('.xlsx'):
                rows = spreadsheet.read_xlsx(path)
            else:
                with open(path, newline='', encoding='utf-8-sig') as handle:
                    sample = handle.read(4096)
                    handle.seek(0)
                    dialect = csv.Sniffer().sniff(sample, delimiters=',;\t') if sample else csv.excel
                    rows = list(csv.reader(handle, dialect))
            entries, skipped, file_fps = self.timestamps_from_rows(rows)
        except (OSError, ValueError, csv.Error, KeyError, zipfile.BadZipFile) as e:
            self._error('Import Error', f'Could not import timestamps:\n{e}')
            return
        if not entries:
            self._warning('Import Timestamps', 'No valid timestamps were found in the file.')
            return
        if self.timestamps:
            choice = self._replace_or_append('Import Timestamps', f'Replace the {len(self.timestamps)} existing timestamps?\n\nYes = replace    No = add to existing    Cancel = abort')
            if choice is None:
                return
            if choice:
                self.timestamps = []
        self.timestamps.extend(entries)
        notes = []
        if file_fps is not None and abs(file_fps - self.fps) > 1e-06:
            self.fps = file_fps
            self.update_info()
            self.update_mark_status()
            notes.append(f'frame rate set to {file_fps:g} fps')
        if skipped:
            notes.append(f'{skipped} skipped')
        self.refresh_timestamps()
        note = f" ({', '.join(notes)})" if notes else ''
        self.progress_label.setText(f'Imported {len(entries)} timestamps{note}')

    def timestamp_view_order(self):
        """Indices into ``self.timestamps`` in the order currently sorted for display."""
        column, descending = self.timestamp_sort
        keys = {'#0': lambda i: i, 'num': lambda i: i, 'time': lambda i: (self.timestamps[i]['frame'], i), 'frame': lambda i: (self.timestamps[i]['frame'], i), 'description': lambda i: (self.timestamps[i]['description'].lower(), i)}
        return sorted(range(len(self.timestamps)), key=keys[column], reverse=descending)

    def sort_timestamps_by(self, column):
        """Sort by ``column``; clicking the active column again reverses the order."""
        active, descending = self.timestamp_sort
        self.timestamp_sort = (column, not descending if column == active else False)
        self.refresh_timestamps()

    def set_frame_rate(self):
        """Override the source frame rate used for time display and export timing.

        Useful when container metadata (e.g. slow-motion capture rate) was lost.
        """
        if self.cap is None or self.busy:
            return
        value = self._ask_float('Set Frame Rate', 'Frame rate (FPS) of the source footage, e.g. 240 for iPhone slo-mo:\n\nThis overrides the FPS used for time display, timestamp times, and export timing.', initialvalue=round(self.fps, 3), minvalue=0.1, maxvalue=10000.0)
        if value is None:
            return
        self.fps = float(value)
        self.update_info()
        self.update_mark_status()
        self.refresh_timestamps()

    def reset_frame_rate(self):
        """Restore the FPS read when this video was loaded."""
        if self.cap is None or self.busy or (not self.frame_rate_overridden()):
            return
        self.fps = self.original_fps
        self.update_info()
        self.update_mark_status()
        self.refresh_timestamps()

    def read_frame(self, frame_num):
        """Seek to and decode one frame from the active proxy."""
        if self.cap is None:
            return None
        frame_num = max(0, min(frame_num, self.frame_count - 1))
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
        ret, frame = self.cap.read()
        return frame if ret else None

    def _view_geometry(self, frame_w, frame_h, zoom=None):
        """Return ``(scale, crop_w, crop_h)`` for the preview at ``zoom``.

        Zoom 1 fits the whole frame inside the canvas. Zooming in scales the
        picture continuously (square pixels, no stretching). Once the picture
        is bigger than the canvas on an axis, the view crops to the canvas
        shape on that axis, so past the point where both axes overflow the
        view fills the canvas edge to edge.
        """
        zoom = self.zoom if zoom is None else zoom
        available_w = max(self.video_canvas.width(), 1)
        available_h = max(self.video_canvas.height(), 1)
        fit = min(available_w / frame_w, available_h / frame_h, PREVIEW_MAX_UPSCALE)
        if zoom <= 1.0:
            return (fit, frame_w, frame_h)
        scale = fit * zoom
        crop_w = min(frame_w, max(1, round(available_w / scale)))
        crop_h = min(frame_h, max(1, round(available_h / scale)))
        return (scale, crop_w, crop_h)

    def _max_zoom(self, frame_w, frame_h):
        available_w = max(self.video_canvas.width(), 1)
        available_h = max(self.video_canvas.height(), 1)
        fit = min(available_w / frame_w, available_h / frame_h, PREVIEW_MAX_UPSCALE)
        return max(1.0, MAX_PIXEL_SCALE / fit)

    def resize_frame_for_preview(self, frame):
        """Crop ``frame`` to the zoomed view, then scale it for the canvas."""
        h, w = frame.shape[:2]
        scale, crop_w, crop_h = self._view_geometry(w, h)
        self._scale = scale
        if self.zoom > 1.0:
            x0 = min(max(int(round(self.view_x * w)), 0), w - crop_w)
            y0 = min(max(int(round(self.view_y * h)), 0), h - crop_h)
            frame = frame[y0:y0 + crop_h, x0:x0 + crop_w]
            new_w = min(max(1, round(crop_w * scale)), max(self.video_canvas.width(), 1))
            new_h = min(max(1, round(crop_h * scale)), max(self.video_canvas.height(), 1))
        else:
            new_w = max(1, int(w * scale))
            new_h = max(1, int(h * scale))
        interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_NEAREST
        return cv2.resize(frame, (new_w, new_h), interpolation=interpolation)

    def show_frame(self, frame_num):
        frame_num = int(frame_num)
        if self.cap is None:
            return
        frame_num = max(0, min(frame_num, self.frame_count - 1))
        frame = self.read_frame(frame_num)
        if frame is None:
            return
        self.current_frame = frame_num
        self._frame_bgr = frame
        self._draw_preview()
        self._updating_slider = True
        try:
            self.slider.setValue(self.current_frame)
        finally:
            self._updating_slider = False
        self.update_info()

    def _clamp_view(self):
        """Keep the zoomed crop inside the frame."""
        if self._frame_bgr is None:
            return
        h, w = self._frame_bgr.shape[:2]
        _, crop_w, crop_h = self._view_geometry(w, h)
        self.view_x = min(max(self.view_x, 0.0), 1.0 - crop_w / w)
        self.view_y = min(max(self.view_y, 0.0), 1.0 - crop_h / h)

    def zoom_at(self, factor, canvas_x, canvas_y):
        """Zoom by ``factor`` keeping the frame point under the cursor fixed."""
        h, w = self._frame_bgr.shape[:2]
        box_x, box_y, _, _ = self._preview_box
        old = self.zoom
        old_scale, _, _ = self._view_geometry(w, h, old)
        point_x = self.view_x * w + (canvas_x - box_x) / old_scale
        point_y = self.view_y * h + (canvas_y - box_y) / old_scale
        new = min(max(old * factor, 1.0), self._max_zoom(w, h))
        if new == old:
            return
        if new == 1.0:
            self.reset_zoom()
            return
        new_scale, crop_w, crop_h = self._view_geometry(w, h, new)
        available_w = max(self.video_canvas.width(), 1)
        available_h = max(self.video_canvas.height(), 1)
        new_box_x = max(0.0, (available_w - crop_w * new_scale) / 2)
        new_box_y = max(0.0, (available_h - crop_h * new_scale) / 2)
        self.zoom = new
        self.view_x = (point_x - (canvas_x - new_box_x) / new_scale) / w
        self.view_y = (point_y - (canvas_y - new_box_y) / new_scale) / h
        self._clamp_view()
        self._schedule_redraw()

    def reset_zoom(self):
        if self.zoom == 1.0 and self.view_x == 0.0 and (self.view_y == 0.0):
            return
        self.zoom, self.view_x, self.view_y = (1.0, 0.0, 0.0)
        self._schedule_redraw()

    def slider_changed(self, value):
        if self._updating_slider or self.cap is None or self.busy:
            return
        try:
            frame_num = int(round(float(value)))
        except (TypeError, ValueError):
            return
        if frame_num == self.current_frame:
            return
        self.show_frame(frame_num)

    def jump_frames(self, delta_frames):
        if self.cap is None or self.busy:
            return
        self.show_frame(self.current_frame + delta_frames)

    def jump_seconds(self, delta_seconds):
        if self.cap is None or self.busy:
            return
        self.jump_frames(self.seconds_to_frames(delta_seconds))

    def jump_to_frame_from_entry(self, event=None):
        if self.cap is None or self.busy:
            return
        try:
            frame_num = int(self.frame_entry.text().strip())
        except ValueError:
            self._warning('Invalid Frame', 'Enter a whole frame number.')
            self.frame_entry.setText(str(self.current_frame))
            return
        self.show_frame(frame_num)
        self.focus_preview()

    def set_start(self):
        if self.cap is None or self.busy:
            return
        self.start_frame = self.current_frame
        self.update_mark_status()

    def set_stop(self):
        if self.cap is None or self.busy:
            return
        self.stop_frame = self.current_frame
        self.update_mark_status()

    def get_current_frame_pil_image(self):
        if self.cap is None:
            return None
        frame = self.read_frame(self.current_frame)
        if frame is None:
            return None
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        return Image.fromarray(rgb_frame)

    def get_image_output_settings(self):
        base_name = self.image_basename_entry.text().strip() or self.name or 'video'
        output_dir = self.folder
        if self.image_to_frames_subfolder_checkbox.isChecked():
            subfolder = self.image_subfolder_entry.text().strip()
            reserved = {'CON', 'PRN', 'AUX', 'NUL'}
            reserved.update((f'{prefix}{n}' for prefix in ('COM', 'LPT') for n in '123456789Â¹Â²Â³'))
            if not subfolder or subfolder.endswith(('.', ' ')) or any((ch in '<>:"/\\|?*' or ord(ch) < 32 for ch in subfolder)) or (subfolder.split('.')[0].upper() in reserved):
                self._error('Invalid Subfolder', 'Enter a valid single subfolder name, such as Frames.')
                return None
            output_dir = os.path.join(output_dir, subfolder)
        return (base_name, output_dir)

    def get_frame_filename(self, base_name, frame_num):
        safe_name = self.sanitize_filename_part(base_name or 'video')
        milliseconds = int(round(self.frame_to_seconds(frame_num) * 1000))
        output_name = f'{safe_name}_frame{frame_num:06d}_{milliseconds:08d}ms.bmp'
        return output_name

    def save_current_frame_bitmap(self):
        """
        Save the currently displayed frame as a BMP image.

        The "Save to subfolder" checkbox controls whether the image
        is saved beside the source video or in a Frames subfolder.

        The "Monochrome" checkbox controls whether the image is saved as
        grayscale or full color.
        """
        if self.cap is None:
            self._warning('No Video', 'Load a video first.')
            return
        pil_image = self.get_current_frame_pil_image()
        if pil_image is None:
            self._error('Save Frame', 'Could not read the current frame.')
            return
        settings = self.get_image_output_settings()
        if settings is None:
            return
        base_name, output_dir = settings
        output_name = self.get_frame_filename(base_name, self.current_frame)
        try:
            os.makedirs(output_dir, exist_ok=True)
            output_path = self.get_unique_path(os.path.join(output_dir, output_name))
            if self.image_monochrome_checkbox.isChecked():
                pil_image.convert('L').save(output_path, 'BMP')
            else:
                pil_image.convert('RGB').save(output_path, 'BMP')
            self.set_progress(f'Saved frame bitmap: {output_path}', None)
            self.flash_video_border()
        except Exception as e:
            self._error('Save Frame', f'Could not save frame bitmap:\n{e}')

    def populate_image_range_from_marks(self):
        if self.start_frame is None or self.stop_frame is None:
            self._error('Missing Points', 'Set both START and STOP frames first.')
            return
        self.image_start_entry.setText(str(self.start_frame))
        self.image_stop_entry.setText(str(self.stop_frame))

    def get_image_export_range(self):
        if self.cap is None:
            self._error('No Video', 'Load a video first.')
            return None
        try:
            local_start_frame = int(self.image_start_entry.text().strip())
            local_stop_frame = int(self.image_stop_entry.text().strip())
            local_step = int(self.image_step_entry.text().strip())
        except ValueError:
            self._error('Invalid Frame Range', 'Start, Stop, and Step must be whole numbers.')
            return None
        if local_step <= 0:
            self._error('Invalid Step', 'Step must be 1 or greater.')
            return None
        if local_start_frame < 0 or local_stop_frame < 0:
            self._error('Invalid Frame Range', 'Start and Stop frames cannot be negative.')
            return None
        if local_start_frame >= self.frame_count or local_stop_frame >= self.frame_count:
            self._error('Invalid Frame Range', f'Start and Stop must be between 0 and {self.frame_count - 1}.')
            return None
        if local_stop_frame < local_start_frame:
            self._error('Invalid Frame Range', 'Stop frame must be greater than or equal to Start frame.')
            return None
        return (local_start_frame, local_stop_frame, local_step)

    def export_frame_images(self):
        if self.busy:
            self._info('Busy', 'Please wait for the current operation to finish.')
            return
        if self.cap is None:
            self._error('No Video', 'Load a video first.')
            return
        image_range = self.get_image_export_range()
        if image_range is None:
            return
        settings = self.get_image_output_settings()
        if settings is None:
            return
        base_name, output_dir = settings
        local_start_frame, local_stop_frame, local_step = image_range
        total = len(range(local_start_frame, local_stop_frame + 1, local_step))
        if total <= 0:
            self._error('Invalid Frame Range', 'No frames are included in this export range.')
            return
        self.set_busy(True, 'Saving frame images...')
        self.set_progress('Saving frame images...', 0)
        threading.Thread(target=self._export_frame_images, args=(self.proxy_path, local_start_frame, local_stop_frame, local_step, output_dir, base_name, self.image_monochrome_checkbox.isChecked()), daemon=True).start()

    def _export_frame_images(self, local_proxy_path, local_start_frame, local_stop_frame, local_step, local_folder, local_name, export_monochrome):
        """Save the selected proxy frames and report progress to the UI thread."""
        export_cap = open_video_capture(local_proxy_path)
        if not export_cap.isOpened():
            self.ui_queue.put(('error', 'Image Export Error', 'Could not open proxy video for image export.'))
            return
        frame_numbers = list(range(local_start_frame, local_stop_frame + 1, local_step))
        total = len(frame_numbers)
        saved_count = 0
        frames_folder = local_folder
        try:
            os.makedirs(frames_folder, exist_ok=True)
            for idx, frame_num in enumerate(frame_numbers, start=1):
                export_cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
                ret, frame = export_cap.read()
                if not ret:
                    raise RuntimeError(f'Could not read frame {frame_num}.')
                output_name = self.get_frame_filename(local_name, frame_num)
                output_path = self.get_unique_path(os.path.join(frames_folder, output_name))
                if export_monochrome:
                    gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    Image.fromarray(gray_frame).save(output_path, 'BMP')
                else:
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    Image.fromarray(rgb_frame).save(output_path, 'BMP')
                saved_count += 1
                percent = idx / total * 100 if total else 100
                self.ui_queue.put(('progress', f'Saving frame images... {idx}/{total} ({percent:0.1f}%)', percent))
        except Exception as e:
            self.ui_queue.put(('error', 'Image Export Error', f'Failed during image export:\n{e}'))
            return
        finally:
            export_cap.release()
        self.ui_queue.put(('image_export_done', frames_folder, saved_count))

    def export_clip(self):
        if self.busy:
            self._info('Busy', 'Please wait for the current operation to finish.')
            return
        if self.cap is None:
            self._error('No Video', 'Load a video first.')
            return
        if self.start_frame is None or self.stop_frame is None:
            self._error('Missing Points', 'Set both START and STOP frames.')
            return
        if self.stop_frame <= self.start_frame:
            self._error('Invalid Range', 'STOP frame must be after START frame.')
            return
        output_speed = self.get_output_speed()
        if output_speed is None:
            return
        output_path = self.get_output_path()
        if os.path.exists(output_path):
            overwrite = self._confirm('Overwrite File', f'This file already exists:\n{output_path}\n\nOverwrite it?')
            if not overwrite:
                return
        self.set_busy(True, 'Saving video...')
        self.set_progress('Saving video...', 0)
        threading.Thread(target=self._export_clip, args=(output_path, output_speed, self.proxy_path, self.fps, self.start_frame, self.stop_frame), daemon=True).start()

    def _export_clip(self, output_path, output_speed, local_proxy_path, local_fps, local_start_frame, local_stop_frame):
        """Render a silent clip at the requested playback speed."""
        source_duration = (local_stop_frame - local_start_frame + 1) / local_fps
        output_duration = source_duration / output_speed
        output_frame_count = max(1, int(round(output_duration * OUTPUT_FPS)))
        export_cap = open_video_capture(local_proxy_path)
        if not export_cap.isOpened():
            self.ui_queue.put(('error', 'Export Error', 'Could not open proxy video for export.'))
            return
        width = int(export_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(export_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        writer = cv2.VideoWriter(output_path, fourcc, OUTPUT_FPS, (width, height))
        if not writer.isOpened():
            export_cap.release()
            self.ui_queue.put(('error', 'Export Error', 'Could not open output video writer.'))
            return
        export_cap.set(cv2.CAP_PROP_POS_FRAMES, local_start_frame)
        source_idx = local_start_frame
        ret, current_source_frame = export_cap.read()
        if not ret:
            writer.release()
            export_cap.release()
            self.ui_queue.put(('error', 'Export Error', 'Could not read first source frame.'))
            return
        try:
            last_percent_int = -1
            for out_idx in range(output_frame_count):
                output_time = out_idx / OUTPUT_FPS
                desired_source_frame = local_start_frame + int(round(output_time * output_speed * local_fps))
                desired_source_frame = max(local_start_frame, min(desired_source_frame, local_stop_frame))
                while source_idx < desired_source_frame:
                    ret, current_source_frame = export_cap.read()
                    if not ret:
                        break
                    source_idx += 1
                writer.write(current_source_frame)
                percent = (out_idx + 1) / output_frame_count * 100
                percent_int = int(percent)
                if percent_int != last_percent_int:
                    last_percent_int = percent_int
                    self.ui_queue.put(('progress', f'Saving video... {percent:0.1f}%', percent))
        except Exception as e:
            self.ui_queue.put(('error', 'Export Error', f'Failed during export:\n{e}'))
            return
        finally:
            writer.release()
            export_cap.release()
        self.ui_queue.put(('export_done', output_path))
