"""Regression coverage for the Qt port using real generated video frames."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np
from PIL import Image
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from framelab.qt_window import FrameLabApplication, configure_theme
from framelab.operations import open_video_capture


class QtApplicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])
        # Windows' offscreen plugin does not discover system fonts itself.
        font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/segoeui.ttf"
        if not QFontDatabase.families() and font.is_file():
            QFontDatabase.addApplicationFont(str(font))
            cls.application.setFont(QFont("Segoe UI", 9))
        configure_theme(cls.application)
        cls.directory = tempfile.TemporaryDirectory()
        cls.video = Path(cls.directory.name) / "sample.mp4"
        writer = cv2.VideoWriter(str(cls.video), cv2.VideoWriter_fourcc(*"mp4v"), 30, (320, 240))
        assert writer.isOpened()
        for index in range(120):
            frame = np.full((240, 320, 3), (index, 50, 200), np.uint8)
            cv2.putText(frame, str(index), (60, 100), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
            writer.write(frame)
        writer.release()

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def setUp(self):
        self.window = FrameLabApplication()
        self.window._error = Mock(side_effect=lambda title, text: self.fail(f"{title}: {text}"))
        self.window._info = Mock()
        self.window._warning = Mock()
        self.window.show()
        self.application.processEvents()
        self.window.source_path = str(self.video)
        self.window.proxy_path = str(self.video)
        self.window.folder = self.directory.name
        self.window.filename = "sample.mp4"
        self.window.name, self.window.ext = "sample", ".mp4"
        self.assertTrue(self.window._open_proxy())
        self.window.show_frame(0)
        self.window.set_busy(False)
        self.application.processEvents()

    def tearDown(self):
        self.window.busy = False
        self.window.delete_proxy_checkbox.setChecked(False)
        self.window.close()
        self.application.processEvents()

    def wait_for_worker(self):
        deadline = time.monotonic() + 15
        while self.window.busy and time.monotonic() < deadline:
            self.application.processEvents()
            time.sleep(.01)
        self.assertFalse(self.window.busy, "Background operation did not finish")

    def test_navigation_hotkeys_and_text_focus(self):
        window = self.window
        window.focus_preview()
        QTest.keyClick(window.video_canvas, Qt.Key.Key_Right)
        self.assertEqual(window.current_frame, 1)
        QTest.keyClick(window.video_canvas, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(window.current_frame, 11)
        QTest.keyClick(window.video_canvas, Qt.Key.Key_Left, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(window.current_frame, 0)
        window.frame_entry.setText("45")
        QTest.keyClick(window.frame_entry, Qt.Key.Key_Return)
        self.assertEqual(window.current_frame, 45)
        window.notebook.setCurrentWidget(window.timestamps_tab)
        window.timestamp_entry.setFocus()
        self.application.processEvents()
        QTest.keyClicks(window.timestamp_entry, "flag")
        self.assertEqual(window.timestamp_entry.text(), "flag")
        self.assertEqual(window.timestamps, [])
        QTest.keyClick(window.timestamp_entry, Qt.Key.Key_Return)
        self.assertEqual(window.timestamps[0], {"frame": 45, "description": "flag"})
        QTest.keyClick(window.video_canvas, Qt.Key.Key_F)
        self.assertEqual(len(window.timestamps), 2)
        QTest.keyClick(window.video_canvas, Qt.Key.Key_T)
        self.assertEqual(len(window.timestamps), 2)

    def test_flags_sort_select_delete_and_timeline(self):
        window = self.window
        window.timestamps = [{"frame": 90, "description": "late"}, {"frame": 15, "description": "early"}]
        window.refresh_timestamps()
        window.sort_timestamps_by("frame")
        self.assertEqual(window.timestamp_tree.topLevelItem(0).text(3), "15")
        item = window.timestamp_tree.topLevelItem(0)
        window.timestamp_tree.setCurrentItem(item)
        self.assertEqual(window.current_frame, 15)
        window.delete_timestamp()
        self.assertEqual(window.timestamps, [{"frame": 90, "description": "late"}])
        QTest.mouseClick(window.flag_canvas, Qt.MouseButton.LeftButton, pos=QPoint(round(window.slider.frame_x(90)), 6))
        self.assertEqual(window.current_frame, 90)

    def test_fps_override_reset_and_busy_state(self):
        window = self.window
        window.timestamps = [{"frame": 60, "description": "test"}]
        window.refresh_timestamps()
        with patch.object(window, "_ask_float", return_value=60):
            window.set_frame_rate()
        self.assertEqual(window.original_fps, 30)
        self.assertIn("Override FPS:", window.info_label.text())
        self.assertEqual(window.timestamp_tree.topLevelItem(0).text(2), "00:01.000")
        window.set_busy(True)
        self.assertFalse(window.reset_fps_button.isEnabled())
        window.reset_frame_rate()
        self.assertEqual(window.fps, 60)
        window.set_busy(False)
        window.reset_fps_button.click()
        self.assertEqual(window.fps, 30)
        self.assertNotIn("Override FPS:", window.info_label.text())
        self.assertEqual(window.timestamp_tree.topLevelItem(0).text(2), "00:02.000")

    def test_preview_zoom_pan_and_compact_layout(self):
        window = self.window
        self.assertFalse(window.video_canvas.image.isNull())
        window.zoom_at(2, window.video_canvas.width() / 2, window.video_canvas.height() / 2)
        self.application.processEvents()
        self.assertEqual(window.zoom, 2)
        self.assertGreater(window._scale, 1)
        window.view_x = window.view_y = 10
        window._clamp_view()
        self.assertLess(window.view_x, 1)
        window.reset_zoom()
        self.application.processEvents()
        self.assertEqual(window.zoom, 1)
        for index in range(window.notebook.count()):
            window.notebook.setCurrentIndex(index)
            self.application.processEvents()
            page = window.notebook.currentWidget()
            self.assertGreaterEqual(page.height(), page.minimumSizeHint().height())
        self.assertLess(window.bottom.height(), 240)

    def test_bottom_pane_height_follows_selected_tab(self):
        window = self.window
        heights = {}
        for tab in (window.nav_tab, window.timestamps_tab, window.clip_tab, window.images_tab, window.nav_tab):
            window.notebook.setCurrentWidget(tab)
            for _ in range(3):
                self.application.processEvents()
            heights[tab] = window.bottom.height()
            self.assertGreaterEqual(tab.height(), tab.minimumSizeHint().height())
        for tab in (window.nav_tab, window.clip_tab, window.images_tab):
            self.assertLess(heights[tab], heights[window.timestamps_tab])
        before = window.bottom.height()
        window.vertical_pane.setSizes([400, 400])
        self.application.processEvents()
        self.assertGreater(window.bottom.height(), before)
        window.notebook.setCurrentWidget(window.timestamps_tab)
        for _ in range(3):
            self.application.processEvents()
        self.assertEqual(window.bottom.height(), heights[window.timestamps_tab])

    def test_each_tab_remembers_its_height_for_the_session(self):
        window = self.window
        tabs = (window.nav_tab, window.timestamps_tab, window.clip_tab, window.images_tab)
        saved = {}
        for index, tab in enumerate(tabs):
            window.notebook.setCurrentWidget(tab)
            for _ in range(3):
                self.application.processEvents()
            window.vertical_pane.moveSplitter(window.vertical_pane.height() - 240 - index * 30, 1)
            self.application.processEvents()
            saved[tab] = window.bottom.height()
        for tab in reversed(tabs):
            window.notebook.setCurrentWidget(tab)
            for _ in range(3):
                self.application.processEvents()
            self.assertEqual(window.bottom.height(), saved[tab])
        fresh = FrameLabApplication()
        try:
            fresh.show()
            self.application.processEvents()
            self.assertLess(fresh.bottom.height(), saved[window.nav_tab])
            self.assertEqual(fresh._tab_heights, {})
        finally:
            fresh.close()

    def test_sidebar_reflows_without_horizontal_clipping(self):
        window = self.window
        window.progress_label.setText("Exporting video to a very long output filename " * 3)
        window.set_progress(percent=57)
        for width in (360, 200, 280, 180, 360):
            window.main_pane.setSizes([window.main_pane.width() - width, width])
            for _ in range(3):
                self.application.processEvents()
            viewport = window.inspector_scroll.viewport()
            self.assertLessEqual(window.inspector.width(), viewport.width())
            for widget in (window.progress_bar, window.set_fps_button, window.reset_fps_button,
                           window.set_start_button, window.set_stop_button):
                position = widget.mapTo(window.inspector, QPoint(0, 0))
                self.assertGreaterEqual(position.x(), 0)
                self.assertLessEqual(position.x() + widget.width(), viewport.width())
                self.assertGreaterEqual(widget.width(), widget.minimumSizeHint().width())
            if width <= 200:
                self.assertGreater(window.reset_fps_button.y(), window.set_fps_button.y())
                self.assertGreater(window.set_stop_button.y(), window.set_start_button.y())
            elif width == 360:
                self.assertEqual(window.reset_fps_button.y(), window.set_fps_button.y())
                self.assertEqual(window.set_stop_button.y(), window.set_start_button.y())

    def test_csv_xlsx_and_clipboard_roundtrip(self):
        window = self.window
        expected = [{"frame": 60, "description": "Unicode café, tab\there"}]
        window.timestamps = expected.copy()
        for suffix in ("csv", "xlsx"):
            target = Path(self.directory.name) / f"flags.{suffix}"
            with patch.object(window, "_save_file", return_value=str(target)):
                window.export_timestamps()
            window.timestamps = []
            with patch.object(window, "_open_file", return_value=str(target)):
                window.import_timestamps()
            self.assertEqual(window.timestamps, expected)
        window.copy_timestamps_to_clipboard()
        self.assertIn("Unicode café", QApplication.clipboard().text())
        window.copy_current_frame_image()
        self.assertEqual(QApplication.clipboard().image().width(), 320)

    def test_image_save_and_worker_export(self):
        window = self.window
        window.image_subfolder_entry.setText("qt-images")
        window.image_basename_entry.setText("qt-test")
        window.show_frame(15)
        window.save_current_frame_bitmap()
        target = Path(self.directory.name) / "qt-images" / window.get_frame_filename("qt-test", 15)
        with Image.open(target) as image:
            self.assertEqual(image.mode, "L")
        window.start_frame, window.stop_frame = 0, 4
        window.populate_image_range_from_marks()
        window.image_step_entry.setText("2")
        window.image_monochrome_checkbox.setChecked(False)
        window.export_frame_images()
        self.wait_for_worker()
        for frame in (0, 2, 4):
            with Image.open(target.parent / window.get_frame_filename("qt-test", frame)) as image:
                self.assertEqual(image.mode, "RGB")

    def test_clip_worker_preserves_timing(self):
        window = self.window
        window.start_frame, window.stop_frame = 0, 29
        window.speed_entry.setText("0.5")
        window.output_filename_entry.setText("qt-export.mp4")
        window.export_clip()
        self.wait_for_worker()
        cap = open_video_capture(str(Path(self.directory.name) / "qt-export.mp4"))
        try:
            self.assertTrue(cap.isOpened())
            self.assertEqual(round(cap.get(cv2.CAP_PROP_FPS)), 30)
            self.assertEqual(round(cap.get(cv2.CAP_PROP_FRAME_COUNT)), 60)
        finally:
            cap.release()

    def test_proxy_worker_loads_and_clears_video(self):
        self.window.start_load_video(str(self.video))
        self.wait_for_worker()
        self.assertEqual(self.window.frame_count, 120)
        self.assertEqual(self.window.original_fps, 30)
        self.assertEqual(self.window.current_frame, 0)
        self.assertFalse(self.window.video_canvas.image.isNull())
        self.window.clear_current_video()
        self.assertIsNone(self.window.cap)
        self.assertTrue(self.window.video_canvas.image.isNull())
        self.assertFalse(self.window.set_fps_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
