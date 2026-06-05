/**
 * Claude Token Monitor – Popup Script
 * ------------------------------------
 * Reads cached usage from chrome.storage.local (set by background.js).
 * "Sync Now" asks the background service worker to fetch fresh data.
 * Works completely standalone – no desktop app server required.
 */

"use strict";

const STORAGE_KEY = "claude_usage_data";

document.addEventListener("DOMContentLoaded", () => {
  const statusDot  = document.getElementById("status-dot");
  const statusText = document.getElementById("status-text");
  const quotaBar   = document.getElementById("quota-bar");
  const quotaFill  = document.getElementById("quota-fill");
  const pctEl      = document.getElementById("pct-val");
  const msgsEl     = document.getElementById("msgs-val");
  const resetEl    = document.getElementById("reset-val");
  const orgEl      = document.getElementById("org-val");
  const syncedEl   = document.getElementById("synced-val");
  const syncBtn    = document.getElementById("sync-btn");

  // ── Helpers ───────────────────────────────────────────────────────────────
  function clamp(v, min, max) { return Math.max(min, Math.min(max, v)); }

  // pct = % USED: low → green, high → red
  function colorForPct(pct) {
    if (pct < 50) return { bar: "#4ade80", text: "#4ade80" }; // green
    if (pct < 80) return { bar: "#fbbf24", text: "#fbbf24" }; // amber
    return { bar: "#f87171", text: "#f87171" };               // red
  }

  function fmtReset(isoStr) {
    if (!isoStr) return "—";
    try {
      const d = new Date(isoStr);
      const diffMs = d - Date.now();
      if (diffMs < 0) return "Soon";
      const mins = Math.floor(diffMs / 60000);
      if (mins < 60) return `${mins}m`;
      return `${Math.floor(mins / 60)}h ${mins % 60}m`;
    } catch { return isoStr; }
  }

  function fmtSynced(isoStr) {
    if (!isoStr) return "Never";
    try {
      return new Date(isoStr).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    } catch { return isoStr; }
  }

  // ── Render data ───────────────────────────────────────────────────────────
  function renderData(data) {
    if (!data) {
      pctEl.textContent = "—";
      msgsEl.textContent = "—";
      resetEl.textContent = "—";
      orgEl.textContent = "—";
      syncedEl.textContent = "Never";
      statusDot.className = "status-dot offline";
      statusText.textContent = "No data yet – click Sync";
      return;
    }

    // percentage = % USED (0 = nothing used, 100 = fully exhausted)
    const pct = clamp(parseFloat(data.percentage ?? 0), 0, 100);
    const colors = colorForPct(pct);

    // Status
    statusDot.className = "status-dot online";
    statusText.textContent = "Synced ✓";

    // Progress bar fills with usage
    quotaFill.style.width = pct + "%";
    quotaFill.style.background = `linear-gradient(90deg, ${colors.bar}, ${colors.bar}cc)`;
    quotaFill.style.boxShadow = `0 0 8px ${colors.bar}66`;

    // Percentage
    pctEl.textContent = pct.toFixed(1) + "% used";
    pctEl.style.color = colors.text;

    // Messages used
    if (data.limit > 0) {
      msgsEl.textContent = `${Math.round(data.used_count)} / ${Math.round(data.limit)}`;
    } else {
      msgsEl.textContent = `${pct.toFixed(1)}% used`;
    }
    msgsEl.style.color = colors.text;

    // Reset & org
    resetEl.textContent = fmtReset(data.reset_at);
    orgEl.textContent = data.org_name || "—";
    syncedEl.textContent = fmtSynced(data.synced_at);
  }

  // ── Load from storage ─────────────────────────────────────────────────────
  chrome.storage.local.get(STORAGE_KEY, (result) => {
    renderData(result[STORAGE_KEY] || null);
  });

  // Watch for storage changes (background updated it)
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === "local" && changes[STORAGE_KEY]) {
      renderData(changes[STORAGE_KEY].newValue);
    }
  });

  // ── Sync button ────────────────────────────────────────────────────────────
  syncBtn.addEventListener("click", () => {
    syncBtn.disabled = true;
    syncBtn.innerHTML = `<span class="spinner"></span> Syncing…`;

    chrome.runtime.sendMessage({ action: "sync_now" }, (response) => {
      syncBtn.disabled = false;
      syncBtn.textContent = "Sync Now";

      if (chrome.runtime.lastError) {
        statusText.textContent = "Error – reload extension";
        return;
      }

      if (response?.success && response.data) {
        renderData(response.data);
      } else {
        statusDot.className = "status-dot offline";
        statusText.textContent = response?.error || "Sync failed";
      }
    });
  });
});
