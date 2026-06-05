"""
main.py – Entry point for Claude Token Monitor desktop app.
------------------------------------------------------------
Architecture:
  • Main thread  : Tkinter widget (always-on-top HUD)
  • Daemon thread: Local HTTP server (receives push from browser extension)
  • Daemon thread: Claude Code log watcher (reads ~/.claude/projects/*.jsonl)
  • fetch_fn     : claude_fetcher.fetch_usage() – calls claude.ai API
                   directly using browser cookies.  Polled every 60 s
                   by the widget itself.

The browser extension (if running) can also push data via POST
/api/usage → port 9988, which immediately refreshes the HUD too.
"""

import sys
import os
import logging
import threading
import traceback

# ── Logging ──────────────────────────────────────────────────────────────
LOG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s – %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# ── Imports ───────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from app.claude_fetcher import fetch_usage
    from app.server  import start_server
    from app.watcher import ProjectLogWatcher
    from app.tray    import SystemTrayManager
    from app.widget  import TokenMonitorWidget
    from app.storage import StorageManager
except Exception as e:
    crash = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "crash_log.txt")
    with open(crash, "w") as f:
        f.write(f"Import Error: {e}\n{traceback.format_exc()}")
    raise


# ── Globals ───────────────────────────────────────────────────────────────
widget:  TokenMonitorWidget | None = None
watcher: ProjectLogWatcher  | None = None
tray:    SystemTrayManager  | None = None
storage: StorageManager     | None = None
_lock_socket = None  # Prevent garbage collection of lock socket


def main():
    global widget, watcher, tray, storage, _lock_socket

    # Single-instance lock
    import socket
    _lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        _lock_socket.bind(("127.0.0.1", 9987))
    except socket.error:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showwarning(
            "Already Running",
            "Claude Token Monitor is already running.\n"
            "Please check the system tray (bottom-right icon near clock)."
        )
        root.destroy()
        sys.exit(0)

    logger.info("=" * 60)
    logger.info("Claude Token Monitor starting…")

    # 1. Storage (used only by watcher for Claude Code CLI stats)
    storage = StorageManager()

    # 2. Widget
    #    fetch_usage is called by the widget itself on its own poll timer.
    widget = TokenMonitorWidget(
        fetch_fn=fetch_usage,
        on_hide_callback=lambda: logger.info("Widget hidden by user"),
    )

    # 3. Local HTTP server (receives push from browser extension)
    #    When the extension POSTs new data, immediately refresh the HUD.
    def _on_web_push(web_stats=None, **_):
        if web_stats and widget:
            # Adapt storage format → UsageData format
            # web_stats["percentage"] stores remaining percentage for legacy reasons,
            # so we convert it to USED percentage for the widget.
            rem_pct = float(web_stats.get("percentage", 100.0))
            used_pct = 100.0 - rem_pct
            payload = {
                "percentage":  used_pct,
                "used_count":  int(web_stats.get("limit", 0) - web_stats.get("remaining", 0)),
                "limit":       int(web_stats.get("limit", 0)),
                "reset_at":    web_stats.get("reset_at", ""),
                "org_name":    web_stats.get("org_name", ""),
                "synced_at":   web_stats.get("last_updated", ""),
            }
            widget.update_data(payload)

    start_server(
        host="127.0.0.1",
        port=9988,
        storage_manager=storage,
        update_callback=_on_web_push,
    )

    # 4. Claude Code log watcher (background thread)
    def _on_cli_update(cli_stats=None, **_):
        pass  # Currently not shown in HUD; extend here if desired

    watcher = ProjectLogWatcher(storage, _on_cli_update)
    watcher.start()

    # 5. System tray
    def _show():  widget and widget.root.after(0, widget.show_widget)
    def _hide():  widget and widget.root.after(0, widget.hide_widget)
    def _sync():  widget and widget.root.after(0, widget._manual_sync)
    def _setup(): widget and widget.root.after(0, widget.setup_session_key)
    def _quit():
        logger.info("Shutdown requested via tray.")
        watcher and watcher.stop()
        widget  and widget.root.after(0, widget.destroy)
        sys.exit(0)

    tray = SystemTrayManager(
        show_callback=_show,
        hide_callback=_hide,
        reset_callback=_sync,   # repurpose "Reset" → "Sync Now"
        exit_callback=_quit,
        setup_key_callback=_setup,
    )
    tray.start()

    # 6. Run Tkinter main loop (blocks)
    logger.info("Entering Tkinter main loop.")
    try:
        widget.run()
    except KeyboardInterrupt:
        _quit()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        crash = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "crash_log.txt")
        with open(crash, "w") as f:
            f.write(f"Runtime Error: {e}\n{traceback.format_exc()}")
        logger.critical(f"Fatal error: {e}")
        raise
