from __future__ import annotations

import os
from typing import Any, Dict, Optional

import requests
from dotenv import load_dotenv

load_dotenv()

BACKEND_URL = os.getenv("BACKEND_URL")
BACKEND_EMAIL = os.getenv("BACKEND_EMAIL")
BACKEND_PASSWORD = os.getenv("BACKEND_PASSWORD")

_session = requests.Session()
_token: Optional[str] = None


def set_token(token: str) -> None:
    """Override the cached token (used by UI logins)."""
    global _token
    _token = token


def _get_token() -> Optional[str]:
    """Login once and cache the access token."""
    global _token
    if _token:
        return _token

    if not (BACKEND_URL and BACKEND_EMAIL and BACKEND_PASSWORD):
        return None

    try:
        resp = _session.post(
            f"{BACKEND_URL}/auth/login",
            json={"email": BACKEND_EMAIL, "password": BACKEND_PASSWORD},
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json()
        _token = payload.get("access_token")
        return _token
    except Exception:
        return None


def get_shared_state() -> Optional[Dict[str, Any]]:
    """Fetch shared_state from backend if configured; otherwise return None."""
    if not BACKEND_URL:
        return None

    token = _get_token()
    if not token:
        return None

    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = _session.get(f"{BACKEND_URL}/me/shared-state", headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None
