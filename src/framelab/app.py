"""
FrameLab

Desktop application for frame-accurate video inspection, trimming,
slow-motion export, and frame extraction.

Requires:
    pip install opencv-python pillow sv-ttk

The ffmpeg executable must be installed separately and available on PATH.

sv_ttk is optional. If it is not installed, the app falls back to the best
available built-in ttk theme.
"""

import ctypes
import io
import os
import queue
import re
import shutil
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import cv2
from PIL import Image, ImageTk

try:
    import sv_ttk
except ImportError:  # App still works without sv_ttk.
    sv_ttk = None


# Video/export defaults are centralized here so UI code and worker code use
# the same encoding assumptions.
DEFAULT_OUTPUT_SPEED = 0.1
OUTPUT_FPS = 30.0
PROXY_CRF = "23"
PROXY_PRESET = "ultrafast"
PREVIEW_MAX_UPSCALE = 1.0      # 1.0 = never enlarge beyond source resolution
POLL_MS = 50



class Tooltip:
    """Show delayed help text in a small borderless popup."""

    def __init__(self, widget, text_getter, delay_ms=350):
        self.widget = widget
        self.text_getter = text_getter
        self.delay_ms = delay_ms
        self._after_id = None
        self._tip = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, event=None):
        self._cancel()
        self._after_id = self.widget.after(self.delay_ms, self._show)

    def _cancel(self):
        if self._after_id is not None:
            self.widget.after_cancel(self._after_id)
            self._after_id = None

    def _show(self):
        self._after_id = None
        text = self.text_getter() if callable(self.text_getter) else str(self.text_getter)
        if not text:
            return

        self._hide()
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8

        self._tip = tk.Toplevel(self.widget)
        self._tip.wm_overrideredirect(True)
        self._tip.wm_geometry(f"+{x}+{y}")

        label = tk.Label(
            self._tip,
            text=text,
            justify=tk.LEFT,
            background="#ffffe0",
            foreground="#111111",
            relief=tk.SOLID,
            borderwidth=1,
            padx=8,
            pady=5,
            wraplength=900,
        )
        label.pack()

    def _hide(self, event=None):
        self._cancel()
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None


