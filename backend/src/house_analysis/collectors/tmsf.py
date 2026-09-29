"""Transparent Housing Network (TMSF) public community-page adapter.

The site serves public pages but may answer non-browser clients with an Aliyun
WAF challenge.  This adapter never attempts to solve or bypass that challenge:
it stops immediately and supports parsing a complete HTML page saved from a
normal browser instead.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


ALLOWED_HOSTS = {"www.tmsf.com", "tmsf.com"}
WAF_MARKERS = ("aliyun_waf_aa", "_waf_bd8ce2ce37", "aliyunwaf_")


class TmsfAccessBlocked(RuntimeError):
    """The public page was replaced by TMSF's access-control challenge."""


def _validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError("只允许访问透明售房网公开 HTTPS 页面")


def _assert_not_blocked(html: str) -> None:
    if any(marker in html for marker in WAF_MARKERS):
        raise TmsfAccessBlocked(
            "透明售房网返回了阿里云 WAF 浏览器挑战；已停止自动请求。"
            "请在正常浏览器中打开公开小区详情页并保存完整 HTML，再使用 import-tmsf-html 导入。"
        )


def fetch_public_page(url: str, timeout: int = 20) -> str:
    _validate_public_url(url)
    request = Request(
        url,
        headers={
            "User-Agent": "house-analysis/0.3 (+low-frequency public snapshot)",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - allow-listed host
            if response.status != 200:
                raise RuntimeError(f"透明售房网页面返回 HTTP {response.status}")
            html = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        if exc.code in {403, 418, 429}:
            raise TmsfAccessBlocked(f"透明售房网访问控制返回 HTTP {exc.code}；已停止自动请求。") from exc
        raise RuntimeError(f"透明售房网页面返回 HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"透明售房网网络请求失败: {exc.reason}") from exc
    _assert_not_blocked(html)
    return html


class _ListingCardParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.div_depth = 0
        self.container_depth: int | None = None
        self.card_depth: int | None = None
        self.card: dict[str, object] | None = None
        self.cards: list[dict[str, object]] = []
        self.capture_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if tag == "div":
            self.div_depth += 1
            if "house_guess" in classes and self.container_depth is None:
                self.container_depth = self.div_depth
            elif self.container_depth is not None and "rectItem" in classes and self.card_depth is None:
                self.card_depth = self.div_depth
                self.card = {"texts": [], "href": None, "title": None}
        if self.card is not None and tag == "a":
            href = attributes.get("href")
            if href and "xq_csUpgrade_" in href and not self.card["href"]:
                self.card["href"] = href
            self.capture_title = "houseName" in classes

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self.capture_title = False
        if tag != "div":
            return
        if self.card_depth == self.div_depth and self.card is not None:
            self.cards.append(self.card)
            self.card = None
            self.card_depth = None
        if self.container_depth == self.div_depth:
            self.container_depth = None
        self.div_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.card is None:
            return
        value = re.sub(r"\s+", " ", data).strip()
        if not value:
            return
        self.card["texts"].append(value)
        if self.capture_title and not self.card["title"]:
            self.card["title"] = value


def _first_number(pattern: str, value: str) -> str | None:
    match = re.search(pattern, value)
    return match.group(1) if match else None


def parse_community_detail(url: str, html: str) -> list[dict[str, object]]:
    """Parse the visible current-listing cards on a TMSF community detail page."""
    _validate_public_url(url)
    _assert_not_blocked(html)
    parser = _ListingCardParser()
    parser.feed(html)
    observed_at = datetime.now(timezone.utc).isoformat()
    community_match = re.search(r"/xq_index_(\d+)\.htm", url)
    records: list[dict[str, object]] = []
    seen: set[str] = set()
    for card in parser.cards:
        href = str(card.get("href") or "")
        id_match = re.search(r"xq_csUpgrade_(\d+)\.htm", href)
        if not id_match or id_match.group(1) in seen:
            continue
        external_id = id_match.group(1)
        seen.add(external_id)
        text = " ".join(str(item) for item in card.get("texts") or [])
        total = _first_number(r"(\d+(?:\.\d+)?)\s*万", text)
        unit = _first_number(r"(\d+(?:\.\d+)?)\s*元\s*/\s*㎡", text)
        area = _first_number(r"(\d+(?:\.\d+)?)\s*㎡", text)
        bedrooms = _first_number(r"(\d+)\s*室", text)
        records.append(
            {
                "external_id": external_id,
                "observation_type": "listing",
                "observed_at": observed_at,
                "total_price": total,
                "unit_price": unit,
                "area_sqm": area,
                "bedrooms": int(bedrooms) if bedrooms else None,
                "source_url": urljoin(url, href),
                "confidence": "medium",
                "payload": {
                    "title": card.get("title"),
                    "parser": "tmsf_public_v1",
                    "source_kind": "public_community_detail",
                    "listing_status": "observed",
                    "community_external_id": community_match.group(1) if community_match else None,
                    "verified_tag_visible": "产权核验" in text,
                    "raw_card_text": text,
                },
            }
        )
    if not records:
        raise ValueError("透明售房网页面中没有识别到公开在售卡片；请确认保存的是小区详情完整网页")
    return records


def fetch_and_parse_community(url: str) -> tuple[bytes, list[dict[str, object]]]:
    html = fetch_public_page(url)
    return html.encode("utf-8"), parse_community_detail(url, html)


def parse_saved_html(path: Path, source_url: str) -> tuple[bytes, list[dict[str, object]]]:
    raw = path.read_bytes()
    html = raw.decode("utf-8", errors="replace")
    return raw, parse_community_detail(source_url, html)
