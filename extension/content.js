/**
 * Claude Token Monitor – Content Script (Always-On Floating HUD)
 * ---------------------------------------------------------------
 * Automatically injects a floating HUD into every claude.ai page.
 * The HUD is ALWAYS visible – it never disappears (only collapses to a pill).
 * Data is loaded from chrome.storage.local (set by background.js).
 *
 * Features:
 *  • Glassmorphism card with radial arc progress
 *  • Auto-shows on load, persists across SPA navigation
 *  • Collapsible to a pill (remembers state)
 *  • Draggable, position saved to localStorage
 *  • Color-coded: green → amber → red
 */

"use strict";

const HUD_ID      = "ctm-hud-root";
const STORAGE_KEY = "claude_usage_data";
const POS_KEY     = "ctm_pos";
const STATE_KEY   = "ctm_collapsed";

// ── Utilities ──────────────────────────────────────────────────────────────
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

// pct = % USED: low used → green, high used → red
function colorForPct(pct) {
  if (pct < 50) return { main: "#4ade80", glow: "rgba(74,222,128,0.35)",   dim: "rgba(74,222,128,0.15)" };   // green
  if (pct < 80) return { main: "#fbbf24", glow: "rgba(251,191,36,0.35)",   dim: "rgba(251,191,36,0.15)" };   // amber
  return         { main: "#f87171", glow: "rgba(248,113,113,0.35)", dim: "rgba(248,113,113,0.15)" };          // red
}

function fmtReset(iso) {
  if (!iso) return "—";
  try {
    const ms = new Date(iso) - Date.now();
    if (ms < 0) return "soon";
    const m = Math.floor(ms / 60000);
    return m < 60 ? `${m}m` : `${Math.floor(m / 60)}h ${m % 60}m`;
  } catch { return iso; }
}

