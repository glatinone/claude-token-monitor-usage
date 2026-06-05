"""
claude_fetcher.py – Fetch Claude.ai usage data.
------------------------------------------------
Strategy (tried in order):
  1. Saved session key in local config file (most reliable, cross-browser)
  2. browser_cookie3 from any supported browser (if not locked)
  3. Poll the local HTTP server cache (pushed by browser extension)

The first successful strategy wins.  The saved key approach is best:
the user pastes their sessionKey once via the tray setup dialog.

Returns a normalised UsageData dict:
  {
      "percentage":  float,   # % USED (0=fresh, 100=exhausted)
      "used_count":  int,
      "limit":       int,
      "reset_at":    str,
      "org_name":    str,
      "synced_at":   str,
      "source":      str,     # "saved_key" | "browser_cookie" | "local_server"
  }
"""

import requests
import json
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ── Config paths ──────────────────────────────────────────────────────────
_APP_DIR     = os.path.dirname(os.path.abspath(__file__))
_CONFIG_FILE = os.path.join(_APP_DIR, "config.json")
_SERVER_URL  = "http://127.0.0.1:9988/api/usage"


class NotLoggedInError(Exception):
    """No valid session key available."""


class FetchError(Exception):
    """HTTP / parse failure."""


# ── Config helpers ────────────────────────────────────────────────────────

def load_config() -> dict:
    try:
        with open(_CONFIG_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(data: dict) -> None:
    try:
        existing = load_config()
        existing.update(data)
        with open(_CONFIG_FILE, "w") as f:
            json.dump(existing, f, indent=2)
    except Exception as e:
        logger.warning(f"Could not save config: {e}")


def get_saved_session_key() -> str | None:
    return load_config().get("session_key")


def set_session_key(key: str) -> None:
    save_config({"session_key": key.strip()})
    logger.info("Session key saved to config.")


# ── Parse raw usage API response ──────────────────────────────────────────

def _parse_usage(raw, org_name: str) -> dict | None:
    """
    Normalise any known Claude.ai usage API shape.
    percentage = % USED (0=fresh, 100=exhausted).
    """
    percentage = None
    used_count = 0
    limit      = 0
    reset_at   = ""

    if isinstance(raw, dict):
        fh = raw.get("five_hour")
        if fh and isinstance(fh, dict):
            reset_at = fh.get("resets_at", "")
            rem      = fh.get("remaining_messages")
            lim      = fh.get("message_limit")
            util     = fh.get("utilization")
            used_pct = fh.get("used_percentage")
            rem_pct  = fh.get("remaining_percentage")

            if rem is not None and lim is not None:
                limit      = int(lim)
                used_count = limit - int(rem)
                percentage = (used_count / limit * 100) if limit > 0 else 0.0
            elif util is not None:
                percentage = float(util)
            elif used_pct is not None:
                percentage = float(used_pct)
            elif rem_pct is not None:
                percentage = 100.0 - float(rem_pct)

        elif "percentage" in raw:
            limit      = int(raw.get("limit", 0))
            used_count = int(raw.get("used_count", 0))
            if used_count == 0 and "remaining" in raw and limit > 0:
                used_count = limit - int(raw["remaining"])
            
            if limit > 0:
                percentage = (used_count / limit * 100)
            else:
                percentage = float(raw["percentage"])
            reset_at   = raw.get("resets_at", "") or raw.get("reset_at", "")

    elif isinstance(raw, list):
        for item in raw:
            r = _parse_usage(item, org_name)
            if r:
                return r

    if percentage is None:
        return None

    return {
        "percentage": round(max(0.0, min(100.0, percentage)), 2),
        "used_count": max(0, used_count),
        "limit":      limit,
        "reset_at":   reset_at,
        "org_name":   org_name,
    }


def _make_session(session_key: str, extra_cookies: dict | None = None) -> requests.Session:
    """
    Build a requests.Session that mimics a real browser visiting claude.ai.
    Sends sessionKey plus any extra cookies extracted from the browser.
    """
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Referer":       "https://claude.ai/",
        "Origin":        "https://claude.ai",
        "Accept":        "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "anthropic-client-version": "0",
    })
    # Set extra cookies first (lower priority)
    if extra_cookies:
        for name, value in extra_cookies.items():
            sess.cookies.set(name, value, domain=".claude.ai", path="/")
    # sessionKey overrides any existing session cookie
    sess.cookies.set("sessionKey", session_key, domain=".claude.ai", path="/")
    return sess


def _get_all_browser_cookies() -> dict:
    """
    Try to read ALL claude.ai cookies from the browser (not just sessionKey).
    Returns a dict of {name: value}.
    """
    result = {}
    try:
        import browser_cookie3  # type: ignore
        loaders = [
            browser_cookie3.brave,
            browser_cookie3.chrome,
            browser_cookie3.edge,
            browser_cookie3.chromium,
            browser_cookie3.firefox,
        ]
        for loader in loaders:
            try:
                jar = loader(domain_name=".claude.ai")
                for c in jar:
                    if c.value:
                        result[c.name] = c.value
                if result:
                    logger.info(f"Loaded {len(result)} cookies from browser")
                    break
            except Exception as e:
                logger.debug(f"Browser cookie loader: {e}")
    except ImportError:
        pass
    return result


# ── Core fetch with a session key ─────────────────────────────────────────