class FrameLabApplication:
    """Own the FrameLab interface and coordinate video-processing jobs.

    Tkinter is not thread-safe, so proxy creation and exports run in worker
    threads. Workers communicate with the main thread exclusively through
    ``ui_queue``; ``_process_ui_events`` applies their updates to the UI.
    """
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("FrameLab")
        self.root.geometry("1500x900")
        self.root.minsize(1120, 680)

        # Video/source state
        self.source_path = None
        self.proxy_path = None
        self.folder = None
        self.filename = None
        self.name = None
        self.ext = None

        self.cap = None
        self.fps = 0.0
        self.frame_count = 0
        self.current_frame = 0
        self.start_frame = None
        self.stop_frame = None
        self.current_tk_image = None
        self.resize_job = None

        # UI/work state
        self.busy = False
        self.output_filename_user_edited = False
        self.ui_queue = queue.Queue()
        self.ffmpeg_exe = None

        # Variables
        self.delete_proxy_on_close_var = tk.BooleanVar(value=False)
        self.speed_var = tk.StringVar(value=str(DEFAULT_OUTPUT_SPEED))
        self.output_filename_var = tk.StringVar(value="")
        self.image_start_var = tk.StringVar(value="")
        self.image_stop_var = tk.StringVar(value="")
        self.image_step_var = tk.StringVar(value="1")
        self.image_monochrome_var = tk.BooleanVar(value=True)
        self.image_to_frames_subfolder_var = tk.BooleanVar(value=True)
        self.current_frame_var = tk.StringVar(value="0")
        self._updating_slider = False

        self._configure_theme()
        self._create_widgets()
        self._bind_events()

        self._process_ui_events()

    # -- Interface construction -------------------------------------------------
    def _configure_theme(self):
        if sv_ttk is not None:
            sv_ttk.use_dark_theme()
            return

        style = ttk.Style(self.root)
        preferred = "clam" if "clam" in style.theme_names() else style.theme_use()
        style.theme_use(preferred)
        style.configure("TFrame", background="#1f1f1f")
        style.configure("TLabelframe", background="#1f1f1f", borderwidth=1)
        style.configure("TLabelframe.Label", background="#1f1f1f", foreground="#f3f3f3")
        style.configure("TLabel", background="#1f1f1f", foreground="#f3f3f3")
        style.configure("TButton", padding=(10, 6))
        style.configure("Accent.TButton", padding=(12, 7))

    def _create_widgets(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        # ----- Top command bar -----
        self.toolbar = ttk.Frame(self.root, padding=(10, 8))
        self.toolbar.grid(row=0, column=0, sticky="ew")
        self.toolbar.columnconfigure(10, weight=1)

        self.browse_button = ttk.Button(self.toolbar, text="Browse Video", command=self.browse_video)
        self.browse_button.grid(row=0, column=0, padx=(0, 6))

        self.copy_button = ttk.Button(self.toolbar, text="Copy Frame", command=self.copy_current_frame_image)
        self.copy_button.grid(row=0, column=1, padx=6)

        self.save_frame_button = ttk.Button(self.toolbar, text="Save Frame BMP", command=self.save_current_frame_bitmap)
        self.save_frame_button.grid(row=0, column=2, padx=6)


        self.file_label = ttk.Label(self.toolbar, text="No video loaded", anchor="e")
        self.file_label.grid(row=0, column=10, sticky="e", padx=(20, 0))
        self.file_path_tooltip = Tooltip(self.file_label, lambda: self.source_path or "No video loaded")

        # ----- Main content: preview + right inspector -----
        self.main_pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.main_pane.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))

        self.preview_shell = ttk.Frame(self.main_pane, padding=0)
        self.preview_shell.columnconfigure(0, weight=1)
        self.preview_shell.rowconfigure(0, weight=1)

        self.video_canvas = tk.Canvas(self.preview_shell, bg="black", highlightthickness=0, bd=0)
        self.video_canvas.grid(row=0, column=0, sticky="nsew")
        self.video_canvas.create_text(
            0, 0,
            text="Browse to load a video",
            fill="#9ca3af",
            tags=("empty_text",),
            anchor="center",
            font=("Segoe UI", 16),
        )

        # Right inspector is scrollable so controls stay reachable when the
        # window height is reduced. The visible container is fixed-width-ish,
        # while the inner frame expands to the canvas width.
        self.inspector_container = ttk.Frame(self.main_pane, padding=(8, 0, 0, 0), width=300)
        self.inspector_container.grid_propagate(False)
        self.inspector_container.columnconfigure(0, weight=1)
        self.inspector_container.rowconfigure(0, weight=1)

        self.inspector_canvas = tk.Canvas(self.inspector_container, highlightthickness=0, bd=0)
        self.inspector_scrollbar = ttk.Scrollbar(
            self.inspector_container, orient="vertical", command=self.inspector_canvas.yview
        )
        self.inspector = ttk.Frame(self.inspector_canvas)
        self.inspector.columnconfigure(0, weight=1)

        self.inspector_window = self.inspector_canvas.create_window((0, 0), window=self.inspector, anchor="nw")
        self.inspector_canvas.configure(yscrollcommand=self.inspector_scrollbar.set)
        self.inspector_canvas.grid(row=0, column=0, sticky="nsew")
        self.inspector_scrollbar.grid(row=0, column=1, sticky="ns")

        self.main_pane.add(self.preview_shell, weight=5)
        self.main_pane.add(self.inspector_container, weight=0)

        # ----- Right inspector cards -----
        self.info_card = ttk.LabelFrame(self.inspector, text="Video", padding=10)
        self.info_card.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.info_label = ttk.Label(self.info_card, text="No video loaded", justify=tk.LEFT, wraplength=255)
        self.info_label.pack(fill=tk.X)

        self.marks_card = ttk.LabelFrame(self.inspector, text="Marked Range", padding=10)
        self.marks_card.grid(row=1, column=0, sticky="ew", pady=8)
        self.mark_label = ttk.Label(self.marks_card, text="Start: Not set\nStop:  Not set", justify=tk.LEFT)
        self.mark_label.pack(fill=tk.X)

        mark_buttons = ttk.Frame(self.marks_card)
        mark_buttons.pack(anchor="w", pady=(8, 0))
        self.set_start_button = ttk.Button(mark_buttons, text="Set START  (S)", command=self.set_start, width=14)
        self.set_start_button.grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.set_stop_button = ttk.Button(mark_buttons, text="Set STOP  (E)", command=self.set_stop, width=14)
        self.set_stop_button.grid(row=0, column=1, sticky="w")

        self.progress_card = ttk.LabelFrame(self.inspector, text="Progress", padding=10)
        self.progress_card.grid(row=2, column=0, sticky="ew", pady=8)
        self.progress_label = ttk.Label(self.progress_card, text="Idle", justify=tk.LEFT, wraplength=255)
        self.progress_label.pack(fill=tk.X)
        self.progress_bar = ttk.Progressbar(self.progress_card, mode="determinate", maximum=100)
        self.progress_bar.pack(fill=tk.X, pady=(8, 0))

        self.options_card = ttk.LabelFrame(self.inspector, text="Options", padding=10)
        self.options_card.grid(row=3, column=0, sticky="ew", pady=8)
        self.delete_proxy_checkbox = ttk.Checkbutton(
            self.options_card,
            text="Delete proxy on Browse or Close",
            variable=self.delete_proxy_on_close_var,
        )
        self.delete_proxy_checkbox.pack(anchor="w")

        self.inspector.rowconfigure(9, weight=1)

        # ----- Bottom modern control tabs -----
        self.bottom = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        self.bottom.grid(row=2, column=0, sticky="ew")
        self.bottom.columnconfigure(0, weight=1)

        self.slider = ttk.Scale(self.bottom, from_=0, to=1, command=self.slider_changed)
        self.slider.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.slider.state(["disabled"])

        self.notebook = ttk.Notebook(self.bottom)
        self.notebook.grid(row=1, column=0, sticky="ew")

        self.nav_tab = ttk.Frame(self.notebook, padding=10)
        self.clip_tab = ttk.Frame(self.notebook, padding=10)
        self.images_tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.nav_tab, text="Navigate")
        self.notebook.add(self.clip_tab, text="Clip Export")
        self.notebook.add(self.images_tab, text="Frame Images")

        self._create_nav_tab()
        self._create_clip_tab()
        self._create_images_tab()

        # ----- Context menu -----
        self.frame_context_menu = tk.Menu(self.root, tearoff=0)
        self.frame_context_menu.add_command(label="Copy image from current frame", command=self.copy_current_frame_image)
        self.frame_context_menu.add_command(label="Save bitmap image from current frame", command=self.save_current_frame_bitmap)

        self.inspector.bind("<Configure>", self._update_inspector_scrollregion)
        self.inspector_canvas.bind("<Configure>", self._resize_inspector_window)
        self.inspector_canvas.bind("<Enter>", self._bind_inspector_mousewheel)
        self.inspector_canvas.bind("<Leave>", self._unbind_inspector_mousewheel)
        self.root.after_idle(self._sync_inspector_scroll_state)

    def _create_nav_tab(self):
        self.nav_tab.columnconfigure(7, weight=1)

        ttk.Label(self.nav_tab, text="Frame step").grid(row=0, column=0, padx=(0, 8), sticky="w")
        for idx, (txt, delta) in enumerate((("−100", -100), ("−10", -10), ("−1", -1), ("+1", 1), ("+10", 10), ("+100", 100)), start=1):
            ttk.Button(self.nav_tab, text=txt, command=lambda d=delta: self.jump_frames(d), width=7).grid(row=0, column=idx, padx=3)

        ttk.Label(self.nav_tab, text="Time step").grid(row=1, column=0, padx=(0, 8), pady=(8, 0), sticky="w")
        for idx, (txt, delta) in enumerate((("−5s", -5.0), ("−1s", -1.0), ("−0.1s", -0.1), ("+0.1s", 0.1), ("+1s", 1.0), ("+5s", 5.0)), start=1):
            ttk.Button(self.nav_tab, text=txt, command=lambda d=delta: self.jump_seconds(d), width=7).grid(row=1, column=idx, padx=3, pady=(8, 0))

        ttk.Label(self.nav_tab, text="Jump to frame").grid(row=0, column=8, padx=(20, 6), sticky="e")
        self.frame_entry = ttk.Entry(self.nav_tab, width=10, textvariable=self.current_frame_var)
        self.frame_entry.grid(row=0, column=9, sticky="e")
        self.frame_entry.bind("<Return>", self.jump_to_frame_from_entry)
        self.frame_entry.bind("<Escape>", lambda e: self.root.focus_force())

    def _create_clip_tab(self):
        # Compact two-row layout:
        # Row 1: Output Speed, entry, inline help text.
        # Row 2: Save As, filename entry. The filename field expands.
        self.clip_tab.columnconfigure(2, weight=1)

        ttk.Label(self.clip_tab, text="Output Speed").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.speed_entry = ttk.Entry(self.clip_tab, width=8, textvariable=self.speed_var)
        self.speed_entry.grid(row=0, column=1, sticky="w", padx=(0, 14))
        self.speed_entry.bind("<FocusOut>", lambda e: self.update_default_output_filename_if_allowed())
        self.speed_entry.bind("<Return>", lambda e: self.update_default_output_filename_if_allowed())
        self.speed_entry.bind("<Escape>", lambda e: self.root.focus_force())

        self.clip_help_label = ttk.Label(
            self.clip_tab,
            text="1.0 = normal speed • 0.1 = 10% speed • Output = 30 FPS, no audio",
            anchor="w",
        )
        self.clip_help_label.grid(row=0, column=2, sticky="ew")

        ttk.Label(self.clip_tab, text="Save As").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(10, 0))
        self.output_filename_entry = ttk.Entry(self.clip_tab, textvariable=self.output_filename_var)
        self.output_filename_entry.grid(row=1, column=1, columnspan=2, sticky="ew", pady=(10, 0))
        self.output_filename_entry.bind("<KeyRelease>", lambda e: self.mark_output_filename_edited())
        self.output_filename_entry.bind("<Escape>", lambda e: self.root.focus_force())

        # Keep Export Clip in this tab, but avoid adding another full-height settings row.
        # It is compactly aligned at the lower-right edge of the tab.
        self.export_button = ttk.Button(
            self.clip_tab,
            text="Export Clip",
            command=self.export_clip,
            takefocus=False,
            width=14,
        )
        self.export_button.grid(row=1, column=3, sticky="e", padx=(12, 0), pady=(10, 0))

    def _create_images_tab(self):
        # Small numeric fields stay compact and left-justified; the remaining
        # space is left blank rather than making Start/Stop/Step oversized.
        self.images_tab.columnconfigure(8, weight=1)

        ttk.Label(self.images_tab, text="Start").grid(
            row=0,
            column=0,
            sticky="w",
            padx=(0, 6),
        )

        self.image_start_entry = ttk.Entry(
            self.images_tab,
            width=10,
            textvariable=self.image_start_var,
        )
        self.image_start_entry.grid(
            row=0,
            column=1,
            sticky="w",
            padx=(0, 14),
        )

        ttk.Label(self.images_tab, text="Stop").grid(
            row=0,
            column=2,
            sticky="w",
            padx=(0, 6),
        )

        self.image_stop_entry = ttk.Entry(
            self.images_tab,
            width=10,
            textvariable=self.image_stop_var,
        )
        self.image_stop_entry.grid(
            row=0,
            column=3,
            sticky="w",
            padx=(0, 14),
        )

        ttk.Label(self.images_tab, text="Step").grid(
            row=0,
            column=4,
            sticky="w",
            padx=(0, 6),
        )

        self.image_step_entry = ttk.Entry(
            self.images_tab,
            width=8,
            textvariable=self.image_step_var,
        )
        self.image_step_entry.grid(
            row=0,
            column=5,
            sticky="w",
        )

        self.use_marked_range_button = ttk.Button(
            self.images_tab,
            text="Use START/STOP",
            command=self.populate_image_range_from_marks,
        )
        self.use_marked_range_button.grid(
            row=0,
            column=6,
            padx=(16, 6),
            sticky="w",
        )

        self.export_images_button = ttk.Button(
            self.images_tab,
            text="Export Images",
            command=self.export_frame_images,
            takefocus=False,
        )
        self.export_images_button.grid(
            row=0,
            column=7,
            padx=(6, 0),
            sticky="w",
        )

        self.image_to_frames_subfolder_checkbox = ttk.Checkbutton(
            self.images_tab,
            text="Save to Frames subfolder",
            variable=self.image_to_frames_subfolder_var,
        )
        self.image_to_frames_subfolder_checkbox.grid(
            row=1,
            column=0,
            columnspan=3,
            sticky="w",
            pady=(10, 0),
        )

        self.image_monochrome_checkbox = ttk.Checkbutton(
            self.images_tab,
            text="Monochrome",
            variable=self.image_monochrome_var,
        )
        self.image_monochrome_checkbox.grid(
            row=1,
            column=3,
            columnspan=3,
            sticky="w",
            pady=(10, 0),
        )

        for entry in (
            self.image_start_entry,
            self.image_stop_entry,
            self.image_step_entry,
        ):
            entry.bind(
                "<Escape>",
                lambda e: self.root.focus_force(),
            )

    def _update_inspector_scrollregion(self, event=None):
        self._sync_inspector_scroll_state()

    def _resize_inspector_window(self, event):
        self.inspector_canvas.itemconfigure(self.inspector_window, width=event.width)
        self._sync_inspector_scroll_state()

    def _sync_inspector_scroll_state(self):
        """Only allow right-pane scrolling when the controls do not fit."""
        self.inspector.update_idletasks()
        bbox = self.inspector_canvas.bbox("all")
        if bbox is None:
            self.inspector_scrollbar.grid_remove()
            self.inspector_canvas.configure(scrollregion=(0, 0, 0, 0))
            self._inspector_scroll_enabled = False
            return

        content_height = max(0, bbox[3] - bbox[1])
        viewport_height = max(1, self.inspector_canvas.winfo_height())
        needs_scroll = content_height > viewport_height + 1

        if needs_scroll:
            self.inspector_canvas.configure(scrollregion=bbox)
            if not self.inspector_scrollbar.winfo_ismapped():
                self.inspector_scrollbar.grid(row=0, column=1, sticky="ns")
            self._inspector_scroll_enabled = True
        else:
            self.inspector_scrollbar.grid_remove()
            self.inspector_canvas.yview_moveto(0)
            viewport_width = max(1, self.inspector_canvas.winfo_width())
            self.inspector_canvas.configure(scrollregion=(0, 0, viewport_width, viewport_height))
            self._inspector_scroll_enabled = False

    def _bind_inspector_mousewheel(self, event=None):
        if self._inspector_scroll_enabled:
            self.inspector_canvas.bind_all("<MouseWheel>", self._on_inspector_mousewheel)

    def _unbind_inspector_mousewheel(self, event=None):
        self.inspector_canvas.unbind_all("<MouseWheel>")

    def _on_inspector_mousewheel(self, event):
        if self.text_entry_has_focus() or not self._inspector_scroll_enabled:
            return "break"

        delta = -1 * int(event.delta / 120)
        if delta == 0:
            delta = -1 if event.delta > 0 else 1

        first, last = self.inspector_canvas.yview()
        if (delta < 0 and first <= 0.0) or (delta > 0 and last >= 1.0):
            return "break"

        self.inspector_canvas.yview_scroll(delta, "units")
        return "break"

    def _bind_events(self):
        """Connect mouse, keyboard, and window events to application actions."""
        self.video_canvas.bind("<Configure>", self.on_video_resize)
        self.video_canvas.bind("<Button-1>", lambda e: self.root.focus_force())
        self.video_canvas.bind("<Button-3>", self.show_frame_context_menu)

        self.root.bind("<Left>", lambda e: self.run_hotkey(lambda: self.jump_frames(-1)))
        self.root.bind("<Right>", lambda e: self.run_hotkey(lambda: self.jump_frames(1)))
        self.root.bind("<Shift-Left>", lambda e: self.run_hotkey(lambda: self.jump_frames(-10)))
        self.root.bind("<Shift-Right>", lambda e: self.run_hotkey(lambda: self.jump_frames(10)))
        self.root.bind("<Control-Left>", lambda e: self.run_hotkey(lambda: self.jump_frames(-100)))
        self.root.bind("<Control-Right>", lambda e: self.run_hotkey(lambda: self.jump_frames(100)))
        # Letter hotkeys are handled from keysym.lower(), so Caps Lock and
        # Shift do not change behavior. Entry widgets are ignored by run_hotkey.
        self.root.bind("<KeyPress>", self.handle_keypress)
        self.root.bind("<Control-c>", lambda e: self.copy_current_frame_image())
        self.root.bind("<Control-C>", lambda e: self.copy_current_frame_image())
        self.root.bind("<Control-f>", lambda e: self.save_current_frame_bitmap())
        self.root.bind("<Control-F>", lambda e: self.save_current_frame_bitmap())
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def handle_keypress(self, event):
        key = (event.keysym or "").lower()
        if key == "s":
            self.run_hotkey(self.set_start)
        elif key == "e":
            self.run_hotkey(self.set_stop)
        elif key == "q":
            self.run_hotkey(self.export_clip)
        elif key == "b":
            self.run_hotkey(self.browse_video)

    # -- Interface state and worker messages -----------------------------------
    def text_entry_has_focus(self):
        focused = self.root.focus_get()
        return isinstance(focused, (tk.Entry, ttk.Entry))

    def run_hotkey(self, action):
        if self.text_entry_has_focus():
            return
        action()

    def set_busy(self, value, status_text=None):
        self.busy = value
        state = "disabled" if value else "!disabled"

        for widget in (
            self.browse_button,
            self.copy_button,
            self.save_frame_button,
            self.export_button,
            self.export_images_button,
            self.use_marked_range_button,
            self.set_start_button,
            self.set_stop_button,
            self.image_to_frames_subfolder_checkbox,
            self.image_monochrome_checkbox,
        ):
            widget.state([state])

        if self.cap is not None and not value:
            self.slider.state(["!disabled"])
        else:
            self.slider.state(["disabled"])

        if status_text is not None:
            self.progress_label.config(text=status_text)

    def set_progress(self, label=None, percent=None):
        if label is not None:
            self.progress_label.config(text=label)
        if percent is not None:
            self.progress_bar["value"] = max(0, min(100, float(percent)))

    def _process_ui_events(self):
        """Apply messages from background workers without touching Tk off-thread."""
        while True:
            try:
                item = self.ui_queue.get_nowait()
            except queue.Empty:
                break

            kind = item[0]
            if kind == "progress":
                _, label, percent = item
                self.set_progress(label, percent)
            elif kind == "error":
                _, title, message = item
                self.set_busy(False, "Error")
                messagebox.showerror(title, message)
            elif kind == "proxy_done":
                self.set_progress("Opening proxy...", 100)
                self._finish_loading_proxy(item[1])
            elif kind == "export_done":
                _, output_path = item
                self.set_busy(False, "Export complete")
                self.set_progress("Export complete", 100)
                messagebox.showinfo("Done", f"Saved:\n{output_path}")
            elif kind == "image_export_done":
                _, output_dir, saved_count = item
                self.set_busy(False, "Image export complete")
                self.set_progress("Image export complete", 100)
                messagebox.showinfo("Done", f"Saved {saved_count} image(s) to:\n{output_dir}")

        self.root.after(POLL_MS, self._process_ui_events)

    # -- Formatting, validation, and path helpers ------------------------------
    def frame_to_seconds(self, frame_num):
        return 0.0 if self.fps <= 0 else frame_num / self.fps

    def seconds_to_frames(self, seconds):
        return round(seconds * self.fps)

    @staticmethod
    def format_time(seconds):
        minutes = int(seconds // 60)
        seconds = seconds % 60
        return f"{minutes:02d}:{seconds:06.3f}"

    @staticmethod
    def sanitize_filename_part(text):
        invalid = '<>:"/\\|?*'
        cleaned = ''.join('_' if ch in invalid else ch for ch in text)
        cleaned = cleaned.strip().strip('.')
        return cleaned or 'frame'

    @staticmethod
    def get_unique_path(path):
        """Return an unused path by appending a numeric suffix when necessary."""
        base, extension = os.path.splitext(path)
        candidate = path
        idx = 1
        while os.path.exists(candidate):
            candidate = f"{base}_{idx:03d}{extension}"
            idx += 1
        return candidate

    def update_info(self):
        if self.cap is None:
            self.info_label.config(text="No video loaded")
            self.current_frame_var.set("0")
            return

        current_time = self.format_time(self.frame_to_seconds(self.current_frame))
        total_time = self.format_time(self.frame_to_seconds(self.frame_count - 1))
        self.current_frame_var.set(str(self.current_frame))
        self.info_label.config(
            text=(
                f"File:\n{self.filename}\n\n"
                f"Current Frame:\n{self.current_frame} / {self.frame_count - 1}\n\n"
                f"Current Time:\n{current_time} / {total_time}\n\n"
                f"Source FPS:\n{self.fps:.3f}"
            )
        )

    def update_mark_status(self):
        start_text = (
            f"Frame {self.start_frame} @ {self.format_time(self.frame_to_seconds(self.start_frame))}"
            if self.start_frame is not None else "Not set"
        )
        stop_text = (
            f"Frame {self.stop_frame} @ {self.format_time(self.frame_to_seconds(self.stop_frame))}"
            if self.stop_frame is not None else "Not set"
        )
        self.mark_label.config(text=f"Start: {start_text}\nStop:  {stop_text}")

    def get_output_speed(self):
        try:
            speed = float(self.speed_var.get())
            if speed <= 0:
                raise ValueError
            return speed
        except ValueError:
            messagebox.showerror("Invalid Speed", "Output speed must be a positive number.")
            return None

    def default_output_filename(self, speed=None):
        if not self.name or not self.ext:
            return ""
        if speed is None:
            try:
                speed = float(self.speed_var.get())
            except ValueError:
                speed = DEFAULT_OUTPUT_SPEED
        if speed == 1.0:
            return f"{self.name}_trimmed_30fps_no_audio{self.ext}"
        return f"{self.name}_trimmed_{speed}x_30fps_no_audio{self.ext}"

    def mark_output_filename_edited(self):
        self.output_filename_user_edited = True

    def update_default_output_filename_if_allowed(self):
        if not self.output_filename_user_edited:
            speed = self.get_output_speed()
            if speed is not None:
                self.output_filename_var.set(self.default_output_filename(speed))

    def get_output_path(self):
        proposed = self.output_filename_var.get().strip() or self.default_output_filename(self.get_output_speed())
        proposed = os.path.basename(proposed)
        _, proposed_ext = os.path.splitext(proposed)
        if not proposed_ext:
            proposed += self.ext
        return os.path.join(self.folder, proposed)

    # -- Video lifecycle and all-intra-frame proxy generation ------------------
    def clear_current_video(self, delete_proxy=None):
        """Release the active video and restore the unloaded UI state."""
        if delete_proxy is None:
            delete_proxy = self.delete_proxy_on_close_var.get()

        if self.cap is not None:
            self.cap.release()
            self.cap = None

        if delete_proxy and self.proxy_path and os.path.exists(self.proxy_path):
            try:
                os.remove(self.proxy_path)
            except Exception as e:
                print(f"Could not delete proxy file: {e}")

        self.source_path = None
        self.proxy_path = None
        self.folder = None
        self.filename = None
        self.name = None
        self.ext = None
        self.fps = 0.0
        self.frame_count = 0
        self.current_frame = 0
        self.start_frame = None
        self.stop_frame = None
        self.current_tk_image = None
        self.output_filename_user_edited = False

        self.video_canvas.delete("all")
        self.video_canvas.create_text(
            max(1, self.video_canvas.winfo_width() // 2),
            max(1, self.video_canvas.winfo_height() // 2),
            text="Browse to load a video",
            fill="#9ca3af",
            tags=("empty_text",),
            anchor="center",
            font=("Segoe UI", 16),
        )
        self.file_label.config(text="No video loaded")
        self.output_filename_var.set("")
        self.image_start_var.set("")
        self.image_stop_var.set("")
        self.image_step_var.set("1")
        self.slider.configure(from_=0, to=1)
        self.slider.state(["disabled"])
        self.update_mark_status()
        self.update_info()
        self.root.title("FrameLab")

    def get_source_duration_seconds(self, path):
        temp_cap = cv2.VideoCapture(path, cv2.CAP_MSMF)
        try:
            src_fps = temp_cap.get(cv2.CAP_PROP_FPS)
            src_frames = int(temp_cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if src_fps and src_fps > 0 and src_frames > 0:
                return src_frames / src_fps
        finally:
            temp_cap.release()
        return None

    def browse_video(self):
        if self.busy:
            messagebox.showinfo("Busy", "Please wait for the current operation to finish.")
            return

        path = filedialog.askopenfilename(
            title="Select video file",
            filetypes=[
                ("Video files", "*.mp4 *.mov *.avi *.mkv *.wmv"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self.start_load_video(path)

    def start_load_video(self, path):
        if self.busy:
            return

        self.ffmpeg_exe = shutil.which("ffmpeg")
        if self.ffmpeg_exe is None:
            messagebox.showerror(
                "FFmpeg Required",
                "FrameLab requires a separate FFmpeg installation with the libx264 encoder.\n\n"
                "Install FFmpeg, add its bin directory to PATH, and restart FrameLab.",
            )
            return

        self.clear_current_video(delete_proxy=self.delete_proxy_on_close_var.get())
        self.source_path = path
        self.folder, self.filename = os.path.split(self.source_path)
        self.name, self.ext = os.path.splitext(self.filename)
        self.proxy_path = os.path.join(self.folder, f"{self.name}_proxy_all_i.mp4")

        self.output_filename_user_edited = False
        self.output_filename_var.set(self.default_output_filename())
        self.file_label.config(text=f"Loading: {self.filename}")
        self.root.title(f"FrameLab - Loading {self.filename}")

        duration_seconds = self.get_source_duration_seconds(self.source_path)
        self.set_busy(True, "Importing video / creating proxy...")
        self.set_progress("Importing video / creating proxy...", 0)

        threading.Thread(
            target=self._create_proxy,
            args=(self.source_path, self.proxy_path, duration_seconds),
            daemon=True,
        ).start()

    def _create_proxy(self, path, proxy, duration_seconds):
        """Create a seek-friendly proxy and post progress to ``ui_queue``."""
        if os.path.exists(proxy):
            self.ui_queue.put(("progress", "Using existing proxy", 100))
            self.ui_queue.put(("proxy_done", path))
            return

        cmd_proxy = [
            self.ffmpeg_exe,
            "-y",
            "-i", path,
            "-an",
            "-c:v", "libx264",
            "-preset", PROXY_PRESET,
            "-crf", PROXY_CRF,
            "-x264-params", "keyint=1:min-keyint=1:scenecut=0",
            proxy,
        ]

        try:
            process = subprocess.Popen(
                cmd_proxy,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                universal_newlines=True,
                errors="replace",
            )

            time_re = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")
            if duration_seconds is None or duration_seconds <= 0:
                self.ui_queue.put(("progress", "Importing video / creating proxy...", 0))

            for line in process.stderr:
                if duration_seconds and duration_seconds > 0:
                    match = time_re.search(line)
                    if match:
                        hours = int(match.group(1))
                        minutes = int(match.group(2))
                        seconds = float(match.group(3))
                        current = hours * 3600 + minutes * 60 + seconds
                        percent = min(100, (current / duration_seconds) * 100)
                        self.ui_queue.put(("progress", f"Importing video / creating proxy... {percent:0.1f}%", percent))

            rc = process.wait()
            if rc != 0:
                raise subprocess.CalledProcessError(rc, cmd_proxy)

            self.ui_queue.put(("progress", "Import complete", 100))
            self.ui_queue.put(("proxy_done", path))

        except Exception as e:
            self.ui_queue.put(("error", "Proxy Error", f"Failed to create proxy:\n{e}"))

    def _finish_loading_proxy(self, path):
        if path != self.source_path:
            return
        if not self._open_proxy():
            self.clear_current_video(delete_proxy=self.delete_proxy_on_close_var.get())
            self.set_busy(False, "Idle")
            return

        self.file_label.config(text=self.source_path)
        self.root.title(f"FrameLab - {self.filename}")
        self.update_mark_status()
        self.show_frame(0)
        self.set_busy(False, "Import complete")
        self.set_progress("Import complete", 100)

    def _open_proxy(self):
        self.cap = cv2.VideoCapture(self.proxy_path, cv2.CAP_MSMF)
        if not self.cap.isOpened():
            messagebox.showerror("Error", "Could not open proxy video.")
            return False

        self.fps = self.cap.get(cv2.CAP_PROP_FPS)
        self.frame_count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if self.fps <= 0 or self.frame_count <= 0:
            messagebox.showerror("Error", "Could not read video FPS or frame count.")
            return False

        self.slider.configure(from_=0, to=self.frame_count - 1)
        self.slider.state(["!disabled"])
        return True

    # -- Frame reading, display, and navigation --------------------------------
    def read_frame(self, frame_num):
        """Seek to and decode one frame from the active proxy."""
        if self.cap is None:
            return None
        frame_num = max(0, min(frame_num, self.frame_count - 1))
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
        ret, frame = self.cap.read()
        return frame if ret else None

    def resize_frame_for_preview(self, frame):
        h, w = frame.shape[:2]
        available_w = max(self.video_canvas.winfo_width(), 1)
        available_h = max(self.video_canvas.winfo_height(), 1)
        scale = min(available_w / w, available_h / h, PREVIEW_MAX_UPSCALE)
        new_w = max(1, int(w * scale))
        new_h = max(1, int(h * scale))
        return cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)

    def show_frame(self, frame_num):
        if self.cap is None:
            return

        frame_num = max(0, min(frame_num, self.frame_count - 1))
        frame = self.read_frame(frame_num)
        if frame is None:
            return

        self.current_frame = frame_num
        preview = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        preview = self.resize_frame_for_preview(preview)
        img = Image.fromarray(preview)
        self.current_tk_image = ImageTk.PhotoImage(image=img)

        self.video_canvas.delete("all")
        x = self.video_canvas.winfo_width() // 2
        y = self.video_canvas.winfo_height() // 2
        self.video_canvas.create_image(x, y, image=self.current_tk_image, anchor=tk.CENTER)

        # Updating a ttk.Scale programmatically fires its command callback on some
        # Tk builds. Guard this update so changing frames from buttons/hotkeys
        # does not recursively call slider_changed() -> show_frame() -> set().
        self._updating_slider = True
        try:
            self.slider.set(float(self.current_frame))
        finally:
            self._updating_slider = False

        self.update_info()

    def slider_changed(self, value):
        if self._updating_slider or self.cap is None or self.busy:
            return

        try:
            frame_num = int(round(float(value)))
        except (TypeError, ValueError, tk.TclError):
            return

        # Avoid rereading/redrawing the same frame when the slider is being
        # synchronized to the current frame.
        if frame_num == self.current_frame:
            return

        self.show_frame(frame_num)

    def on_video_resize(self, event):
        if self.cap is None:
            self.video_canvas.coords("empty_text", event.width // 2, event.height // 2)
            return
        if self.resize_job is not None:
            self.root.after_cancel(self.resize_job)
        self.resize_job = self.root.after(100, lambda: self.show_frame(self.current_frame))

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
            frame_num = int(self.current_frame_var.get().strip())
        except ValueError:
            messagebox.showwarning("Invalid Frame", "Enter a whole frame number.")
            self.current_frame_var.set(str(self.current_frame))
            return
        self.show_frame(frame_num)
        self.root.focus_force()

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

    # -- Single-frame copy and save actions ------------------------------------
    def get_current_frame_pil_image(self):
        if self.cap is None:
            return None
        frame = self.read_frame(self.current_frame)
        if frame is None:
            return None
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        return Image.fromarray(rgb_frame)

    @staticmethod
    def copy_pil_image_to_windows_clipboard(pil_image):
        if os.name != "nt":
            raise RuntimeError("Image clipboard copy is currently implemented for Windows only.")

        with io.BytesIO() as output:
            pil_image.convert("RGB").save(output, "BMP")
            dib_data = output.getvalue()[14:]

        CF_DIB = 8
        GMEM_MOVEABLE = 0x0002
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        kernel32.GlobalAlloc.argtypes = [ctypes.wintypes.UINT, ctypes.c_size_t]
        kernel32.GlobalAlloc.restype = ctypes.wintypes.HGLOBAL
        kernel32.GlobalLock.argtypes = [ctypes.wintypes.HGLOBAL]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [ctypes.wintypes.HGLOBAL]
        kernel32.GlobalUnlock.restype = ctypes.wintypes.BOOL
        user32.SetClipboardData.argtypes = [ctypes.wintypes.UINT, ctypes.wintypes.HANDLE]
        user32.SetClipboardData.restype = ctypes.wintypes.HANDLE

        h_global = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(dib_data))
        if not h_global:
            raise RuntimeError("GlobalAlloc failed while copying image to clipboard.")

        locked_ptr = kernel32.GlobalLock(h_global)
        if not locked_ptr:
            raise RuntimeError("GlobalLock failed while copying image to clipboard.")

        ctypes.memmove(locked_ptr, dib_data, len(dib_data))
        kernel32.GlobalUnlock(h_global)

        if not user32.OpenClipboard(None):
            raise RuntimeError("Could not open Windows clipboard.")

        try:
            user32.EmptyClipboard()
            if not user32.SetClipboardData(CF_DIB, h_global):
                raise RuntimeError("SetClipboardData failed while copying image to clipboard.")
            h_global = None
        finally:
            user32.CloseClipboard()

    def copy_current_frame_image(self):
        if self.cap is None:
            messagebox.showwarning("No Video", "Load a video first.")
            return
        pil_image = self.get_current_frame_pil_image()
        if pil_image is None:
            messagebox.showerror("Copy Frame", "Could not read the current frame.")
            return
        try:
            self.copy_pil_image_to_windows_clipboard(pil_image)
            self.set_progress(f"Copied frame {self.current_frame} image to clipboard.", None)
        except Exception as e:
            messagebox.showerror("Copy Frame", f"Could not copy frame image:\n{e}")

    def flash_video_border(self, color="#00ff00", thickness=4, duration_ms=150):
        # Draw the confirmation border directly on the canvas, then remove it.
        w = self.video_canvas.winfo_width()
        h = self.video_canvas.winfo_height()
        rect = self.video_canvas.create_rectangle(2, 2, w - 2, h - 2, outline=color, width=thickness)
        self.root.after(duration_ms, lambda: self.video_canvas.delete(rect))

    def save_current_frame_bitmap(self):
        """
        Save the currently displayed frame as a BMP image.

        The "Save to Frames subfolder" checkbox controls whether the image
        is saved beside the source video or in a Frames subfolder.

        The "Monochrome" checkbox controls whether the image is saved as
        grayscale or full color.
        """
        if self.cap is None:
            messagebox.showwarning("No Video", "Load a video first.")
            return

        pil_image = self.get_current_frame_pil_image()
        if pil_image is None:
            messagebox.showerror("Save Frame", "Could not read the current frame.")
            return

        safe_name = self.sanitize_filename_part(self.name or "video")
        milliseconds = int(round(self.frame_to_seconds(self.current_frame) * 1000))
        output_name = f"{safe_name}_frame_{self.current_frame:06d}_{milliseconds:06d}ms.bmp"

        # Select the output folder using the checkbox.
        if self.image_to_frames_subfolder_var.get():
            output_dir = os.path.join(self.folder, "Frames")
        else:
            output_dir = self.folder

        # Create the Frames folder when needed.
        os.makedirs(output_dir, exist_ok=True)

        output_path = self.get_unique_path(
            os.path.join(output_dir, output_name)
        )

        try:
            # Select monochrome or color using the checkbox.
            if self.image_monochrome_var.get():
                pil_image.convert("L").save(output_path, "BMP")
            else:
                pil_image.convert("RGB").save(output_path, "BMP")

            self.set_progress(f"Saved frame bitmap: {output_path}", None)
            self.flash_video_border()

        except Exception as e:
            messagebox.showerror("Save Frame", f"Could not save frame bitmap:\n{e}")

    def show_frame_context_menu(self, event):
        if self.cap is None or self.busy:
            return
        self.frame_context_menu.tk_popup(event.x_root, event.y_root)

    # -- Multi-frame image export ----------------------------------------------
    def populate_image_range_from_marks(self):
        if self.start_frame is None or self.stop_frame is None:
            messagebox.showerror("Missing Points", "Set both START and STOP frames first.")
            return
        self.image_start_var.set(str(self.start_frame))
        self.image_stop_var.set(str(self.stop_frame))

    def get_image_export_range(self):
        if self.cap is None:
            messagebox.showerror("No Video", "Load a video first.")
            return None

        try:
            local_start_frame = int(self.image_start_var.get().strip())
            local_stop_frame = int(self.image_stop_var.get().strip())
            local_step = int(self.image_step_var.get().strip())
        except ValueError:
            messagebox.showerror("Invalid Frame Range", "Start, Stop, and Step must be whole numbers.")
            return None

        if local_step <= 0:
            messagebox.showerror("Invalid Step", "Step must be 1 or greater.")
            return None
        if local_start_frame < 0 or local_stop_frame < 0:
            messagebox.showerror("Invalid Frame Range", "Start and Stop frames cannot be negative.")
            return None
        if local_start_frame >= self.frame_count or local_stop_frame >= self.frame_count:
            messagebox.showerror("Invalid Frame Range", f"Start and Stop must be between 0 and {self.frame_count - 1}.")
            return None
        if local_stop_frame < local_start_frame:
            messagebox.showerror("Invalid Frame Range", "Stop frame must be greater than or equal to Start frame.")
            return None
        return local_start_frame, local_stop_frame, local_step

    def export_frame_images(self):
        if self.busy:
            messagebox.showinfo("Busy", "Please wait for the current operation to finish.")
            return
        if self.cap is None:
            messagebox.showerror("No Video", "Load a video first.")
            return

        image_range = self.get_image_export_range()
        if image_range is None:
            return

        local_start_frame, local_stop_frame, local_step = image_range
        total = len(range(local_start_frame, local_stop_frame + 1, local_step))
        if total <= 0:
            messagebox.showerror("Invalid Frame Range", "No frames are included in this export range.")
            return

        self.set_busy(True, "Saving frame images...")
        self.set_progress("Saving frame images...", 0)
        threading.Thread(
            target=self._export_frame_images,
            args=(
                self.proxy_path,
                self.fps,
                local_start_frame,
                local_stop_frame,
                local_step,
                self.folder,
                self.name,
                self.image_to_frames_subfolder_var.get(),
                self.image_monochrome_var.get(),
            ),
            daemon=True,
        ).start()

    def _export_frame_images(
        self,
        local_proxy_path,
        local_fps,
        local_start_frame,
        local_stop_frame,
        local_step,
        local_folder,
        local_name,
        export_to_frames_subfolder,
        export_monochrome,
    ):
        """Save the selected proxy frames and report progress to the UI thread."""
        export_cap = cv2.VideoCapture(local_proxy_path, cv2.CAP_MSMF)
        if not export_cap.isOpened():
            self.ui_queue.put(("error", "Image Export Error", "Could not open proxy video for image export."))
            return

        safe_name = self.sanitize_filename_part(local_name or "video")
        frame_numbers = list(range(local_start_frame, local_stop_frame + 1, local_step))
        total = len(frame_numbers)
        saved_count = 0
        frames_folder = os.path.join(local_folder, "Frames") if export_to_frames_subfolder else local_folder
        os.makedirs(frames_folder, exist_ok=True)

        try:
            for idx, frame_num in enumerate(frame_numbers, start=1):
                export_cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
                ret, frame = export_cap.read()
                if not ret:
                    raise RuntimeError(f"Could not read frame {frame_num}.")

                milliseconds = int(round((frame_num / local_fps if local_fps > 0 else 0.0) * 1000))
                output_name = f"{safe_name}_frame_{frame_num:06d}_{milliseconds}ms.bmp"
                output_path = self.get_unique_path(os.path.join(frames_folder, output_name))

                if export_monochrome:
                    gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    Image.fromarray(gray_frame).save(output_path, "BMP")
                else:
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    Image.fromarray(rgb_frame).save(output_path, "BMP")

                saved_count += 1
                percent = (idx / total) * 100 if total else 100
                self.ui_queue.put(("progress", f"Saving frame images... {idx}/{total} ({percent:0.1f}%)", percent))

        except Exception as e:
            self.ui_queue.put(("error", "Image Export Error", f"Failed during image export:\n{e}"))
            return
        finally:
            export_cap.release()

        self.ui_queue.put(("image_export_done", frames_folder, saved_count))

    # -- Clip export ------------------------------------------------------------
    def export_clip(self):
        if self.busy:
            messagebox.showinfo("Busy", "Please wait for the current operation to finish.")
            return
        if self.cap is None:
            messagebox.showerror("No Video", "Load a video first.")
            return
        if self.start_frame is None or self.stop_frame is None:
            messagebox.showerror("Missing Points", "Set both START and STOP frames.")
            return
        if self.stop_frame <= self.start_frame:
            messagebox.showerror("Invalid Range", "STOP frame must be after START frame.")
            return

        output_speed = self.get_output_speed()
        if output_speed is None:
            return

        output_path = self.get_output_path()
        if os.path.exists(output_path):
            overwrite = messagebox.askyesno("Overwrite File", f"This file already exists:\n{output_path}\n\nOverwrite it?")
            if not overwrite:
                return

        self.set_busy(True, "Saving video...")
        self.set_progress("Saving video...", 0)
        threading.Thread(
            target=self._export_clip,
            args=(output_path, output_speed, self.proxy_path, self.fps, self.start_frame, self.stop_frame),
            daemon=True,
        ).start()

    def _export_clip(self, output_path, output_speed, local_proxy_path, local_fps, local_start_frame, local_stop_frame):
        """Render a silent clip at the requested playback speed."""
        source_duration = (local_stop_frame - local_start_frame + 1) / local_fps
        output_duration = source_duration / output_speed
        output_frame_count = max(1, int(round(output_duration * OUTPUT_FPS)))

        export_cap = cv2.VideoCapture(local_proxy_path, cv2.CAP_MSMF)
        if not export_cap.isOpened():
            self.ui_queue.put(("error", "Export Error", "Could not open proxy video for export."))
            return

        width = int(export_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(export_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(output_path, cv2.CAP_MSMF, fourcc, OUTPUT_FPS, (width, height))

        if not writer.isOpened():
            export_cap.release()
            self.ui_queue.put(("error", "Export Error", "Could not open output video writer."))
            return

        export_cap.set(cv2.CAP_PROP_POS_FRAMES, local_start_frame)
        source_idx = local_start_frame
        ret, current_source_frame = export_cap.read()

        if not ret:
            writer.release()
            export_cap.release()
            self.ui_queue.put(("error", "Export Error", "Could not read first source frame."))
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
                percent = ((out_idx + 1) / output_frame_count) * 100
                percent_int = int(percent)
                if percent_int != last_percent_int:
                    last_percent_int = percent_int
                    self.ui_queue.put(("progress", f"Saving video... {percent:0.1f}%", percent))

        except Exception as e:
            self.ui_queue.put(("error", "Export Error", f"Failed during export:\n{e}"))
            return
        finally:
            writer.release()
            export_cap.release()

        self.ui_queue.put(("export_done", output_path))

    # -- Shutdown ---------------------------------------------------------------
    def on_close(self):
        if self.busy:
            if not messagebox.askyesno("Operation Running", "An operation is still running. Close anyway?"):
                return
        self.clear_current_video(delete_proxy=self.delete_proxy_on_close_var.get())
        self.root.destroy()


def main():
    """Launch the FrameLab desktop application."""
    root = tk.Tk()
    FrameLabApplication(root)
    root.mainloop()


if __name__ == "__main__":
    main()
