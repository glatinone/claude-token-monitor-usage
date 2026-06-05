"""
tray.py – System tray icon for Claude Token Monitor.
------------------------------------------------------
Menu items:
  • Show / Hide Widget
  • ↺ Sync Now
  • ── separator ──
  • 🔑 Setup Session Key   ← opens a simple tkinter dialog
  • ── separator ──
  • Exit
"""

import threading
import logging
from PIL import Image, ImageDraw
import pystray

logger = logging.getLogger(__name__)


def _make_icon(color: str = "#7C3AED") -> Image.Image:
    """Generate a 64×64 tray icon: rounded purple square with a white arc."""
    img  = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([2, 2, 62, 62], radius=18, fill=color)
    draw.arc([14, 14, 50, 50], start=40, end=320, fill="white", width=7)
    draw.ellipse([28, 8, 36, 16], fill="white")   # dot
    return img


class SystemTrayManager:
    def __init__(
        self,
        show_callback,
        hide_callback,
        reset_callback,       # now used for "Sync Now"
        exit_callback,
        setup_key_callback=None,
    ):
        self.show_callback      = show_callback
        self.hide_callback      = hide_callback
        self.sync_callback      = reset_callback
        self.exit_callback      = exit_callback
        self.setup_key_callback = setup_key_callback
        self.icon: pystray.Icon | None = None
        self._visible = True

    # ── Menu actions ──────────────────────────────────────────────────────

    def _toggle(self, icon, item):
        if self._visible:
            self.hide_callback()
        else:
            self.show_callback()
        self._visible = not self._visible

    def _sync(self, icon, item):
        self.sync_callback()

    def _setup_key(self, icon, item):
        if self.setup_key_callback:
            self.setup_key_callback()
        else:
            self._default_key_dialog()

    def _default_key_dialog(self):
        """Simple Tkinter dialog to paste a session key."""
        import tkinter as tk
        from tkinter import simpledialog, messagebox
        from app.claude_fetcher import set_session_key, get_saved_session_key

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)

        current = get_saved_session_key() or ""
        prompt = (
            "Disclaimer: This app is unofficial and not affiliated with Anthropic.\n\n"
            "Paste your Claude.ai sessionKey cookie below.\n\n"
            "How to get it:\n"
            "  1. Open claude.ai in your browser\n"
            "  2. Press F12 → Application → Cookies → claude.ai\n"
            "  3. Copy the value of 'sessionKey'\n"
        )
        key = simpledialog.askstring(
            "Setup Session Key",
            prompt,
            initialvalue=current,
            parent=root,
        )
        root.destroy()

        if key and key.strip():
            set_session_key(key.strip())
            messagebox.showinfo(
                "Session Key Saved",
                "Session key saved!  The widget will sync automatically.",
            )
            # Trigger an immediate sync
            self.sync_callback()

    def _exit(self, icon, item):
        self.icon and self.icon.stop()
        self.exit_callback()

    def update_tray_tooltip(self, text: str):
        if self.icon:
            self.icon.title = text

    # ── Start ─────────────────────────────────────────────────────────────

    def start(self):
        menu = pystray.Menu(
            pystray.MenuItem("Show / Hide Widget",    self._toggle, default=True),
            pystray.MenuItem("↺  Sync Now",           self._sync),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("🔑  Setup Session Key", self._setup_key),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit",                   self._exit),
        )

        self.icon = pystray.Icon(
            "claude_monitor",
            _make_icon(),
            "Claude Token Monitor",
            menu,
        )

        t = threading.Thread(target=self.icon.run, daemon=True)
        t.start()
        logger.info("System tray icon started.")
