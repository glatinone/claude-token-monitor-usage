/**
 * Claude Token Monitor - Background Service Worker
 * -----------------------------------------------
 * This service worker syncs Claude usage data independently of the local
 * desktop server. Data is always persisted in chrome.storage.local so the
 * extension works standalone (no desktop app required).
 *
 * Flow:
 *  1. Fetch /api/organizations from claude.ai (uses existing session cookie)
 *  2. For each org, fetch /api/organizations/{uuid}/usage
 *  3. Pick the org with the most usage (lowest % remaining)
 *  4. Persist result in chrome.storage.local
 *  5. Broadcast to all claude.ai tabs so the HUD updates instantly
 *  6. Optionally POST to the local desktop server (best-effort, non-blocking)
 */

"use strict";

const SYNC_ALARM_NAME = "sync-claude-usage";
const LOCAL_SERVER_URL = "http://127.0.0.1:9988/api/usage";
const STORAGE_KEY = "claude_usage_data";

// ── Logging ────────────────────────────────────────────────────────────────
function log(...args) {
  console.log("[Claude Monitor]", ...args);
}

// ── Alarm setup ────────────────────────────────────────────────────────────
chrome.runtime.onInstalled.addListener(() => {
  log("Installed. Creating alarm...");
  chrome.alarms.create(SYNC_ALARM_NAME, { periodInMinutes: 2 });
  syncUsage();
});

chrome.runtime.onStartup.addListener(() => {
  log("Browser started. Syncing...");
  syncUsage();
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === SYNC_ALARM_NAME) {
    log("Alarm fired. Syncing...");
    syncUsage();
  }
});

// ── Tab triggers ───────────────────────────────────────────────────────────
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === "complete" && tab.url?.includes("claude.ai")) {
    log("Tab updated, syncing...");
    syncUsage();
  }
});

chrome.tabs.onActivated.addListener((activeInfo) => {
  chrome.tabs.get(activeInfo.tabId, (tab) => {
    if (tab?.url?.includes("claude.ai")) {
      log("Tab activated, syncing...");
      syncUsage();
    }
  });
});

// ── Message handler ────────────────────────────────────────────────────────
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === "sync_now") {
    syncUsage()
      .then((data) => sendResponse({ success: true, data }))
      .catch((err) => sendResponse({ success: false, error: err.message }));
    return true; // keep port open for async
  }

  if (request.action === "get_cached_usage") {
    chrome.storage.local.get(STORAGE_KEY, (result) => {
      sendResponse({ success: true, data: result[STORAGE_KEY] || null });
    });
    return true;
  }

  if (request.action === "trigger_sync_bg") {
    syncUsage().catch(() => {});
    return false;
  }
});

// ── Broadcast to all claude.ai tabs ────────────────────────────────────────
function broadcastToTabs(payload) {
  chrome.tabs.query({ url: "https://claude.ai/*" }, (tabs) => {
    for (const tab of tabs) {
      chrome.tabs.sendMessage(tab.id, { action: "update_hud", data: payload }).catch(() => {});
    }
  });
}

