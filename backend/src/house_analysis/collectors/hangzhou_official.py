"""Legacy Hangzhou second-hand transaction supervision platform adapter.

The formerly published host is currently not resolvable.  The implementation
keeps the public legacy endpoint isolated, low-frequency, and fail-closed so a
future restored endpoint can be tested without mixing it with broker data.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


PUBLIC_ENDPOINT = "https://jjhygl.hzfc.gov.cn/webty/WebFyAction_getGpxxSelectList.jspx"


class OfficialPlatformUnavailable(RuntimeError):
    """The published official platform is unavailable or has retired its endpoint."""


def parse_listing_payload(payload: dict[str, object]) -> list[dict[str, object]]:
    items = payload.get("list")
    if not isinstance(items, list):
        raise ValueError("官方平台响应缺少 list 数组")
    observed_at = datetime.now(timezone.utc).isoformat()
    records: list[dict[str, object]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        external_id = item.get("fwtybh") or item.get("houseCode") or item.get("id")
        if not external_id:
            continue
        layout = str(item.get("hxs") or item.get("layout") or "")
        bedrooms_match = re.search(r"(\d+)\s*室", layout)
        records.append(
            {
                "external_id": str(external_id),
                "observation_type": "listing",
                "observed_at": observed_at,
                "total_price": item.get("wtcsjg") or item.get("csjg") or item.get("price"),
                "area_sqm": item.get("jzmj") or item.get("buildArea") or item.get("area"),
                "bedrooms": int(bedrooms_match.group(1)) if bedrooms_match else None,
                "source_url": PUBLIC_ENDPOINT,
                "confidence": "high",
                "payload": {"parser": "hangzhou_official_legacy_v1", "raw": item, "listing_status": "observed"},
            }
        )
    return records


def fetch_public_listings(keyword: str, page: int = 1, timeout: int = 15) -> tuple[bytes, list[dict[str, object]]]:
    body = urlencode({"keywords": keyword, "page": page, "xqid": "0"}).encode("utf-8")
    request = Request(
        PUBLIC_ENDPOINT,
        data=body,
        headers={
            "User-Agent": "house-analysis/0.3 (+low-frequency public snapshot)",
            "Accept": "application/json,text/plain,*/*",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed official host
            raw = response.read()
    except (HTTPError, URLError, TimeoutError) as exc:
        reason = getattr(exc, "reason", exc)
        raise OfficialPlatformUnavailable(
            f"杭州二手房交易监管服务平台公开旧接口当前不可用: {reason}"
        ) from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OfficialPlatformUnavailable("官方平台未返回预期 JSON，可能已迁移或停止公开旧接口") from exc
    return raw, parse_listing_payload(payload)
