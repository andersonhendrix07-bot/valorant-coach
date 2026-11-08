"""Website access rules: which API key a request uses, and limits for the shared site key.

- A visitor can paste their own HenrikDev key. It is held only in that visitor's session
  memory, used for their requests, and never written to disk or the cache.
- Otherwise the site owner's key (Streamlit secret HENRIKDEV_API_KEY) is used. All visitors
  share its rate limit, so site-key loads are capped and have a per-session cooldown.
"""
from __future__ import annotations

import os
import re
import time
from collections.abc import Mapping

SITE_MAX_MATCHES_DEFAULT = 20
SITE_COOLDOWN_S_DEFAULT = 60
_KEY_RE = re.compile(r"^[A-Za-z0-9_\-]{16,128}$")


def looks_like_key(value: str | None) -> bool:
    return bool(value) and bool(_KEY_RE.match(value.strip()))


def read_setting(secrets: Mapping | None, name: str, default=None):
    """Streamlit secrets first, then environment variables (local .env), then default."""
    try:
        if secrets is not None and name in secrets:
            return secrets[name]
    except Exception:  # st.secrets raises when no secrets file exists locally
        pass
    return os.getenv(name, default)


def choose_key(site_key: str | None, visitor_key: str | None) -> tuple[str | None, str | None]:
    """Returns (key, source) with source 'visitor', 'site' or None. A visitor key wins."""
    if visitor_key and visitor_key.strip():
        return visitor_key.strip(), "visitor"
    if site_key and site_key.strip():
        return site_key.strip(), "site"
    return None, None


class Cooldown:
    """Per-session limit on refreshes that use the shared site key."""

    def __init__(self, seconds: float, clock=time.time):
        self.seconds = seconds
        self._clock = clock
        self._last: float | None = None

    def remaining(self) -> float:
        if self._last is None:
            return 0.0
        return max(0.0, self.seconds - (self._clock() - self._last))

    def ready(self) -> bool:
        return self.remaining() == 0.0

    def mark(self) -> None:
        self._last = self._clock()