// ── CSS injected as a <style> tag ──────────────────────────────────────────
const CSS = `
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@500;600;700;800&display=swap');

  #${HUD_ID} {
    all: initial;
    position: fixed;
    z-index: 2147483647;
    font-family: 'Inter', system-ui, -apple-system, sans-serif;
    font-size: 12px;
    user-select: none;
    -webkit-user-select: none;
  }
  #${HUD_ID} * { box-sizing: border-box; }

  /* ── Card ── */
  #ctm-card {
    background: rgba(10, 10, 13, 0.88);
    backdrop-filter: blur(24px) saturate(200%);
    -webkit-backdrop-filter: blur(24px) saturate(200%);
    border: 1px solid rgba(255,255,255,0.09);
    border-radius: 20px;
    width: 208px;
    overflow: hidden;
    box-shadow: 0 8px 32px rgba(0,0,0,0.5), 0 0 0 1px rgba(255,255,255,0.03) inset;
    transition: box-shadow 0.3s ease;
    cursor: grab;
  }
  #ctm-card:active { cursor: grabbing; }

  /* header */
  #ctm-hdr {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 12px 0;
  }
  #ctm-hdr-label {
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: rgba(255,255,255,0.3);
  }
  #ctm-collapse-btn {
    width: 18px; height: 18px;
    border-radius: 50%;
    background: rgba(255,255,255,0.07);
    border: none; outline: none;
    color: rgba(255,255,255,0.35);
    font-size: 12px;
    cursor: pointer;
    display: flex; align-items: center; justify-content: center;
    transition: background 0.2s, color 0.2s;
    font-family: inherit; padding: 0;
  }
  #ctm-collapse-btn:hover { background: rgba(255,255,255,0.15); color: #fff; }

  /* body */
  #ctm-body {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 12px;
  }

  /* arc */
  #ctm-arc-wrap {
    flex-shrink: 0;
    width: 68px; height: 68px;
    position: relative;
  }
  #ctm-arc-wrap svg { display: block; overflow: visible; }
  .ctm-arc-track {
    fill: none;
    stroke: rgba(255,255,255,0.06);
    stroke-width: 5.5;
  }
  .ctm-arc-fill {
    fill: none;
    stroke: #4ade80;
    stroke-width: 5.5;
    stroke-linecap: round;
    transform: rotate(-90deg);
    transform-origin: 34px 34px;
    transition: stroke-dashoffset 0.7s cubic-bezier(0.4,0,0.2,1),
                stroke 0.4s ease, filter 0.4s ease;
  }
  #ctm-arc-center {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 0;
  }
  #ctm-pct-num {
    font-size: 16px;
    font-weight: 800;
    color: #fff;
    letter-spacing: -0.02em;
    line-height: 1;
    transition: color 0.4s;
  }
  #ctm-pct-unit {
    font-size: 8px;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: rgba(255,255,255,0.3);
    margin-top: 1px;
  }

  /* stats */
  #ctm-stats {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 5px;
  }
  .ctm-stat-label {
    font-size: 8.5px;
    font-weight: 700;
    letter-spacing: 0.07em;
    text-transform: uppercase;
    color: rgba(255,255,255,0.28);
    margin-bottom: 1px;
  }
  .ctm-stat-val {
    font-size: 12px;
    font-weight: 700;
    color: #e5e7eb;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    transition: color 0.4s;
  }

  /* bar */
  #ctm-bar-wrap {
    height: 3px;
    background: rgba(255,255,255,0.06);
    border-radius: 99px;
    overflow: hidden;
    margin: 0 12px 10px;
  }
  #ctm-bar {
    height: 100%;
    border-radius: 99px;
    width: 0%;
    background: #4ade80;
    transition: width 0.7s cubic-bezier(0.4,0,0.2,1), background 0.4s;
  }

  /* ── Pill (collapsed) ── */
  #ctm-pill {
    display: none;
    align-items: center;
    gap: 6px;
    background: rgba(10, 10, 13, 0.88);
    backdrop-filter: blur(24px) saturate(200%);
    -webkit-backdrop-filter: blur(24px) saturate(200%);
    border: 1px solid rgba(255,255,255,0.09);
    border-radius: 99px;
    padding: 6px 10px 6px 8px;
    cursor: grab;
    box-shadow: 0 4px 16px rgba(0,0,0,0.4);
    transition: box-shadow 0.3s;
    white-space: nowrap;
  }
  #ctm-pill:active { cursor: grabbing; }
  #ctm-pill:hover { box-shadow: 0 4px 20px rgba(0,0,0,0.5); }
  #ctm-pill-dot {
    width: 7px; height: 7px;
    border-radius: 50%;
    background: #4ade80;
    flex-shrink: 0;
    transition: background 0.4s;
  }
  #ctm-pill-label {
    font-size: 11px;
    font-weight: 700;
    color: #e5e7eb;
    transition: color 0.4s;
  }
  #ctm-expand-btn {
    width: 16px; height: 16px;
    border-radius: 50%;
    background: rgba(255,255,255,0.08);
    border: none; outline: none;
    color: rgba(255,255,255,0.4);
    font-size: 11px;
    cursor: pointer;
    display: flex; align-items: center; justify-content: center;
    transition: background 0.2s;
    font-family: inherit; padding: 0; margin-left: 2px;
  }
  #ctm-expand-btn:hover { background: rgba(255,255,255,0.18); color: #fff; }

  /* Loading pulse */
  @keyframes ctm-pulse-dot {
    0%,100% { opacity: 1; }
    50% { opacity: 0.3; }
  }
  .ctm-loading #ctm-pct-num { animation: ctm-pulse-dot 1.2s ease infinite; }
  .ctm-loading #ctm-pill-dot { animation: ctm-pulse-dot 1.2s ease infinite; }
`;

// ── Arc helpers ─────────────────────────────────────────────────────────────
const R = 26.5;
const CIRC = 2 * Math.PI * R; // ≈ 166.5