// ── Main sync function ─────────────────────────────────────────────────────
async function syncUsage() {
  try {
    // 1. Fetch organisations list
    const orgsRes = await fetch("https://claude.ai/api/organizations", {
      credentials: "include",
    });

    if (!orgsRes.ok) {
      const status = orgsRes.status;
      if (status === 401 || status === 403) {
        throw new Error("Not logged in to claude.ai");
      }
      throw new Error(`Organizations fetch failed: ${orgsRes.status} ${orgsRes.statusText}`);
    }

    const orgs = await orgsRes.json();
    if (!Array.isArray(orgs) || orgs.length === 0) {
      throw new Error("No organizations returned from claude.ai");
    }

    log(`Found ${orgs.length} organization(s).`);

    // 2. For each org, fetch usage and pick the most consumed one (highest used %)
    let bestPayload = null;
    let highestUsed = -1;

    for (const org of orgs) {
      try {
        const usageRes = await fetch(
          `https://claude.ai/api/organizations/${org.uuid}/usage`,
          { credentials: "include" }
        );

        if (!usageRes.ok) {
          log(`Usage fetch failed for org ${org.name}: ${usageRes.status}`);
          continue;
        }

        const raw = await usageRes.json();
        log(`Raw usage for "${org.name}":`, JSON.stringify(raw));

        const parsed = parseUsage(raw, org.name);
        if (!parsed) continue;

        // Pick the org with the highest usage (most active)
        const effectiveUsed =
          parsed.limit > 0
            ? (parsed.used_count / parsed.limit) * 100
            : (100 - parsed.percentage);

        if (effectiveUsed > highestUsed) {
          highestUsed = effectiveUsed;
          bestPayload = parsed;
        }
      } catch (err) {
        log(`Error processing org ${org.name}:`, err);
      }
    }

    if (!bestPayload) {
      throw new Error("Could not parse usage from any organization.");
    }

    // Attach timestamp
    bestPayload.synced_at = new Date().toISOString();

    log("Best payload:", bestPayload);

    // 3. Persist to chrome.storage.local (always works, no server required)
    await chrome.storage.local.set({ [STORAGE_KEY]: bestPayload });

    // 4. Broadcast to all HUDs
    broadcastToTabs(bestPayload);

    // 5. Best-effort POST to local desktop server (non-blocking)
    pushToLocalServer(bestPayload);

    return bestPayload;
  } catch (err) {
    log("Sync error:", err.message);
    throw err;
  }
}

/**
 * Parse the raw usage API response into a normalised payload.
 * Claude.ai has returned different shapes over time – this handles all variants.
 */
function parseUsage(raw, orgName) {
  // percentage = % USED (0 = fresh, 100 = exhausted) — matches user preference
  let percentage = null;
  let used_count = 0;   // messages used (count)
  let limit = 0;        // message cap (0 = unknown)
  let reset_at = "";

  // Shape A: { five_hour: { utilization, remaining_messages, message_limit, resets_at } }
  if (raw?.five_hour) {
    const fh = raw.five_hour;
    reset_at = fh.resets_at || "";

    if (fh.remaining_messages != null && fh.message_limit != null) {
      limit = parseFloat(fh.message_limit);
      const remaining = parseFloat(fh.remaining_messages);
      used_count = limit - remaining;
      percentage = limit > 0 ? (used_count / limit) * 100 : 0;
    } else if (fh.utilization != null) {
      // utilization IS the used percentage (0–100)
      percentage = parseFloat(fh.utilization);
    } else if (fh.used_percentage != null) {
      percentage = parseFloat(fh.used_percentage);
    } else if (fh.remaining_percentage != null) {
      percentage = 100 - parseFloat(fh.remaining_percentage);
    }
  }

  // Shape B: flat { percentage, remaining, limit, resets_at }
  else if (raw?.percentage != null) {
    limit = parseFloat(raw.limit ?? 0);
    const rem = parseFloat(raw.remaining ?? 0);
    used_count = limit > 0 ? limit - rem : 0;
    if (limit > 0) {
      percentage = (used_count / limit) * 100;
    } else {
      percentage = parseFloat(raw.percentage);
    }
    reset_at = raw.resets_at || "";
  }

  // Shape C: array of quota objects
  else if (Array.isArray(raw)) {
    for (const item of raw) {
      const inner = parseUsage(item, orgName);
      if (inner) return inner;
    }
  }

  if (percentage === null) return null;

  // Clamp
  percentage = Math.max(0, Math.min(100, percentage));

  return {
    percentage,   // % USED (0 = fresh, 100 = exhausted)
    is_used: true,
    used_count,   // messages used (count, 0 if unknown)
    limit,        // message cap (0 if unknown)
    reset_at,
    org_name: orgName,
  };
}

/**
 * Optionally push to the local desktop server.
 * Errors are silently swallowed so the extension works without the app.
 */
async function pushToLocalServer(payload) {
  try {
    const res = await fetch(LOCAL_SERVER_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (res.ok) {
      log("Local server updated.");
    }
  } catch (_) {
    // Desktop server is not running – that's fine.
  }
}
