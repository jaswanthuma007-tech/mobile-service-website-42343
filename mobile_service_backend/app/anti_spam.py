import os
import threading
import time
import logging
import hashlib
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_DIGITS_ONLY_RE = re.compile(r"\D+")


def _env_int(name: str, default: int) -> int:
    """Read an integer env var with a safe fallback."""
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return int(default)
    try:
        return int(raw)
    except ValueError:
        return int(default)


def _clamp_int(value: int, min_value: int, max_value: int) -> int:
    """Clamp an int into [min_value, max_value]."""
    return max(min_value, min(int(value), max_value))


def _now() -> float:
    """Monotonic-ish current time for rate limiting."""
    return time.time()


@dataclass
class _Bucket:
    """Token bucket state for a single key (e.g., IP)."""

    tokens: float
    last_refill_ts: float


class RateLimiter:
    """Simple token-bucket rate limiter with per-key buckets.

    This is intended for single-instance deployments (in-process memory). Thread-safe.

    Two-bucket strategy:
    - minute bucket enforces bursts
    - hour bucket enforces sustained usage

    Note: this does not attempt to be perfectly 'sliding window', but token bucket is
    acceptable and recommended in the task requirements.
    """

    def __init__(self, per_minute: int = 5, per_hour: int = 50) -> None:
        self.per_minute = _clamp_int(per_minute, 1, 10_000)
        self.per_hour = _clamp_int(per_hour, 1, 1_000_000)

        # Refill rates (tokens per second)
        self._minute_rate = self.per_minute / 60.0
        self._hour_rate = self.per_hour / 3600.0

        self._minute_buckets: dict[str, _Bucket] = {}
        self._hour_buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def _refill(self, bucket: _Bucket, capacity: int, rate_per_sec: float, now_ts: float) -> None:
        elapsed = max(0.0, now_ts - bucket.last_refill_ts)
        bucket.tokens = min(float(capacity), bucket.tokens + (elapsed * rate_per_sec))
        bucket.last_refill_ts = now_ts

    # PUBLIC_INTERFACE
    def allow(self, key: str, tokens: float = 1.0) -> bool:
        """Check and consume tokens for a given key.

        Args:
            key: Rate-limit key, typically an IP string.
            tokens: cost of the request (default 1).

        Returns:
            True if allowed, False if rate limited.
        """
        if not key:
            # Defensive: if key missing, do not block, but still log.
            logger.warning("RateLimiter.allow called with empty key; allowing request")
            return True

        now_ts = _now()
        with self._lock:
            mb = self._minute_buckets.get(key)
            if mb is None:
                mb = _Bucket(tokens=float(self.per_minute), last_refill_ts=now_ts)
                self._minute_buckets[key] = mb
            hb = self._hour_buckets.get(key)
            if hb is None:
                hb = _Bucket(tokens=float(self.per_hour), last_refill_ts=now_ts)
                self._hour_buckets[key] = hb

            self._refill(mb, self.per_minute, self._minute_rate, now_ts)
            self._refill(hb, self.per_hour, self._hour_rate, now_ts)

            if mb.tokens < tokens or hb.tokens < tokens:
                return False

            mb.tokens -= tokens
            hb.tokens -= tokens
            return True

    # PUBLIC_INTERFACE
    def cleanup(self, max_idle_seconds: int = 6 * 3600) -> None:
        """Remove buckets that haven't been used in a while to avoid unbounded growth."""
        now_ts = _now()
        cutoff = now_ts - float(max(60, int(max_idle_seconds)))
        with self._lock:
            self._minute_buckets = {
                k: b for k, b in self._minute_buckets.items() if b.last_refill_ts >= cutoff
            }
            self._hour_buckets = {k: b for k, b in self._hour_buckets.items() if b.last_refill_ts >= cutoff}


