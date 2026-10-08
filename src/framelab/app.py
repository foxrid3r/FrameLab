"""Application entry point for the PySide6 interface."""
from framelab.qt_window import FrameLabApplication, main

__all__ = ["FrameLabApplication", "main"]

if __name__ == "__main__":
    raise SystemExit(main())