def _fetch_with_key(session_key: str, extra_cookies: dict | None = None) -> dict:
    """Call claude.ai API using a session key cookie."""
    sess = _make_session(session_key, extra_cookies)

    # Fetch organisations
    try:
        resp = sess.get("https://claude.ai/api/organizations", timeout=12)
    except requests.RequestException as e:
        raise FetchError(f"Network error: {e}") from e

    if resp.status_code in (401, 403):
        logger.warning(f"403 response body: {resp.text[:300]}")
        raise NotLoggedInError(
            "Session key rejected (403).\n"
            "Please update it via tray → 🔑 Setup Session Key."
        )
    if not resp.ok:
        raise FetchError(f"Organisations API {resp.status_code}: {resp.text[:120]}")

    orgs = resp.json()
    if not isinstance(orgs, list) or not orgs:
        raise FetchError("No organisations returned.")

    best: dict | None = None
    highest = -1.0

    for org in orgs:
        uuid     = org.get("uuid", "")
        org_name = org.get("name", uuid)
        if not uuid:
            continue
        try:
            r = sess.get(f"https://claude.ai/api/organizations/{uuid}/usage", timeout=12)
            if not r.ok:
                continue
            parsed = _parse_usage(r.json(), org_name)
            if parsed is None:
                continue
            eff = parsed["percentage"]
            if eff > highest:
                highest = eff
                best = parsed
        except Exception as e:
            logger.debug(f"Org {org_name}: {e}")

    if best is None:
        raise FetchError("Could not parse usage from any organisation.")

    return best


# ── Strategy 2: browser cookies ────────────────────────────────────────────

def _try_browser_cookies() -> str | None:
    """Try to extract sessionKey from installed browsers. Returns key or None."""
    try:
        import browser_cookie3  # type: ignore
    except ImportError:
        return None

    loaders = [
        ("Chrome",   browser_cookie3.chrome),
        ("Brave",    browser_cookie3.brave),
        ("Edge",     browser_cookie3.edge),
        ("Chromium", browser_cookie3.chromium),
        ("Firefox",  browser_cookie3.firefox),
    ]
    for name, loader in loaders:
        try:
            jar = loader(domain_name=".claude.ai")
            for c in jar:
                if c.name == "sessionKey" and c.value:
                    logger.info(f"Session cookie found in {name}")
                    return c.value
        except Exception as e:
            logger.debug(f"{name}: {e}")
    return None


# ── Strategy 3: pull from local HTTP server cache ─────────────────────────

def _fetch_from_local_server() -> dict:
    """
    GET http://127.0.0.1:9988/api/usage
    Returns cached data pushed by the browser extension.
    """
    try:
        r = requests.get(_SERVER_URL, timeout=3)
        if r.ok and r.text.strip():
            data = r.json()
            if data and "percentage" in data:
                logger.info("Using data from browser extension (local server).")
                return data
    except Exception as e:
        logger.debug(f"Local server not available: {e}")
    raise FetchError("Local server has no data yet.")


# ── Public API ─────────────────────────────────────────────────────────────

def fetch_usage() -> dict:
    """
    Try all strategies in order.  Raises FetchError / NotLoggedInError only
    if every strategy fails.
    """
    source = "unknown"
    result = None

    # Load all browser cookies (helps bypass Cloudflare — sends full cookie jar)
    browser_cookies = _get_all_browser_cookies()

    # Strategy 1: saved session key + browser cookies (for CF tokens)
    key = get_saved_session_key()
    if key:
        # Send all browser cookies except sessionKey (we override that with saved key)
        extra = {k: v for k, v in browser_cookies.items() if k != "sessionKey"}
        try:
            result = _fetch_with_key(key, extra_cookies=extra or None)
            source = "saved_key"
        except NotLoggedInError as e:
            logger.warning(f"Saved session key rejected: {e}")
        except FetchError as e:
            logger.warning(f"Fetch with saved key failed: {e}")

    # Strategy 2: full browser cookie jar (sessionKey from browser)
    if result is None:
        bkey = browser_cookies.get("sessionKey") or _try_browser_cookies()
        if bkey:
            extra = {k: v for k, v in browser_cookies.items() if k != "sessionKey"}
            try:
                result = _fetch_with_key(bkey, extra_cookies=extra or None)
                source = "browser_cookie"
                save_config({"session_key": bkey})
            except Exception as e:
                logger.warning(f"Browser-cookie fetch failed: {e}")

    # Strategy 3: local server cache (pushed by browser extension)
    if result is None:
        try:
            data = _fetch_from_local_server()
            pct   = float(data.get("percentage", 0))
            limit = int(data.get("limit", 0))
            used  = int(data.get("used_count", 0))
            if used == 0 and "remaining" in data:
                used = max(0, limit - int(data["remaining"]))
            result = {
                "percentage": pct,
                "used_count": used,
                "limit":      limit,
                "reset_at":   data.get("reset_at", ""),
                "org_name":   data.get("org_name", ""),
            }
            source = "local_server"
        except FetchError as e:
            logger.warning(f"Local server strategy failed: {e}")

    if result is None:
        raise NotLoggedInError(
            "No session key found and local server has no data.\n"
            "Click 'Setup Session Key' in the tray menu to configure."
        )

    result["synced_at"] = datetime.now(timezone.utc).isoformat()
    result["source"]    = source
    logger.info(f"Fetched via {source}: {result}")
    return result