// ── Build DOM ──────────────────────────────────────────────────────────────
function buildHUD() {
  const root = document.createElement("div");
  root.id = HUD_ID;

  // Load saved pos
  let pos = { bottom: 28, right: 28 };
  try { const p = JSON.parse(localStorage.getItem(POS_KEY) || "{}"); if (p.bottom != null) pos = p; } catch {}

  root.style.cssText = `bottom:${pos.bottom}px;right:${pos.right}px;`;

  const style = document.createElement("style");
  style.textContent = CSS;

  root.innerHTML = `
    <div id="ctm-card" class="ctm-loading">
      <div id="ctm-hdr">
        <span id="ctm-hdr-label">Claude Monitor</span>
        <button id="ctm-collapse-btn" title="Collapse to pill">−</button>
      </div>

      <div id="ctm-body">
        <div id="ctm-arc-wrap">
          <svg width="68" height="68" viewBox="0 0 68 68">
            <circle class="ctm-arc-track" cx="34" cy="34" r="${R}"
              stroke-dasharray="${CIRC.toFixed(2)}" />
            <circle class="ctm-arc-fill" id="ctm-arc-fill" cx="34" cy="34" r="${R}"
              stroke-dasharray="${CIRC.toFixed(2)}" stroke-dashoffset="${CIRC.toFixed(2)}" />
          </svg>
          <div id="ctm-arc-center">
            <span id="ctm-pct-num">--</span>
            <span id="ctm-pct-unit">used</span>
          </div>
        </div>

        <div id="ctm-stats">
          <div>
            <div class="ctm-stat-label">Quota Left</div>
            <div class="ctm-stat-val" id="ctm-msgs">--</div>
          </div>
          <div>
            <div class="ctm-stat-label">Resets in</div>
            <div class="ctm-stat-val" id="ctm-reset">--</div>
          </div>
          <div>
            <div class="ctm-stat-label">Plan</div>
            <div class="ctm-stat-val" id="ctm-org" style="font-size:10px">--</div>
          </div>
        </div>
      </div>

      <div id="ctm-bar-wrap"><div id="ctm-bar"></div></div>
    </div>

    <div id="ctm-pill">
      <span id="ctm-pill-dot"></span>
      <span id="ctm-pill-label">-- used</span>
      <button id="ctm-expand-btn" title="Expand">+</button>
    </div>
  `;

  root.prepend(style);
  return root;
}

// ── State: collapsed vs card ───────────────────────────────────────────────
function applyCollapsed(root, collapsed) {
  const card = root.querySelector("#ctm-card");
  const pill = root.querySelector("#ctm-pill");
  card.style.display = collapsed ? "none" : "";
  pill.style.display = collapsed ? "flex" : "none";
  try { localStorage.setItem(STATE_KEY, collapsed ? "1" : "0"); } catch {}
}

// ── Render data ────────────────────────────────────────────────────────────
function renderData(root, data) {
  if (!data) return;

  // percentage = % USED (0 = fresh, 100 = fully exhausted)
  const pct = clamp(parseFloat(data.percentage ?? 0), 0, 100);
  const col = colorForPct(pct);

  // Remove loading state
  root.querySelector("#ctm-card").classList.remove("ctm-loading");

  // Arc fills up as used percentage increases
  const arcFill = root.querySelector("#ctm-arc-fill");
  const offset = CIRC - (pct / 100) * CIRC;
  arcFill.style.strokeDashoffset = offset.toFixed(2);
  arcFill.style.stroke = col.main;
  arcFill.style.filter = `drop-shadow(0 0 5px ${col.glow})`;

  // Center label shows used %
  root.querySelector("#ctm-pct-num").textContent = Math.round(pct) + "%";
  root.querySelector("#ctm-pct-num").style.color = col.main;

  // Bar fills based on used percentage
  const bar = root.querySelector("#ctm-bar");
  bar.style.width = pct + "%";
  bar.style.background = col.main;
  bar.style.boxShadow = `0 0 8px ${col.glow}`;

  // Stats: show remaining percentage
  const msgsEl = root.querySelector("#ctm-msgs");
  const remPct = 100.0 - pct;
  msgsEl.textContent = `${remPct.toFixed(1)}%`;
  msgsEl.style.color = col.main;
  root.querySelector("#ctm-reset").textContent = fmtReset(data.reset_at);
  if (data.org_name) root.querySelector("#ctm-org").textContent = data.org_name;

  // Pill shows used % / remaining msgs count
  root.querySelector("#ctm-pill-dot").style.background = col.main;
  root.querySelector("#ctm-pill-dot").style.boxShadow = `0 0 6px ${col.glow}`;
  root.querySelector("#ctm-pill-label").textContent = `${remPct.toFixed(1)}% left`;
  root.querySelector("#ctm-pill-label").style.color = col.main;
}

