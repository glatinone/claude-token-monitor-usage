"""
widget.py – Always-on-top floating HUD for Claude Token Monitor.
"""

import customtkinter as ctk
import tkinter as tk
import threading
import json
import os
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

POLL_INTERVAL = 60

POS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "widget_pos.json")

# Sleek Dark Palette
BG      = "#0A0A0D"
SURFACE = "#121216"
BORDER  = "#22222A"
HOVER   = "#282834"
TEXT    = "#F3F4F6"
MUTED   = "#8E919A"
GREEN   = "#4ADE80"
AMBER   = "#FBBF24"
RED     = "#F87171"


def _col(pct: float) -> str:
    if pct < 50: return GREEN
    if pct < 80: return AMBER
    return RED


def _fmt_reset(iso: str) -> str:
    if not iso:
        return "—"
    try:
        dt   = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        secs = int((dt - datetime.now(timezone.utc)).total_seconds())
        if secs < 0:
            return "soon"
        m = secs // 60
        return f"{m}m" if m < 60 else f"{m // 60}h {m % 60}m"
    except Exception:
        return iso[:16]


def _fmt_synced(iso: str) -> str:
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%H:%M:%S")
    except Exception:
        return iso[:19]


def _load_pos():
    try:
        with open(POS_FILE) as f:
            d = json.load(f)
            return d.get("x", -1), d.get("y", -1)
    except Exception:
        return -1, -1


def _save_pos(x: int, y: int) -> None:
    try:
        with open(POS_FILE, "w") as f:
            json.dump({"x": x, "y": y}, f)
    except Exception:
        pass


