"""Native Qt widgets, painting, and event handling for FrameLab."""
import csv
import io
import os
import queue
import sys

import cv2
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QFileDialog, QGridLayout,
    QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLayout, QLineEdit, QMainWindow,
    QMenu, QMessageBox, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
    QSlider, QSplitter, QStyle, QStyleOptionSlider, QTabWidget, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)
from framelab.operations import DEFAULT_OUTPUT_SPEED, FLAG_STRIP_HEIGHT, POLL_MS, TIMESTAMP_COLORS, VideoOperations, ZOOM_STEP


class ButtonFlowLayout(QLayout):
    """Wrap buttons onto another row when their natural widths no longer fit."""
    def __init__(self):
        super().__init__()
        self._items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(6)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._arrange(QRect(0, 0, width, 0), measure=True)

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def sizeHint(self):
        return self.minimumSize()

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._arrange(rect)

    def _arrange(self, rect, measure=False):
        x, y, row_height = rect.x(), rect.y(), 0
        for item in self._items:
            size = item.sizeHint()
            if row_height and x + size.width() > rect.x() + rect.width():
                x = rect.x()
                y += row_height + self.spacing()
                row_height = 0
            if not measure:
                item.setGeometry(QRect(QPoint(x, y), size))
            x += size.width() + self.spacing()
            row_height = max(row_height, size.height())
        return y + row_height - rect.y()


class CheckboxLabel(QLabel):
    """Keep a wrapping checkbox caption clickable."""
    def __init__(self, text, checkbox):
        super().__init__(text)
        self.checkbox = checkbox
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setWordWrap(True)
        self.setBuddy(checkbox)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.checkbox.click()
        else:
            super().mouseReleaseEvent(event)


class Preview(QWidget):
    """Paint the cached frame and accept mouse zoom/pan gestures."""
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.image = QImage()
        self.border = self.anchor = None
        self.setMinimumSize(240, 160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def clear(self):
        self.image = QImage()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.black)
        if self.image.isNull():
            prompt_font = painter.font()
            prompt_font.setPointSize(20)
            painter.setFont(prompt_font)
            painter.setPen(QColor('#9ca3af'))
            painter.drawText(
                self.rect().adjusted(16, 16, -16, -16),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                'Browse to load a video',
            )
        else:
            painter.drawImage(QPointF((self.width() - self.image.width()) / 2, (self.height() - self.image.height()) / 2), self.image)
            if self.owner.zoom > 1:
                text = f'Zoom {self.owner._scale * 100:.0f}% • drag to pan, double-click to reset'
                painter.setPen(Qt.GlobalColor.black)
                painter.drawText(13, 25, text)
                painter.setPen(QColor('#f3f3f3'))
                painter.drawText(12, 24, text)
        if self.border:
            painter.setPen(QPen(QColor(self.border), 4))
            painter.drawRect(self.rect().adjusted(2, 2, -3, -3))

    def resizeEvent(self, event):
        self.owner._clamp_view()
        self.owner._schedule_redraw()
        super().resizeEvent(event)

    def wheelEvent(self, event):
        if self.owner._frame_bgr is not None and self.owner._preview_box is not None:
            point = event.position()
            self.owner.zoom_at(ZOOM_STEP ** (event.angleDelta().y() / 120), point.x(), point.y())
        event.accept()

    def mousePressEvent(self, event):
        self.setFocus()
        if event.button() == Qt.MouseButton.LeftButton:
            self.anchor = event.position()
        elif event.button() == Qt.MouseButton.RightButton:
            self.owner.show_frame_context_menu(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event):
        owner = self.owner
        if self.anchor is not None and owner.zoom > 1 and owner._frame_bgr is not None:
            delta = event.position() - self.anchor
            self.anchor = event.position()
            h, w = owner._frame_bgr.shape[:2]
            owner.view_x -= delta.x() / owner._scale / w
            owner.view_y -= delta.y() / owner._scale / h
            owner._clamp_view()
            owner._schedule_redraw()

    def mouseReleaseEvent(self, event):
        self.anchor = None

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.owner.reset_zoom()


