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
SURFACE_CARD = "#17171C"
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
    W = 260
    H = 320

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

    # ── Build UI (modern vertical card) ───────────────────────────────────

    def _build_ui(self):
        self._card = ctk.CTkFrame(
            self.root, fg_color=SURFACE,
            border_color=BORDER, border_width=1, corner_radius=16,
        )
        self._card.pack(fill="both", expand=True, padx=1, pady=1)

        # Header — always visible
        self._hdr = ctk.CTkFrame(self._card, fg_color="transparent", height=34)
        self._hdr.pack(fill="x", padx=14, pady=(12, 0))

        icon_lbl = ctk.CTkLabel(
            self._hdr, text="🔮", font=("Segoe UI", 16)
        )
        icon_lbl.pack(side="left", padx=(0, 6))

        title_col = ctk.CTkFrame(self._hdr, fg_color="transparent")
        title_col.pack(side="left")

        self._title_lbl = ctk.CTkLabel(
            title_col, text="Claude Monitor",
            font=("Segoe UI", 12, "bold"), text_color=TEXT, height=14
        )
        self._title_lbl.pack(anchor="w")

        self._sub_lbl = ctk.CTkLabel(
            title_col, text="USAGE TRACKER",
            font=("Segoe UI Semibold", 8), text_color=MUTED, height=10
        )
        self._sub_lbl.pack(anchor="w")

        self._collapse_btn = ctk.CTkButton(
            self._hdr, text="−",
            width=20, height=20, corner_radius=10,
            fg_color="transparent", hover_color=HOVER,
            text_color=MUTED, font=("Segoe UI", 14, "bold"),
            command=self._toggle_collapse,
        )
        self._collapse_btn.pack(side="right")

        # Body — hidden when collapsed
        self._body = ctk.CTkFrame(self._card, fg_color="transparent")
        self._body.pack(fill="both", expand=True, padx=14, pady=(12, 0))

        # Progress Row
        self._prog_wrap = ctk.CTkFrame(self._body, fg_color="transparent")
        self._prog_wrap.pack(fill="x", pady=(0, 16))

        lbl_row = ctk.CTkFrame(self._prog_wrap, fg_color="transparent")
        lbl_row.pack(fill="x", pady=(0, 4))
        
        self._quota_lbl = ctk.CTkLabel(
            lbl_row, text="QUOTA USED", font=("Segoe UI Semibold", 9), text_color=MUTED
        )
        self._quota_lbl.pack(side="left")

        self._pct_val = ctk.CTkLabel(
            lbl_row, text="—", font=("Segoe UI", 14, "bold"), text_color=GREEN
        )
        self._pct_val.pack(side="right")

        self._progress = ctk.CTkProgressBar(
            self._prog_wrap, height=5, corner_radius=2.5, fg_color=BORDER,
        )
        self._progress.pack(fill="x")
        self._progress.set(0)

        def _make_card(parent, label_text, is_full=False):
            f = ctk.CTkFrame(parent, fg_color=SURFACE_CARD, border_color=BORDER, border_width=1, corner_radius=10)
            if is_full:
                f.pack(fill="x", pady=(0, 8))
            else:
                f.pack(side="left", fill="both", expand=True)
            lbl = ctk.CTkLabel(
                f, text=label_text, font=("Segoe UI Semibold", 9),
                text_color=MUTED, anchor="w"
            )
            lbl.pack(fill="x", padx=12, pady=(10, 0))
            val = ctk.CTkLabel(
                f, text="—", font=("Segoe UI", 13, "bold"),
                text_color=TEXT, anchor="w"
            )
            val.pack(fill="x", padx=12, pady=(0, 10))
            return f, val

        # Cards
        self._cards_frame = ctk.CTkFrame(self._body, fg_color="transparent")
        self._cards_frame.pack(fill="x", pady=(0, 16))

        self._rem_frame, self._msgs_val = _make_card(self._cards_frame, "QUOTA REMAINING", is_full=True)

        row2 = ctk.CTkFrame(self._cards_frame, fg_color="transparent")
        row2.pack(fill="x")

        self._reset_frame, self._reset_val = _make_card(row2, "RESETS IN", is_full=False)
        self._reset_frame.pack_configure(padx=(0, 4))
        
        self._org_frame, self._org_lbl = _make_card(row2, "ORGANIZATION", is_full=False)
        self._org_frame.pack_configure(padx=(4, 0))
        self._org_lbl.configure(font=("Segoe UI", 11, "bold")) # slightly smaller for long names

        # Sync Button
        self._sync_btn = ctk.CTkButton(
            self._body, text="⟳ Sync Now",
            height=34, corner_radius=10,
            fg_color="#6366f1", hover_color="#4f46e5",
            text_color="#ffffff", font=("Segoe UI", 12, "bold"),
            command=self._manual_sync,
        )
        self._sync_btn.pack(fill="x", pady=(0, 12))

        # Footer — always visible
        self._ftr = ctk.CTkFrame(self._card, fg_color="transparent")
        self._ftr.pack(fill="x", padx=14, pady=(4, 10))

        sync_row = ctk.CTkFrame(self._ftr, fg_color="transparent")
        sync_row.pack(anchor="center")

        self._dot_lbl = ctk.CTkLabel(
            sync_row, text="●", font=("Segoe UI", 8), text_color=MUTED,
        )
        self._dot_lbl.pack(side="left", padx=(0, 4))

        self._footer_lbl = ctk.CTkLabel(
            sync_row, text="Starting…", font=("Segoe UI Semibold", 9), text_color=MUTED,
        )
        self._footer_lbl.pack(side="left")

        self._disc_lbl = ctk.CTkLabel(
            self._ftr, text="Unofficial client. Not affiliated with Anthropic.",
            font=("Segoe UI", 8), text_color=MUTED, height=10
        )
        self._disc_lbl.pack(anchor="center", pady=(4, 0))

        # Bind drag to non-button widgets
        for w in (self._card, self._hdr, icon_lbl, title_col, self._title_lbl, self._sub_lbl,
                  self._body, self._prog_wrap, lbl_row, self._quota_lbl, self._pct_val,
                  self._cards_frame, self._rem_frame, self._msgs_val, row2,
                  self._reset_frame, self._reset_val, self._org_frame, self._org_lbl,
                  self._ftr, sync_row, self._dot_lbl, self._footer_lbl, self._disc_lbl):
            w.bind("<Button-1>",        self._drag_start, add="+")
            w.bind("<B1-Motion>",       self._drag_move,  add="+")
            w.bind("<ButtonRelease-1>", self._drag_end,   add="+")

    # ── Render ────────────────────────────────────────────────────────────

    def _render(self, data: dict):
        try:
            self._last_data = data
            pct   = max(0.0, min(100.0, float(data.get("percentage", 0))))
            color = _col(pct)

            self._pct_val.configure(text=f"{pct:.1f}% used", text_color=color)

            rem_pct = 100.0 - pct
            self._msgs_val.configure(text=f"{rem_pct:.1f}%", text_color=color)

            org_name = data.get("org_name", "")
            if len(org_name) > 18:
                org_name = org_name[:15] + "..."
            self._org_lbl.configure(text=org_name)

            self._reset_val.configure(text=_fmt_reset(data.get("reset_at", "")))

            self._progress.set(pct / 100.0)
            self._progress.configure(progress_color=color)

            self._dot_lbl.configure(text_color=GREEN)
            self._footer_lbl.configure(
                text=f"Synced {_fmt_synced(data.get('synced_at', ''))}",
                text_color=MUTED,
            )
            self._sync_btn.configure(state="normal", text="⟳ Sync Now")
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
                    text=f"{msg[:40]}", text_color=RED,
                )
                self._sync_btn.configure(state="normal", text="⟳ Sync Now")
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
            self._sync_btn.configure(state="disabled", text="Syncing...")
            self._footer_lbl.configure(text="Syncing…", text_color=MUTED)
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
                self._ftr.pack_forget()
                self._collapse_btn.configure(text="+")
                self.root.geometry(f"{self.W}x58")
            else:
                self._body.pack(fill="both", expand=True, padx=14, pady=(12, 0))
                self._ftr.pack(fill="x", padx=14, pady=(4, 10))
                self._collapse_btn.configure(text="−")
                self.root.geometry(f"{self.W}x{self.H}")
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
