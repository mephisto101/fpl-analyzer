from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests
from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


@dataclass(frozen=True)
class FplApiError(Exception):
    message: str
    url: str
    status_code: int | None = None

    def __str__(self) -> str:
        base = self.message
        if self.status_code is not None:
            base = f"{base} (HTTP {self.status_code})"
        return base


def build_http_session() -> Session:
    session = requests.Session()
    retries = Retry(
        total=3,
        connect=3,
        read=3,
        status=3,
        backoff_factor=0.4,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def fetch_json(*, session: Session, url: str, timeout_s: int) -> dict[str, Any] | list[dict[str, Any]]:
    try:
        resp = session.get(url, timeout=timeout_s)
        if not resp.ok:
            raise FplApiError("Request failed", url=url, status_code=resp.status_code)
        return resp.json()
    except requests.RequestException as e:
        raise FplApiError(str(e), url=url) from e
    except ValueError as e:
        raise FplApiError(f"Invalid JSON: {e}", url=url) from e