class DuplicateSubmissionGuard:
    """Duplicate-submission guard with a fixed "hint window" (in-process).

    Important behavior for this project:
    - This guard MUST NOT block inserts/booking creation.
    - It is used only to detect "same details submitted recently" so the API can
      include a user-friendly hint message while still returning success.

    Stores last-seen timestamps per dedupe key. Thread-safe.
    """

    def __init__(self, cooldown_seconds: int = 60) -> None:
        self.cooldown_seconds = _clamp_int(int(cooldown_seconds), 1, 24 * 3600)
        self._last_seen: dict[str, float] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _hash_key(raw_key: str) -> str:
        # Hash for privacy, avoids logging/storing PII in plain text.
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    # PUBLIC_INTERFACE
    def check_and_mark_hint(self, raw_key: str) -> bool:
        """Return whether this submission should show a "duplicate" hint, and mark as seen.

        Args:
            raw_key: dedupe key material (should already be normalized).

        Returns:
            True if a previous submission with the same key occurred within the
            cooldown window (i.e., show a hint).
            False otherwise.

        Notes:
            This function intentionally never blocks. Callers should always proceed
            with normal insert/reuse-or-create logic.
        """
        key = self._hash_key(raw_key)
        now_ts = _now()
        with self._lock:
            last = self._last_seen.get(key)
            is_hint = bool(last is not None and (now_ts - last) < float(self.cooldown_seconds))
            self._last_seen[key] = now_ts
            return is_hint

    # PUBLIC_INTERFACE
    def cleanup(self, max_age_seconds: int = 24 * 3600) -> None:
        """Remove old keys to avoid unbounded growth."""
        now_ts = _now()
        cutoff = now_ts - float(max(60, int(max_age_seconds)))
        with self._lock:
            self._last_seen = {k: ts for k, ts in self._last_seen.items() if ts >= cutoff}


# A single module-level store is fine for this codebase (single Flask app).
_RATE_LIMITER = RateLimiter(
    per_minute=_env_int("RATE_LIMIT_PER_MINUTE", 5),
    per_hour=_env_int("RATE_LIMIT_PER_HOUR", 50),
)

_DUP_GUARD = DuplicateSubmissionGuard(
    cooldown_seconds=_env_int("DUP_SUBMISSION_COOLDOWN_SECONDS", 60),
)


def normalize_name_for_dedupe(name: str) -> str:
    """Normalize name to a stable, low-variance representation for dedupe keys."""
    return " ".join((name or "").strip().lower().split())


def normalize_phone_digits(phone: str) -> str:
    """Normalize phone to digits-only for dedupe keys."""
    return _DIGITS_ONLY_RE.sub("", (phone or "").strip())


def normalize_pincode_digits(pincode: str) -> str:
    """Normalize pincode to digits-only for dedupe keys."""
    return _DIGITS_ONLY_RE.sub("", (pincode or "").strip())


# PUBLIC_INTERFACE
def enforce_booking_anti_spam(
    ip: str, name: str, phone_normalized_10: str, pincode_normalized_6: str
) -> tuple[bool, str | None, str | None, bool]:
    """Enforce rate limiting and detect recent duplicate submissions for booking creation.

    Authoritative requirements (current):
    - Rate limit: 5/min per IP (configurable via RATE_LIMIT_PER_MINUTE), return 429 if exceeded.
    - Duplicate logic: only consider *same phone + pincode* within 60 seconds
      (configurable via DUP_SUBMISSION_COOLDOWN_SECONDS).
    - Duplicate detection MUST NOT block inserts. It only produces a "hint" that
      callers may surface as a clear message.

    Args:
        ip: best-effort client IP string
        name: customer-provided name (unused for dedupe now, kept for compatibility)
        phone_normalized_10: already-normalized and validated 10-digit phone
        pincode_normalized_6: already-normalized and validated 6-digit pincode

    Returns:
        (allowed, error_code, error_message, duplicate_hint)
        - If allowed=True: error_code/message are None; duplicate_hint indicates whether
          the same phone+pincode was submitted within the cooldown window.
        - If allowed=False: error_code/message describe the rate-limit rejection.
    """
    # Periodic cleanup (cheap, but keep it light). Not strictly required.
    # Only cleanup occasionally based on time modulo; avoids adding timers.
    try:
        if int(_now()) % 300 == 0:
            _RATE_LIMITER.cleanup()
            _DUP_GUARD.cleanup()
    except Exception:
        # Never fail requests due to cleanup.
        logger.debug("Anti-spam cleanup failed", exc_info=True)

    if not _RATE_LIMITER.allow(ip):
        return False, "RATE_LIMITED", "Too many requests. Please wait a moment and try again.", False

    # Dedupe is now strictly (phone+pincode) per requirement. Name is intentionally excluded.
    dedupe_key = f"{phone_normalized_10}|{pincode_normalized_6}"
    duplicate_hint = False
    try:
        duplicate_hint = _DUP_GUARD.check_and_mark_hint(dedupe_key)
    except Exception:
        # Never break booking flow due to hint detection.
        duplicate_hint = False

    return True, None, None, duplicate_hint
