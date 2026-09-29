"""Low-frequency, public-page Lianjia snapshot helper.

This module deliberately accepts an explicit public URL. It does not discover
URLs, log in, call private APIs, or attempt to bypass anti-bot controls.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


ALLOWED_HOSTS = {"hz.lianjia.com", "news.lianjia.com"}
BLOCK_MARKERS = (
    "访问已被拦截",
    "检测到您的账号在过去使用了自动化工具",
    "贝壳信息安全中心",
    "hip.lianjia.com/forbidden",
)


class LianjiaAccessBlocked(RuntimeError):
    """The public page was rejected by Lianjia's access-control layer."""


def _validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError("只允许访问杭州链家公开 HTTPS 页面")


def _assert_not_blocked(html: str, final_url: str = "") -> None:
    if "hip.lianjia.com/forbidden" in final_url or any(marker in html for marker in BLOCK_MARKERS):
        raise LianjiaAccessBlocked(
            "链家拒绝了自动化访问；请勿重试轰炸、代理绕过或破解验证码。"
            "可在正常浏览器中打开公开页面并保存 HTML，再使用 import-lianjia-html 导入。"
        )


def fetch_public_page(url: str, timeout: int = 15) -> str:
    _validate_public_url(url)
    request = Request(
        url,
        headers={
            "User-Agent": "house-analysis/0.2 (+low-frequency, reviewed public snapshot)",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - host is allow-listed above
            if response.status != 200:
                raise RuntimeError(f"链家页面返回 HTTP {response.status}")
            html = response.read().decode("utf-8", errors="replace")
            final_url = response.geturl()
    except HTTPError as exc:
        if exc.code in {403, 418, 429}:
            raise LianjiaAccessBlocked(
                f"链家访问控制返回 HTTP {exc.code}；请改用正常浏览器保存 HTML 后导入。"
            ) from exc
        raise RuntimeError(f"链家页面返回 HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"链家网络请求失败: {exc.reason}") from exc
    _assert_not_blocked(html, final_url)
    return html


def _clean(value: str | None) -> str | None:
    if not value:
        return None
    value = re.sub(r"<[^>]+>", " ", unescape(value))
    value = re.sub(r"\s+", " ", value).strip()
    return value or None


def _number(value: str | None) -> str | None:
    cleaned = _clean(value)
    if not cleaned:
        return None
    match = re.search(r"\d+(?:\.\d+)?", cleaned.replace(",", ""))
    return match.group(0) if match else None


def parse_public_listing(url: str, html: str) -> dict[str, object]:
    """Parse stable identifiers and common visible fields without guessing."""
    _validate_public_url(url)
    _assert_not_blocked(html)
    match = re.search(r"/ershoufang/(\d+)\.html", url)
    external_id = match.group(1) if match else None
    def first(pattern: str) -> str | None:
        found = re.search(pattern, html, re.I | re.S)
        return _clean(found.group(1)) if found else None
    total = _number(first(r'class="total"[^>]*>([^<]+)'))
    unit = _number(first(r'class="unitPrice"[^>]*>([^<]+)'))
    area = _number(first(r'class="area"[^>]*>.*?class="mainInfo"[^>]*>([^<]+)'))
    title = first(r'<title[^>]*>(.*?)</title>')
    return {
        "external_id": external_id,
        "observation_type": "listing",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "total_price": total,
        "unit_price": unit,
        "area_sqm": area,
        "source_url": url,
        "confidence": "medium" if external_id else "low",
        "payload": {"title": title, "parser": "lianjia_public_v1"},
    }


def fetch_and_parse_listing(url: str) -> dict[str, object]:
    return parse_public_listing(url, fetch_public_page(url))


def parse_public_listing_page(url: str, html: str) -> list[dict[str, object]]:
    """Parse visible listing cards from a user-reviewed public HTML snapshot."""
    _validate_public_url(url)
    _assert_not_blocked(html)
    observed_at = datetime.now(timezone.utc).isoformat()
    records: list[dict[str, object]] = []
    cards = re.findall(
        r'<li\b[^>]*class="[^"]*(?:LOGVIEWDATA|LOGCLICKDATA|clear)[^"]*"[^>]*>(.*?)</li>',
        html,
        re.I | re.S,
    )
    for card in cards:
        href_match = re.search(r'href="([^"]*/ershoufang/(\d+)\.html[^"]*)"', card, re.I)
        if not href_match:
            continue
        source_url = urljoin(url, unescape(href_match.group(1)))
        external_id = href_match.group(2)

        def first(pattern: str) -> str | None:
            found = re.search(pattern, card, re.I | re.S)
            return _clean(found.group(1)) if found else None

        house_info = first(r'class="houseInfo"[^>]*>(.*?)</div>') or ""
        title = first(r'class="title"[^>]*>(.*?)</a>')
        total = _number(first(r'class="totalPrice[^"]*"[^>]*>.*?<span[^>]*>(.*?)</span>'))
        unit = _number(first(r'class="unitPrice"[^>]*>.*?<span[^>]*>(.*?)</span>'))
        area = _number(re.search(r'(\d+(?:\.\d+)?)\s*平米', house_info).group(1)) if re.search(r'(\d+(?:\.\d+)?)\s*平米', house_info) else None
        bedrooms_match = re.search(r'(\d+)\s*室', house_info)
        floor_text = first(r'class="positionInfo"[^>]*>(.*?)</div>')
        records.append(
            {
                "external_id": external_id,
                "observation_type": "listing",
                "observed_at": observed_at,
                "total_price": total,
                "unit_price": unit,
                "area_sqm": area,
                "bedrooms": int(bedrooms_match.group(1)) if bedrooms_match else None,
                "floor_text": floor_text,
                "source_url": source_url,
                "confidence": "medium",
                "payload": {
                    "title": title,
                    "house_info": house_info or None,
                    "parser": "lianjia_public_v2",
                    "source_kind": "browser_saved_html",
                    "listing_status": "observed",
                },
            }
        )
    return records


def parse_saved_html(path: Path, source_url: str) -> tuple[bytes, list[dict[str, object]]]:
    """Read a page saved by a normal browser and return traceable normalized records."""
    raw = path.read_bytes()
    html = raw.decode("utf-8", errors="replace")
    records = parse_public_listing_page(source_url, html)
    if not records:
        raise ValueError("保存的链家页面中没有识别到公开房源卡片；请确认保存的是二手房列表完整网页")
    return raw, records
