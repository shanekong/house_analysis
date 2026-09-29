"""Source-priority market update pipeline with per-source circuit breaking."""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from sqlalchemy.orm import Session

from .collectors.lianjia import LianjiaAccessBlocked, fetch_and_parse_listing
from .collectors.hangzhou_official import OfficialPlatformUnavailable, fetch_public_listings
from .collectors.tmsf import TmsfAccessBlocked, fetch_and_parse_community
from .seed import import_market_snapshot_json, upsert_market_observation


def run_market_update(
    session: Session,
    *,
    community_id: str,
    lianjia_url: Optional[str] = None,
    woaiwojia_snapshot: Optional[Path] = None,
    tmsf_snapshot: Optional[Path] = None,
    tmsf_url: Optional[str] = None,
    official_keyword: Optional[str] = None,
    lianjia_fetcher: Callable[[str], dict[str, object]] = fetch_and_parse_listing,
    tmsf_fetcher: Callable[[str], tuple[bytes, list[dict[str, object]]]] = fetch_and_parse_community,
    official_fetcher: Callable[[str, int], tuple[bytes, list[dict[str, object]]]] = fetch_public_listings,
) -> dict[str, object]:
    """Run each approved source independently; one blocked source never aborts later sources."""
    attempts: list[dict[str, object]] = []

    if official_keyword:
        try:
            _raw, records = official_fetcher(official_keyword, 1)
            created = updated = 0
            for record in records:
                result = upsert_market_observation(
                    session,
                    community_id=community_id,
                    source_code="hangzhou_secondhand_official",
                    record=record,
                )
                created += result["created"]
                updated += result["updated"]
            attempts.append({"source": "hangzhou_secondhand_official", "status": "succeeded", "seen": len(records), "created": created, "updated": updated})
        except OfficialPlatformUnavailable as exc:
            attempts.append({"source": "hangzhou_secondhand_official", "status": "blocked", "message": str(exc), "circuit_open": True})
        except Exception as exc:
            attempts.append({"source": "hangzhou_secondhand_official", "status": "failed", "message": str(exc)})

    if lianjia_url:
        try:
            result = upsert_market_observation(
                session,
                community_id=community_id,
                source_code="lianjia_public",
                record=lianjia_fetcher(lianjia_url),
            )
            attempts.append({"source": "lianjia_public", "status": "succeeded", **result})
        except LianjiaAccessBlocked as exc:
            attempts.append(
                {
                    "source": "lianjia_public",
                    "status": "blocked",
                    "message": str(exc),
                    "circuit_open": True,
                    "fallback": "import-lianjia-html",
                }
            )
        except Exception as exc:  # a source failure must not suppress later approved sources
            attempts.append(
                {"source": "lianjia_public", "status": "failed", "message": str(exc)}
            )
    else:
        attempts.append({"source": "lianjia_public", "status": "skipped"})

    for source_code, snapshot in (("woaiwojia_public", woaiwojia_snapshot),):
        if snapshot is None:
            attempts.append({"source": source_code, "status": "skipped"})
            continue
        try:
            result = import_market_snapshot_json(session, snapshot, source_code)
            attempts.append({"source": source_code, "status": "succeeded", **result})
        except Exception as exc:
            attempts.append({"source": source_code, "status": "failed", "message": str(exc)})

    if tmsf_url:
        try:
            _raw, records = tmsf_fetcher(tmsf_url)
            created = updated = 0
            for record in records:
                result = upsert_market_observation(
                    session,
                    community_id=community_id,
                    source_code="tmsf_public",
                    record=record,
                )
                created += result["created"]
                updated += result["updated"]
            attempts.append({"source": "tmsf_public", "status": "succeeded", "seen": len(records), "created": created, "updated": updated})
        except TmsfAccessBlocked as exc:
            if tmsf_snapshot is not None:
                result = import_market_snapshot_json(session, tmsf_snapshot, "tmsf_public")
                attempts.append({"source": "tmsf_public", "status": "succeeded", "direct_status": "blocked", "message": str(exc), **result})
            else:
                attempts.append({"source": "tmsf_public", "status": "blocked", "message": str(exc), "circuit_open": True, "fallback": "import-tmsf-html"})
        except Exception as exc:
            attempts.append({"source": "tmsf_public", "status": "failed", "message": str(exc)})
    elif tmsf_snapshot is not None:
        try:
            result = import_market_snapshot_json(session, tmsf_snapshot, "tmsf_public")
            attempts.append({"source": "tmsf_public", "status": "succeeded", **result})
        except Exception as exc:
            attempts.append({"source": "tmsf_public", "status": "failed", "message": str(exc)})
    else:
        attempts.append({"source": "tmsf_public", "status": "skipped"})

    succeeded = sum(item["status"] == "succeeded" for item in attempts)
    blocked = sum(item["status"] == "blocked" for item in attempts)
    failed = sum(item["status"] == "failed" for item in attempts)
    return {
        "status": "succeeded" if succeeded and not failed else "partial" if succeeded else "blocked" if blocked else "failed",
        "community_id": community_id,
        "summary": {"succeeded": succeeded, "blocked": blocked, "failed": failed},
        "attempts": attempts,
    }
