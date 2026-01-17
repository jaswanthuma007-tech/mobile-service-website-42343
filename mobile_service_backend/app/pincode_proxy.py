import json
import logging
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

logger = logging.getLogger(__name__)


def _now() -> float:
    """Return current time in seconds."""
    return time.time()


@dataclass
class _CacheEntry:
    """Internal cache entry."""
    value: dict
    expires_at: float


class TTLCache:
    """A tiny in-process TTL cache (thread-safe).

    This is intentionally simple: single-instance Flask deployments can safely use
    in-memory caching to reduce repeated calls to the external Postal API.
    """

    def __init__(self, ttl_seconds: int = 6 * 3600, max_entries: int = 2000) -> None:
        self.ttl_seconds = max(30, int(ttl_seconds))
        self.max_entries = max(10, int(max_entries))
        self._items: dict[str, _CacheEntry] = {}
        self._lock = threading.Lock()

    def _prune_if_needed(self) -> None:
        # Remove expired entries and enforce max size (best-effort).
        now_ts = _now()
        expired = [k for k, v in self._items.items() if v.expires_at <= now_ts]
        for k in expired:
            self._items.pop(k, None)

        if len(self._items) <= self.max_entries:
            return

        # If still over capacity, drop entries with earliest expiry first.
        keys_by_expiry = sorted(self._items.items(), key=lambda kv: kv[1].expires_at)
        to_drop = len(self._items) - self.max_entries
        for i in range(max(0, to_drop)):
            self._items.pop(keys_by_expiry[i][0], None)

    # PUBLIC_INTERFACE
    def get(self, key: str) -> dict | None:
        """Get a cached value if present and not expired."""
        if not key:
            return None
        with self._lock:
            entry = self._items.get(key)
            if not entry:
                return None
            if entry.expires_at <= _now():
                self._items.pop(key, None)
                return None
            return dict(entry.value)

    # PUBLIC_INTERFACE
    def set(self, key: str, value: dict) -> None:
        """Set a cached value."""
        if not key:
            return
        with self._lock:
            self._items[key] = _CacheEntry(value=dict(value), expires_at=_now() + float(self.ttl_seconds))
            # Best-effort pruning
            try:
                self._prune_if_needed()
            except Exception:
                logger.debug("TTLCache prune failed", exc_info=True)


# Module-level cache for pincode responses
_PINCODE_CACHE = TTLCache(ttl_seconds=6 * 3600, max_entries=5000)


def _http_get_json(url: str, timeout_seconds: int = 6) -> object:
    """GET JSON using stdlib urllib (keeps deps minimal)."""
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "mobile-service-backend/1.0 (+pincode-proxy)",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw)


def _extract_city_district_state(post_offices: list[dict]) -> tuple[str, str, str]:
    """Extract city/district/state from Postal API PostOffice list."""
    if not post_offices:
        return "", "", ""
    first = post_offices[0] or {}
    # Postal API uses District/State; region/city can vary, but Block is often the "city"
    city = str(first.get("Block") or first.get("Name") or "").strip()
    district = str(first.get("District") or "").strip()
    state = str(first.get("State") or "").strip()
    return city, district, state


# PUBLIC_INTERFACE
def check_pincode_via_postal_api(pincode: str) -> dict:
    """Check a 6-digit Indian pincode via Postal API with caching.

    Calls:
      https://api.postalpincode.in/pincode/{PINCODE}

    Returns a stable shape for the frontend:
      {
        "valid": bool,
        "message": str,
        "location": { "city": str, "district": str, "state": str } | None
      }

    Notes:
    - We cache both success and error responses to reduce repeated external requests.
    - We never raise raw urllib errors to the client; route should map failures to a friendly message.
    """
    cached = _PINCODE_CACHE.get(pincode)
    if cached is not None:
        return cached

    url = f"https://api.postalpincode.in/pincode/{pincode}"
    data = _http_get_json(url, timeout_seconds=6)

    # Postal API returns a list with one object: [{ Status, Message, PostOffice: [...] }]
    if not isinstance(data, list) or len(data) == 0 or not isinstance(data[0], dict):
        result = {"valid": False, "message": "Unable to verify pincode. Please try again.", "location": None}
        _PINCODE_CACHE.set(pincode, result)
        return result

    item = data[0]
    status = str(item.get("Status") or "").strip()
    if status.lower() == "success":
        post_offices = item.get("PostOffice") or []
        if not isinstance(post_offices, list) or len(post_offices) == 0:
            # Rare, but treat as not serviceable.
            result = {"valid": False, "message": "Service not available in this area.", "location": None}
            _PINCODE_CACHE.set(pincode, result)
            return result

        city, district, state = _extract_city_district_state(post_offices)
        loc = {"city": city, "district": district, "state": state}
        msg = "Service available."
        # Provide more informative message for UI
        if district or state or city:
            msg = f"Service available in {', '.join([x for x in [city, district, state] if x])}."
        result = {"valid": True, "message": msg, "location": loc}
        _PINCODE_CACHE.set(pincode, result)
        return result

    # "Error" => unserviceable/invalid per requirement
    result = {"valid": False, "message": "Service not available in this area.", "location": None}
    _PINCODE_CACHE.set(pincode, result)
    return result


# PUBLIC_INTERFACE
def safe_check_pincode(pincode: str) -> dict:
    """Wrapper that converts network/HTTP errors into a friendly message response."""
    try:
        return check_pincode_via_postal_api(pincode)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        logger.info("Postal API request failed for pincode=%s", pincode, exc_info=True)
        return {"valid": False, "message": "Unable to verify pincode. Please try again.", "location": None}
    except Exception:
        logger.exception("Unexpected error checking pincode=%s", pincode)
        return {"valid": False, "message": "Unable to verify pincode. Please try again.", "location": None}