// ── Drag logic ─────────────────────────────────────────────────────────────
function makeDraggable(root, handle) {
  handle.addEventListener("mousedown", (e) => {
    if (e.target.closest("button")) return;
    e.preventDefault();

    const rootRect = root.getBoundingClientRect();
    const startX = e.clientX, startY = e.clientY;
    const startRight  = window.innerWidth  - rootRect.right;
    const startBottom = window.innerHeight - rootRect.bottom;

    const onMove = (mv) => {
      const newRight  = clamp(startRight  + (startX - mv.clientX), 0, window.innerWidth  - rootRect.width);
      const newBottom = clamp(startBottom + (startY - mv.clientY), 0, window.innerHeight - rootRect.height);
      root.style.right  = newRight  + "px";
      root.style.bottom = newBottom + "px";
    };
    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup",   onUp);
      try { localStorage.setItem(POS_KEY, JSON.stringify({ right: parseInt(root.style.right), bottom: parseInt(root.style.bottom) })); } catch {}
    };

    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup",   onUp);
  });
}

// ── Mount HUD ─────────────────────────────────────────────────────────────
let hudRoot = null;

function mountHUD() {
  if (document.getElementById(HUD_ID)) return; // already mounted

  hudRoot = buildHUD();
  document.body.appendChild(hudRoot);

  // Restore collapse state
  const wasCollapsed = localStorage.getItem(STATE_KEY) === "1";
  applyCollapsed(hudRoot, wasCollapsed);

  // Wire up buttons
  hudRoot.querySelector("#ctm-collapse-btn").addEventListener("click", (e) => {
    e.stopPropagation();
    applyCollapsed(hudRoot, true);
  });
  hudRoot.querySelector("#ctm-expand-btn").addEventListener("click", (e) => {
    e.stopPropagation();
    applyCollapsed(hudRoot, false);
  });

  // Drag for both card and pill
  makeDraggable(hudRoot, hudRoot.querySelector("#ctm-card"));
  makeDraggable(hudRoot, hudRoot.querySelector("#ctm-pill"));

  // Load cached data immediately
  chrome.runtime.sendMessage({ action: "get_cached_usage" }, (res) => {
    if (chrome.runtime.lastError) return;
    if (res?.data) renderData(hudRoot, res.data);
  });

  // Request fresh data
  setTimeout(() => {
    chrome.runtime.sendMessage({ action: "trigger_sync_bg" });
  }, 800);
}

// ── Re-mount on SPA navigation (claude.ai is a React SPA) ─────────────────
function ensureHUD() {
  if (!document.getElementById(HUD_ID) && document.body) {
    mountHUD();
  }
}

// Initial mount
if (document.body) {
  mountHUD();
} else {
  document.addEventListener("DOMContentLoaded", mountHUD);
}

// Watch for body replacements (SPA route changes)
const bodyObserver = new MutationObserver(() => ensureHUD());
bodyObserver.observe(document.documentElement, { childList: true, subtree: false });

// Also poll every 5s as a safety net (cheap check)
setInterval(ensureHUD, 5000);

// ── Receive live updates from background ───────────────────────────────────
chrome.runtime.onMessage.addListener((msg) => {
  if (msg.action === "update_hud" && msg.data) {
    if (!document.getElementById(HUD_ID)) mountHUD();
    renderData(document.getElementById(HUD_ID), msg.data);
  }
});

// ── Trigger sync on message submit ────────────────────────────────────────
document.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    setTimeout(() => chrome.runtime.sendMessage({ action: "trigger_sync_bg" }), 3500);
  }
}, true);

document.addEventListener("click", (e) => {
  if (e.target.closest("button[aria-label], button[type='submit']")) {
    setTimeout(() => chrome.runtime.sendMessage({ action: "trigger_sync_bg" }), 3500);
  }
}, true);
