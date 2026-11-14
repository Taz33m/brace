"""Polite HTTP and on-disk cache helpers shared by the hazard modules.

Every request has a timeout, a generic User-Agent, a small per-host gap between
calls, and a short backoff on 429 / 5xx. Failures surface as HazardError.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from backend.config import HAZARDS_DIR

from .errors import HazardError

USER_AGENT = "brace-hackathon"
CACHE_ROOT: Path = HAZARDS_DIR  # tests point this at a temp folder

DEFAULT_TIMEOUT = httpx.Timeout(25.0, connect=8.0)
BULK_TIMEOUT = httpx.Timeout(90.0, connect=10.0)  # for the few multi-megabyte downloads
MIN_INTERVAL_S = 0.2
RETRY_STATUS = {429, 500, 502, 503, 504}

_client: httpx.Client | None = None
_lock = threading.Lock()
_last_call: dict[str, float] = {}


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True)
    return _client


def _throttle(host: str) -> None:
    with _lock:
        wait = _last_call.get(host, 0.0) + MIN_INTERVAL_S - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call[host] = time.monotonic()


def get(url: str, params: dict | None = None, *, timeout: httpx.Timeout | None = None,
        retries: int = 2, headers: dict | None = None) -> httpx.Response:
    """GET with timeout, throttle and backoff. Raises HazardError on failure."""
    host = urlsplit(url).netloc
    problem = "no attempt made"
    for attempt in range(retries + 1):
        _throttle(host)
        try:
            resp = _get_client().get(url, params=params, timeout=timeout or DEFAULT_TIMEOUT, headers=headers)
        except httpx.HTTPError as exc:
            problem = f"{type(exc).__name__}: {exc}".strip(": ")
        else:
            if resp.status_code < 400:
                return resp
            problem = f"HTTP {resp.status_code}"
            if resp.status_code not in RETRY_STATUS:
                break
            retry_after = resp.headers.get("Retry-After", "")
            if retry_after.isdigit() and attempt < retries:
                time.sleep(min(30.0, float(retry_after)))
                continue
        if attempt < retries:
            time.sleep(min(30.0, 1.5 * 2 ** attempt))
    raise HazardError(f"{host} request failed ({problem}): {url}")


def get_json(url: str, params: dict | None = None, **kw: Any) -> Any:
    resp = get(url, params, **kw)
    try:
        return resp.json()
    except ValueError as exc:
        raise HazardError(f"{urlsplit(url).netloc} did not return JSON: {url}") from exc


def get_text(url: str, params: dict | None = None, **kw: Any) -> str:
    return get(url, params, **kw).text


def get_bytes(url: str, params: dict | None = None, **kw: Any) -> bytes:
    return get(url, params, **kw).content


# ---------------------------------------------------------------- disk cache

def cache_file(*parts: str) -> Path:
    """Path under the hazards cache folder; parent folders are created."""
    path = CACHE_ROOT.joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def write_json(path: Path, obj: Any) -> None:
    _atomic_write(path, json.dumps(obj, separators=(",", ":")).encode("utf-8"))


def write_text(path: Path, text: str) -> None:
    _atomic_write(path, text.encode("utf-8"))


def write_bytes(path: Path, data: bytes) -> None:
    _atomic_write(path, data)


def read_json(path: Path) -> Any | None:
    """Parsed JSON, or None when the file is missing or unreadable."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def file_age_s(path: Path) -> float | None:
    try:
        return time.time() - path.stat().st_mtime
    except OSError:
        return None