class TokenMonitorWidget:
    W = 230
    H = 142

    def __init__(self, fetch_fn, on_hide_callback=None):
        self._fetch_fn  = fetch_fn
        self._on_hide   = on_hide_callback
        self._last_data = {}
        self._collapsed = False
        self._poll_job  = None
        self._drag_ox   = 0
        self._drag_oy   = 0

        ctk.set_appearance_mode("dark")
        self.root = ctk.CTk()
        self.root.title("Claude Monitor")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.96)
        self.root.configure(fg_color=BG)

        sx, sy = _load_pos()
        if sx < 0:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            sx = sw - self.W - 28
            sy = sh - self.H - 60
        self.root.geometry(f"{self.W}x{self.H}+{sx}+{sy}")

        self._build_ui()
        self.root.after(1200, self._safe_fetch)

    # ── Build UI (modern, compact & dynamic) ─────────────────────────────

    def _build_ui(self):
        self._card = ctk.CTkFrame(
            self.root, fg_color=SURFACE,
            border_color=BORDER, border_width=1, corner_radius=16,
        )
        self._card.pack(fill="both", expand=True, padx=1, pady=1)

        # Header — always visible
        self._hdr = ctk.CTkFrame(self._card, fg_color="transparent", height=26)
        self._hdr.pack(fill="x", padx=12, pady=(8, 0))

        self._title_lbl = ctk.CTkLabel(
            self._hdr, text="CLAUDE MONITOR",
            font=("Segoe UI Semibold", 8), text_color=MUTED,
        )
        self._title_lbl.pack(side="left")

        self._collapse_btn = ctk.CTkButton(
            self._hdr, text="−",
            width=18, height=18, corner_radius=9,
            fg_color="transparent", hover_color=HOVER,
            text_color=MUTED, font=("Segoe UI", 12, "bold"),
            command=self._toggle_collapse,
        )
        self._collapse_btn.pack(side="right")

        # Body — hidden when collapsed
        self._body = ctk.CTkFrame(self._card, fg_color="transparent")
        self._body.pack(fill="x", padx=12, pady=(6, 0))

        self._canvas = tk.Canvas(
            self._body, width=64, height=64,
            bg=SURFACE, highlightthickness=0,
        )
        self._canvas.pack(side="left")
        self._draw_arc(0.0, MUTED)

        stats_col = ctk.CTkFrame(self._body, fg_color="transparent")
        stats_col.pack(side="left", padx=(10, 0), fill="both", expand=True)

        def _stat(parent, label_text):
            f = ctk.CTkFrame(parent, fg_color="transparent")
            lbl = ctk.CTkLabel(
                f, text=label_text, font=("Segoe UI Semibold", 8),
                text_color=MUTED, anchor="w", height=10
            )
            lbl.pack(fill="x", pady=0)
            val = ctk.CTkLabel(
                f, text="—", font=("Segoe UI", 11, "bold"),
                text_color=TEXT, anchor="w", height=14
            )
            val.pack(fill="x", pady=0)
            return f, val

        self._msgs_frame, self._msgs_val = _stat(stats_col, "MESSAGES LEFT")
        self._msgs_frame.pack(fill="x", pady=(0, 2))

        self._reset_frame, self._reset_val = _stat(stats_col, "RESET IN")
        self._reset_frame.pack(fill="x", pady=(0, 2))

        self._org_lbl = ctk.CTkLabel(
            stats_col, text="—", font=("Segoe UI Semibold", 8),
            text_color=MUTED, anchor="w", height=10
        )
        self._org_lbl.pack(fill="x", pady=(2, 0))

        # Progress bar — hidden when collapsed
        self._bar_frame = ctk.CTkFrame(self._card, fg_color="transparent")
        self._bar_frame.pack(fill="x", padx=12, pady=(6, 0))

        self._progress = ctk.CTkProgressBar(
            self._bar_frame, height=3, corner_radius=1.5, fg_color=BORDER,
        )
        self._progress.pack(fill="x")
        self._progress.set(0)

        # Footer — always visible
        self._ftr = ctk.CTkFrame(self._card, fg_color="transparent")
        self._ftr.pack(fill="x", padx=12, pady=(4, 6))

        self._dot_lbl = ctk.CTkLabel(
            self._ftr, text="●", font=("Segoe UI", 7), text_color=MUTED,
        )
        self._dot_lbl.pack(side="left")

        self._footer_lbl = ctk.CTkLabel(
            self._ftr, text=" Starting…", font=("Segoe UI", 8), text_color=MUTED,
        )
        self._footer_lbl.pack(side="left")

        self._sync_btn = ctk.CTkButton(
            self._ftr, text="↺",
            width=20, height=16, corner_radius=4,
            fg_color="transparent", hover_color=HOVER,
            text_color=MUTED, font=("Segoe UI", 11),
            command=self._manual_sync,
        )
        self._sync_btn.pack(side="right")

        # Bind drag to non-button widgets
        for w in (self._card, self._hdr, self._title_lbl,
                  self._body, self._canvas, stats_col,
                  self._bar_frame, self._ftr, self._dot_lbl, self._footer_lbl):
            w.bind("<Button-1>",        self._drag_start, add="+")
            w.bind("<B1-Motion>",       self._drag_move,  add="+")
            w.bind("<ButtonRelease-1>", self._drag_end,   add="+")

    # ── Arc ───────────────────────────────────────────────────────────────

    def _draw_arc(self, pct: float, color: str):
        try:
            c = self._canvas
            c.delete("all")
            cx = cy = 32
            r  = 23
            c.create_oval(cx-r, cy-r, cx+r, cy+r, outline=BORDER, width=4, fill="")
            if pct > 0.5:
                ext = min(pct / 100 * 359.9, 359.9)
                c.create_arc(cx-r, cy-r, cx+r, cy+r,
                             start=90, extent=-ext,
                             outline=color, width=4, style="arc")
            c.create_text(cx, cy-6, text=f"{int(round(pct))}%",
                          fill=color, font=("Segoe UI", 15, "bold"), anchor="center")
            c.create_text(cx, cy+10, text="USED",
                          fill=MUTED, font=("Segoe UI", 7, "bold"), anchor="center")
        except Exception as e:
            logger.debug(f"Arc draw: {e}")

    # ── Render ────────────────────────────────────────────────────────────

    def _render(self, data: dict):
        try:
            self._last_data = data
            pct   = max(0.0, min(100.0, float(data.get("percentage", 0))))
            color = _col(pct)
            limit = int(data.get("limit", 0))
            used  = int(data.get("used_count", 0))

            self._draw_arc(pct, color)

            # Unpack all to ensure correct ordering
            self._msgs_frame.pack_forget()
            self._reset_frame.pack_forget()
            self._org_lbl.pack_forget()

            if limit > 0:
                self._msgs_frame.pack(fill="x", pady=(0, 2))
                rem_msgs = max(0, limit - used)
                self._msgs_val.configure(text=f"{rem_msgs} / {limit} msgs", text_color=color)

            self._reset_frame.pack(fill="x", pady=(0, 2))
            
            org_name = data.get("org_name", "")
            if len(org_name) > 24:
                org_name = org_name[:21] + "..."
            self._org_lbl.configure(text=org_name)
            self._org_lbl.pack(fill="x", pady=(2, 0))

            self._reset_val.configure(text=_fmt_reset(data.get("reset_at", "")))

            self._progress.set(pct / 100.0)
            self._progress.configure(progress_color=color)

            self._dot_lbl.configure(text_color=GREEN)
            self._footer_lbl.configure(
                text=f" Synced {_fmt_synced(data.get('synced_at', ''))}",
                text_color=MUTED,
            )
        except Exception as e:
            logger.warning(f"_render: {e}")

    def update_data(self, data: dict):
        try:
            self.root.after(0, lambda: self._render(data))
        except Exception as e:
            logger.warning(f"update_data: {e}")

    def _set_error(self, msg: str):
        def _do():
            try:
                self._dot_lbl.configure(text_color=RED)
                self._footer_lbl.configure(
                    text=f" {msg[:40]}", text_color=RED,
                )
            except Exception:
                pass
        try:
            self.root.after(0, _do)
        except Exception:
            pass

    # ── Fetch & poll ──────────────────────────────────────────────────────

    def _safe_fetch(self):
        def _worker():
            try:
                data = self._fetch_fn()
                self.update_data(data)
            except Exception as e:
                logger.warning(f"Fetch error: {e}")
                self._set_error(str(e)[:60])
        threading.Thread(target=_worker, daemon=True).start()
        try:
            self._poll_job = self.root.after(POLL_INTERVAL * 1000, self._safe_fetch)
        except Exception:
            pass

    def _manual_sync(self):
        try:
            if self._poll_job:
                self.root.after_cancel(self._poll_job)
                self._poll_job = None
            self._footer_lbl.configure(text=" Syncing…", text_color=MUTED)
            self._dot_lbl.configure(text_color=MUTED)
            self._safe_fetch()
        except Exception as e:
            logger.warning(f"manual_sync: {e}")

    # ── Collapse / expand  ────────────────────────────────────────────────

    def _toggle_collapse(self):
        try:
            self._collapsed = not self._collapsed
            if self._collapsed:
                self._body.pack_forget()
                self._bar_frame.pack_forget()
                self._ftr.pack_forget()
                self._collapse_btn.configure(text="+")
                self.root.geometry(f"{self.W}x36")
            else:
                self._body.pack(fill="x", padx=12, pady=(6, 0))
                self._bar_frame.pack(fill="x", padx=12, pady=(6, 0))
                self._ftr.pack(fill="x", padx=12, pady=(4, 6))
                self._collapse_btn.configure(text="−")
                self.root.geometry(f"{self.W}x{self.H}")
                if self._last_data:
                    self._render(self._last_data)
        except Exception as e:
            logger.warning(f"toggle_collapse: {e}")

    # ── Drag ─────────────────────────────────────────────────────────────

    def _drag_start(self, event):
        self._drag_ox = event.x_root - self.root.winfo_x()
        self._drag_oy = event.y_root - self.root.winfo_y()

    def _drag_move(self, event):
        try:
            self.root.geometry(f"+{event.x_root - self._drag_ox}+{event.y_root - self._drag_oy}")
        except Exception:
            pass

    def _drag_end(self, event):
        try:
            _save_pos(self.root.winfo_x(), self.root.winfo_y())
        except Exception:
            pass

    # ── Visibility & Key Setup ───────────────────────────────────────────

    def setup_session_key(self):
        import tkinter as tk
        from tkinter import simpledialog, messagebox
        from app.claude_fetcher import set_session_key, get_saved_session_key

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
            parent=self.root,
        )
        if key and key.strip():
            key_val = key.strip()
            if "sessionKey=" in key_val:
                key_val = key_val.split("sessionKey=")[-1].split(";")[0].strip()
            
            set_session_key(key_val)
            messagebox.showinfo(
                "Session Key Saved",
                "Session key saved! The widget will sync automatically.",
                parent=self.root
            )
            self._manual_sync()

    def show_widget(self):
        try:
            self.root.deiconify()
            self.root.attributes("-topmost", True)
            self.root.lift()
        except Exception as e:
            logger.warning(f"show_widget: {e}")

    def hide_widget(self):
        try:
            self.root.withdraw()
            if self._on_hide:
                self._on_hide()
        except Exception as e:
            logger.warning(f"hide_widget: {e}")

    def destroy(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self):
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            pass
        except Exception as e:
            logger.error(f"Mainloop: {e}", exc_info=True)
            raise
