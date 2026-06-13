"""Virtual display management for headless Linux environments.

On macOS and Windows, headed Chromium runs against the native display session —
no virtual display is needed and this module is a no-op.

On Linux *without* a $DISPLAY (CI runners, Docker, SSH servers), Chromium
requires an X server. We start Xvfb via pyvirtualdisplay so the browser runs
in a real X session rather than headless mode, which sidesteps the automation
fingerprints that headless Chrome leaks.

Install on Linux:  pip install 'meeting-agent[linux]'
System packages:   sudo apt-get install xvfb
"""
import os
import platform
import logging

logger = logging.getLogger(__name__)

_SYSTEM = platform.system()


class VirtualDisplay:
    """Xvfb virtual display for headless Linux; no-op everywhere else.

    Usage::

        with VirtualDisplay() as vd:
            # browser launched here sees a real X display
            ...
    """

    def __init__(self, width: int = 1280, height: int = 720):
        self._width = width
        self._height = height
        self._display = None

    @staticmethod
    def is_needed() -> bool:
        """True only on Linux when no X display is available."""
        return _SYSTEM == "Linux" and not os.environ.get("DISPLAY")

    def start(self) -> None:
        """Start Xvfb if needed; silently skipped on macOS/Windows."""
        if not self.is_needed():
            return
        try:
            from pyvirtualdisplay import Display  # type: ignore[import-untyped]
            self._display = Display(visible=False, size=(self._width, self._height))
            self._display.start()
            logger.info("Xvfb virtual display started (%dx%d)", self._width, self._height)
        except ImportError:
            logger.warning(
                "pyvirtualdisplay not installed — headless Linux browser automation "
                "may be detected as a bot. Fix: pip install 'meeting-agent[linux]'"
            )
        except Exception as e:
            logger.warning("Could not start Xvfb virtual display: %s", e)

    def stop(self) -> None:
        """Stop Xvfb if it was started."""
        if self._display is not None:
            try:
                self._display.stop()
                logger.debug("Xvfb virtual display stopped")
            except Exception:
                pass
            self._display = None

    def __enter__(self) -> "VirtualDisplay":
        self.start()
        return self

    def __exit__(self, *_) -> None:
        self.stop()
