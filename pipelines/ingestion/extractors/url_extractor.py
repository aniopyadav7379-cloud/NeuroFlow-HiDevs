"""
URL extraction: fetch (async, httpx), respect robots.txt before fetching
the target page, extract main content + tables with trafilatura, and pull
title/author/canonical-url/publish-date metadata.
"""
import logging
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
import trafilatura
from trafilatura.settings import use_config

from pipelines.ingestion.extractors.base import ExtractedPage

logger = logging.getLogger("neuroflow.ingestion.url")

USER_AGENT = "NeuroFlowBot/1.0 (+https://github.com/neuroflow/ingestion)"
FETCH_TIMEOUT_S = 15.0


class RobotsDisallowed(Exception):
    """Raised when robots.txt disallows fetching the requested URL."""


async def _fetch_text(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        resp = await client.get(url, timeout=FETCH_TIMEOUT_S)
        if resp.status_code >= 400:
            return None
        return resp.text
    except httpx.HTTPError:
        return None


async def _check_robots_allowed(client: httpx.AsyncClient, url: str) -> bool:
    parsed = urlparse(url)
    robots_url = urljoin(f"{parsed.scheme}://{parsed.netloc}", "/robots.txt")

    robots_text = await _fetch_text(client, robots_url)
    parser = RobotFileParser()
    if robots_text is None:
        # No robots.txt (or unreachable) — default-allow, standard
        # robots.txt semantics when the file simply doesn't exist.
        return True
    parser.parse(robots_text.splitlines())
    return parser.can_fetch(USER_AGENT, url)


async def extract_url(url: str) -> list[ExtractedPage]:
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
        if not await _check_robots_allowed(client, url):
            raise RobotsDisallowed(f"robots.txt disallows fetching {url}")

        resp = await client.get(url, timeout=FETCH_TIMEOUT_S)
        resp.raise_for_status()
        html = resp.text

    config = use_config()
    config.set("DEFAULT", "EXTRACTION_TIMEOUT", "0")

    content_md = trafilatura.extract(
        html, include_tables=True, output_format="markdown", url=url, config=config
    )
    if not content_md:
        content_md = ""

    metadata_obj = trafilatura.extract_metadata(html, default_url=url)
    metadata = {
        "source": "url",
        "url": url,
        "title": getattr(metadata_obj, "title", None),
        "author": getattr(metadata_obj, "author", None),
        "canonical_url": getattr(metadata_obj, "url", None) or url,
        "publish_date": getattr(metadata_obj, "date", None),
    }

    return [
        ExtractedPage(
            page_number=1,
            content=content_md,
            content_type="text",
            metadata=metadata,
        )
    ]