class TimelineSlider(QSlider):
    def __init__(self):
        super().__init__(Qt.Orientation.Horizontal)

    def handle_width(self):
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        return self.style().subControlRect(QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, self).width()

    def frame_x(self, frame):
        handle = self.handle_width()
        return handle / 2 + QStyle.sliderPositionFromValue(self.minimum(), self.maximum(), frame, max(1, self.width() - handle))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.handle_width()
            value = QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), round(event.position().x() - handle / 2), max(1, self.width() - handle))
            self.setValue(value)
        super().mousePressEvent(event)


class FlagStrip(QWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.setFixedHeight(FLAG_STRIP_HEIGHT)

    def paintEvent(self, event):
        painter = QPainter(self)
        if self.owner.cap is None or self.owner.frame_count < 2:
            return
        for index, entry in enumerate(self.owner.timestamps):
            x = self.owner.slider.frame_x(entry['frame'])
            color = QColor(TIMESTAMP_COLORS[index % len(TIMESTAMP_COLORS)])
            painter.setPen(QPen(color, 2))
            painter.drawLine(QPointF(x, 2), QPointF(x, FLAG_STRIP_HEIGHT))
            painter.setBrush(color)
            painter.drawPolygon(QPolygonF([QPointF(x, 2), QPointF(x + 11, 6), QPointF(x, 10)]))

    def mousePressEvent(self, event):
        if self.owner.busy or self.owner.cap is None or not self.owner.timestamps:
            return
        entry = min(self.owner.timestamps, key=lambda row: abs(self.owner.slider.frame_x(row['frame']) - event.position().x()))
        if abs(self.owner.slider.frame_x(entry['frame']) - event.position().x()) <= 12:
            self.owner.show_frame(entry['frame'])


class CompactTabs(QTabWidget):
    """Use the current page's minimum height so hidden pages do not waste space."""
    def minimumSizeHint(self):
        size = super().minimumSizeHint()
        if self.currentWidget():
            size.setHeight(self.tabBar().sizeHint().height() + self.currentWidget().minimumSizeHint().height() + 6)
        return size


class FrameLabApplication(QMainWindow, VideoOperations):
    """Keep all Qt operations on the main thread; poll messages from workers."""
    def __init__(self):
        super().__init__()
        self.setWindowTitle('FrameLab')
        self.resize(1500, 900)
        self.setMinimumSize(1120, 680)
        self.source_path = self.proxy_path = self.folder = self.filename = self.name = self.ext = None
        self.cap = None
        self.fps = self.original_fps = 0.0
        self.frame_count = self.current_frame = 0
        self.start_frame = self.stop_frame = None
        self.timestamps = []
        self.timestamp_sort = ('num', False)
        self.zoom = 1.0
        self.view_x = self.view_y = 0.0
        self._frame_bgr = self._preview_box = None
        self._scale = 1.0
        self._updating_slider = False
        self.busy = False
        self.output_filename_user_edited = False
        self.ui_queue = queue.Queue()
        self.ffmpeg_exe = None
        self._closed = self._initial_layout = False
        self._tab_heights = {}
        self._restoring_tab_height = False
        self._create_widgets()
        self.redraw_timer = QTimer(self)
        self.redraw_timer.setSingleShot(True)
        self.redraw_timer.timeout.connect(self._draw_preview)
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self._process_ui_events)
        self.poll_timer.start(POLL_MS)
        QApplication.instance().installEventFilter(self)
        self.set_busy(False)

    @staticmethod
    def _button(text, callback, tooltip=None):
        button = QPushButton(text)
        button.clicked.connect(lambda checked=False: callback())
        if tooltip:
            button.setToolTip(tooltip)
        return button

    @staticmethod
    def _entry(text='', width=None):
        entry = QLineEdit(text)
        if width:
            entry.setFixedWidth(width)
        return entry

    @staticmethod
    def _label(text):
        label = QLabel(text)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        return label

    def _card(self, title, layout):
        card = QGroupBox(title)
        contents = QVBoxLayout(card)
        layout.addWidget(card)
        return contents

    def _create_widgets(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        toolbar = QHBoxLayout()
        self.browse_button = self._button('Browse Video', self.browse_video, 'Open a video. Shortcut: B (outside text fields).')
        self.copy_button = self._button('Copy Frame', self.copy_current_frame_image, 'Copy the current frame image. Shortcut: Ctrl+C (outside text fields).')
        self.save_frame_button = self._button('Save Frame BMP', self.save_current_frame_bitmap, 'Save the current frame as a bitmap. Shortcut: Ctrl+F (outside text fields).')
        for button in (self.browse_button, self.copy_button, self.save_frame_button):
            toolbar.addWidget(button)
        toolbar.addStretch()
        self.file_label = self._label('No video loaded')
        toolbar.addWidget(self.file_label)
        layout.addLayout(toolbar)
        self.vertical_pane = QSplitter(Qt.Orientation.Vertical)
        self.vertical_pane.setChildrenCollapsible(False)
        self.vertical_pane.splitterMoved.connect(self._remember_bottom_height)
        layout.addWidget(self.vertical_pane, 1)
        self.main_pane = QSplitter(Qt.Orientation.Horizontal)
        self.main_pane.setChildrenCollapsible(False)
        self.vertical_pane.addWidget(self.main_pane)
        self.video_canvas = Preview(self)
        self.main_pane.addWidget(self.video_canvas)
        self.inspector = QWidget()
        inspector_layout = QVBoxLayout(self.inspector)
        self.inspector_scroll = QScrollArea()
        self.inspector_scroll.setWidgetResizable(True)
        self.inspector_scroll.setWidget(self.inspector)
        self.inspector_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.inspector_scroll.setMinimumWidth(180)
        self.main_pane.addWidget(self.inspector_scroll)
        self.main_pane.setStretchFactor(0, 1)
        self.main_pane.setStretchFactor(1, 0)
        self.main_pane.setSizes([1180, 300])
        card = self._card('Video', inspector_layout)
        self.info_label = self._label('No video loaded')
        self.info_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        card.addWidget(self.info_label)
        row = ButtonFlowLayout()
        self.set_fps_button = self._button('Set Frame Rate…', self.set_frame_rate)
        self.reset_fps_button = self._button('Reset', self.reset_frame_rate)
        row.addWidget(self.set_fps_button)
        row.addWidget(self.reset_fps_button)
        card.addLayout(row)
        card = self._card('Marked Range', inspector_layout)
        self.mark_label = self._label('Start: Not set\nStop: Not set')
        self.mark_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        card.addWidget(self.mark_label)
        row = ButtonFlowLayout()
        self.set_start_button = self._button('Set START (S)', self.set_start, 'Mark the current frame as START. Shortcut: S (outside text fields).')
        self.set_stop_button = self._button('Set STOP (E)', self.set_stop, 'Mark the current frame as STOP. Shortcut: E (outside text fields).')
        row.addWidget(self.set_start_button)
        row.addWidget(self.set_stop_button)
        card.addLayout(row)
        card = self._card('Progress', inspector_layout)
        self.progress_label = self._label('Idle')
        self.progress_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.progress_bar = QProgressBar()
        self.progress_bar.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.progress_bar.setMinimumWidth(50)
        self.progress_bar.setValue(0)
        card.addWidget(self.progress_label)
        card.addWidget(self.progress_bar)
        card = self._card('Options', inspector_layout)
        option_row = QHBoxLayout()
        self.delete_proxy_checkbox = QCheckBox()
        self.delete_proxy_checkbox.setToolTip('Delete proxy on Browse or Close')
        self.delete_proxy_checkbox.setAccessibleName('Delete proxy on Browse or Close')
        option_label = CheckboxLabel('Delete proxy on Browse or Close', self.delete_proxy_checkbox)
        option_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        option_row.addWidget(self.delete_proxy_checkbox)
        option_row.addWidget(option_label, 1)
        card.addLayout(option_row)
        inspector_layout.addStretch()
        self.bottom = QWidget()
        bottom = QVBoxLayout(self.bottom)
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(3)
        self.flag_canvas = FlagStrip(self)
        self.slider = TimelineSlider()
        self.slider.setRange(0, 1)
        self.slider.valueChanged.connect(self.slider_changed)
        bottom.addWidget(self.flag_canvas)
        bottom.addWidget(self.slider)
        self.notebook = CompactTabs()
        bottom.addWidget(self.notebook, 1)
        self.vertical_pane.addWidget(self.bottom)
        self.vertical_pane.setStretchFactor(0, 1)
        self.vertical_pane.setStretchFactor(1, 0)
        self._create_nav_tab()
        self._create_flags_tab()
        self._create_clip_tab()
        self._create_images_tab()
        self.notebook.currentChanged.connect(self._selected_tab_changed)

    def _create_nav_tab(self):
        self.nav_tab = QWidget()
        self.notebook.addTab(self.nav_tab, 'Navigate')
        grid = QGridLayout(self.nav_tab)
        grid.setContentsMargins(6, 4, 6, 4)
        grid.setVerticalSpacing(4)
        grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        for row, label, values in ((0, 'Frame step', (-100, -10, -1, 1, 10, 100)), (1, 'Time step', (-5, -1, -.1, .1, 1, 5))):
            grid.addWidget(QLabel(label), row, 0)
            for column, delta in enumerate(values, 1):
                callback = (lambda d=delta: self.jump_frames(d)) if row == 0 else (lambda d=delta: self.jump_seconds(d))
                tooltip = None
                if row == 0:
                    modifier = {1: '', 10: 'Shift+', 100: 'Ctrl+'}[abs(delta)]
                    arrow = 'Left' if delta < 0 else 'Right'
                    tooltip = f'Move {abs(delta)} frame(s) {"backward" if delta < 0 else "forward"}. Shortcut: {modifier}{arrow} (outside text fields).'
                grid.addWidget(self._button(f'{delta:+g}' + ('s' if row else ''), callback, tooltip), row, column)
        grid.setColumnStretch(7, 1)
        grid.addWidget(QLabel('Jump to frame'), 0, 8)
        self.frame_entry = self._entry('0', 100)
        self.frame_entry.returnPressed.connect(self.jump_to_frame_from_entry)
        grid.addWidget(self.frame_entry, 0, 9)

    def _create_flags_tab(self):
        self.timestamps_tab = QWidget()
        self.notebook.addTab(self.timestamps_tab, 'Flags')
        layout = QHBoxLayout(self.timestamps_tab)
        entry_layout = QVBoxLayout()
        entry_layout.addWidget(QLabel('Description'))
        self.timestamp_entry = self._entry()
        self.timestamp_entry.setMinimumWidth(230)
        self.timestamp_entry.returnPressed.connect(self.add_timestamp)
        entry_layout.addWidget(self.timestamp_entry)
        self.add_timestamp_button = self._button('Add Flag (F)', self.add_timestamp, 'Flag the current frame. Shortcut: F (outside text fields), or Enter in the description field.')
        entry_layout.addWidget(self.add_timestamp_button)
        entry_layout.addStretch()
        layout.addLayout(entry_layout)
        self.timestamp_tree = QTreeWidget()
        self.timestamp_tree.setColumnCount(5)
        self.timestamp_tree.setHeaderLabels(['Flag', '#', 'Time', 'Frame', 'Description'])
        self.timestamp_tree.setRootIsDecorated(False)
        self.timestamp_tree.setUniformRowHeights(True)
        self.timestamp_tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.timestamp_tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.timestamp_tree.setMinimumHeight(90)
        self.timestamp_tree.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        for index, width in enumerate((48, 45, 100, 85)):
            self.timestamp_tree.setColumnWidth(index, width)
        self.timestamp_tree.header().setSectionsClickable(True)
        self.timestamp_tree.header().sectionClicked.connect(lambda index: self.sort_timestamps_by(('#0', 'num', 'time', 'frame', 'description')[index]))
        self.timestamp_tree.itemSelectionChanged.connect(self.jump_to_selected_timestamp)
        layout.addWidget(self.timestamp_tree, 1)
        actions = QGridLayout()
        self.import_timestamps_button = self._button('Import…', self.import_timestamps)
        self.export_timestamps_button = self._button('Export…', self.export_timestamps)
        self.delete_timestamp_button = self._button('Delete', self.delete_timestamp, 'Delete selected flags. Shortcut: Delete (when the flags table has focus).')
        self.copy_timestamps_button = self._button('Copy', self.copy_timestamps_to_clipboard)
        for row, column, button in ((0, 0, self.import_timestamps_button), (0, 1, self.export_timestamps_button), (1, 0, self.delete_timestamp_button), (1, 1, self.copy_timestamps_button)):
            actions.addWidget(button, row, column)
        actions.setRowStretch(2, 1)
        layout.addLayout(actions)

    def _create_clip_tab(self):
        self.clip_tab = QWidget()
        self.notebook.addTab(self.clip_tab, 'Clip Export')
        grid = QGridLayout(self.clip_tab)
        grid.setContentsMargins(6, 4, 6, 4)
        grid.setVerticalSpacing(4)
        grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        grid.addWidget(QLabel('Output Speed'), 0, 0)
        self.speed_entry = self._entry(str(DEFAULT_OUTPUT_SPEED), 80)
        self.speed_entry.editingFinished.connect(self.update_default_output_filename_if_allowed)
        grid.addWidget(self.speed_entry, 0, 1)
        grid.addWidget(QLabel('1.0 = normal speed • 0.1 = 10% speed • Output = 30 FPS, no audio'), 0, 2)
        grid.addWidget(QLabel('Save As'), 1, 0)
        self.output_filename_entry = self._entry()
        self.output_filename_entry.textEdited.connect(lambda text: self.mark_output_filename_edited())
        grid.addWidget(self.output_filename_entry, 1, 1, 1, 2)
        self.export_button = self._button('Export Clip (Q)', self.export_clip, 'Export the marked range as a clip. Shortcut: Q (outside text fields).')
        grid.addWidget(self.export_button, 1, 3)
        grid.setColumnStretch(2, 1)

    def _create_images_tab(self):
        self.images_tab = QWidget()
        self.notebook.addTab(self.images_tab, 'Frame Images')
        outer = QVBoxLayout(self.images_tab)
        outer.setContentsMargins(6, 4, 6, 4)
        outer.setSpacing(4)
        outer.setAlignment(Qt.AlignmentFlag.AlignTop)
        row = QHBoxLayout()
        for label, name, value in (('Start', 'image_start_entry', ''), ('Stop', 'image_stop_entry', ''), ('Step', 'image_step_entry', '1')):
            entry = self._entry(value, 85)
            setattr(self, name, entry)
            row.addWidget(QLabel(label))
            row.addWidget(entry)
        self.use_marked_range_button = self._button('Use START/STOP', self.populate_image_range_from_marks)
        row.addWidget(self.use_marked_range_button)
        row.addStretch()
        self.image_monochrome_checkbox = QCheckBox('Monochrome')
        self.image_monochrome_checkbox.setChecked(True)
        self.export_images_button = self._button('Export Images', self.export_frame_images)
        row.addWidget(self.image_monochrome_checkbox)
        row.addWidget(self.export_images_button)
        outer.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel('Basename'))
        self.image_basename_entry = self._entry()
        row.addWidget(self.image_basename_entry, 3)
        self.image_to_frames_subfolder_checkbox = QCheckBox('Save to subfolder')
        self.image_to_frames_subfolder_checkbox.setChecked(True)
        self.image_to_frames_subfolder_checkbox.toggled.connect(self.update_image_subfolder_state)
        row.addWidget(self.image_to_frames_subfolder_checkbox)
        self.image_subfolder_entry = self._entry('Frames')
        row.addWidget(self.image_subfolder_entry, 2)
        outer.addLayout(row)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._initial_layout:
            self._initial_layout = True
            QTimer.singleShot(0, self._fit_bottom_to_selected_tab)

    def _selected_tab_changed(self, index):
        self.notebook.updateGeometry()
        if self._initial_layout:
            QTimer.singleShot(0, self._fit_bottom_to_selected_tab)

    def _fit_bottom_to_selected_tab(self):
        page = self.notebook.currentWidget()
        if page is None:
            return
        minimum = self.bottom.minimumSizeHint().height()
        height = max(minimum, self._tab_heights.get(page, minimum))
        available = self.vertical_pane.height() - self.vertical_pane.handleWidth()
        self._restoring_tab_height = True
        try:
            self.vertical_pane.setSizes([max(160, available - height), height])
        finally:
            self._restoring_tab_height = False

    def _remember_bottom_height(self, position, index):
        if not self._restoring_tab_height and self._initial_layout:
            self._tab_heights[self.notebook.currentWidget()] = self.bottom.height()

    def focus_preview(self):
        self.video_canvas.setFocus()

    def text_entry_has_focus(self):
        return isinstance(QApplication.focusWidget(), QLineEdit)

    def eventFilter(self, watched, event):
        if event.type() != QEvent.Type.KeyPress or not isinstance(watched, QWidget):
            return super().eventFilter(watched, event)
        if watched is not self and not self.isAncestorOf(watched):
            return super().eventFilter(watched, event)
        if QApplication.activeModalWidget() is not None:
            return False
        if self.text_entry_has_focus():
            if event.key() == Qt.Key.Key_Escape:
                self.focus_preview()
                return True
            return False
        key, modifiers = event.key(), event.modifiers()
        control = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        if modifiers & (Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier):
            return False
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            step = 100 if control else 10 if shift else 1
            self.jump_frames(-step if key == Qt.Key.Key_Left else step)
            return True
        if control:
            if key == Qt.Key.Key_C:
                self.copy_current_frame_image()
                return True
            if key == Qt.Key.Key_F:
                self.save_current_frame_bitmap()
                return True
            if key == Qt.Key.Key_A and watched is self.timestamp_tree:
                self.timestamp_tree.selectAll()
                return True
            return False
        if key == Qt.Key.Key_Delete and watched is self.timestamp_tree:
            self.delete_timestamp()
            return True
        actions = {Qt.Key.Key_S: self.set_start, Qt.Key.Key_E: self.set_stop, Qt.Key.Key_Q: self.export_clip, Qt.Key.Key_F: self.add_timestamp, Qt.Key.Key_B: self.browse_video}
        if key in actions:
            actions[key]()
            return True
        return False

    def set_busy(self, value, status_text=None):
        self.busy = value
        for widget in (self.browse_button, self.copy_button, self.save_frame_button, self.add_timestamp_button, self.delete_timestamp_button, self.copy_timestamps_button, self.export_timestamps_button, self.import_timestamps_button, self.export_button, self.export_images_button, self.use_marked_range_button, self.set_start_button, self.set_stop_button, self.image_to_frames_subfolder_checkbox, self.image_monochrome_checkbox, self.image_basename_entry, self.speed_entry, self.output_filename_entry, self.image_start_entry, self.image_stop_entry, self.image_step_entry):
            widget.setEnabled(not value)
        self.slider.setEnabled(self.cap is not None and not value)
        self.update_frame_rate_controls()
        self.update_image_subfolder_state()
        if status_text is not None:
            self.progress_label.setText(status_text)

    def update_frame_rate_controls(self):
        enabled = self.cap is not None and not self.busy
        self.set_fps_button.setEnabled(enabled)
        self.reset_fps_button.setEnabled(enabled and self.frame_rate_overridden())

    def update_image_subfolder_state(self):
        self.image_subfolder_entry.setEnabled(self.image_to_frames_subfolder_checkbox.isChecked() and not self.busy)

    def set_progress(self, label=None, percent=None):
        if label is not None:
            self.progress_label.setText(label)
        if percent is not None:
            self.progress_bar.setValue(round(max(0, min(100, float(percent)))))

    def _process_ui_events(self):
        while not self._closed:
            try:
                item = self.ui_queue.get_nowait()
            except queue.Empty:
                break
            kind = item[0]
            if kind == 'progress':
                self.set_progress(item[1], item[2])
            elif kind == 'error':
                self.set_busy(False, 'Error')
                self._error(item[1], item[2])
            elif kind == 'proxy_done':
                self.set_progress('Opening proxy…', 100)
                self._finish_loading_proxy(item[1])
            elif kind in ('export_done', 'image_export_done'):
                self.set_busy(False, 'Export complete')
                self.set_progress('Export complete', 100)
                message = f'Saved:\n{item[1]}' if kind == 'export_done' else f'Saved {item[2]} image(s) to:\n{item[1]}'
                self._info('Done', message)

    def add_timestamp(self):
        if self.cap is None or self.busy:
            return
        self.timestamps.append({'frame': self.current_frame, 'description': self.timestamp_entry.text().strip()})
        self.timestamp_entry.clear()
        self.refresh_timestamps()
        self.timestamp_tree.scrollToItem(self._items[len(self.timestamps) - 1])
        self.focus_preview()

    def delete_timestamp(self):
        if self.busy:
            return
        indices = [item.data(0, Qt.ItemDataRole.UserRole) for item in self.timestamp_tree.selectedItems()]
        for index in sorted(indices, reverse=True):
            del self.timestamps[index]
        self.refresh_timestamps()

    def jump_to_selected_timestamp(self):
        selection = self.timestamp_tree.selectedItems()
        if len(selection) == 1 and self.cap is not None and not self.busy:
            self.show_frame(self.timestamps[selection[0].data(0, Qt.ItemDataRole.UserRole)]['frame'])

    def refresh_timestamps(self):
        self.timestamp_tree.blockSignals(True)
        try:
            self.timestamp_tree.clear()
            self._items = {}
            for index in self.timestamp_view_order():
                entry = self.timestamps[index]
                item = QTreeWidgetItem(['', str(index + 1), self.format_time(self.frame_to_seconds(entry['frame'])), str(entry['frame']), entry['description']])
                item.setData(0, Qt.ItemDataRole.UserRole, index)
                icon = QPixmap(16, 16)
                icon.fill(Qt.GlobalColor.transparent)
                painter = QPainter(icon)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(self.timestamp_color(index)))
                painter.drawEllipse(QRectF(2, 2, 12, 12))
                painter.end()
                item.setIcon(0, QIcon(icon))
                self.timestamp_tree.addTopLevelItem(item)
                self._items[index] = item
            active, descending = self.timestamp_sort
            self.timestamp_tree.header().setSortIndicator(('#0', 'num', 'time', 'frame', 'description').index(active), Qt.SortOrder.DescendingOrder if descending else Qt.SortOrder.AscendingOrder)
            self.timestamp_tree.header().setSortIndicatorShown(True)
        finally:
            self.timestamp_tree.blockSignals(False)
        self.draw_flags()

    def draw_flags(self):
        self.flag_canvas.update()

    def copy_timestamps_to_clipboard(self):
        if not self.timestamps:
            self._info('No Flags', 'Add at least one flag first.')
            return
        buffer = io.StringIO()
        csv.writer(buffer, delimiter='\t', lineterminator='\n').writerows(self.timestamp_text_rows())
        QApplication.clipboard().setText(buffer.getvalue())
        self.progress_label.setText(f'Copied {len(self.timestamps)} flags to clipboard')

    def _draw_preview(self):
        if self._frame_bgr is None or self._closed:
            return
        preview = cv2.cvtColor(self.resize_frame_for_preview(self._frame_bgr), cv2.COLOR_BGR2RGB)
        h, w = preview.shape[:2]
        self.video_canvas.image = QImage(preview.data, w, h, preview.strides[0], QImage.Format.Format_RGB888).copy()
        self._preview_box = ((self.video_canvas.width() - w) / 2, (self.video_canvas.height() - h) / 2, w, h)
        self.video_canvas.update()

    def _schedule_redraw(self):
        if hasattr(self, 'redraw_timer') and not self.redraw_timer.isActive():
            self.redraw_timer.start(0)

    def copy_current_frame_image(self):
        if self.cap is None or self.busy:
            return
        image = self.get_current_frame_pil_image()
        if image is None:
            self._error('Copy Frame', 'Could not read the current frame.')
            return
        rgb = image.convert('RGB')
        data = rgb.tobytes()
        QApplication.clipboard().setImage(QImage(data, rgb.width, rgb.height, rgb.width * 3, QImage.Format.Format_RGB888).copy())
        self.set_progress(f'Copied frame {self.current_frame} image to clipboard.')

    def flash_video_border(self, color='#00ff00', thickness=4, duration_ms=150):
        self.video_canvas.border = color
        self.video_canvas.update()
        QTimer.singleShot(duration_ms, self._clear_video_border)

    def _clear_video_border(self):
        self.video_canvas.border = None
        self.video_canvas.update()

    def show_frame_context_menu(self, position):
        if self.cap is None or self.busy:
            return
        menu = QMenu(self)
        menu.addAction('Copy image from current frame', self.copy_current_frame_image)
        menu.addAction('Save bitmap image from current frame', self.save_current_frame_bitmap)
        menu.exec(position)

    def _error(self, title, text):
        QMessageBox.critical(self, title, text)

    def _warning(self, title, text):
        QMessageBox.warning(self, title, text)

    def _info(self, title, text):
        QMessageBox.information(self, title, text)

    def _confirm(self, title, text):
        return QMessageBox.question(self, title, text) == QMessageBox.StandardButton.Yes

    def _replace_or_append(self, title, text):
        answer = QMessageBox.question(self, title, text, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel)
        return None if answer == QMessageBox.StandardButton.Cancel else answer == QMessageBox.StandardButton.Yes

    @staticmethod
    def _filters(filetypes):
        return ';;'.join(f'{label} ({patterns})' for label, patterns in filetypes)

    def _open_file(self, title, filetypes, initialdir=None):
        return QFileDialog.getOpenFileName(self, title, initialdir or '', self._filters(filetypes))[0]

    def _save_file(self, title, filetypes, initialdir=None, initialfile='', defaultextension=''):
        dialog = QFileDialog(self, title, os.path.join(initialdir or '', initialfile))
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dialog.setNameFilters(self._filters(filetypes).split(';;'))
        dialog.setDefaultSuffix(defaultextension.lstrip('.'))
        dialog.filterSelected.connect(lambda selected: dialog.setDefaultSuffix('csv' if '*.csv' in selected else 'xlsx'))
        return dialog.selectedFiles()[0] if dialog.exec() else ''

    def _ask_float(self, title, text, initialvalue, minvalue, maxvalue):
        value, accepted = QInputDialog.getDouble(self, title, text, initialvalue, minvalue, maxvalue, 3)
        return value if accepted else None

    def closeEvent(self, event):
        if self.busy and not self._confirm('Operation Running', 'An operation is still running. Close anyway?'):
            event.ignore()
            return
        self._closed = True
        self.poll_timer.stop()
        self.redraw_timer.stop()
        QApplication.instance().removeEventFilter(self)
        if not self.busy:
            self.clear_current_video()
        elif self.cap is not None:
            self.cap.release()
            self.cap = None
        event.accept()


def configure_theme(application):
    application.setStyle('Fusion')
    application.setStyleSheet('''
        QWidget { background: #202124; color: #f3f3f3; font-size: 12px; }
        QGroupBox { border: 1px solid #484b50; border-radius: 5px; margin-top: 10px; padding-top: 8px; }
        QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
        QPushButton { background: #34363b; border: 1px solid #55585f; border-radius: 4px; padding: 6px 10px; }
        QPushButton:hover { background: #454850; }
        QLineEdit, QTreeWidget { background: #17181b; border: 1px solid #55585f; padding: 4px; }
        QTreeWidget::item { height: 26px; }
        QTreeWidget::item:selected { background: #315c80; }
        QWidget:disabled { color: #808080; }
        QTabBar::tab { padding: 7px 14px; background: #292b30; }
        QTabBar::tab:selected { background: #41444b; }
        QHeaderView::section { background: #34363b; padding: 5px; }
        QSplitter::handle { background: #44474d; }
    ''')


def main():
    application = QApplication.instance() or QApplication(sys.argv)
    application.setApplicationName('FrameLab')
    configure_theme(application)
    window = FrameLabApplication()
    window.showMaximized()
    return application.exec()
